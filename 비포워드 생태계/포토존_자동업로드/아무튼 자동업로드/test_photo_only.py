"""사진 업로드 단독 테스트 스크립트.

Row 82의 로컬 다운로드 폴더를 사용해서 사진 업로드 기능만 검증합니다.
기본정보 입력 단계를 건너뛰고 직접 사진 업로드 페이지를 찾아 테스트합니다.

실행: python test_photo_only.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import nodriver as uc

import config
from mango_uploader import MangoUploader, _clear_mangocar_cookies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Row 82 사진 폴더 (이미 로컬에 다운로드됨)
PHOTO_DIR = config.DOWNLOADS_DIR / "row_82_KMHEC41BBBA225136"

# Row 82 계정정보
EMAIL = "jhsoon119@nate.com"
PASSWORD = "aa120110"


def build_category_files(photo_dir: Path) -> dict[str, list[Path]]:
    category_files: dict[str, list[Path]] = {}
    for canonical, aliases in config.PHOTO_CATEGORIES:
        for alias in aliases:
            folder = photo_dir / alias
            if folder.exists():
                files = sorted(folder.iterdir())
                if files:
                    category_files[canonical] = files
                    logging.info("카테고리 %s: %d장 (%s)", canonical, len(files), alias)
                    break
    return category_files


async def amain() -> None:
    category_files = build_category_files(PHOTO_DIR)
    ordered = [
        str(p)
        for canonical, _aliases in config.PHOTO_CATEGORIES
        for p in category_files.get(canonical, [])
    ]
    logging.info("총 업로드 예정 사진: %d장", len(ordered))
    if not ordered:
        logging.error("사진 없음 — PHOTO_DIR를 확인하세요: %s", PHOTO_DIR)
        return

    browser = await uc.start(
        user_data_dir=str(config.PROFILE_DIR),
        headless=False,
    )
    try:
        uploader = MangoUploader(browser)

        # 1) 로그인
        await uploader.login(EMAIL, PASSWORD)
        logging.info("로그인 성공")

        # 2) 매물 등록 페이지로 이동
        await uploader.tab.get(config.CAR_CREATE_URL)
        await uploader.tab.sleep(2)

        # 3) VIN 입력 후 조회 (직접입력 모드 유도)
        vin_input = await uploader.tab.select('input[type="text"],input[placeholder]')
        await vin_input.send_keys("KMHEC41BBBA225136")
        await uploader.tab.sleep(0.5)

        search_btn = await uploader.tab.evaluate("""
        (() => {
            for (const btn of document.querySelectorAll('button')) {
                const t = (btn.textContent||'').trim();
                if (t.includes('조회')) { btn.click(); return t; }
            }
            return null;
        })()
        """)
        logging.info("조회 클릭: %s", search_btn)
        await uploader.tab.sleep(3)

        # 4) 모달 처리 (직접입력 확인, 면책고지 등)
        for _ in range(5):
            modal_ok = await uploader.tab.evaluate("""
            (() => {
                const d = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')]
                    .find(el => window.getComputedStyle(el).display !== 'none');
                if (!d) return null;
                const text = (d.innerText||'').slice(0,40);
                const btns = d.querySelectorAll('button');
                const confirmIdx = btns.length >= 2 ? 1 : 0;
                if (btns[confirmIdx]) { btns[confirmIdx].click(); return 'modal:' + text; }
                return null;
            })()
            """)
            if modal_ok:
                logging.info("모달 처리: %s", modal_ok)
                await uploader.tab.sleep(1.5)
            else:
                break

        # 5) 사진 업로드 페이지로 바로 이동하려면 submit 루프를 돌려야 합니다.
        #    여기서는 기본정보 → 옵션 → 사진 단계를 빠르게 통과합니다.
        #    (기본정보 검증 오류가 있어도 버튼 클릭 반복으로 사진 단계에 도달하는지 확인)

        _JS_CLICK = """
        (() => {
            const SKIP = ['조회하기', 'Logout', 'My page', 'offers', '(KST)'];
            for (const label of ['다음', '등록하기', '매물등록', '등록완료']) {
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.textContent||'').trim().replace(/\\s+/g,'');
                    if (SKIP.some(s => t.includes(s)) || btn.type === 'reset') continue;
                    if (t === label || t.startsWith(label)) { btn.click(); return t; }
                }
            }
            return null;
        })()
        """

        photo_uploaded = False
        for attempt in range(30):
            await uploader.tab.sleep(2)

            url = await uploader.tab.evaluate("window.location.href")
            if isinstance(url, str) and "MGC_" in url:
                logging.info("등록 완료! URL: %s", url)
                break

            # 사진 input 감지
            has_file = await uploader.tab.evaluate("!!document.querySelector('input[type=\"file\"]')")
            if has_file and not photo_uploaded:
                logging.info("사진 업로드 단계 진입 — %d장 전송 시작", len(ordered))
                try:
                    file_input = await uploader.tab.select("input[type=file]")
                    await file_input.send_file(*ordered)
                    logging.info("send_file 완료")
                    await uploader.tab.sleep(5)  # 업로드 완료 대기
                    photo_uploaded = True
                except Exception as exc:
                    logging.error("사진 업로드 실패: %s", exc)
                    break
                continue

            clicked = await uploader.tab.evaluate(_JS_CLICK)
            if clicked:
                logging.info("[attempt %d] 버튼 클릭: %r", attempt, clicked)

        if photo_uploaded:
            logging.info("사진 업로드 테스트 성공 — 브라우저를 수동으로 확인하세요")
        else:
            logging.warning("사진 업로드 단계에 도달하지 못함 (30회 시도)")

        input("Enter를 눌러 브라우저 종료...")
    finally:
        browser.stop()


if __name__ == "__main__":
    uc.loop().run_until_complete(amain())
