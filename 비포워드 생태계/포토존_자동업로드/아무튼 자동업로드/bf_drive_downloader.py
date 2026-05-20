"""포토존 Drive 폴더 → BeForward 업로드용 이미지 다운로더 (sync, requests 기반).

[설계]
- 포토존 자체 drive_downloader.py 와 동일한 순서/로직을 따른다:
  * config.PHOTO_CATEGORIES 순서 (외부 → 내부 → 하부/차대 → 엔진룸)
  * 각 카테고리는 alias 목록으로 매칭 ("외부", "외관", "1. 외부", …)
  * 카테고리 폴더 안 파일은 파일명 사전순 정렬
  * 카테고리가 하나도 매칭되지 않으면 루트의 이미지를 "외부"로 평탄 처리
- BeForward 크롤러는 Selenium 동기 컨텍스트이므로 nodriver 를 못 쓴다.
  대신 requests 로 Drive embeddedfolderview HTML 을 파싱한다 ("anyone with link"
  공유 권한 가정 — 기존 BeForward 측 다운로더도 동일 가정).
- 매직넘버로 이미지 유효성 검증 + 1회 재시도 (포토존 측과 동일).

브릿지에서 BefowordCrawler 인스턴스의 `_download_images_from_drive_link` 를
이 모듈의 `download_photozone_drive` 로 monkey-patch 해서 사용한다.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp"}
MIN_VALID_BYTES = 200

_IMAGE_MAGIC_PREFIXES = (
    b"\xFF\xD8\xFF",          # JPG
    b"\x89PNG\r\n\x1a\n",     # PNG
    b"GIF87a", b"GIF89a",     # GIF
    b"RIFF",                  # WebP (RIFF....WEBP)
    b"BM",                    # BMP
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)


def _extract_folder_id(drive_url: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_url)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", drive_url)
    if m:
        return m.group(1)
    raise ValueError(f"구글드라이브 URL에서 folder id 추출 실패: {drive_url}")


_FLIP_ENTRY_OPEN = re.compile(r'<div[^>]*class="flip-entry"')


def _list_folder(folder_id: str, session: requests.Session) -> list[dict]:
    """embeddedfolderview HTML → [{id, name, kind}] 목록.

    flip-entry 블록 사이를 잘라 각 항목에서 href + title 을 뽑는다.
    """
    url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    starts = [m.start() for m in _FLIP_ENTRY_OPEN.finditer(html)]
    if not starts:
        return []
    starts.append(len(html))

    entries: list[dict] = []
    for i in range(len(starts) - 1):
        block = html[starts[i]:starts[i + 1]]
        href_m = re.search(r'href="([^"]+)"', block)
        title_m = re.search(r'flip-entry-title[^>]*>([^<]+)<', block)
        if not href_m:
            continue
        href = href_m.group(1)
        name = title_m.group(1).strip() if title_m else ""
        kind: str | None = None
        fid: str | None = None
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", href)
        if m:
            kind, fid = "file", m.group(1)
        else:
            m = re.search(r"/drive/folders/([a-zA-Z0-9_-]+)", href)
            if m:
                kind, fid = "folder", m.group(1)
        if fid:
            entries.append({"id": fid, "name": name, "kind": kind})
    return entries


def _is_valid_image(content: bytes) -> bool:
    if len(content) < MIN_VALID_BYTES:
        return False
    return any(content[:16].startswith(magic) for magic in _IMAGE_MAGIC_PREFIXES)


def _download_file(file_id: str, dest: Path, session: requests.Session) -> bool:
    """Drive 공용 다운로드 URL → 파일 저장 + 매직넘버 검증."""
    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={file_id}&export=download&confirm=t&authuser=0"
    )
    try:
        resp = session.get(url, timeout=120)
        resp.raise_for_status()
        content = resp.content
        if not _is_valid_image(content):
            logger.warning("매직넘버 검증 실패 (%s, %d bytes)", file_id, len(content))
            return False
        dest.write_bytes(content)
        return True
    except Exception as exc:
        logger.warning("다운로드 예외 (%s): %s", file_id, exc)
        return False


def _download_with_retry(file_id: str, dest: Path, session: requests.Session) -> bool:
    if _download_file(file_id, dest, session):
        return True
    if dest.exists():
        try:
            dest.unlink()
        except Exception:
            pass
    return _download_file(file_id, dest, session)


def download_photozone_drive(drive_link: str, row_num: int) -> list[str]:
    """포토존 Drive 폴더에서 이미지 다운로드 (PHOTO_CATEGORIES 순서).

    Returns:
        평탄화된 파일 경로 리스트. 외부 → 내부 → 하부/차대 → 엔진룸 순.
        카테고리 매칭 0개면 루트 이미지를 "외부" 로 평탄 처리.
    """
    if not drive_link:
        logger.warning("drive_link 비어있음")
        return []

    folder_id = _extract_folder_id(drive_link)
    target_root = config.DOWNLOADS_DIR / "beforward_photos" / f"row_{row_num}"
    if target_root.exists():
        shutil.rmtree(target_root, ignore_errors=True)
    target_root.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})

    root_entries = _list_folder(folder_id, session)
    sub_folders = {
        e["name"].strip(): e["id"] for e in root_entries if e["kind"] == "folder"
    }
    logger.info("루트 하위 폴더: %s", list(sub_folders.keys()))

    flat_paths: list[str] = []
    any_matched = False

    for canonical, aliases in config.PHOTO_CATEGORIES:
        sub_id = next((sub_folders[a] for a in aliases if a in sub_folders), None)
        if sub_id is None:
            logger.warning("카테고리 폴더 없음: %s (찾는 이름들=%s)", canonical, aliases)
            continue
        any_matched = True

        safe = canonical.replace("/", "_").replace("\\", "_")
        cat_dir = target_root / safe
        cat_dir.mkdir(parents=True, exist_ok=True)

        cat_entries = _list_folder(sub_id, session)
        files = [
            e for e in cat_entries
            if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS
        ]
        files.sort(key=lambda e: e["name"])
        logger.info("[%s] %d장 다운로드 시작", canonical, len(files))

        cat_ok = 0
        for e in files:
            dest = cat_dir / e["name"]
            if _download_with_retry(e["id"], dest, session):
                flat_paths.append(str(dest))
                cat_ok += 1
            else:
                logger.warning("[%s] 최종 실패: %s", canonical, e["name"])
        logger.info("[%s] 완료 %d/%d장", canonical, cat_ok, len(files))

    if not any_matched:
        root_files = [
            e for e in root_entries
            if e["kind"] == "file" and Path(e["name"]).suffix.lower() in IMAGE_EXTS
        ]
        root_files.sort(key=lambda e: e["name"])
        if root_files:
            flat_dir = target_root / "외부"
            flat_dir.mkdir(parents=True, exist_ok=True)
            logger.info("평탄 폴더 감지 — 루트 이미지 %d장을 '외부' 로 처리", len(root_files))
            for e in root_files:
                dest = flat_dir / e["name"]
                if _download_with_retry(e["id"], dest, session):
                    flat_paths.append(str(dest))
        else:
            logger.warning("루트 폴더에도 이미지 없음 — 사진 0장")

    logger.info(
        "총 %d장 다운로드 완료 (순서: %s)",
        len(flat_paths),
        " → ".join(c for c, _ in config.PHOTO_CATEGORIES),
    )
    return flat_paths
