"""Row 103 테스트 — 이미 다운로드된 외부(EXTERIOR) 사진만 업로드까지 진행."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import nodriver as uc

import config
from mango_uploader import MangoUploader
from sheet_client import read_pending_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OVERRIDE_EMAIL    = "josero@mangoworldcar.com"
OVERRIDE_PASSWORD = "vamostodavia@"
TARGET_ROW        = 103

# 이미 다운로드된 외부(EXTERIOR) 사진만 사용
PHOTO_DIR = config.DOWNLOADS_DIR / "row_103_test" / "외부"


async def amain() -> None:
    photos = sorted(PHOTO_DIR.iterdir()) if PHOTO_DIR.exists() else []
    ordered = [str(p) for p in photos if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    logging.info("업로드할 사진: %d장 (%s)", len(ordered), PHOTO_DIR)
    if not ordered:
        logging.error("사진 없음 — 폴더를 확인하세요: %s", PHOTO_DIR)
        return

    rows = await read_pending_rows()
    listing = next((r for r in rows if r.sheet_row == TARGET_ROW), None)
    if listing is None:
        logging.error("Row %d를 pending 목록에서 찾을 수 없습니다.", TARGET_ROW)
        return

    listing.raw[config.COL["계정정보"]] = f"{OVERRIDE_EMAIL}\n{OVERRIDE_PASSWORD}"
    logging.info("계정 오버라이드: %s", OVERRIDE_EMAIL)

    # 브라우저 시작 전에 프로파일 SQLite DB에서 망고카 쿠키 강제 삭제
    import sqlite3
    for db_path in [
        config.PROFILE_DIR / "Default" / "Network" / "Cookies",
        config.PROFILE_DIR / "Default" / "Cookies",
    ]:
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
                conn.execute("DELETE FROM cookies WHERE host_key LIKE '%mangoworldcar.com%'")
                conn.commit()
                conn.close()
                logging.info("쿠키 DB 망고카 쿠키 삭제: %s", db_path)
            except Exception as e:
                logging.warning("쿠키 DB 삭제 실패: %s", e)

    browser = await uc.start(user_data_dir=str(config.PROFILE_DIR), headless=False)
    try:
        uploader = MangoUploader(browser)

        # 로그인
        await uploader.login(OVERRIDE_EMAIL, OVERRIDE_PASSWORD)

        # 차량 조회
        result = await uploader.lookup_vehicle(listing.identifier)
        if not result.ok:
            logging.error("차량 조회 실패: %s", result.reason)
            return

        # 기본정보 + 옵션 입력
        await uploader.fill_step02(listing)

        # submit 루프 — 사진 업로드 후 멈춤 (등록하기 안 클릭)
        photo_uploaded = False
        _JS_NEXT = """
        (() => {
            const SKIP = ['조회하기','Logout','My page','offers','(KST)'];
            for (const label of ['다음','매물등록']) {
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.textContent||'').trim().replace(/\\s+/g,'');
                    if (SKIP.some(s=>t.includes(s)) || btn.type==='reset') continue;
                    if (t===label || t.startsWith(label)) { btn.click(); return t; }
                }
            }
            return null;
        })()
        """

        for attempt in range(30):
            await uploader.tab.sleep(2)
            url = await uploader.tab.evaluate("window.location.href")
            if isinstance(url, str) and "MGC_" in url:
                logging.info("등록 완료(예상치 못함): %s", url)
                break

            # 모달 처리
            modal = await uploader.tab.evaluate("""
            (() => {
                const d = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')]
                    .find(el => window.getComputedStyle(el).display !== 'none');
                if (!d) return null;
                const btns = d.querySelectorAll('button');
                const idx = btns.length >= 2 ? 1 : 0;
                if (btns[idx]) { btns[idx].click(); return (d.innerText||'').slice(0,40); }
                return null;
            })()
            """)
            if modal:
                logging.info("[%d] 모달 처리: %r", attempt, modal)
                continue

            # 사진 input 감지
            has_file = await uploader.tab.evaluate(
                "!!document.querySelector('input[type=\"file\"]')"
            )
            if has_file and not photo_uploaded:
                logging.info("=== 사진 업로드 단계 진입! (%d장) ===", len(ordered))
                try:
                    file_input = await uploader.tab.select("input[type=file]")
                    await file_input.send_file(*ordered)
                    logging.info("send_file 완료 — %d장", len(ordered))
                    await uploader.tab.sleep(5)
                except Exception as exc:
                    logging.error("사진 업로드 실패: %s", exc)
                photo_uploaded = True
                logging.info("=== 사진 업로드 완료 (등록하기는 클릭 안 함) ===")
                break

            clicked = await uploader.tab.evaluate(_JS_NEXT)
            if clicked:
                logging.info("[%d] 클릭: %r", attempt, clicked)

        if not photo_uploaded:
            logging.warning("30회 시도 후에도 사진 단계 미도달")

        input("\nEnter를 눌러 브라우저 종료...")
    finally:
        browser.stop()


if __name__ == "__main__":
    uc.loop().run_until_complete(amain())
