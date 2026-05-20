"""Download a Google Drive folder via Chrome's own download mechanism.

Uses two pieces of Drive's public infrastructure:

  1. `https://drive.google.com/embeddedfolderview?id=<FOLDER_ID>#list`
     A simple folder-listing endpoint that returns plain HTML; we walk its
     `.flip-entry` items in JS to enumerate sub-folders and files.

  2. `https://drive.usercontent.google.com/download?id=<FILE_ID>&export=download`
     The standard public file-download URL. We point Chrome at a known
     download directory via `Browser.setDownloadBehavior`, then navigate
     to this URL — the file lands on disk using the persistent profile's
     Google session.

This avoids cookie extraction entirely (nodriver's cookie store hangs on
Google) and avoids fragile right-click-menu UI driving.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path

import nodriver as uc
from nodriver import cdp

import config

logger = logging.getLogger(__name__)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}


def _extract_folder_id(drive_url: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", drive_url)
    if m:
        return m.group(1)
    raise ValueError(f"구글드라이브 URL에서 folder id를 찾을 수 없습니다: {drive_url}")


_LIST_JS = """
(() => {
    const entries = document.querySelectorAll('.flip-entry');
    const out = [];
    for (const e of entries) {
        const a = e.querySelector('a');
        const t = e.querySelector('.flip-entry-title');
        if (!a) continue;
        const href = a.href || '';
        let kind = null, id = null;
        let m = href.match(/\\/file\\/d\\/([a-zA-Z0-9_-]+)/);
        if (m) { kind = 'file'; id = m[1]; }
        else {
            m = href.match(/\\/drive\\/folders\\/([a-zA-Z0-9_-]+)/);
            if (m) { kind = 'folder'; id = m[1]; }
        }
        if (!id) continue;
        out.push({id, name: (t ? t.textContent.trim() : ''), kind});
    }
    return JSON.stringify(out);
})()
"""


async def _list_folder(tab: uc.Tab, folder_id: str) -> list[dict]:
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    await tab.get(url)
    # Retry the DOM read until entries appear or we give up (some folders
    # take a few seconds to hydrate, especially when the user's session is
    # just getting its auth refreshed).
    for _ in range(8):
        await tab.sleep(1.5)
        raw = await tab.evaluate(_LIST_JS)
        try:
            entries = json.loads(raw) if isinstance(raw, str) else []
        except Exception:
            entries = []
        if entries:
            return entries
    return []


def _wait_for_download(target_dir: Path, expected_name: str | None, deadline_sec: float) -> Path | None:
    deadline = time.time() + deadline_sec
    seen_before = {p.name for p in target_dir.glob("*") if not p.name.endswith(".crdownload")}
    while time.time() < deadline:
        in_progress = any(target_dir.glob("*.crdownload"))
        # Pick a finished file we didn't already see
        for p in target_dir.glob("*"):
            if p.name.endswith(".crdownload"):
                continue
            if expected_name and p.name == expected_name:
                return p
            if not expected_name and p.name not in seen_before:
                return p
        if not in_progress:
            time.sleep(0.3)
        else:
            time.sleep(0.5)
    return None


async def _download_one(tab: uc.Tab, file_id: str, expected_name: str, dest_dir: Path) -> Path | None:
    """Navigate to the file's download URL and wait for it to land in dest_dir."""
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
    try:
        await tab.get(url)
    except Exception:
        pass
    p = await asyncio.to_thread(_wait_for_download, dest_dir, expected_name, 60)
    if p:
        return p
    # Retry with confirm=t in case Drive showed the virus-scan warning
    url2 = url + "&confirm=t"
    try:
        await tab.get(url2)
    except Exception:
        pass
    return await asyncio.to_thread(_wait_for_download, dest_dir, expected_name, 60)


PARALLEL_DOWNLOADS = 5
MIN_VALID_BYTES = 200  # 이보다 작은 파일은 HTML 에러 페이지일 가능성 높음

# 이미지 파일 시그니처 (magic numbers). JPG/PNG/GIF/WebP/BMP 헤더.
_IMAGE_MAGIC_PREFIXES = (
    b"\xFF\xD8\xFF",          # JPG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a", b"GIF89a",     # GIF
    b"RIFF",                  # WebP (RIFF....WEBP)
    b"BM",                    # BMP
)


def _is_valid_image(path: Path) -> bool:
    """다운로드된 파일이 실제 이미지인지(매직넘버) 검증.

    Drive가 가상스캔 경고나 rate-limit 시 HTML을 반환하는 경우, 파일은
    존재하지만 내용은 이미지가 아니다. 매직넘버로 거른다.
    """
    try:
        size = path.stat().st_size
        if size < MIN_VALID_BYTES:
            return False
        with path.open("rb") as f:
            head = f.read(16)
        return any(head.startswith(magic) for magic in _IMAGE_MAGIC_PREFIXES)
    except Exception:
        return False


async def _download_files_parallel(
    files: list[dict],
    dest_dir: Path,
    workers: list[uc.Tab],
    label: str,
) -> list[Path]:
    """병렬 워커로 파일들을 dest_dir에 다운로드 + 매직넘버 검증 + 1회 재시도.

    호출 직전에 set_download_behavior 로 dest_dir 이 지정되어 있어야 함.
    """
    queue: asyncio.Queue = asyncio.Queue()
    for e in files:
        queue.put_nowait(e)

    paths: list[Path] = []
    invalid: list[str] = []

    async def worker(wtab: uc.Tab) -> None:
        while True:
            try:
                e = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            success = False
            for attempt in range(2):
                p = await _download_one(wtab, e["id"], e["name"], dest_dir)
                if p and await asyncio.to_thread(_is_valid_image, p):
                    paths.append(p)
                    success = True
                    break
                # 검증 실패 또는 다운로드 실패 — 파일 정리 후 재시도
                if p:
                    try:
                        p.unlink()
                    except Exception:
                        pass
                    logger.warning("[%s] 검증 실패 (시도 %d): %s — 재다운로드",
                                   label, attempt + 1, e["name"])
                else:
                    logger.warning("[%s] 다운로드 실패 (시도 %d): %s",
                                   label, attempt + 1, e["name"])
                await asyncio.sleep(1.0)
            if not success:
                invalid.append(e["name"])

    await asyncio.gather(*[worker(w) for w in workers])
    paths.sort(key=lambda p: p.name)  # 업로드 순서 일관성
    logger.info("[%s] 완료 %d장 (실패 %d)", label, len(paths), len(invalid))
    if invalid:
        logger.error("[%s] 최종 실패 파일: %s", label, invalid)
    return paths


async def download_folder(browser: uc.Browser, drive_url: str, target_dir: Path) -> dict[str, list[Path]]:
    """Walk the Drive folder, find each PHOTO_CATEGORIES sub-folder, download
    its image files into `target_dir/<category>/`, return paths bucketed by
    canonical category name (the first element of each PHOTO_CATEGORIES tuple).

    Per-category 병렬 다운로드 + 매직넘버 검증 + 1회 재시도.

    Flat-folder handling: 카테고리 하위 폴더가 하나도 없으면 루트 이미지 전부를
    "외부" 키로 매핑. 망고카 업로드 시점에서 카테고리는 무시되고 순서대로 일괄
    업로드되므로, 평탄 폴더 매물도 정상 처리된다.
    """
    if not drive_url:
        raise ValueError("드라이브 URL이 비어있습니다 — 사진 다운로드 불가")

    target_dir.mkdir(parents=True, exist_ok=True)
    folder_id = _extract_folder_id(drive_url)

    tab = await browser.get("about:blank", new_tab=True)
    workers: list[uc.Tab] = []
    for _ in range(PARALLEL_DOWNLOADS):
        workers.append(await browser.get("about:blank", new_tab=True))
    try:
        root_entries = await _list_folder(tab, folder_id)
        sub_folders = {e["name"].strip(): e["id"] for e in root_entries if e["kind"] == "folder"}
        logger.info("루트 폴더 하위 폴더: %s", list(sub_folders.keys()))

        result: dict[str, list[Path]] = {}
        any_category_matched = False
        for canonical, aliases in config.PHOTO_CATEGORIES:
            sub_id = next((sub_folders[a] for a in aliases if a in sub_folders), None)
            if sub_id is None:
                logger.warning("카테고리 폴더 없음: %s (찾는 이름들=%s)", canonical, aliases)
                result[canonical] = []
                continue
            any_category_matched = True

            # Sanitize: '/' in "하부/차대" would create nested dirs on Windows.
            safe_name = canonical.replace("/", "_").replace("\\", "_")
            cat_dir = target_dir / safe_name
            cat_dir.mkdir(parents=True, exist_ok=True)
            # set_download_behavior는 브라우저 전역 — 1회 호출로 모든 탭에 적용
            await tab.send(
                cdp.browser.set_download_behavior(behavior="allow", download_path=str(cat_dir.resolve()))
            )

            entries = await _list_folder(tab, sub_id)
            files = [e for e in entries if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS]
            files.sort(key=lambda e: e["name"])
            logger.info("[%s] %d장 다운로드 시작 (병렬 %d)", canonical, len(files), PARALLEL_DOWNLOADS)
            result[canonical] = await _download_files_parallel(files, cat_dir, workers, canonical)

        # Flat 폴더 처리: 카테고리가 하나도 매칭되지 않았을 때만 루트 이미지 사용
        if not any_category_matched:
            root_files = [
                e for e in root_entries
                if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS
            ]
            root_files.sort(key=lambda e: e["name"])
            if root_files:
                flat_dir = target_dir / "외부"
                flat_dir.mkdir(parents=True, exist_ok=True)
                await tab.send(
                    cdp.browser.set_download_behavior(
                        behavior="allow", download_path=str(flat_dir.resolve())
                    )
                )
                logger.info("평탄 폴더 감지 — 루트 이미지 %d장을 '외부' 카테고리로 다운로드 (병렬 %d)",
                            len(root_files), PARALLEL_DOWNLOADS)
                result["외부"] = await _download_files_parallel(
                    root_files, flat_dir, workers, "외부(평탄)"
                )
            else:
                logger.warning("루트 폴더에도 이미지 없음 — 사진 업로드 건너뜀")

        return result
    finally:
        for t in [*workers, tab]:
            try:
                await t.close()
            except Exception:
                pass