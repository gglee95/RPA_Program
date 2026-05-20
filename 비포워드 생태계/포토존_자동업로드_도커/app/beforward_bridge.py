"""Bridge between the 아무튼 자동업로드 sheet format and BefowordCrawler.

망고카 ListingRow 데이터를 BeForward CarInfo 로 변환하고,
비포워드_자동화 폴더의 BefowordCrawler를 사용해 업로드합니다.

asyncio.to_thread() 로 호출하세요 (Selenium이 sync이므로 별도 스레드에서 실행).

[config 충돌 해결]
upload_mangocar.py 의 config.py 와 비포워드_자동화/config.py 이름이 같아서
sys.modules 에 먼저 등록된 망고카 config 가 비포워드 크롤러까지 오염됩니다.
모듈 임포트 직전에 sys.modules['config'] 를 비포워드 버전으로 교체하고
임포트 완료 후 망고카 버전으로 복원합니다.
"""
from __future__ import annotations

import logging
import re
import sys
import importlib
import importlib.util
from pathlib import Path

logger = logging.getLogger(__name__)

_BF_DIR = Path(__file__).resolve().parent.parent.parent / "비포워드_자동화"


def _import_bf_modules():
    """비포워드 모듈을 config 충돌 없이 임포트."""
    # 1) sys.path 앞에 BF 폴더 삽입
    if str(_BF_DIR) not in sys.path:
        sys.path.insert(0, str(_BF_DIR))

    # 2) 현재 sys.modules['config'] (망고카) 임시 보관
    mango_config = sys.modules.get("config")

    # 3) 비포워드 config.py 를 직접 로드해서 sys.modules['config'] 로 교체
    bf_config_path = _BF_DIR / "config.py"
    spec = importlib.util.spec_from_file_location("config", str(bf_config_path))
    bf_config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf_config)
    sys.modules["config"] = bf_config

    try:
        # 4) 비포워드_crawling, 엔카_크롤러 임포트 (이때 내부에서 config 를 참조)
        import 비포워드_crawling
        import 엔카_크롤러
        BefowordCrawler = 비포워드_crawling.BefowordCrawler
        CarInfo         = 엔카_크롤러.CarInfo
        OptionItem      = 엔카_크롤러.OptionItem
    finally:
        # 5) 망고카 config 복원
        if mango_config is not None:
            sys.modules["config"] = mango_config
        else:
            sys.modules.pop("config", None)

    return BefowordCrawler, CarInfo, OptionItem


BefowordCrawler, CarInfo, OptionItem = _import_bf_modules()


# 망고카 시트 옵션 키 → BeForward 체크박스 표시명 매핑
_OPTION_MAP: dict[str, str | None] = {
    "선루프":           "선루프",
    "가죽시트":         "가죽시트",
    "열선시트(앞좌석)": "열선 시트",
    "통풍시트(앞좌석)": "통풍 시트",
    "후방카메라":       "백 카메라",
    "스마트키":         "Push Start",
    "네비게이션":       "네비게이션",
    "에어컨":           "에어컨",
    "4WD":              None,   # 구동방식 라디오버튼으로 처리 (체크박스 없음)
}


def _build_car_info(listing) -> CarInfo:
    """망고카 ListingRow → BeForward CarInfo 변환."""
    차종    = listing.get("차종").strip()
    세부차종 = listing.get("세부차종").strip()
    car_type = f"{차종} {세부차종}".strip() if 세부차종 else 차종

    mileage = re.sub(r"[,\s]", "", listing.get("실주행거리").strip())

    options: list[OptionItem] = []
    for key, mapped in _OPTION_MAP.items():
        if listing.options.get(key) and mapped:
            options.append(OptionItem(name=key, mapped_name=mapped))

    return CarInfo(
        car_type=car_type,
        year_month=listing.get("연식").strip(),
        mileage=mileage,
        fuel_type=listing.get("유종").strip(),
        transmission=listing.get("미션").strip(),
        color=listing.get("차량색상").strip(),
        seating_capacity=listing.get("인승").strip(),
        price=listing.ad_price_number,
        inspection_chassis_no=listing.identifier,
        options=options,
    )


def upload_listing_to_beforward(listing) -> str:
    """비포워드에 차량 한 건 업로드 (동기 함수 — asyncio.to_thread()로 호출).

    Returns:
        listing_id (str): 업로드 성공 시 BeForward listing ID 또는 'ok'.
        ''             : 실패.
    """
    car_info = _build_car_info(listing)
    car_info.drive_link = listing.drive_url   # type: ignore[attr-defined]
    car_info.sheet_row  = listing.sheet_row   # type: ignore[attr-defined]

    crawler = BefowordCrawler(headless=False)
    try:
        if not crawler.login():
            logger.error("[비포워드] 로그인 실패 (행 %s)", listing.sheet_row)
            return ""

        ok = crawler.fill_vehicle_data(car_info, auto_submit=True)
        submitted = getattr(crawler, "_listing_submitted", False)

        if ok or submitted:
            listing_id = getattr(car_info, "_listing_id", "") or "ok"
            logger.info("[비포워드] 업로드 성공 (행 %s) → ID=%s", listing.sheet_row, listing_id)
            return listing_id

        step  = getattr(crawler, "_last_error_step",  "") or "unknown"
        cause = getattr(crawler, "_last_error_cause", "") or "fill_vehicle_data returned False"
        logger.warning("[비포워드] 업로드 실패 (행 %s) — %s: %s", listing.sheet_row, step, cause)
        return ""

    except Exception:
        logger.exception("[비포워드] 업로드 예외 (행 %s)", listing.sheet_row)
        return ""

    finally:
        try:
            crawler.close()
        except Exception:
            pass
