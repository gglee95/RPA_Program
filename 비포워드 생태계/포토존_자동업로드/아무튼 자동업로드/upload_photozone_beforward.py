"""Photozone/Mango upload followed by BeForward upload.

운영용 엔트리:
  1. 포토존 사진으로 망고카 매물 업로드
  2. 성공한 같은 행을 비포워드에도 업로드
  3. 시트 AD/AF/AG/AK 결과 기록

Examples:
    python upload_photozone_beforward.py --row 192
    python upload_photozone_beforward.py --rows 180-193
    python upload_photozone_beforward.py --all
    python upload_photozone_beforward.py --row 192 --beforward-only
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

# BeForward config.py reads these at import time through os.getenv.
os.environ.setdefault("BEFORWARD_USERNAME", "joonsookang@mangoworldcar.com")
os.environ.setdefault("BEFORWARD_PASSWORD", "k4ycwYk6")

import nodriver as uc

import config
import sheet_client
from beforward_bridge import upload_listing_to_beforward
from sheet_client import ListingRow, SheetWriter, today_kst_str
from upload_mangocar import (
    _ensure_google_login,
    _wipe_mango_cookies_from_profile,
    process_listing,
)

BEFORWARD_TARGET_MARKER = "비포워드 업로드 요망"


def _setup_logging() -> Path:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOGS_DIR / f"photozone_bf_{datetime.now():%Y%m%d_%H%M%S}.log"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="포토존 업로드 후 같은 매물을 비포워드에도 업로드")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--row", type=int, help="시트의 1-based 행 번호 한 건만 처리")
    target.add_argument("--rows", type=str, help="행 번호 범위(예: 180-193) 또는 콤마 목록")
    target.add_argument("--all", action="store_true", help="대상 전체 처리 (기본)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="제출 직전까지만 실행. 일반 모드에서는 망고카까지만, --beforward-only와 함께 쓰면 비포워드 폼만 채움",
    )
    p.add_argument("--headless", action="store_true", help="망고카 브라우저 창 숨김")
    p.add_argument(
        "--beforward-only",
        action="store_true",
        help="망고카 업로드는 건너뛰고 AF열 링크가 있는 행만 비포워드 업로드",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="시트에 결과를 기록하지 않음",
    )
    return p.parse_args()


def _parse_row_spec(spec: str) -> set[int]:
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
    return wanted


async def _read_all_rows() -> list[ListingRow]:
    ws = await asyncio.to_thread(sheet_client._open_worksheet)
    all_values = await asyncio.to_thread(ws.get_all_values)
    return sheet_client._parse_rows(all_values)


async def _select_rows(args: argparse.Namespace) -> list[ListingRow]:
    explicit_rows = bool(args.row or args.rows)
    if args.beforward_only:
        rows = await _read_all_rows()
        rows = [r for r in rows if r.get("판매여부").strip() != "타 경로 판매"]
        if not explicit_rows:
            rows = [
                r for r in rows
                if r.get("링크").strip()
                and r.get("비포워드 링크").strip() == BEFORWARD_TARGET_MARKER
            ]
    else:
        if explicit_rows:
            rows = await _read_all_rows()
            rows = [r for r in rows if r.get("판매여부").strip() != "타 경로 판매"]
        else:
            rows = await sheet_client.read_pending_rows()

    if args.row:
        rows = [r for r in rows if r.sheet_row == args.row]
    elif args.rows:
        wanted = _parse_row_spec(args.rows)
        rows = [r for r in rows if r.sheet_row in wanted]
        logging.info("--rows 필터 적용: %d건 (요청 %d개 중)", len(rows), len(wanted))

    if explicit_rows:
        logging.info("명시 행 지정: AG열 요청문구 필터는 생략")
    else:
        rows = [
            r for r in rows
            if r.get("비포워드 링크").strip() == BEFORWARD_TARGET_MARKER
        ]
        logging.info(
            "AG열 '%s' 대상 필터 적용 후: %d건",
            BEFORWARD_TARGET_MARKER,
            len(rows),
        )
    return rows


async def _write_beforward_log(writer: SheetWriter, sheet_row: int, value: str) -> None:
    await writer.update_beforward_result(sheet_row, value)


def _with_mango_url(listing: ListingRow, mango_url: str) -> ListingRow:
    """Return a ListingRow copy whose AF column contains the newly uploaded URL."""
    raw = list(listing.raw)
    link_idx = config.COL["링크"]
    if len(raw) <= link_idx:
        raw.extend([""] * (link_idx + 1 - len(raw)))
    raw[link_idx] = mango_url
    return replace(listing, raw=raw)


def _validate_beforward_inputs(listing: ListingRow) -> None:
    required = {
        "차종": listing.get("차종"),
        "연식": listing.get("연식"),
        "실주행거리": listing.get("실주행거리"),
        "유종": listing.get("유종"),
        "미션": listing.get("미션"),
        "차량색상": listing.get("차량색상"),
        "인승": listing.get("인승"),
        "광고가": listing.ad_price_number,
        "A1": listing.identifier,
        "구글드라이브": listing.drive_url,
        "망고카 링크(AF)": listing.get("링크"),
    }
    missing = [k for k, v in required.items() if not str(v).strip()]
    if missing:
        raise RuntimeError(f"비포워드 필수 컬럼 비어있음: {', '.join(missing)}")


async def _upload_beforward(listing: ListingRow, args: argparse.Namespace) -> tuple[str, str]:
    try:
        _validate_beforward_inputs(listing)
        listing_id = await asyncio.to_thread(
            upload_listing_to_beforward,
            listing,
            not args.dry_run,
            args.dry_run,
        )
    except Exception as exc:
        logging.exception("[행 %s] 비포워드 업로드 예외", listing.sheet_row)
        return "FAIL", f"{type(exc).__name__}: {str(exc)[:180]}"

    if listing_id:
        return "DRY_RUN" if args.dry_run else "SUCCESS", listing_id
    return "FAIL", "비포워드 업로드 실패 (상세 로그 확인)"


async def _run_mango_browser_rows(
    rows: list[ListingRow],
    args: argparse.Namespace,
    writer: SheetWriter,
) -> list[tuple[int, str, str]]:
    config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    config.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    _wipe_mango_cookies_from_profile()

    browser = await uc.start(
        user_data_dir=str(config.PROFILE_DIR),
        headless=args.headless,
    )
    summary: list[tuple[int, str, str]] = []
    try:
        await _ensure_google_login(browser)
        for listing in rows:
            existing_mango_url = listing.get("링크").strip()
            if existing_mango_url:
                logging.info(
                    "[행 %s] AF 망고카 링크가 이미 있어 망고카 업로드 생략: %s",
                    listing.sheet_row,
                    existing_mango_url,
                )
                bf_status, bf_detail = await _upload_beforward(listing, args)
                logging.info("[행 %s] 비포워드 %s - %s", listing.sheet_row, bf_status, bf_detail)

                final_status = "SUCCESS" if bf_status == "SUCCESS" else "FAIL"
                summary.append((listing.sheet_row, final_status, bf_detail))

                if not args.no_write and bf_status != "DRY_RUN":
                    if bf_status == "SUCCESS":
                        await writer.update_beforward_link(listing.sheet_row, bf_detail)
                        await _write_beforward_log(
                            writer,
                            listing.sheet_row,
                            f"비포워드 성공 - {bf_detail}",
                        )
                    else:
                        await _write_beforward_log(
                            writer,
                            listing.sheet_row,
                            f"비포워드 실패 - {bf_detail}",
                        )
                continue

            try:
                mango_status, mango_detail = await process_listing(listing, browser, args)
            except Exception as exc:
                logging.exception("[행 %s] 망고카 처리 중 예외", listing.sheet_row)
                mango_status = "FAIL"
                mango_detail = f"예상하지 못한 망고카 오류 ({type(exc).__name__}: {str(exc)[:120]})"

            logging.info("[행 %s] 망고카 %s - %s", listing.sheet_row, mango_status, mango_detail)

            if mango_status == "DRY_RUN":
                summary.append((
                    listing.sheet_row,
                    "DRY_RUN",
                    "망고카 submit 직전까지 완료 (AF 링크 미생성으로 비포워드 생략)",
                ))
                if not args.no_write:
                    await _write_beforward_log(
                        writer,
                        listing.sheet_row,
                        "비포워드 미진행 - 망고카 dry-run",
                    )
                continue

            if mango_status != "SUCCESS":
                summary.append((listing.sheet_row, mango_status, mango_detail))
                if not args.no_write:
                    ak = f"건너뜀 - {mango_detail}" if mango_status == "SKIP" else f"실패 - {mango_detail}"
                    await writer.update_upload_result(listing.sheet_row, ak)
                    await _write_beforward_log(
                        writer,
                        listing.sheet_row,
                        f"비포워드 미진행 - 망고카 {mango_status}: {mango_detail}",
                    )
                continue

            bf_listing = _with_mango_url(listing, mango_detail)
            bf_status, bf_detail = await _upload_beforward(bf_listing, args)
            logging.info("[행 %s] 비포워드 %s - %s", listing.sheet_row, bf_status, bf_detail)

            final_status = "SUCCESS" if bf_status == "SUCCESS" else "PARTIAL"
            final_detail = f"망고카 성공 / 비포워드 {bf_status}: {bf_detail}"
            summary.append((listing.sheet_row, final_status, final_detail))

            if not args.no_write:
                await writer.update_row_after_upload(listing.sheet_row, today_kst_str(), mango_detail)
                await writer.update_upload_result(listing.sheet_row, "업로드 성공")
                if bf_status == "SUCCESS":
                    await writer.update_beforward_link(listing.sheet_row, bf_detail)
                    await _write_beforward_log(
                        writer,
                        listing.sheet_row,
                        f"비포워드 성공 - {bf_detail}",
                    )
                else:
                    await _write_beforward_log(
                        writer,
                        listing.sheet_row,
                        f"비포워드 {bf_status} - {bf_detail}",
                    )
    finally:
        browser.stop()

    return summary


async def _run_beforward_only_rows(
    rows: list[ListingRow],
    args: argparse.Namespace,
    writer: SheetWriter,
) -> list[tuple[int, str, str]]:
    summary: list[tuple[int, str, str]] = []
    for listing in rows:
        bf_status, bf_detail = await _upload_beforward(listing, args)
        summary.append((listing.sheet_row, bf_status, bf_detail))
        logging.info("[행 %s] 비포워드 %s - %s", listing.sheet_row, bf_status, bf_detail)
        if not args.no_write and bf_status != "DRY_RUN":
            if bf_status == "SUCCESS":
                await writer.update_beforward_link(listing.sheet_row, bf_detail)
                await _write_beforward_log(
                    writer,
                    listing.sheet_row,
                    f"비포워드 성공 - {bf_detail}",
                )
            else:
                await _write_beforward_log(
                    writer,
                    listing.sheet_row,
                    f"비포워드 실패 - {bf_detail}",
                )
    return summary


async def amain() -> int:
    args = parse_args()
    if not args.all and not args.row and not args.rows:
        args.all = True

    log_path = _setup_logging()
    logging.info("로그 파일: %s", log_path)

    writer = SheetWriter()
    if not args.no_write:
        await writer.open()

    rows = await _select_rows(args)
    if not rows:
        logging.error("처리 대상 행이 없습니다")
        return 1
    logging.info("처리 대상 %d건: %s", len(rows), [r.sheet_row for r in rows])

    if args.beforward_only:
        summary = await _run_beforward_only_rows(rows, args, writer)
    else:
        summary = await _run_mango_browser_rows(rows, args, writer)

    logging.info("=" * 60)
    failed = 0
    for sheet_row, status, detail in summary:
        logging.info("행 %3d  %-8s  %s", sheet_row, status, detail)
        if status in {"FAIL", "PARTIAL"}:
            failed += 1
    return 1 if failed else 0


def main() -> int:
    return uc.loop().run_until_complete(amain())


if __name__ == "__main__":
    raise SystemExit(main())
