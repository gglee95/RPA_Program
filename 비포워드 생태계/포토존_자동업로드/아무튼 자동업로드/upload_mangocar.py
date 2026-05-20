"""Mango Car batch uploader entry point (nodriver / asyncio build).

A single nodriver Browser instance hosts both:
  - one persistent Sheet tab (for AC/AE write-back) that uses the user's
    Google session
  - one ephemeral Mango Car tab per row (cookies for mangoworldcar.com are
    explicitly cleared between rows, so seller sessions never leak)

CSV reading and Drive file downloads piggy-back on the same browser's
cookies but happen via plain HTTP (urllib) — no UI driving for those.

Examples:
    python upload_mangocar.py --row 88 --dry-run
    python upload_mangocar.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

import nodriver as uc

import config
import sheet_client
import drive_downloader
from mango_uploader import MangoUploader
from sheet_client import ListingRow, SheetWriter, today_kst_str


def _wipe_mango_cookies_from_profile() -> None:
    """Delete every mangoworldcar.com cookie row directly from the nodriver
    profile's SQLite Cookies DB *before* launching Chrome.

    CDP-based cookie clearing is unreliable for this profile (storage
    clears do not always land), so we belt-and-braces it by editing the
    on-disk database when the browser is not running. Google cookies are
    untouched.
    """
    import sqlite3
    candidates = [
        config.PROFILE_DIR / "Default" / "Network" / "Cookies",
        config.PROFILE_DIR / "Default" / "Cookies",
    ]
    for db in candidates:
        if not db.exists():
            continue
        try:
            conn = sqlite3.connect(str(db))
            conn.execute("DELETE FROM cookies WHERE host_key LIKE '%mangoworldcar.com%'")
            conn.commit()
            conn.close()
            logging.info("프로파일 쿠키 DB에서 망고카 쿠키 삭제: %s", db)
        except Exception as exc:
            logging.warning("프로파일 쿠키 DB 삭제 실패 (%s): %s", db, exc)


def _setup_logging() -> Path:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOGS_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
    # Force UTF-8 on Windows cp949 console so em-dashes/emoji don't crash logging.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    handlers = [logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    return log_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="망고카 매물 자동 업로드 (nodriver)")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--row", type=int, help="시트의 1-based 행 번호 한 건만 처리")
    target.add_argument("--rows", type=str, help="행 번호 범위(예: 180-193) 또는 콤마 목록(예: 180,182,190)")
    target.add_argument("--all", action="store_true", help="AC가 비어있는 모든 행 처리 (기본)")
    p.add_argument("--dry-run", action="store_true", help="제출 직전까지만 실행, 시트도 갱신하지 않음")
    p.add_argument("--headless", action="store_true", help="브라우저 창 숨김 (기본: 보이게 실행)")
    return p.parse_args()


async def _current_url(tab: uc.Tab) -> str:
    """nodriver's `tab.url` property can lag — read window.location.href instead."""
    try:
        result = await tab.evaluate("window.location.href")
        return str(result) if result else ""
    except Exception:
        return tab.url or ""


async def _ensure_google_login(browser: uc.Browser, login_timeout_sec: int = 600) -> uc.Tab:
    """Navigate to Google Drive to verify the user is logged in to Google.

    We need an active Google session in the browser for Drive folder downloads.
    Sheet read/write now uses the Sheets API (service account) so we no longer
    need access to the specific spreadsheet URL.

    Returns a tab that can be closed immediately; the caller keeps it only for
    compat with the old SheetWriter interface (SheetWriter now ignores it).
    """
    tab = await browser.get("https://drive.google.com/drive/my-drive")
    await tab.sleep(3)  # let initial navigation settle

    msg_shown = False
    deadline = asyncio.get_event_loop().time() + login_timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        url = await _current_url(tab)
        # Success: landed on drive.google.com (not accounts.google.com)
        if "drive.google.com" in url and "accounts.google.com" not in url:
            logging.info("구글 드라이브 로그인 확인됨")
            await tab.sleep(1.0)
            return tab

        # Still on accounts.google.com or intermediate page — prompt + wait
        if not msg_shown:
            print(
                "\n" + "=" * 70 +
                "\n구글 로그인이 필요합니다. 열려있는 Chrome 창에서"
                "\n구글 드라이브에 접근 권한이 있는 계정으로 로그인해 주세요."
                f"\n로그인 완료 시 자동으로 진행됩니다 (최대 {login_timeout_sec}초).\n" +
                "=" * 70 + "\n",
                flush=True,
            )
            logging.info("구글 로그인 대기 시작 (현재 URL: %s)", url)
            msg_shown = True

        await asyncio.sleep(3)

    raise RuntimeError("구글 로그인 대기 시간 초과 (드라이브로 진입 못 함)")


def _humanize_error(stage: str, exc: Exception) -> str:
    """기술적 예외 메시지를 비전공자도 이해할 수 있는 한글 설명으로 변환."""
    msg = str(exc)
    msg_lower = msg.lower()

    # 단계별 + 에러 내용별 매핑
    if stage == "로그인":
        if "세션 클리어" in msg or "여전히" in msg:
            return "망고카 자동 로그아웃이 안 됩니다. 브라우저를 닫고 다시 시도해주세요."
        if "25초" in msg or "sign-in" in msg_lower:
            return "망고카 로그인 실패 — P열(계정정보) 이메일/비밀번호를 확인해주세요."
        if "password" in msg_lower or "input" in msg_lower:
            return "망고카 로그인 페이지를 찾지 못했습니다. 사이트 점검 중일 수 있습니다."
        return f"망고카 로그인 중 오류 발생: {msg[:120]}"

    if stage == "차량조회":
        return f"차대번호(K열) 조회 중 오류 발생: {msg[:120]}"

    if stage == "기본정보 입력":
        if "기본정보 입력 오류" in msg:
            # 폼 validation 에러 — 어느 필드인지 추출
            return f"차량 기본정보 입력 실패 — 다음 항목을 확인해주세요: {msg[:200]}"
        if "STEP 01 입력창" in msg:
            return "차대번호 입력칸을 찾지 못했습니다. 망고카 페이지가 정상 로딩되지 않았습니다."
        return f"차량 기본정보 입력 중 오류: {msg[:120]}"

    if stage == "제출/사진업로드":
        if "MGC_ URL 미확인" in msg:
            return "최종 등록 버튼은 눌렸지만 망고카가 완료 페이지로 이동하지 않았습니다. 망고카에서 직접 확인이 필요합니다."
        if "validation" in msg_lower or "validation 오류" in msg:
            return f"제출 단계에서 망고카 폼 검증 실패: {msg[:200]}"
        if "사진" in msg or "photo" in msg_lower:
            return f"사진 업로드 중 오류: {msg[:120]}"
        return f"매물 등록 제출 중 오류: {msg[:120]}"

    return f"[{stage}] {msg[:200]}"


def _humanize_skip(reason: str) -> str:
    """차량조회 SKIP 사유를 한글 설명으로 변환."""
    if reason == "duplicate":
        return "이미 망고카에 등록된 차량입니다."
    if reason == "not_found":
        return "망고카에서 차량 조회 결과 화면(매물 등록 폼)으로 진입하지 못했습니다."
    if reason == "unsupported_id":
        return "K열 차대번호(VIN 17자리) 또는 차량번호(예: 12가1234) 형식이 아닙니다."
    if reason == "vin_not_found":
        return "차대번호 없음"
    return f"차량조회 실패: {reason}"


async def process_listing(
    listing: ListingRow,
    browser: uc.Browser,
    args: argparse.Namespace,
) -> tuple[str, str]:
    """Returns (status, mango_detail).
    status ∈ {SUCCESS, SKIP, FAIL, DRY_RUN}.
    """
    if not listing.email or not listing.password:
        return "SKIP", "P열(계정정보) 셀이 비어있어 망고카 로그인을 할 수 없습니다."
    if not listing.identifier:
        return "SKIP", "K열(차대번호/차량번호) 셀이 비어있어 차량 조회를 할 수 없습니다."
    if not listing.ad_price_number:
        return "SKIP", "O열(광고가) 셀이 비어있어 가격 입력을 할 수 없습니다."

    # 1) Drive folder download (HTTP with cookies, no UI)
    target_dir = config.DOWNLOADS_DIR / f"row_{listing.sheet_row}_{listing.identifier}"
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    category_files = await drive_downloader.download_folder(browser, listing.drive_url, target_dir)

    # 2) Mango Car upload in the same browser, but with cookies cleared
    uploader = MangoUploader(browser)
    mango_url = ""
    try:
        try:
            await uploader.login(listing.email, listing.password)
        except Exception as exc:
            return "FAIL", _humanize_error("로그인", exc)

        try:
            result = await uploader.lookup_vehicle(listing.identifier)
        except Exception as exc:
            return "FAIL", _humanize_error("차량조회", exc)
        if not result.ok:
            return "SKIP", _humanize_skip(result.reason)

        try:
            await uploader.fill_step02(listing)
        except Exception as exc:
            return "FAIL", _humanize_error("기본정보 입력", exc)

        if args.dry_run:
            return "DRY_RUN", "submit 직전까지 완료"

        # submit() handles photo upload and 특이사항 fill on the photo step
        try:
            mango_url = await uploader.submit(category_files=category_files, listing=listing)
        except Exception as exc:
            return "FAIL", _humanize_error("제출/사진업로드", exc)
    finally:
        try:
            await uploader.logout()
        except Exception:
            pass
        if uploader.tab is not None:
            try:
                await uploader.tab.close()
            except Exception:
                pass
        await asyncio.sleep(1.5)

    return "SUCCESS", mango_url


async def amain() -> int:
    args = parse_args()
    log_path = _setup_logging()
    logging.info("로그 파일: %s", log_path)

    config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    config.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Belt-and-braces: wipe mangoworldcar.com cookies at the DB level BEFORE
    # Chrome starts. CDP clears are unreliable for this profile.
    _wipe_mango_cookies_from_profile()

    browser = await uc.start(
        user_data_dir=str(config.PROFILE_DIR),
        headless=args.headless,
        # System Chrome is undetected; Playwright Chromium is detected.
        # nodriver auto-finds Chrome on Windows (look in Program Files).
    )
    summary: list[tuple[int, str, str]] = []
    try:
        await _ensure_google_login(browser)
        writer = SheetWriter()
        logging.info("SheetWriter.open() 시작")
        await writer.open()
        logging.info("SheetWriter.open() 완료 — 시트 읽기 시작")

        rows = await sheet_client.read_pending_rows()
        logging.info("시트 읽기 완료 — 전체 pending 행: %d건", len(rows))
        if args.row:
            rows = [r for r in rows if r.sheet_row == args.row]
            if not rows:
                logging.error("행 %s 가 pending 목록에 없습니다", args.row)
                return 1
        elif args.rows:
            spec = args.rows.strip()
            wanted: set[int] = set()
            for part in spec.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    lo_s, hi_s = part.split("-", 1)
                    lo, hi = int(lo_s), int(hi_s)
                    if lo > hi:
                        lo, hi = hi, lo
                    wanted.update(range(lo, hi + 1))
                else:
                    wanted.add(int(part))
            rows = [r for r in rows if r.sheet_row in wanted]
            if not rows:
                logging.error("--rows %s 에 해당하는 pending 행 없음", args.rows)
                return 1
            logging.info("--rows 필터 적용: %d건 (요청 %d개 중)", len(rows), len(wanted))
        logging.info("처리 대상 %d건", len(rows))

        for listing in rows:
            try:
                status, detail = await process_listing(listing, browser, args)
            except Exception as exc:
                logging.exception("행 %s 처리 중 예외", listing.sheet_row)
                status, detail = "FAIL", f"예상하지 못한 오류 — 로그 파일을 확인해주세요. ({type(exc).__name__}: {str(exc)[:120]})"

            summary.append((listing.sheet_row, status, detail))
            logging.info("[행 %s] %s — %s", listing.sheet_row, status, detail)

            if status == "SUCCESS":
                try:
                    await writer.update_row_after_upload(listing.sheet_row, today_kst_str(), detail)
                    logging.info("[행 %s] 시트 업데이트 완료", listing.sheet_row)
                except Exception:
                    logging.exception("[행 %s] 시트 업데이트 실패", listing.sheet_row)

            # AK열 — 업로드 결과 기록 (DRY_RUN 제외)
            if status != "DRY_RUN":
                if status == "SUCCESS":
                    ak_value = "업로드 성공"
                elif status == "SKIP":
                    ak_value = f"건너뜀 — {detail}"
                else:  # FAIL
                    ak_value = f"실패 — {detail}"
                try:
                    await writer.update_upload_result(listing.sheet_row, ak_value)
                    logging.info("[행 %s] AK열 결과 기록: %s", listing.sheet_row, ak_value[:60])
                except Exception:
                    logging.exception("[행 %s] AK열 결과 기록 실패", listing.sheet_row)
    finally:
        browser.stop()

    logging.info("=" * 60)
    for sheet_row, status, detail in summary:
        logging.info("행 %3d  %-8s  %s", sheet_row, status, detail)
    return 0


def main() -> int:
    return uc.loop().run_until_complete(amain())


if __name__ == "__main__":
    raise SystemExit(main())
