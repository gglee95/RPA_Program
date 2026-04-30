"""
게시정지 로직 XPath 검증 스크립트 (실제 클릭 없이 요소 존재 여부만 확인)
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except Exception:
    pass

from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD
from beforward_suspension_manager import (
    LISTING_BASE_URL,
    LISTING_PAGE_URL_TAB3,
    SEARCH_INPUT_XPATH,
    TOGGLE_ALL_CHECKBOX_XPATH,
    ALL_VEHICLES_TAB_XPATH,
    UNSELLABLE_BUTTON_XPATH,
    YES_BUTTON_XPATH_DIV17,
)

WAIT = 10


def check_xpath(driver, xpath, label, click=False):
    """XPath 요소 존재 여부 확인. click=True이면 실제 클릭."""
    try:
        wait = WebDriverWait(driver, WAIT)
        el = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
        visible = el.is_displayed()
        text = el.text.strip()[:40] if el.text else el.get_attribute('value') or ''
        status = "OK" if visible else "존재하나 hidden"
        print(f"  [{status}] {label}")
        print(f"         XPath : {xpath}")
        print(f"         텍스트: '{text}'")
        if click and visible:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            try:
                el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", el)
            print(f"         → 클릭 완료")
        return el
    except TimeoutException:
        print(f"  [FAIL] {label} - 요소 없음")
        print(f"         XPath : {xpath}")
        return None


def main():
    import sys
    # 인자: python test_suspension_xpath.py [차대번호] [--click]
    test_chassis = sys.argv[1] if len(sys.argv) > 1 else ""
    do_actual_click = "--click" in sys.argv

    options = Options()
    options.add_argument('--window-size=1400,900')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)

    try:
        # ── 1. 로그인 ─────────────────────────────────────────────
        print(f"\n[STEP 1] 로그인")
        driver.get(BEFORWARD_LOGIN_URL)
        time.sleep(2)

        if 'login' in driver.current_url.lower():
            wait = WebDriverWait(driver, WAIT)
            email = wait.until(EC.presence_of_element_located((By.NAME, 'data[VendorUser][email]')))
            email.send_keys(BEFORWARD_USERNAME)
            pw = driver.find_element(By.NAME, 'data[VendorUser][password]')
            pw.send_keys(BEFORWARD_PASSWORD)
            for sel in ["//button[@type='submit']", "//input[@type='submit']"]:
                try:
                    driver.find_element(By.XPATH, sel).click()
                    break
                except Exception:
                    continue
            time.sleep(2)

        if 'login' in driver.current_url.lower():
            print("[FAIL] 로그인 실패")
            return
        print(f"[OK] 로그인 성공: {driver.current_url}")

        # ── 2. tab=3 페이지 이동 + 검색창 확인 ───────────────────
        print(f"\n[STEP 2] tab=3 이동 및 검색창 확인")
        driver.get(LISTING_PAGE_URL_TAB3)
        time.sleep(2)
        print(f"  URL: {driver.current_url}")

        search_el = check_xpath(driver, SEARCH_INPUT_XPATH, "검색 input")

        # ── 3. 테스트 차대번호 입력 ────────────────────────────────
        print(f"\n  테스트 차대번호: '{test_chassis}'" if test_chassis else "\n  차대번호 없음 (스킵)")
        if test_chassis and search_el:
            search_el.clear()
            search_el.send_keys(test_chassis)
            search_el.send_keys(Keys.ENTER)
            print(f"  검색어 입력: '{test_chassis}'")
            time.sleep(2)

        # ── 4. 모든차량 탭 클릭 ───────────────────────────────────
        print(f"\n[STEP 3] 모든차량 탭")
        check_xpath(driver, ALL_VEHICLES_TAB_XPATH, "모든차량 탭", click=True)
        time.sleep(1)

        # ── 5. 전체선택 체크박스 ──────────────────────────────────
        print(f"\n[STEP 4] 전체선택 체크박스")
        check_xpath(driver, TOGGLE_ALL_CHECKBOX_XPATH, "전체선택 체크박스", click=True)
        time.sleep(1)

        # ── 6. 판매불가 버튼 (클릭 여부 확인) ────────────────────
        print(f"\n[STEP 5] 판매불가 버튼")
        unsellable_el = check_xpath(driver, UNSELLABLE_BUTTON_XPATH, "판매불가 버튼")

        if do_actual_click and unsellable_el:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", unsellable_el)
            time.sleep(0.3)
            try:
                unsellable_el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", unsellable_el)
            print("  → 판매불가 버튼 클릭 완료")
            time.sleep(1)

            # ── 7. Yes 버튼 - div 인덱스 전체 스캔 ─────────────────
            print(f"\n[STEP 6] Yes 확인 버튼 스캔 (div[1]~div[30])")
            time.sleep(1)
            found_yes = False
            for n in range(1, 31):
                xpath = f'/html/body/div[{n}]/button[1]'
                try:
                    el = driver.find_element(By.XPATH, xpath)
                    if el.is_displayed():
                        txt = el.text.strip()
                        print(f"  [표시됨] div[{n}]/button[1] | 텍스트: '{txt}'")
                        found_yes = True
                except Exception:
                    pass
            if not found_yes:
                print("  [없음] 표시된 button[1] 없음 - 팝업이 안 떴을 수 있음")
        else:
            print("  → 클릭 건너뜀 (검증만 완료)")

        print("\n\n========================================")
        print("검증 완료. 5초 후 브라우저 종료...")
        time.sleep(5)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
