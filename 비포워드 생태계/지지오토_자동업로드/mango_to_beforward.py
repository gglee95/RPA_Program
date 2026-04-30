"""
망고월드카 지지오토 차량 → 비포워드 자동 업로드
1. mango_crawler.py 로 지지오토 차량 목록+상세 수집
2. CarInfo 객체로 변환
3. BefowordCrawler.fill_vehicle_data() 로 비포워드 업로드
4. 판매 완료 차량 감지 → BeforwardSuspensionManager 로 게시 정지
"""
import sys
import os
import re
import time
import logging
import traceback
from pathlib import Path
from datetime import datetime

# ── 비포워드_자동화 모듈 경로 추가 ────────────────────────────────────────────
BEFORWARD_DIR = Path(r"C:\Users\gglee\OneDrive\Desktop\비포워드 생태계\비포워드_자동화")
if str(BEFORWARD_DIR) not in sys.path:
    sys.path.insert(0, str(BEFORWARD_DIR))

from 비포워드_crawling import BefowordCrawler  # noqa: E402
from 엔카_크롤러 import CarInfo, OptionItem     # noqa: E402
from beforward_suspension_manager import BeforwardSuspensionManager  # noqa: E402

# ── 현재 디렉토리 (지지오토_자동업로드) ──────────────────────────────────────
HERE = Path(__file__).parent

LOG_FILE = HERE / "mango_to_beforward.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── 설정 ─────────────────────────────────────────────────────────────────────
DETAIL_BASE = "https://mangoworldcar.com/ko/car-detail"
OPTION_MAPPING_FILE = HERE / "비포워드 엔카 옵션_망고카 추가.xlsx"
OPTION_MAPPING_SHEET = "망고카"

# 업로드 대상 브랜드/모델 리스트 (엑셀)
# 시트: 1열=브랜드, 2열=모델 (모델 빈 칸이면 브랜드 전체)
# 파일이 없으면 브랜드/모델 필터 없이 지지오토 전체 수집
TARGET_LIST_FILE = HERE / "업로드대상_브랜드모델.xlsx"
TARGET_LIST_SHEET = "대상"

# 비포워드 계정 (비포워드_자동화/config.py 에서 읽어오거나 직접 지정)
os.environ.setdefault("BEFORWARD_USERNAME", "echam@mangoworldcar.com")
os.environ.setdefault("BEFORWARD_PASSWORD", "VJSXaPQR")

# 테스트 시 True → 자동 제출 안 함 (폼 채운 상태로 멈춤)
DRY_RUN = False


# ── 필드 변환 유틸 ────────────────────────────────────────────────────────────

def _strip_price(raw: str) -> str:
    """'$12,000' → '12000'"""
    if not raw:
        return ""
    cleaned = re.sub(r"[^\d.]", "", str(raw))
    if not cleaned:
        return ""
    try:
        return str(int(float(cleaned)))
    except ValueError:
        return ""


def _apply_beforward_fee(price_usd: int) -> int:
    """망고 USD 가격에 비포워드 업로드용 수수료 가산.

    구간(USD) → 가산액(USD):
        ≤1000:263, ≤1500:278, ≤2000:283, ≤3000:303,
        ≤5000:358, ≤6000:388, ≤7000:410, ≤8000:439,
        ≤10000:495, ≤15000:630, ≤20000:739, 그 외: 5%
    """
    if price_usd <= 1000:    fee = 263
    elif price_usd <= 1500:  fee = 278
    elif price_usd <= 2000:  fee = 283
    elif price_usd <= 3000:  fee = 303
    elif price_usd <= 5000:  fee = 358
    elif price_usd <= 6000:  fee = 388
    elif price_usd <= 7000:  fee = 410
    elif price_usd <= 8000:  fee = 439
    elif price_usd <= 10000: fee = 495
    elif price_usd <= 15000: fee = 630
    elif price_usd <= 20000: fee = 739
    else:                    fee = round(price_usd * 0.05)
    return price_usd + fee


def _normalize_mileage(raw: str) -> str:
    """'50,000KM' → '50000'"""
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", str(raw))
    return digits if digits else ""


def _normalize_displacement(raw: str) -> str:
    """'2,400cc' → '2400'  숫자만 추출 (비포워드 필수 입력값)"""
    if not raw:
        return ""
    digits = re.sub(r"[^\d]", "", str(raw))
    return digits if digits else ""


def _normalize_fuel(raw: str) -> str:
    """GASOLINE / DIESEL / LPG / ELECTRIC / HYBRID → 비포워드 FUEL_MAP 키"""
    if not raw:
        return ""
    return raw.strip().lower()


def _normalize_transmission(raw: str) -> str:
    """AUTO / MANUAL / DCT / CVT → 비포워드 TRANSMISSION_MAP 키"""
    if not raw:
        return ""
    mapping = {
        "AUTO": "automatic",
        "AUTOMATIC": "automatic",
        "MANUAL": "manual",
        "DCT": "dct",
        "CVT": "cvt",
    }
    return mapping.get(raw.strip().upper(), raw.strip().lower())


def _normalize_color(raw: str) -> str:
    """BLACK / WHITE / ... → 비포워드 COLOR_MAP_KO 키 (소문자로 전달해도 매핑됨)"""
    if not raw:
        return ""
    return raw.strip().lower()


# ── 망고카 옵션 → 비포워드 옵션 매핑 ─────────────────────────────────────────

def _normalize_option_name(raw: str) -> str:
    """옵션명 비교용 정규화: 공백/구분문자 제거, 소문자화"""
    if raw is None:
        return ""
    return re.sub(r"[\s\-_·/()]+", "", str(raw).strip()).lower()


_MANGO_OPTION_MAP_CACHE: dict[str, str] | None = None


def _load_mango_option_map() -> dict[str, str]:
    """엑셀 '망고카' 시트 A열(망고카) → B열(비포워드) 매핑 로드"""
    global _MANGO_OPTION_MAP_CACHE
    if _MANGO_OPTION_MAP_CACHE is not None:
        return _MANGO_OPTION_MAP_CACHE

    mapping: dict[str, str] = {}
    try:
        from openpyxl import load_workbook
        wb = load_workbook(OPTION_MAPPING_FILE, data_only=True, read_only=True)
        ws = wb[OPTION_MAPPING_SHEET] if OPTION_MAPPING_SHEET in wb.sheetnames else wb.active
        for row in ws.iter_rows(min_row=2, min_col=1, max_col=2, values_only=True):
            mango_name = str(row[0]).strip() if row and row[0] is not None else ""
            beforward_name = str(row[1]).strip() if row and row[1] is not None else ""
            if mango_name and beforward_name:
                mapping[_normalize_option_name(mango_name)] = beforward_name
        wb.close()
        log.info("망고카 옵션 매핑 로드: %d개", len(mapping))
    except Exception as e:
        log.warning("망고카 옵션 매핑 로드 실패: %s", e)

    _MANGO_OPTION_MAP_CACHE = mapping
    return mapping


def _map_mango_options(raw_options: list[str]) -> list[OptionItem]:
    """망고카 추출 옵션 → 엑셀 매핑표 기준 비포워드 OptionItem 리스트"""
    option_map = _load_mango_option_map()
    mapped: list[OptionItem] = []
    seen: set[str] = set()
    unmapped: list[str] = []

    for raw in raw_options:
        mango_name = str(raw).strip()
        if not mango_name:
            continue
        bf_name = option_map.get(_normalize_option_name(mango_name))
        if not bf_name:
            unmapped.append(mango_name)
            continue
        if bf_name in seen:
            continue
        mapped.append(OptionItem(name=mango_name, mapped_name=bf_name))
        seen.add(bf_name)

    if mapped:
        log.info("  옵션 매핑: %d/%d 건 매핑됨", len(mapped), len(raw_options))
    if unmapped:
        log.info("  옵션 매핑 없음: %s", ", ".join(unmapped[:10]))
    return mapped


# 영문 모델명 → 재원표 한국어 키워드 매핑
_EN_TO_KO_MODEL = {
    "Grandeur":  "그랜저",
    "Sonata":    "소나타",
    "Avante":    "아반떼",
    "Elantra":   "아반떼",
    "Santa Fe":  "싼타페",
    "Tucson":    "투싼",
    "Ioniq":     "아이오닉",
    "Kona":      "코나",
    "Casper":    "캐스퍼",
    "Palisade":  "팰리세이드",
    "Sportage":  "스포티지",
    "Carnival":  "카니발",
    "Stinger":   "스팅어",
    "Seltos":    "셀토스",
    "Morning":   "모닝",
    "Soul":      "소울",
    "Spark":     "스파크",
    "SM6":       "SM6",
    "Ray":       "레이",
    "Ray ":      "레이",      # 뒤 공백으로 'Array' 오매칭 방지
    "Sorento":   "쏘렌토",
    "Mohave":    "모하비",
    "Starex":    "스타렉스",
    "Porter":    "포터",
    "Bongo":     "봉고",
    "Cruze":     "크루즈",
    "Malibu":    "말리부",
    "Trax":      "트랙스",
    "Captiva":   "캡티바",
    "Equinox":   "이쿼녹스",
}


def _append_korean_model(car_type: str) -> str:
    """영문 차종명에 재원표 한국어 키워드를 추가 (이미 있으면 그대로)."""
    ct_lower = car_type.lower()
    for en, ko in _EN_TO_KO_MODEL.items():
        if en.lower() in ct_lower and ko not in car_type:
            return f"{car_type} {ko}"
    return car_type


def _make_car_info(detail: dict) -> CarInfo:
    """
    mango_crawler 상세 dict → CarInfo 객체 변환.

    mango 데이터 키:
        상품코드, 차량명, 연식, 가격(USD), 변속기, 색상, 배기량,
        구동방식, 연료타입, 최초등록일, 위치, 차대번호, 차대번호_상세,
        주행거리(상세), 보유옵션(전체), 판매자
    """
    code = detail.get("상품코드", "")

    info = CarInfo()

    # 차종명 — 비포워드 재원표 조회에 사용 (가장 중요)
    # 영문 공개 페이지에서 수집된 경우 한국어 키워드를 추가해 재원표 매칭 보정
    info.car_type = _append_korean_model((detail.get("차량명") or "").strip())

    # 연식 (예: "2020")
    yr = detail.get("연식", "")
    if yr:
        info.year_month = yr.replace("년", "").strip()

    # 주행거리
    info.mileage = _normalize_mileage(detail.get("주행거리(상세)", ""))

    # 배기량
    info.displacement = _normalize_displacement(detail.get("배기량", ""))

    # 연료
    info.fuel_type = _normalize_fuel(detail.get("연료타입", ""))

    # 변속기
    info.transmission = _normalize_transmission(detail.get("변속기", ""))

    # 색상
    info.color = _normalize_color(detail.get("색상", ""))

    # 위치
    info.location = (detail.get("위치") or "").strip()

    # 가격 (USD 숫자만) — 비포워드 업로드용 수수료 가산
    raw_price = _strip_price(detail.get("가격(USD)", ""))
    if raw_price:
        info.price = str(_apply_beforward_fee(int(raw_price)))
        log.info("  가격 변환: $%s → $%s (수수료 가산)", raw_price, info.price)
    else:
        info.price = ""

    # 차대번호 — 상세 페이지 우선, 없으면 목록 데이터
    vin = (detail.get("차대번호_상세") or detail.get("차대번호") or "").strip()
    info.inspection_chassis_no = vin

    # 옵션 리스트 — 망고카 옵션을 엑셀 매핑표에 따라 비포워드 옵션으로 변환
    opts_raw = detail.get("보유옵션(전체)", "")
    if opts_raw:
        raw_list = [o.strip() for o in opts_raw.split("/") if o.strip()]
        info.options = _map_mango_options(raw_list)
    else:
        info.options = []

    # 이미지 소스 — 망고 공개 상세 페이지 (MangocarImageDownloader 가 처리)
    if code:
        info.drive_link = f"{DETAIL_BASE}/{code}"

    return info


# ── 수집 단계 ─────────────────────────────────────────────────────────────────

def _load_target_brand_models() -> list[tuple[str, str]]:
    """엑셀에서 업로드 대상 (브랜드, 모델) 리스트 로드.

    파일/시트 없으면 빈 리스트 반환 → 필터 없이 전체 수집.
    """
    if not TARGET_LIST_FILE.exists():
        log.info("대상 리스트 파일 없음 → 전체 수집 (%s)", TARGET_LIST_FILE.name)
        return []

    targets: list[tuple[str, str]] = []
    try:
        from openpyxl import load_workbook
        wb = load_workbook(TARGET_LIST_FILE, data_only=True, read_only=True)
        ws = wb[TARGET_LIST_SHEET] if TARGET_LIST_SHEET in wb.sheetnames else wb.active
        for row in ws.iter_rows(min_row=2, min_col=1, max_col=2, values_only=True):
            brand = str(row[0]).strip() if row and row[0] is not None else ""
            model = str(row[1]).strip() if row and len(row) > 1 and row[1] is not None else ""
            if brand:
                targets.append((brand, model))
        wb.close()
        log.info("대상 브랜드/모델 로드: %d건", len(targets))
    except Exception as e:
        log.warning("대상 리스트 로드 실패: %s", e)
    return targets


def collect_mango_data() -> list[dict]:
    """
    mango_crawler.py 의 함수를 직접 호출해 차량 상세 데이터 수집.

    엑셀 대상 리스트가 있으면 (브랜드, 모델) 별로 순회하며 검색→누적.
    없으면 필터 없이 전체 수집.
    """
    log.info("망고월드카 크롤링 시작...")

    # mango_crawler 모듈 import (같은 디렉토리)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mango_crawler", HERE / "mango_crawler.py"
    )
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)

    targets = _load_target_brand_models()

    driver = mc.make_driver()
    detail_rows: list[dict] = []

    try:
        mc.login(driver)

        # 대상 리스트가 있으면 (브랜드, 모델) 별 순회, 없으면 1회 전체
        if targets:
            list_rows: list[dict] = []
            seen_codes: set[str] = set()
            for i, (brand, model) in enumerate(targets, 1):
                log.info("─" * 60)
                log.info("[%d/%d] 필터 적용: 브랜드='%s' 모델='%s'",
                         i, len(targets), brand, model or "(전체)")
                mc.apply_filters(driver, brand=brand, model=model or None)
                rows = mc.collect_list(driver)
                # 상품코드 기준 중복 제거하며 누적
                for r in rows:
                    code = r.get("상품코드", "")
                    if code and code not in seen_codes:
                        seen_codes.add(code)
                        list_rows.append(r)
                log.info("  → 누계 %d건", len(list_rows))
        else:
            mc.apply_filters(driver)
            list_rows = mc.collect_list(driver)

        if not list_rows:
            log.warning("목록 수집 결과 없음")
            return []

        # ── 목록 단계에서 지지오토 매물만 1차 필터 (판매자 누수 방지) ──
        SELLER_RE = re.compile(r"지지오토|GG[-\s]?AUTO", re.IGNORECASE)
        filtered_rows = []
        skipped_seller = []
        for r in list_rows:
            seller_name = (r.get("판매자명") or "").strip()
            member_type = (r.get("회원구분") or "").strip()
            seller_full = f"{member_type} {seller_name}".strip()
            if not SELLER_RE.search(seller_full):
                skipped_seller.append(f"{r.get('상품코드','?')}={seller_full}")
                continue
            filtered_rows.append(r)
        if skipped_seller:
            log.warning("판매자 미일치 → 제외 %d건: %s",
                        len(skipped_seller), ", ".join(skipped_seller[:5]))
        log.info("판매자 필터 후: %d/%d건 (지지오토)", len(filtered_rows), len(list_rows))

        codes = [r.get("상품코드", "") for r in filtered_rows if r.get("상품코드", "").startswith("MGC_")]
        codes = list(dict.fromkeys(codes))
        log.info("상세 크롤링 대상: %d건", len(codes))

        for i, code in enumerate(codes, 1):
            log.info("[%d/%d] %s", i, len(codes), code)
            d = mc.extract_detail(driver, code)

            # 목록의 차대번호/판매자명 병합
            matched = next(
                (r for r in filtered_rows if r.get("상품코드", "") == code), None
            )
            if matched:
                if matched.get("차대번호") and not d.get("차대번호"):
                    d["차대번호"] = matched["차대번호"]
                # 목록의 판매자명 항상 우선 (상세페이지 정규식보다 신뢰도 높음)
                if matched.get("판매자명"):
                    d["판매자"] = matched["판매자명"]

            detail_rows.append(d)
            time.sleep(1.5)

    finally:
        driver.quit()
        log.info("크롤러 드라이버 종료")

    log.info("총 %d건 수집 완료", len(detail_rows))
    return detail_rows


# ── 업로드 단계 ───────────────────────────────────────────────────────────────

def upload_to_beforward(detail_rows: list[dict]) -> tuple[int, int]:
    """
    CarInfo 로 변환 후 비포워드 업로드.
    Returns:
        (총시도, 성공)
    """
    if not detail_rows:
        log.warning("업로드할 데이터 없음")
        return 0, 0

    uploader = BefowordCrawler(headless=False)

    log.info("비포워드 로그인...")
    if not uploader.login():
        log.error("비포워드 로그인 실패")
        return 0, 0

    total = 0
    success = 0

    for i, detail in enumerate(detail_rows, 1):
        code = detail.get("상품코드", f"ROW_{i}")
        log.info("[%d/%d] 업로드: %s", i, len(detail_rows), code)

        car_info = _make_car_info(detail)

        if not car_info.car_type:
            log.warning("  [SKIP] 차량명 없음 → 건너뜀")
            continue

        if not car_info.inspection_chassis_no:
            log.warning("  [SKIP] 차대번호 없음 → 건너뜀 (%s)", code)
            continue

        if not car_info.price:
            log.warning("  [SKIP] 가격 없음 → 건너뜀 (%s)", code)
            continue

        # ── 안전장치: 지지오토 매물만 업로드 (필터 누수 방지) ──
        seller = (detail.get("판매자") or "").strip()
        if not re.search(r"GG[-\s]?AUTO|지지오토", seller, re.IGNORECASE):
            log.warning("  [SKIP] 판매자 미확인 → 업로드 차단 (%s, 판매자='%s')",
                        code, seller)
            continue

        log.info("  차종: %s | 연식: %s | 주행: %s | 가격: $%s | VIN: %s",
                 car_info.car_type, car_info.year_month, car_info.mileage,
                 car_info.price, car_info.inspection_chassis_no)

        total += 1
        try:
            ok = uploader.fill_vehicle_data(car_info, auto_submit=not DRY_RUN)

            submitted = getattr(uploader, '_listing_submitted', False)
            if DRY_RUN and ok and not submitted:
                log.info("  [DRY_RUN] form filled only; not submitted")
            elif ok or submitted:
                listing_id = getattr(car_info, '_listing_id', '')
                log.info("  [OK] 업로드 성공 | ID=%s", listing_id)
                success += 1
            else:
                step  = getattr(uploader, '_last_error_step', '미캡처')
                cause = getattr(uploader, '_last_error_cause', '')
                log.error("  [FAIL] 단계: %s | 원인: %s", step, cause)

        except Exception as e:
            log.error("  [ERROR] %s\n%s", e, traceback.format_exc())

            # Chrome 세션 복구
            err_s = str(e).lower()
            if any(k in err_s for k in ('invalid session', 'session', 'crashed', 'disconnected')):
                log.info("  Chrome 세션 복구 시도...")
                try:
                    uploader.close()
                except Exception:
                    pass
                time.sleep(2)
                uploader._setup_driver()
                if not uploader.login():
                    log.error("  재로그인 실패 — 업로드 중단")
                    break

        # 이미지 임시파일 정리
        downloads = getattr(uploader, '_last_downloaded_image_files', [])
        if downloads:
            try:
                uploader._cleanup_downloaded_images(downloads)
            except Exception:
                pass
            uploader._last_downloaded_image_files = []

        time.sleep(2)

    try:
        uploader.close()
    except Exception:
        pass

    return total, success


# ── 판매 완료 감지 + 게시 정지 ───────────────────────────────────────────────

# 망고 공개 상세 페이지에서 판매 완료 여부를 판단하는 XPath
SOLD_XPATH = "/html/body/div[1]/div/div/div[2]/p"


def _is_sold_on_mango(driver, code: str) -> bool:
    """망고 공개 상세 페이지에서 판매 완료 여부 확인.

    XPath SOLD_XPATH 가 존재하면 판매 완료로 판단.
    """
    url = f"{DETAIL_BASE}/{code}"
    try:
        driver.get(url)
        time.sleep(1.5)
        elems = driver.find_elements("xpath", SOLD_XPATH)
        return len(elems) > 0
    except Exception as e:
        log.warning("  [WARN] 판매여부 확인 실패 (%s): %s", code, e)
        return False


def suspend_sold_vehicles(detail_rows: list[dict]) -> tuple[list[str], int]:
    """수집된 차량 중 판매 완료된 것을 비포워드에서 게시 정지.

    Args:
        detail_rows: collect_mango_data() 반환값

    Returns:
        (판매완료_VIN_목록, 게시정지_성공수)
    """
    if not detail_rows:
        log.warning("점검할 차량 데이터 없음")
        return [], 0

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "mango_crawler", HERE / "mango_crawler.py"
    )
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)

    driver = mc.make_driver()
    sold_codes: list[tuple[str, str]] = []  # (code, vin)

    try:
        for row in detail_rows:
            code = row.get("상품코드", "")
            vin = (row.get("차대번호_상세") or row.get("차대번호") or "").strip()
            if not code or not vin:
                continue
            if _is_sold_on_mango(driver, code):
                log.info("  [SOLD] %s (VIN: %s)", code, vin)
                sold_codes.append((code, vin))
            else:
                log.info("  [ON SALE] %s", code)
    finally:
        driver.quit()

    sold_vins = [vin for _, vin in sold_codes]

    if not sold_codes:
        log.info("판매 완료 차량 없음 — 게시 정지 불필요")
        return [], 0

    log.info("판매 완료 %d건 → 비포워드 게시 정지 시작", len(sold_codes))

    suspender = BeforwardSuspensionManager(headless=False)
    if not suspender.login():
        log.error("비포워드 로그인 실패 — 게시 정지 중단")
        return sold_vins, 0

    suspended = 0
    for code, vin in sold_codes:
        log.info("  게시 정지 시도: %s (VIN: %s)", code, vin)
        try:
            ok = suspender.search_and_delete_listing(vin)
            if ok:
                log.info("  [OK] 게시 정지 완료: %s", code)
                suspended += 1
            else:
                log.warning("  [FAIL] 게시 정지 실패: %s", code)
        except Exception as e:
            log.error("  [ERROR] %s: %s", code, e)
        time.sleep(1)

    try:
        suspender.close()
    except Exception:
        pass

    return sold_vins, suspended


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("망고월드카 → 비포워드 자동 업로드 시작")
    log.info("=" * 60)

    # 1. 수집
    detail_rows = collect_mango_data()

    if not detail_rows:
        log.warning("수집된 차량 없음. 종료.")
        return

    # 2. 판매 완료 차량 → 게시 정지
    sold_vins, suspended_cnt = suspend_sold_vehicles(detail_rows)
    if sold_vins:
        log.info("판매완료 감지: %d건 / 게시정지 성공: %d건", len(sold_vins), suspended_cnt)

    # 3. 업로드 (판매 완료 차량 제외)
    sold_vin_set = set(sold_vins)
    upload_rows = [
        r for r in detail_rows
        if (r.get("차대번호_상세") or r.get("차대번호") or "").strip() not in sold_vin_set
    ]

    total, success = upload_to_beforward(upload_rows)

    log.info("=" * 60)
    log.info("완료: 업로드 %d/%d 성공 | 게시정지 %d/%d 완료",
             success, total, suspended_cnt, len(sold_vins))
    log.info("=" * 60)


if __name__ == "__main__":
    main()
