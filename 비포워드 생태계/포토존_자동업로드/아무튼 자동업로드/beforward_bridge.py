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
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path

logger = logging.getLogger(__name__)

_BF_DIR = Path(__file__).resolve().parent.parent.parent / "비포워드_자동화"
_BEFORWARD_EDIT_URL_PREFIX = "https://external-vendor.beforward.jp/tempVehDetails/edit"


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


def _build_upload_price(base_price: str) -> str:
    """비포워드 기존 자동화와 같은 구간별 마크업 가격을 반환."""
    if not base_price:
        return ""

    try:
        base_value = Decimal(str(base_price))
    except InvalidOperation:
        return ""

    if base_value <= Decimal("1000"):
        markup = Decimal("263")
    elif base_value <= Decimal("1500"):
        markup = Decimal("278")
    elif base_value <= Decimal("2000"):
        markup = Decimal("283")
    elif base_value <= Decimal("3000"):
        markup = Decimal("303")
    elif base_value <= Decimal("5000"):
        markup = Decimal("358")
    elif base_value <= Decimal("6000"):
        markup = Decimal("388")
    elif base_value <= Decimal("7000"):
        markup = Decimal("410")
    elif base_value <= Decimal("8000"):
        markup = Decimal("439")
    elif base_value <= Decimal("10000"):
        markup = Decimal("495")
    elif base_value <= Decimal("15000"):
        markup = Decimal("630")
    elif base_value <= Decimal("20000"):
        markup = Decimal("739")
    else:
        markup = (base_value * Decimal("0.05")).quantize(
            Decimal("1"),
            rounding=ROUND_DOWN,
        )

    final_price = (base_value + markup).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return str(int(final_price))


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

    # 배기량 — AF열의 망고카 listing 페이지에서 스크랩한다. 시트에 컬럼이 없어
    # 망고 페이지가 유일한 소스. 실패하면 폴백 없이 즉시 예외 (글로벌 규칙).
    from mango_displacement import fetch_displacement
    mango_url = listing.get("링크").strip()
    if not mango_url:
        raise RuntimeError(
            f"행 {listing.sheet_row}: AF열(망고카 링크) 비어있음 — 배기량 조회 불가"
        )
    displacement = fetch_displacement(mango_url)

    upload_price = _build_upload_price(listing.ad_price_number)
    if not upload_price:
        raise RuntimeError(
            f"행 {listing.sheet_row}: 광고가({listing.ad_price_raw!r})로 비포워드 업로드 가격 계산 불가"
        )
    logger.info(
        "[비포워드] 가격 계산 (행 %s): 원본=%s → 업로드가=%s",
        listing.sheet_row,
        listing.ad_price_number,
        upload_price,
    )

    return CarInfo(
        car_type=car_type,
        year_month=listing.get("연식").strip(),
        mileage=mileage,
        displacement=displacement,
        fuel_type=listing.get("유종").strip(),
        transmission=listing.get("미션").strip(),
        color=listing.get("차량색상").strip(),
        seating_capacity=listing.get("인승").strip(),
        price=upload_price,
        inspection_chassis_no=listing.identifier,
        options=options,
    )


def upload_listing_to_beforward(
    listing,
    auto_submit: bool = True,
    pause_before_close: bool = False,
) -> str:
    """비포워드에 차량 한 건 업로드 (동기 함수 — asyncio.to_thread()로 호출).

    Args:
        listing: 망고카 ListingRow.
        auto_submit: False면 폼 채우기만 하고 최종 제출 버튼은 누르지 않는다 (dry-run).
        pause_before_close: True면 작업 종료 후 Enter 입력을 기다린 다음 브라우저를
            닫는다. dry-run 시 채워진 폼을 사람이 확인할 수 있도록 사용.

    Returns:
        listing_id (str): 업로드 성공 시 BeForward edit URL 또는 'ok'.
        ''             : 실패.
    """
    car_info = _build_car_info(listing)
    car_info.drive_link = listing.drive_url   # type: ignore[attr-defined]
    car_info.sheet_row  = listing.sheet_row   # type: ignore[attr-defined]

    crawler = BefowordCrawler(headless=False)
    # BeForward 기본 다운로더는 엔카용 EXTERIOR 폴더 가정이라 포토존 카테고리
    # (외부/내부/하부 차대/엔진룸) 구조에서 1장만 받아옴. 포토존 로직(PHOTO_CATEGORIES
    # 순서, alias 매칭, 평탄화) 으로 교체.
    from bf_drive_downloader import download_photozone_drive
    crawler._download_images_from_drive_link = download_photozone_drive  # type: ignore[assignment]

    try:
        if not crawler.login():
            logger.error("[비포워드] 로그인 실패 (행 %s)", listing.sheet_row)
            return ""

        ok = crawler.fill_vehicle_data(car_info, auto_submit=auto_submit)
        submitted = getattr(crawler, "_listing_submitted", False)

        if ok or submitted:
            listing_id = getattr(car_info, "_listing_id", "") or "ok"
            if listing_id != "ok":
                listing_url = f"{_BEFORWARD_EDIT_URL_PREFIX}/{listing_id}"
                logger.info(
                    "[비포워드] 업로드 성공 (행 %s) → ID=%s URL=%s",
                    listing.sheet_row,
                    listing_id,
                    listing_url,
                )
                return listing_url

            logger.info("[비포워드] 업로드 성공 (행 %s) → ID 미확인", listing.sheet_row)
            return listing_id

        step  = getattr(crawler, "_last_error_step",  "") or "unknown"
        cause = getattr(crawler, "_last_error_cause", "") or "fill_vehicle_data returned False"
        logger.warning("[비포워드] 업로드 실패 (행 %s) — %s: %s", listing.sheet_row, step, cause)
        return ""

    except Exception:
        logger.exception("[비포워드] 업로드 예외 (행 %s)", listing.sheet_row)
        return ""

    finally:
        if pause_before_close:
            try:
                input(
                    "\n[DRY-RUN] 비포워드 폼이 채워졌습니다. "
                    "브라우저에서 입력값을 확인한 뒤 Enter 를 누르면 종료합니다... "
                )
            except (EOFError, KeyboardInterrupt):
                pass
        try:
            crawler.close()
        except Exception:
            pass
