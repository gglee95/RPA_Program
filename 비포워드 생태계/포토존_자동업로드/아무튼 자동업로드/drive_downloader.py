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


async def download_folder(browser: uc.Browser, drive_url: str, target_dir: Path) -> dict[str, list[Path]]:
    """Walk the Drive folder, find each PHOTO_CATEGORIES sub-folder, download
    its image files into `target_dir/<category>/`, return paths bucketed by
    canonical category name (the first element of each PHOTO_CATEGORIES tuple).
    """
    if not drive_url:
        logger.warning("드라이브 URL이 비어있습니다 - 사진 다운로드 건너뜀")
        return {cat: [] for cat, _ in config.PHOTO_CATEGORIES}

    target_dir.mkdir(parents=True, exist_ok=True)
    folder_id = _extract_folder_id(drive_url)

    tab = await browser.get("about:blank", new_tab=True)
    try:
        await tab.send(
            cdp.browser.set_download_behavior(behavior="allow", download_path=str(target_dir.resolve()))
        )

        root_entries = await _list_folder(tab, folder_id)
        sub_folders = {e["name"].strip(): e["id"] for e in root_entries if e["kind"] == "folder"}
        logger.info("루트 폴더 하위 폴더: %s", list(sub_folders.keys()))

        result: dict[str, list[Path]] = {}
        for canonical, aliases in config.PHOTO_CATEGORIES:
            sub_id = next((sub_folders[a] for a in aliases if a in sub_folders), None)
            if sub_id is None:
                logger.warning("카테고리 폴더 없음: %s (찾는 이름들=%s)", canonical, aliases)
                result[canonical] = []
                continue

            # Sanitize: '/' in "하부/차대" would create nested dirs on Windows.
            safe_name = canonical.replace("/", "_").replace("\\", "_")
            cat_dir = target_dir / safe_name
            cat_dir.mkdir(parents=True, exist_ok=True)
            await tab.send(
                cdp.browser.set_download_behavior(behavior="allow", download_path=str(cat_dir.resolve()))
            )

            entries = await _list_folder(tab, sub_id)
            files = [e for e in entries if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS]
            files.sort(key=lambda e: e["name"])
            logger.info("[%s] %d장 다운로드 시작", canonical, len(files))

            paths: list[Path] = []
            for e in files:
                p = await _download_one(tab, e["id"], e["name"], cat_dir)
                if p:
                    paths.append(p)
                else:
                    logger.warning("파일 다운로드 실패: %s", e["name"])
            logger.info("[%s] 완료 %d장", canonical, len(paths))
            result[canonical] = paths

        # ── 폴백: 카테고리 폴더에서 이미지를 하나도 못 받았으면 ──────────────────
        # 루트 폴더에 바로 있는 이미지 파일을 모두 다운로드해서 "외부" 키로 반환.
        if not any(result.values()):
            root_files = [
                e for e in root_entries
                if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS
            ]
            if root_files:
                logger.info("카테고리 폴더 없음 — 루트 이미지 %d장 전체 다운로드 (폴백)", len(root_files))
                fallback_dir = target_dir / "fallback"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                await tab.send(
                    cdp.browser.set_download_behavior(
                        behavior="allow", download_path=str(fallback_dir.resolve())
                    )
                )
                root_files.sort(key=lambda e: e["name"])
                paths: list[Path] = []
                for e in root_files:
                    p = await _download_one(tab, e["id"], e["name"], fallback_dir)
                    if p:
                        paths.append(p)
                    else:
                        logger.warning("폴백 파일 다운로드 실패: %s", e["name"])
                logger.info("폴백 완료: %d장", len(paths))
                result["외부"] = paths   # 업로더는 순서대로 전부 올림
            else:
                logger.warning("루트 폴더에도 이미지 없음 — 사진 업로드 건너뜀")

        return result
    finally:
        try:
            await tab.close()
        except Exception:
            pass
