"""
망고월드카 지지오토 차량 크롤러 v2
- adminv2: 테이블 헤더 기반 정확한 컬럼 추출
- 상세 페이지: Next.js 텍스트 패턴 + 스크롤 + API 탐지
"""

import time
import logging
import traceback
import re
import json
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
import pandas as pd

# ──────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────
ADMIN_URL   = "https://adminv2.mangoworldcar.com"
MANAGE_URL  = "https://adminv2.mangoworldcar.com/cars/manage"
DETAIL_BASE = "https://mangoworldcar.com/ko/car-detail"
EMAIL    = "admin@mangoworldcar.com"
PASSWORD = "mango8802!"

OUTPUT_DIR = Path(__file__).parent
LOG_FILE   = OUTPUT_DIR / "mango_crawler.log"
MAPPING_FILE = OUTPUT_DIR / "비포워드 엔카 옵션_망고카 추가.xlsx"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

WAIT = 20


# ──────────────────────────────────────────────────────────
# 드라이버
# ──────────────────────────────────────────────────────────
def make_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1600,960")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=ko-KR")
    driver = uc.Chrome(options=opts, version_main=147)
    driver.set_page_load_timeout(60)
    return driver


def wc(driver, by, val, t=WAIT):
    el = WebDriverWait(driver, t).until(EC.element_to_be_clickable((by, val)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    el.click()
    return el


def wp(driver, by, val, t=WAIT):
    return WebDriverWait(driver, t).until(EC.presence_of_element_located((by, val)))


def scroll_to_bottom(driver):
    """페이지 끝까지 스크롤해 lazy-load 유발"""
    last = driver.execute_script("return document.body.scrollHeight")
    for _ in range(10):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)
        now = driver.execute_script("return document.body.scrollHeight")
        if now == last:
            break
        last = now
    driver.execute_script("window.scrollTo(0, 0);")


# ──────────────────────────────────────────────────────────
# 옵션 매핑 로드
# ──────────────────────────────────────────────────────────
def load_option_mapping():
    """
    엑셀 파일에서 망고카 → 비포워드 옵션 매핑표 로드
    """
    mapping_dict = {}
    try:
        df = pd.read_excel(MAPPING_FILE, sheet_name="망고카")
        # A열: 망고카, B열: 비포워드
        for _, row in df.iterrows():
            mango_opt = str(row.iloc[0]).strip()  # A열
            before_opt = str(row.iloc[1]).strip()  # B열
            if mango_opt and mango_opt != "nan" and before_opt and before_opt != "nan":
                mapping_dict[mango_opt] = before_opt
        log.info("옵션 매핑표 로드 완료: %d건", len(mapping_dict))
        return mapping_dict
    except Exception as e:
        log.error("옵션 매핑표 로드 실패: %s", e)
        return {}


def map_mango_to_before(mango_options, mapping_dict):
    """
    망고카 옵션 목록을 비포워드 옵션으로 매핑
    """
    before_options = []
    mapping_log = []
    
    for mango_opt in mango_options:
        mango_opt_clean = mango_opt.strip()
        # 정확히 일치하는 매핑 찾기
        if mango_opt_clean in mapping_dict:
            before_opt = mapping_dict[mango_opt_clean]
            before_options.append(before_opt)
            mapping_log.append(f"{mango_opt_clean} → {before_opt}")
        else:
            # 부분 일치 시도 (망고카 옵션명이 매핑표의 키를 포함하는 경우)
            found = False
            for key, value in mapping_dict.items():
                if key in mango_opt_clean or mango_opt_clean in key:
                    before_options.append(value)
                    mapping_log.append(f"{mango_opt_clean} → {value} (부분일치: {key})")
                    found = True
                    break
            if not found:
                mapping_log.append(f"{mango_opt_clean} → 매핑 없음")
    
    # 중복 제거
    before_options = list(dict.fromkeys(before_options))
    
    if mapping_log:
        log.debug("옵션 매핑 로그:\n  %s", "\n  ".join(mapping_log))
    
    return before_options


# ──────────────────────────────────────────────────────────
# 로그인
# ──────────────────────────────────────────────────────────
def login(driver):
    log.info("로그인: %s", ADMIN_URL)
    driver.get(ADMIN_URL)
    time.sleep(2)

    # ID 필드 (placeholder='ID')
    id_el = wp(driver, By.XPATH,
        "//input[@placeholder='ID' or @name='email' or @name='id' or @name='username' or @type='text']")
    id_el.clear()
    id_el.send_keys(EMAIL)

    pw_el = wp(driver, By.XPATH, "//input[@type='password']")
    pw_el.clear()
    pw_el.send_keys(PASSWORD)

    # "Login" 버튼 (영문)
    btn = wp(driver, By.XPATH,
        "//button[text()='Login' or @type='submit']")
    btn.click()
    time.sleep(3)
    log.info("로그인 후 URL: %s", driver.current_url)


# ──────────────────────────────────────────────────────────
# 필터 적용
# ──────────────────────────────────────────────────────────
def _click_dropdown_option(driver, label: str) -> bool:
    """열린 드롭다운에서 텍스트가 일치하는 옵션을 클릭."""
    # 정확 일치 우선, 없으면 부분 일치
    xpaths = [
        f"//*[contains(@class,'dropdown') or contains(@role,'option') or contains(@class,'option')]"
        f"//*[normalize-space(text())={repr(label)}]",
        f"//li[normalize-space(.)={repr(label)}]",
        f"//*[normalize-space(text())={repr(label)}]",
        f"//*[contains(@class,'dropdown') or contains(@role,'option') or contains(@class,'option')]"
        f"//*[contains(normalize-space(.), {repr(label)})]",
    ]
    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
            for el in elems:
                try:
                    if el.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        time.sleep(0.15)
                        el.click()
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def select_brand(driver, brand: str) -> bool:
    """브랜드 카테고리 드롭다운 선택"""
    log.info("브랜드 선택: %s", brand)
    try:
        wc(driver, By.XPATH, '//*[@id="car-list-filter-form"]/div[4]/div/button[1]')
        time.sleep(1)
        if _click_dropdown_option(driver, brand):
            log.info("  → 브랜드 '%s' 선택", brand)
            time.sleep(0.8)
            return True
        log.warning("  브랜드 '%s' 옵션 없음", brand)
        driver.save_screenshot(str(OUTPUT_DIR / "err_brand.png"))
        return False
    except Exception as e:
        log.warning("브랜드 선택 실패: %s", e)
        driver.save_screenshot(str(OUTPUT_DIR / "err_brand.png"))
        return False


def select_model(driver, model: str) -> bool:
    """모델 드롭다운 선택 (브랜드 선택 후 활성화됨)"""
    log.info("모델 선택: %s", model)
    try:
        wc(driver, By.XPATH, '//*[@id="car-list-filter-form"]/div[4]/div/button[2]')
        time.sleep(1)
        if _click_dropdown_option(driver, model):
            log.info("  → 모델 '%s' 선택", model)
            time.sleep(0.8)
            return True
        log.warning("  모델 '%s' 옵션 없음", model)
        driver.save_screenshot(str(OUTPUT_DIR / "err_model.png"))
        return False
    except Exception as e:
        log.warning("모델 선택 실패: %s", e)
        driver.save_screenshot(str(OUTPUT_DIR / "err_model.png"))
        return False


def apply_filters(driver, brand: str | None = None, model: str | None = None):
    """필터 적용. brand/model 지정 시 해당 카테고리만 검색."""
    log.info("관리 페이지 이동: %s", MANAGE_URL)
    driver.get(MANAGE_URL)
    time.sleep(3)
    driver.save_screenshot(str(OUTPUT_DIR / "01_manage.png"))

    # ① 판매중 체크박스
    log.info("① 판매중 체크박스")
    try:
        wc(driver, By.XPATH, '//*[@id="car-status-is-active"]')
        time.sleep(0.8)
    except Exception as e:
        log.warning("판매중 체크 실패: %s", e)
        driver.save_screenshot(str(OUTPUT_DIR / "err_step1.png"))

    # ② 브랜드 (옵션)
    if brand:
        select_brand(driver, brand)

    # ③ 모델 (브랜드 선택 후에만 활성화)
    if brand and model:
        select_model(driver, model)

    # ④ 판매자 드롭다운
    log.info("④ 판매자 드롭다운")
    try:
        wc(driver, By.XPATH,
            '//*[@id="car-list-filter-form"]/div[8]/div/button')
        time.sleep(1)

        # 지지오토 선택
        options = driver.find_elements(By.XPATH,
            "//*[contains(@class,'dropdown') or contains(@role,'option') or contains(@class,'option')]"
            "//*[contains(text(),'지지오토')] | //*[contains(text(),'지지오토')]")
        if options:
            options[0].click()
            log.info("  → 지지오토 선택")
        else:
            log.warning("  지지오토 옵션 없음")
            driver.save_screenshot(str(OUTPUT_DIR / "err_step2.png"))
        time.sleep(0.8)
    except Exception as e:
        log.warning("드롭다운 실패: %s", e)
        driver.save_screenshot(str(OUTPUT_DIR / "err_step2.png"))

    # ⑤ 검색
    log.info("⑤ 검색 버튼")
    try:
        wc(driver, By.XPATH,
            '//*[@id="car-list-filter-form"]/div[9]/div[2]/button[1]')
    except Exception:
        try:
            wc(driver, By.XPATH, "//button[contains(text(),'검색')]")
        except Exception as e:
            log.error("검색 버튼 실패: %s", e)
            driver.save_screenshot(str(OUTPUT_DIR / "err_step3.png"))
    time.sleep(3)
    driver.save_screenshot(str(OUTPUT_DIR / "02_search_result.png"))


# ──────────────────────────────────────────────────────────
# 테이블 헤더 파싱
# ──────────────────────────────────────────────────────────
def get_headers(driver):
    """테이블 헤더 텍스트 → 인덱스 매핑"""
    try:
        ths = driver.find_elements(By.XPATH, "//table//thead//th")
        headers = [th.text.strip() for th in ths]
        log.info("테이블 헤더: %s", headers)
        return headers
    except Exception:
        return []


# ──────────────────────────────────────────────────────────
# 테이블 행 파싱
# ──────────────────────────────────────────────────────────
def parse_rows(driver, headers):
    rows_data = []
    try:
        trs = driver.find_elements(By.XPATH, "//table//tbody/tr")
        for tr in trs:
            tds = tr.find_elements(By.TAG_NAME, "td")
            cells = [td.text.strip() for td in tds]

            row = {}
            # 헤더 기반 매핑
            if headers:
                for i, h in enumerate(headers):
                    if i < len(cells) and h:
                        row[h] = cells[i]
            else:
                row["_cells"] = cells

            # 상품코드/차대번호 정규식 추출 (전체 텍스트에서)
            full = " ".join(cells)
            code = re.search(r'MGC_\d{6}_\d+', full)
            vin  = re.search(r'\b[A-HJ-NPR-Z0-9]{14,17}\b', full)

            # 링크에서 상품코드 추출 (더 안정적)
            try:
                links = tr.find_elements(By.TAG_NAME, "a")
                for a in links:
                    href = a.get_attribute("href") or ""
                    m = re.search(r'MGC_\d{6}_\d+', href)
                    if m and not code:
                        code = m
            except Exception:
                pass

            row["상품코드"] = code.group() if code else row.get("상품코드", "")
            row["차대번호"] = vin.group()  if vin  else row.get("차대번호", "")

            if any(v for v in row.values()):
                rows_data.append(row)
    except Exception as e:
        log.error("행 파싱 오류: %s", e)
    return rows_data


def _row_key(row):
    code = row.get("?곹뭹肄붾뱶", "")
    vin = row.get("李⑤?踰덊샇", "")
    if code or vin:
        return f"{code}|{vin}"
    cells = row.get("_cells")
    if cells:
        return "|".join(cells)
    return "|".join(str(v) for v in row.values())


def _table_signature(driver):
    try:
        trs = driver.find_elements(By.XPATH, "//table//tbody/tr")
        return "\n".join(tr.text.strip() for tr in trs[:3])
    except Exception:
        return ""


def _find_next_page_button(driver, next_page):
    xpaths = [
        "//a[@rel='next']",
        "//button[@rel='next']",
        "//a[contains(translate(@aria-label,'NEXT','next'),'next')]",
        "//button[contains(translate(@aria-label,'NEXT','next'),'next')]",
        "//a[contains(translate(@title,'NEXT','next'),'next')]",
        "//button[contains(translate(@title,'NEXT','next'),'next')]",
        "//a[contains(translate(@class,'NEXT','next'),'next')]",
        "//button[contains(translate(@class,'NEXT','next'),'next')]",
        "//li[contains(translate(@class,'NEXT','next'),'next')]/a",
        "//a[normalize-space()='Next' or normalize-space()='>' or normalize-space()='›' or normalize-space()='다음']",
        "//button[normalize-space()='Next' or normalize-space()='>' or normalize-space()='›' or normalize-space()='다음']",
        f"//a[normalize-space()='{next_page}']",
        f"//button[normalize-space()='{next_page}']",
    ]
    for xp in xpaths:
        for el in driver.find_elements(By.XPATH, xp):
            try:
                cls = (el.get_attribute("class") or "").lower()
                aria_disabled = (el.get_attribute("aria-disabled") or "").lower()
                disabled = el.get_attribute("disabled")
                if disabled or aria_disabled == "true" or "disabled" in cls or "not-allowed" in cls:
                    continue
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
    return None


def _click_next_page(driver, page):
    before = _table_signature(driver)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(0.5)

    nxt = _find_next_page_button(driver, page + 1)
    if not nxt:
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
        time.sleep(0.2)
        driver.execute_script("arguments[0].click();", nxt)
    except Exception:
        nxt.click()

    for _ in range(20):
        time.sleep(0.5)
        after = _table_signature(driver)
        if after and after != before:
            return True
    log.warning("  next page click did not change table; stopping")
    return False


# ──────────────────────────────────────────────────────────
# 전체 목록 수집 (페이지네이션)
# ──────────────────────────────────────────────────────────
def collect_list(driver):
    headers = get_headers(driver)
    all_rows = []
    seen = set()
    page = 1

    while True:
        log.info("  페이지 %d 수집...", page)
        time.sleep(2)
        rows = parse_rows(driver, headers)
        if not rows:
            log.info("  행 없음 → 중단")
            break
        new_rows = []
        for row in rows:
            key = _row_key(row)
            if key and key in seen:
                continue
            seen.add(key)
            new_rows.append(row)
        all_rows.extend(new_rows)
        log.info("  page %d rows=%d new=%d total=%d", page, len(rows), len(new_rows), len(all_rows))
        if _click_next_page(driver, page):
            page += 1
            continue
        log.info("  no next page found")
        break
        log.info("  → %d건 (누계 %d건)", len(rows), len(all_rows))

        # 다음 페이지 시도
        try:
            nxt = driver.find_element(By.XPATH,
                "//a[contains(@aria-label,'Next') or contains(@class,'next')]"
                "[not(contains(@class,'disabled'))]"
                " | //li[contains(@class,'next')][not(contains(@class,'disabled'))]/a"
                " | //button[contains(@aria-label,'Next')][not(@disabled)]")
            nxt.click()
            page += 1
            time.sleep(2)
        except NoSuchElementException:
            log.info("  마지막 페이지")
            break

    log.info("목록 수집 완료: %d건", len(all_rows))
    return all_rows


# ──────────────────────────────────────────────────────────
# 상세 페이지 파싱
# ──────────────────────────────────────────────────────────
def _row_key(row):
    full = " ".join(str(v) for v in row.values())
    code = re.search(r"MGC_\d{6}_\d+", full)
    vin = re.search(r"\b[A-HJ-NPR-Z0-9]{14,17}\b", full)
    if code or vin:
        return f"{code.group() if code else ''}|{vin.group() if vin else ''}"
    return full


def _table_signature(driver):
    try:
        rows = driver.find_elements(By.XPATH, "//table//tbody/tr")
        return "\n".join(row.text.strip() for row in rows[:3])
    except Exception:
        return ""


def _find_next_page_button(driver, next_page):
    next_labels = ["Next", ">", "\u203a", "\u00bb", "\ub2e4\uc74c", str(next_page)]
    xpaths = [
        "//a[@rel='next']",
        "//button[@rel='next']",
        "//a[contains(translate(@aria-label,'NEXT','next'),'next')]",
        "//button[contains(translate(@aria-label,'NEXT','next'),'next')]",
        "//a[contains(translate(@title,'NEXT','next'),'next')]",
        "//button[contains(translate(@title,'NEXT','next'),'next')]",
        "//a[contains(translate(@class,'NEXT','next'),'next')]",
        "//button[contains(translate(@class,'NEXT','next'),'next')]",
        "//li[contains(translate(@class,'NEXT','next'),'next')]/a",
    ]
    for label in next_labels:
        xpaths.append(f"//a[normalize-space()='{label}']")
        xpaths.append(f"//button[normalize-space()='{label}']")

    for xpath in xpaths:
        for el in driver.find_elements(By.XPATH, xpath):
            try:
                cls = (el.get_attribute("class") or "").lower()
                aria_disabled = (el.get_attribute("aria-disabled") or "").lower()
                disabled = el.get_attribute("disabled")
                if disabled or aria_disabled == "true" or "disabled" in cls or "not-allowed" in cls:
                    continue
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
    return None


def _click_next_page(driver, page):
    before = _table_signature(driver)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(0.5)

    next_button = _find_next_page_button(driver, page + 1)
    if not next_button:
        return False

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_button)
        time.sleep(0.2)
        driver.execute_script("arguments[0].click();", next_button)
    except Exception:
        next_button.click()

    for _ in range(20):
        time.sleep(0.5)
        after = _table_signature(driver)
        if after and after != before:
            return True
    log.warning("  next page click did not change table; stopping")
    return False


def collect_list(driver):
    headers = get_headers(driver)
    all_rows = []
    seen = set()
    page = 1

    while True:
        log.info("  page %d collecting...", page)
        time.sleep(2)
        rows = parse_rows(driver, headers)
        if not rows:
            log.info("  no rows; stop")
            break

        new_rows = []
        for row in rows:
            key = _row_key(row)
            if key and key in seen:
                continue
            seen.add(key)
            new_rows.append(row)

        all_rows.extend(new_rows)
        log.info("  page %d rows=%d new=%d total=%d", page, len(rows), len(new_rows), len(all_rows))

        if not _click_next_page(driver, page):
            log.info("  no next page found")
            break
        page += 1

    log.info("list collection complete: %d rows", len(all_rows))
    return all_rows


def safe_get(driver, url, retries=2):
    for attempt in range(retries + 1):
        try:
            driver.get(url)
            return True
        except Exception as e:
            log.warning("  페이지 로드 실패 (%d/%d): %s", attempt+1, retries+1, e)
            time.sleep(2)
    return False


def get_text_nodes(driver):
    """JS TreeWalker로 가시 텍스트 노드를 DOM 순서대로 반환"""
    return driver.execute_script("""
        const skip = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','PATH']);
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const out = [];
        while(walker.nextNode()) {
            const p = walker.currentNode.parentElement;
            if(!p || skip.has(p.tagName)) continue;
            const t = walker.currentNode.textContent.trim();
            if(t.length > 0) out.push(t);
        }
        return out;
    """)


def extract_spec_section(text_nodes):
    """
    차량정보 탭 label-value 파싱.
    DOM 순서 문제로 일부 라벨이 잘못된 위치에 있을 수 있으므로
    값 검증 로직 포함.
    """
    LABELS = {
        "연식": ("연식", lambda v: bool(re.match(r'^\d{4}년?$', v))),
        "변속기": ("변속기", lambda v: bool(re.match(r'^(AUTO|MANUAL|DCT|CVT|오토|수동)$', v, re.I))),
        "색상": ("색상", lambda v: len(v) < 20 and not v.startswith("$")),
        "배기량": ("배기량", lambda v: "cc" in v.lower()),
        "구동방식": ("구동방식", lambda v: v in ("2WD","4WD","AWD","FWD","RWD","N/A","FF","FR","MR","RR") or len(v)<10),
        "최초등록일": ("최초등록일", lambda v: bool(re.match(r'^\d{4}\.\d{2}\.\d{2}$', v))),
        "주행거리": ("주행거리(상세)", lambda v: bool(re.search(r'KM|km|키로', v))),
        "Location": ("위치", lambda v: v not in (":", "") and len(v) < 30),
    }
    # "연료타입" 은 DOM 위치 불안정 → 정규식 폴백에서 처리 (LABELS에서 제외)
    result = {}
    for i, t in enumerate(text_nodes):
        if t in LABELS:
            key, validator = LABELS[t]
            # 콜론 등 무의미한 토큰 스킵하며 유효한 값 탐색
            for j in range(i + 1, min(i + 4, len(text_nodes))):
                candidate = text_nodes[j].strip()
                if candidate in LABELS:
                    break          # 다른 라벨이면 포기
                if candidate and candidate != ":" and validator(candidate):
                    result[key] = candidate
                    break
    return result


def extract_options_from_nodes(text_nodes):
    """
    텍스트 노드에서 카테고리별 옵션 파싱.
    카테고리(편의/기타, 안전 등) 뒤에 오는 옵션 이름만 수집.
    차량 스펙 데이터(KM, cc, $, GASOLINE 등)가 나타나면 해당 카테고리 종료.
    """
    CAT_LABELS = {"편의/기타", "안전", "주행/외관", "멀티미디어", "기타"}
    STOP_PATTERNS = re.compile(
        r'\d+\s*(KM|km|cc)|^\$|\b(GASOLINE|DIESEL|LPG|ELECTRIC|HYBRID'
        r'|가솔린|디젤|전기|하이브리드|AUTO|MANUAL|Korea|Location)\b'
        r'|^\d{4}년?$|^CS\s|^Overseas|MANGO|망고카|GG-AUTO|지지오토'
        r'|구매하기|문의|sign up|login|FAQ|커뮤니티|자동차검색',
        re.IGNORECASE
    )
    SECTION_STOP = {"차량정보", "옵션정보", "Sales history", "커뮤니티", "망고카 소개"}

    options_by_cat = {}
    current_cat = None

    for node in text_nodes:
        stripped = node.strip()
        if not stripped:
            continue

        # 카테고리 헤더
        if stripped in CAT_LABELS:
            current_cat = stripped
            options_by_cat[current_cat] = []
            continue

        # 다른 주요 섹션에 도달 → 전체 종료
        if stripped in SECTION_STOP:
            current_cat = None
            continue

        if current_cat:
            # 스펙 데이터가 나타나면 이 카테고리 종료
            if STOP_PATTERNS.search(stripped):
                current_cat = None
                continue
            # 괄호 단독 문자, 숫자만인 경우 제외
            if stripped in ("(", ")", ":", "/") or stripped.isdigit():
                current_cat = None
                continue
            if len(stripped) > 0 and len(stripped) <= 30:
                options_by_cat[current_cat].append(stripped)

    return options_by_cat


def extract_options(driver):
    """
    옵션정보 탭 클릭 → 활성 옵션 수집 (아이콘+텍스트).
    비활성(회색) 옵션은 제외.
    카테고리별 목록도 추출.
    """
    options_active = []
    options_by_category = {}

    try:
        # 옵션정보 탭 클릭
        tab = WebDriverWait(driver, 8).until(EC.element_to_be_clickable(
            (By.XPATH,
             "//button[contains(text(),'옵션정보')] | //a[contains(text(),'옵션정보')]"
             " | //*[contains(@class,'tab') and contains(text(),'옵션')]")))
        driver.execute_script("arguments[0].click();", tab)
        time.sleep(1.5)
    except Exception as e:
        log.debug("옵션정보 탭 클릭 실패: %s", e)
        return options_active, options_by_category

    try:
        # 활성 옵션: opacity/color로 구분 — JS로 computed style 확인
        # 비활성 옵션은 보통 opacity:0.3~0.5 또는 gray 색상
        option_items = driver.find_elements(By.XPATH,
            "//*[contains(@class,'option') or contains(@class,'feature')]"
            "//*[string-length(normalize-space(text()))>0 and string-length(normalize-space(text()))<30]"
            " | //figure | //li")

        # 더 직접적인 방법: 텍스트가 있는 모든 small 컨테이너 중 active 여부 JS 판별
        active_opts = driver.execute_script("""
            const results = [];
            // 옵션 아이콘 영역 탐색 (div/figure 등)
            const candidates = document.querySelectorAll(
                'div[class*="option"], div[class*="feature"], figure, li');
            for(const el of candidates) {
                const txt = el.innerText ? el.innerText.trim() : '';
                if(!txt || txt.length > 40 || txt.length < 2) continue;
                const style = window.getComputedStyle(el);
                const opacity = parseFloat(style.opacity);
                const color = style.color;
                // opacity < 0.6이면 비활성으로 간주
                if(opacity < 0.6) continue;
                // 부모도 체크
                const parentOpacity = parseFloat(
                    window.getComputedStyle(el.parentElement || el).opacity);
                if(parentOpacity < 0.6) continue;
                results.push(txt);
            }
            return [...new Set(results)];
        """)
        if active_opts:
            # 알려진 옵션 키워드 필터
            OPTION_KEYWORDS = [
                "선루프","썬루프","4WD","AWD","가죽시트","열선시트","통풍시트",
                "후방카메라","360","어라운드","스마트키","내비게이션","에어컨",
                "열선핸들","헤드업디스플레이","HUD","파노라마","어댑티브","크루즈",
                "차선","주차","자동주차","LED","HID","원격시동","빌트인캠",
                "블라인드스팟","후측방","전방충돌","긴급제동","어라운드뷰",
                "Sunroof","Leather","Camera","Navigation","Smart Key",
                "Heated","Ventilated","Drive","Cruise","Lane",
            ]
            for opt in active_opts:
                if any(kw.lower() in opt.lower() for kw in OPTION_KEYWORDS):
                    options_active.append(opt)
    except Exception as e:
        log.debug("활성 옵션 JS 추출 실패: %s", e)

    try:
        # 카테고리별 옵션 (편의/기타, 안전 등)
        # 카테고리 헤더 → 그 뒤에 오는 옵션 텍스트들
        category_headers = driver.find_elements(By.XPATH,
            "//*[contains(text(),'편의') or contains(text(),'안전')"
            " or contains(text(),'주행') or contains(text(),'외관')"
            " or contains(text(),'멀티미디어') or contains(text(),'기타')]"
            "[string-length(text())<15]")
        for hdr in category_headers:
            cat_name = hdr.text.strip()
            if not cat_name:
                continue
            try:
                # 같은 부모 내 다음 형제 요소들
                siblings = hdr.find_elements(By.XPATH,
                    "following-sibling::*[string-length(normalize-space(.))>0]")
                cat_items = []
                for sib in siblings[:10]:
                    sib_text = sib.text.strip()
                    if sib_text and len(sib_text) < 30:
                        # 다음 카테고리 헤더 만나면 중단
                        if any(c in sib_text for c in ["편의","안전","주행","외관","멀티","기타"]):
                            break
                        cat_items.append(sib_text)
                if cat_items:
                    options_by_category[cat_name] = cat_items
            except Exception:
                pass

        # 폴백: 텍스트 노드 순서로 카테고리 파싱
        if not options_by_category:
            nodes = get_text_nodes(driver)
            CAT_LABELS = ["편의/기타", "안전", "주행/외관", "멀티미디어"]
            current_cat = None
            for node in nodes:
                if node in CAT_LABELS:
                    current_cat = node
                    options_by_category[current_cat] = []
                elif current_cat:
                    if len(node) < 30 and node not in CAT_LABELS:
                        options_by_category[current_cat].append(node)
    except Exception as e:
        log.debug("카테고리 옵션 추출 실패: %s", e)

    return list(dict.fromkeys(options_active)), options_by_category


def extract_detail(driver, code, mapping_dict=None):
    url = f"{DETAIL_BASE}/{code}"
    log.info("  상세: %s", url)

    if not safe_get(driver, url):
        return {"상품코드": code, "오류": "페이지 로드 실패"}

    # 가격 요소 로드 대기
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located(
            (By.XPATH, "//*[contains(text(),'$')]")))
    except TimeoutException:
        log.warning("  가격 요소 미발견")

    # 스크롤로 lazy-load 유발
    scroll_to_bottom(driver)
    driver.execute_script("window.scrollTo(0,0)")
    time.sleep(1)

    data = {"상품코드": code, "상세URL": url}
    html  = driver.page_source
    nodes = get_text_nodes(driver)      # DOM 순서 텍스트 노드
    full  = "\n".join(nodes)

    # ── 차량명 (title 태그) ──
    title_m = re.search(r'<title>([^<|]+)', html)
    if title_m:
        data["차량명"] = title_m.group(1).strip()

    # ── 연식: 타이틀 앞 4자리 ──
    yr = re.match(r'^(\d{4})\s', data.get("차량명", ""))
    if yr:
        data["연식"] = yr.group(1)
    else:
        cur = datetime.now().year
        for y in re.findall(r'\b(19\d{2}|20[012]\d)\b', full):
            if int(y) != cur:
                data["연식"] = y
                break

    # ── 가격 ──
    price_m = re.search(r'\$\s*([\d,]+)', full)
    if price_m:
        data["가격(USD)"] = "$" + price_m.group(1)

    # ── 차량정보 탭 label-value 추출 ──
    # 1) 텍스트 노드 기반
    spec = extract_spec_section(nodes)

    # 2) XPath: gray-500(라벨) + font-bold(값) 구조에서 신뢰 필드만 추출
    XPATH_FIELD_MAP = {
        "구동방식": "구동방식",
        "사고이력": "사고이력",
        "최초등록일": "최초등록일",
        "연식": "연식",
        "변속기": "변속기",
        "색상": "색상",
        "배기량": "배기량",
        "주행거리": "주행거리(상세)",
        "Location": "위치",
    }
    try:
        containers = driver.find_elements(By.XPATH,
            "//div[contains(@class,'justify-between') and contains(@class,'gap')]"
            "[.//span[contains(@class,'gray-500')]]")
        for c in containers:
            try:
                label_el = c.find_element(By.XPATH,
                    ".//span[contains(@class,'gray-500')]")
                k_raw = label_el.text.strip()
                if k_raw not in XPATH_FIELD_MAP:
                    continue
                value_el = c.find_element(By.XPATH,
                    ".//span[contains(@class,'font-bold')]//span[last()]"
                    " | .//span[contains(@class,'font-bold') and not(.//span)]")
                v = value_el.text.strip()
                if v:
                    spec[XPATH_FIELD_MAP[k_raw]] = v
            except Exception:
                pass
    except Exception as e:
        log.debug("XPath spec 추출 실패: %s", e)

    data.update(spec)

    # ── 차대번호 (HTML 전체에서) ──
    vin_m = re.search(r'\b[A-HJ-NPR-Z0-9]{16,17}\b', html)
    if vin_m:
        data["차대번호_상세"] = vin_m.group()

    # ── 연료/변속기/주행거리/색상 폴백 (label-value 미취득 시) ──
    if "연료타입" not in data:
        fuel_m = re.search(
            r'\b(GASOLINE|DIESEL|LPG|ELECTRIC|HYBRID|가솔린|디젤|전기|하이브리드)\b',
            full, re.IGNORECASE)
        if fuel_m:
            data["연료타입"] = fuel_m.group()

    if "배기량" not in data:
        try:
            cc_els = driver.find_elements(By.XPATH,
                "//*[not(self::script)][not(self::style)]"
                "[contains(translate(text(),'CC','cc'),'cc')]")
            for el in cc_els:
                t = el.text.strip()
                if re.match(r'^\d[\d,]*cc$', t, re.IGNORECASE):
                    data["배기량"] = t
                    break
        except Exception:
            pass

    if "변속기" not in data:
        tm = re.search(r'\b(AUTO|MANUAL|DCT|CVT)\b', full, re.IGNORECASE)
        if tm:
            data["변속기"] = tm.group().upper()

    if "색상" not in data:
        cm = re.search(
            r'\b(BLACK|WHITE|SILVER|GRAY|RED|BLUE|BROWN|GOLD|GREEN|'
            r'ORANGE|YELLOW|PURPLE|BEIGE|NAVY)\b', full, re.IGNORECASE)
        if cm:
            data["색상"] = cm.group().upper()

    if "위치" not in data:
        lm = re.search(r'Location[:\s]+([A-Za-z가-힣]+)', full)
        if lm:
            data["위치"] = lm.group(1).strip()

    # ── 최초등록일 폴백 ──
    if "최초등록일" not in data:
        date_m = re.search(r'(20\d{2}\.\d{2}\.\d{2})', full)
        if date_m:
            data["최초등록일"] = date_m.group(1)

    # ── 구동방식 폴백 ──
    if "구동방식" not in data:
        # 1) joined full text 정규식
        m = re.search(r'구동방식\s*[\n:]\s*([^\n]{1,15})', full)
        if m:
            val = m.group(1).strip()
            if val:
                data["구동방식"] = val
        # 2) HTML 직접 탐색 (정규식)
        if "구동방식" not in data:
            m2 = re.search(
                r'구동방식.{0,80}?(N/A|2WD|4WD|AWD|FWD|RWD|FF|FR|MR|RR)',
                html, re.DOTALL)
            if m2:
                data["구동방식"] = m2.group(1)
        # 3) body 전체 텍스트에서 패턴 탐색
        if "구동방식" not in data:
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text
                m3 = re.search(r'구동방식\s*([^\n]{1,10})', body_text)
                if m3:
                    data["구동방식"] = m3.group(1).strip()
            except Exception:
                pass

    # 판매자
    dm = re.search(r'GG[-\s]?AUTO|지지오토', full, re.IGNORECASE)
    if dm:
        data["판매자"] = dm.group()

    # ── JSON 필드 (API 응답 포함 시) ──
    json_fields = re.findall(
        r'"(carNo|vin|mileage|fuelType|year|salePrice|transmission|color|'
        r'makerName|modelName|gradeName|displacement|accidentCount|carColor)"'
        r':\s*"?([^",}\]\n]{1,100})"?', html)
    for k, v in json_fields:
        v = v.strip().strip('"')
        if v and v not in ('null', 'undefined', ''):
            data[f"[API]{k}"] = v

    # ── 옵션정보: 텍스트 노드 카테고리 파싱 ──
    opts_by_cat = extract_options_from_nodes(nodes)
    all_opts = []
    for cat, items in opts_by_cat.items():
        if items:
            data[f"옵션_{cat}"] = " / ".join(items)
            all_opts.extend(items)
    if all_opts:
        data["보유옵션(전체)"] = " / ".join(all_opts)

    # ── 비포워드 옵션 매핑 ──
    if mapping_dict and all_opts:
        before_options = map_mango_to_before(all_opts, mapping_dict)
        if before_options:
            data["비포워드옵션"] = " / ".join(before_options)
            log.info("  → 비포워드 옵션 매핑: %d개", len(before_options))

    log.info("  → 필드 %d개 수집", len(data))
    return data


# ──────────────────────────────────────────────────────────
# 엑셀 저장
# ──────────────────────────────────────────────────────────
def save_excel(list_rows, detail_rows):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"지지오토_차량목록_{ts}.xlsx"

    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        def safe_df(rows):
            df = pd.DataFrame(rows)
            # "N/A" 문자열을 pandas NaN으로 오인하지 않도록 보존
            for col in df.columns:
                df[col] = df[col].apply(
                    lambda v: str(v) if isinstance(v, float) and pd.isna(v) else v)
            return df

        if list_rows:
            df1 = safe_df(list_rows)
            df1.drop(columns=[c for c in df1.columns if c.startswith("_")],
                     errors="ignore", inplace=True)
            df1.to_excel(writer, sheet_name="차량목록", index=False)

        if detail_rows:
            df2 = safe_df(detail_rows)
            df2.to_excel(writer, sheet_name="차량상세", index=False)

    log.info("저장 완료: %s", path)
    return path


# ──────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("망고월드카 지지오토 크롤러 v2 시작")
    log.info("=" * 60)

    # 옵션 매핑표 로드
    mapping_dict = load_option_mapping()

    driver = make_driver()
    list_rows = []
    detail_rows = []

    try:
        # 1. 로그인
        login(driver)

        # 2. 필터 적용
        apply_filters(driver)

        # 3. 목록 수집
        list_rows = collect_list(driver)

        if not list_rows:
            log.warning("수집 결과 없음. 스크린샷 확인 요망.")
            driver.save_screenshot(str(OUTPUT_DIR / "no_results.png"))
        else:
            # 상품코드 있는 것만 상세 크롤링
            codes = [r.get("상품코드","") for r in list_rows]
            codes = [c for c in codes if c.startswith("MGC_")]
            codes = list(dict.fromkeys(codes))  # 중복 제거
            # ── 테스트용 제한 (0 = 전체) ──
            TEST_LIMIT = 0
            if TEST_LIMIT:
                codes = codes[:TEST_LIMIT]
            log.info("상세 크롤링: %d건", len(codes))

            for i, code in enumerate(codes, 1):
                log.info("[%d/%d] %s", i, len(codes), code)
                d = extract_detail(driver, code, mapping_dict)

                # 목록의 차대번호 병합
                matched_vin = next(
                    (r.get("차대번호","") for r in list_rows
                     if r.get("상품코드","") == code), "")
                if matched_vin and not d.get("차대번호"):
                    d["차대번호"] = matched_vin

                detail_rows.append(d)
                time.sleep(1.5)

        # 4. 엑셀 저장
        out = save_excel(list_rows, detail_rows)
        print(f"\n완료! → {out}")

    except Exception as e:
        log.error("치명적 오류: %s\n%s", e, traceback.format_exc())
        try:
            driver.save_screenshot(str(OUTPUT_DIR / "critical_error.png"))
        except Exception:
            pass
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        log.info("드라이버 종료")


if __name__ == "__main__":
    main()
