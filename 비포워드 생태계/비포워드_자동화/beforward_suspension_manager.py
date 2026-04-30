"""
ByForward listing suspension manager
Handles login, search, and soft-delete (게시 정지) of listings via external vendor portal
"""
import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    import chromedriver_autoinstaller
    CHROMEDRIVER_AUTOINSTALLER_AVAILABLE = True
except ImportError:
    CHROMEDRIVER_AUTOINSTALLER_AVAILABLE = False

from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD

LISTING_BASE_URL = (
    "https://external-vendor.beforward.jp/"
    "?limit=50"
    "&vendor_group_id%5B0%5D=1284"
    "&registration_date_from=2025-03-10"
    "&price_type=1"
    "&current_tab_counter_flg=1"
)

# soft delete 검색 탭 순서 (tab=1 대기 포함, 전체 순회)
SOFT_DELETE_TABS = [1, 2, 3, 4, 5, 6]

# tab=2: 판매 가능 탭 → 판매불가 버튼으로 처리
TAB_SALE_AVAILABLE = 2

# tab=3: 정보수정 탭 (판매불가 버튼)
LISTING_PAGE_URL_TAB3 = (
    LISTING_BASE_URL + "&tab=3#search-result-title"
)
SEARCH_INPUT_XPATH = '//*[@id="search"]/div[2]/div/table/tbody/tr[3]/td/input'
TOGGLE_ALL_CHECKBOX_XPATH = '//*[@id="toggle-checkbox-rule"]'
ALL_VEHICLES_TAB_XPATH = '//*[@id="tab"]/ul/li[9]/a/span'
UNSELLABLE_BUTTON_XPATH = '/html/body/div[2]/div[1]/div[12]/div/div/div/div/div[1]/div[1]/div/a[2]'
YES_BUTTON_XPATH_DIV17 = '/html/body/div[17]/button[1]'


class BeforwardSuspensionManager:
    """ByForward 외부 벤더 포털 - 매물 게시 정지 관리"""

    WAIT_TIMEOUT = 10

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None
        self.logged_in = False

    def _setup_driver(self):
        """Chrome 드라이버 초기화"""
        options = Options()
        chrome_binary = os.getenv('CHROME_BINARY')
        if chrome_binary:
            options.binary_location = chrome_binary
        if self.headless:
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        if CHROMEDRIVER_AUTOINSTALLER_AVAILABLE:
            try:
                chromedriver_autoinstaller.install()
            except Exception:
                pass

        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(30)
        print("[INFO] BeForward 드라이버 초기화 완료 (Chrome)")

    def login(self) -> bool:
        """ByForward 외부 벤더 포털 로그인"""
        if not self.driver:
            self._setup_driver()

        try:
            print(f"[INFO] BeForward 로그인 중: {BEFORWARD_LOGIN_URL}")
            self.driver.get(BEFORWARD_LOGIN_URL)
            time.sleep(1)

            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)

            # 이미 로그인된 경우
            if 'login' not in self.driver.current_url.lower():
                print("[OK] 이미 로그인 상태")
                self.logged_in = True
                return True

            # 이메일 입력
            email_field = wait.until(EC.presence_of_element_located(
                (By.NAME, 'data[VendorUser][email]')
            ))
            email_field.clear()
            email_field.send_keys(BEFORWARD_USERNAME)
            time.sleep(0.1)

            # 패스워드 입력
            pw_field = self.driver.find_element(By.NAME, 'data[VendorUser][password]')
            pw_field.clear()
            pw_field.send_keys(BEFORWARD_PASSWORD)
            time.sleep(0.1)

            # 로그인 버튼 클릭
            for selector in [
                "//button[@type='submit']",
                "//input[@type='submit']",
                "//button[contains(text(), 'Login')]",
            ]:
                try:
                    btn = self.driver.find_element(By.XPATH, selector)
                    btn.click()
                    break
                except NoSuchElementException:
                    continue

            time.sleep(1.5)

            if 'login' in self.driver.current_url.lower():
                print(f"[오류] 로그인 실패")
                return False

            print(f"[OK] BeForward 로그인 성공")
            self.logged_in = True
            return True

        except Exception as e:
            print(f"[오류] BeForward 로그인 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return False

    def search_and_delete_listing(self, chassis_no: str) -> bool:
        """매물 목록에서 차대번호로 찾아 게시 정지 처리

        전체 탭(1~6) 순회: 수정 페이지 진입 후 게시 정지

        Args:
            chassis_no: 차대번호 (VIN)

        Returns:
            bool: 삭제 성공 여부
        """
        for t in SOFT_DELETE_TABS:
            tab_url = f"{LISTING_BASE_URL}&tab={t}#search-result-title"
            label = f"tab={t}"
            try:
                edit_url = self._find_edit_url_in_tab(chassis_no, tab_url, label)
                if edit_url:
                    if self._soft_delete(edit_url):
                        print(f"  [OK] 게시 정지 완료 ({label})")
                        return True
            except Exception as e:
                print(f"  [경고] 게시 정지 처리 오류 ({label}): {e}")

        print(f"[경고] '{chassis_no}' 게시 정지 실패")
        return False

    def batch_unsellable_by_chassis(self, chassis_numbers: list[str]) -> bool:
        """차대번호들을 공백으로 입력해 일괄 판매불가 처리한다."""
        chassis_numbers = [str(v).strip() for v in chassis_numbers if str(v).strip()]
        if not chassis_numbers:
            print("[경고] 차대번호가 없어 판매불가 처리를 건너뜁니다")
            return False

        try:
            self.driver.get(LISTING_PAGE_URL_TAB3)
            time.sleep(1)

            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            search_input = wait.until(
                EC.presence_of_element_located((By.XPATH, SEARCH_INPUT_XPATH))
            )

            search_text = " ".join(chassis_numbers)
            search_input.clear()
            search_input.send_keys(search_text)
            time.sleep(0.2)
            search_input.send_keys(Keys.ENTER)
            print(f"[INFO] 차대번호 일괄 검색 입력 완료: {len(chassis_numbers)}건")
            time.sleep(2)

            if not self._open_all_vehicles_tab():
                print("[경고] 모든차량 탭 이동 실패")
                return False

            # 검색 결과 건수 확인 - 0건이면 처리 불필요
            try:
                result_rows = self.driver.find_elements(
                    By.CSS_SELECTOR, 'table tbody tr[id]'
                )
                if len(result_rows) == 0:
                    print(f"[경고] 검색 결과 없음 - 처리 건너뜀 (차대번호: {chassis_numbers})")
                    return False
                print(f"[INFO] 검색 결과: {len(result_rows)}건")
            except Exception:
                pass  # 확인 실패 시 계속 진행

            if not self._click_toggle_all_checkbox():
                print("[경고] 모두선택 체크박스 클릭 실패")
                return False

            unsellable_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, UNSELLABLE_BUTTON_XPATH))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", unsellable_btn
            )
            time.sleep(0.2)
            try:
                unsellable_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", unsellable_btn)
            print("[OK] 판매불가 버튼 클릭 완료")
            time.sleep(0.5)

            yes_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, YES_BUTTON_XPATH_DIV17))
            )
            try:
                yes_btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", yes_btn)
            print("[OK] Yes 버튼 클릭 완료")
            time.sleep(1)
            return True

        except Exception as e:
            print(f"[오류] 일괄 판매불가 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _click_toggle_all_checkbox(self) -> bool:
        """검색 결과 모두선택 체크박스를 클릭한다."""
        try:
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            checkbox = wait.until(
                EC.element_to_be_clickable((By.XPATH, TOGGLE_ALL_CHECKBOX_XPATH))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", checkbox
            )
            time.sleep(0.2)
            try:
                checkbox.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", checkbox)
            time.sleep(0.5)
            return True
        except Exception:
            return False

    def _open_all_vehicles_tab(self) -> bool:
        """SOLD OUT 일괄 처리 전에 모든차량 탭으로 이동한다."""
        try:
            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
            tab = wait.until(
                EC.element_to_be_clickable((By.XPATH, ALL_VEHICLES_TAB_XPATH))
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", tab
            )
            time.sleep(0.2)
            try:
                tab.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", tab)
            time.sleep(1)
            print("[OK] 모든차량 탭 이동 완료")
            return True
        except Exception as e:
            print(f"[경고] 모든차량 탭 이동 오류: {e}")
            return False

    def _find_edit_url_in_tab(self, chassis_no: str, tab_url: str, label: str) -> str | None:
        """단일 탭에서 차대번호에 해당하는 수정 링크 찾기 (페이지 순회)"""
        JS_FIND_EDIT = """
            var chassis = arguments[0];
            var rows = document.querySelectorAll('tr');
            for (var i = 0; i < rows.length; i++) {
                if (rows[i].textContent.indexOf(chassis) !== -1) {
                    var links = rows[i].querySelectorAll('a');
                    for (var j = 0; j < links.length; j++) {
                        var text = links[j].textContent.trim();
                        var href = links[j].getAttribute('href') || '';
                        if (text === '修正' || text === '수정' || text === 'Edit'
                            || href.indexOf('/edit/') !== -1
                            || href.toLowerCase().indexOf('tempvehdetails/edit') !== -1) {
                            return links[j].href || href;
                        }
                    }
                    if (rows[i].querySelector('a[href*="edit"]')) {
                        return rows[i].querySelector('a[href*="edit"]').href;
                    }
                }
            }
            return null;
        """

        print(f"[INFO] 매물 검색 ({label}): {chassis_no}")
        self.driver.get(tab_url)
        time.sleep(1)

        page = 1
        while True:
            print(f"  [INFO] 페이지 {page} 검색 중 ({label})...")

            result = self.driver.execute_script(JS_FIND_EDIT, chassis_no)
            if result:
                print(f"  [OK] 매물 발견 ({label}, 페이지 {page}): {result[:80]}")
                return result

            if not self._go_next_page():
                print(f"  [{label}] '{chassis_no}' 없음 ({page} 페이지 검색)")
                break
            page += 1

        return None

    def _click_unsellable_row(self, chassis_no: str, tab_url: str, label: str) -> bool:
        """판매 가능 탭에서 차대번호 행의 판매불가 버튼 클릭

        수정 버튼 위에 위치한 판매불가 버튼을 텍스트로 찾아 클릭
        YES XPath: /html/body/div[17]/button[1]
        """
        print(f"[INFO] 판매불가 버튼 처리 ({label}): {chassis_no}")
        self.driver.get(tab_url)
        time.sleep(1)

        page = 1
        while True:
            print(f"  [INFO] 페이지 {page} 검색 중 ({label})...")

            # 차대번호가 있는 행에서 수정 버튼 앞의 판매불가 버튼을 찾아 클릭
            # (수정 버튼과 같은 td 안에서 수정보다 먼저 나오는 첫 번째 링크가 판매불가)
            result = self.driver.execute_script("""
                var chassis = arguments[0];
                var rows = document.querySelectorAll('#search-result tbody tr');
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].textContent.indexOf(chassis) !== -1) {
                        var tds = rows[i].querySelectorAll('td');
                        for (var k = 0; k < tds.length; k++) {
                            var links = tds[k].querySelectorAll('a, button');
                            for (var j = 0; j < links.length; j++) {
                                var txt = (links[j].textContent || '').trim();
                                if (txt === '修正' || txt === '수정' || txt === 'Edit') {
                                    // 수정 버튼 발견 → 같은 td 첫 번째 링크(판매불가) 클릭
                                    if (j > 0) {
                                        links[0].click();
                                        return 'clicked';
                                    }
                                    return 'edit_only';
                                }
                            }
                        }
                        return 'row_found';
                    }
                }
                return null;
            """, chassis_no)

            if result == 'clicked':
                print(f"  [OK] 판매불가 버튼 클릭 완료 (페이지 {page})")
                time.sleep(0.5)
                return self._click_yes_confirm_div17()

            if result in ('row_found', 'edit_only'):
                print(f"  [경고] 판매불가 버튼을 찾지 못함 (결과: {result}, 페이지 {page})")
                return False

            if not self._go_next_page():
                print(f"  [{label}] '{chassis_no}' 없음 ({page} 페이지 검색)")
                break
            page += 1

        return False

    def _find_edit_url(self, chassis_no: str, listing_url: str = None, tab_label: str = None) -> str | None:
        """매물 목록에서 차대번호에 해당하는 수정 링크 찾기 (전체 탭 순회, 하위 호환)"""
        if listing_url:
            return self._find_edit_url_in_tab(chassis_no, listing_url, tab_label or "")

        for t in SOFT_DELETE_TABS:
            if t == TAB_SALE_AVAILABLE:
                continue  # 판매 가능 탭은 edit URL 없음
            tab_url = f"{LISTING_BASE_URL}&tab={t}#search-result-title"
            result = self._find_edit_url_in_tab(chassis_no, tab_url, f"tab={t}")
            if result:
                return result

        print(f"[경고] '{chassis_no}' 전체 탭 검색 완료 - 매물 없음")
        return None

    def _go_next_page(self) -> bool:
        """다음 페이지로 이동. 성공하면 True, 더 이상 페이지 없으면 False"""
        try:
            # 다음 페이지 링크 찾기
            next_btns = self.driver.find_elements(
                By.XPATH,
                "//a[contains(@class,'next')] | "
                "//li[contains(@class,'next')]/a | "
                "//a[text()='›'] | //a[text()='»'] | "
                "//a[text()='Next'] | //a[text()='次へ']"
            )
            for btn in next_btns:
                if btn.is_displayed() and btn.is_enabled():
                    parent = btn.find_element(By.XPATH, "./..")
                    # disabled 상태 체크
                    parent_class = parent.get_attribute('class') or ''
                    if 'disabled' in parent_class:
                        return False
                    btn.click()
                    time.sleep(1)
                    return True
            return False
        except Exception:
            return False


    def _soft_delete(self, edit_url: str) -> bool:
        """수정 페이지에서 게시 정지 실행

        1. 수정 페이지로 이동
        2. //*[@id="bulk_confirm_form"]/div[1]/div[2]/table/tbody/tr[2]/td[1]/a[1] 클릭
        3. /html/body/div[6]/button[1] 클릭 (Yes 확인)
        """
        try:
            print(f"[INFO] 수정 페이지 이동: {edit_url[:80]}")
            self.driver.get(edit_url)
            time.sleep(1)

            wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)

            # 게시 정지 버튼 클릭
            DELETE_BTN_XPATH = '//*[@id="bulk_confirm_form"]/div[1]/div[2]/table/tbody/tr[2]/td[1]/a[1]'
            try:
                delete_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, DELETE_BTN_XPATH))
                )
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", delete_btn
                )
                time.sleep(0.2)
                delete_btn.click()
                print(f"  [OK] 게시 정지 버튼 클릭 완료")
            except TimeoutException:
                print(f"  [경고] 게시 정지 버튼을 찾지 못했습니다: {DELETE_BTN_XPATH}")
                return False

            time.sleep(0.5)

            # Yes 확인 버튼 클릭
            YES_XPATH = '/html/body/div[6]/button[1]'
            try:
                yes_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, YES_XPATH))
                )
                yes_btn.click()
                print(f"  [OK] Yes 확인 버튼 클릭 완료")
                time.sleep(0.5)
            except TimeoutException:
                print(f"  [경고] Yes 버튼 없음, fallback 시도")
                if not self._click_yes_confirm():
                    print(f"  [경고] Yes 확인 실패")
                    return False

            print(f"[OK] 매물 게시 정지 완료")
            return True

        except Exception as e:
            print(f"[오류] 삭제 처리 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _click_unsellable(self, chassis_no: str) -> bool:
        """tab=3 목록 페이지에서 차대번호 행의 '판매불가' 버튼 클릭 → Yes 확인

        Args:
            chassis_no: 차대번호 (VIN)

        Returns:
            bool: 성공 여부
        """
        print(f"[INFO] tab=3 판매불가 처리 시작: {chassis_no}")
        self.driver.get(LISTING_PAGE_URL_TAB3)
        time.sleep(1)

        page = 1
        while True:
            print(f"  [INFO] 페이지 {page} 검색 중 (tab=3)...")

            # 차대번호가 포함된 행에서 '판매불가' 버튼 찾기 & 클릭
            clicked = self.driver.execute_script("""
                var chassis = arguments[0];
                var rows = document.querySelectorAll('tr');
                for (var i = 0; i < rows.length; i++) {
                    if (rows[i].textContent.indexOf(chassis) !== -1) {
                        // 해당 행에서 '판매불가' 버튼/링크 찾기
                        var btns = rows[i].querySelectorAll('a, button, input[type="button"], input[type="submit"]');
                        for (var j = 0; j < btns.length; j++) {
                            var text = (btns[j].textContent || btns[j].value || '').trim();
                            if (text.indexOf('판매불가') !== -1 || text.indexOf('販売不可') !== -1
                                || text.indexOf('Unsellable') !== -1 || text.indexOf('Not for sale') !== -1) {
                                btns[j].click();
                                return true;
                            }
                        }
                        return 'row_found_no_btn';
                    }
                }
                return false;
            """, chassis_no)

            if clicked is True:
                print(f"  [OK] 판매불가 버튼 클릭 완료 (페이지 {page})")
                time.sleep(0.5)

                # Yes 확인 버튼 클릭
                return self._click_yes_confirm()

            if clicked == 'row_found_no_btn':
                print(f"  [경고] 행은 찾았으나 판매불가 버튼 없음 (페이지 {page})")
                return False

            # 다음 페이지
            if not self._go_next_page():
                print(f"  [경고] tab=3에서 '{chassis_no}' 찾지 못함 (전체 {page} 페이지)")
                return False
            page += 1

    def _click_yes_confirm_div17(self) -> bool:
        """판매 가능 탭 판매불가 후 YES 확인 (/html/body/div[17]/button[1])"""
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)
        try:
            yes_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, '/html/body/div[17]/button[1]'))
            )
            yes_btn.click()
            print(f"  [OK] Yes 확인 버튼 클릭 완료 (div[17])")
            time.sleep(0.5)
            return True
        except TimeoutException:
            print(f"  [경고] div[17] Yes 버튼 없음, 공통 확인 시도")
            return self._click_yes_confirm()

    def _click_yes_confirm(self) -> bool:
        """Yes 확인 버튼 클릭 (판매불가/삭제 후 공통)"""
        wait = WebDriverWait(self.driver, self.WAIT_TIMEOUT)

        # 방법 1: 고정 XPath
        YES_BTN_XPATH = '/html/body/div[7]/button[1]'
        try:
            yes_btn = wait.until(
                EC.element_to_be_clickable((By.XPATH, YES_BTN_XPATH))
            )
            yes_btn.click()
            print(f"  [OK] Yes 확인 버튼 클릭 완료")
            time.sleep(0.5)
            return True
        except TimeoutException:
            pass

        # 방법 2: JS alert
        try:
            alert = self.driver.switch_to.alert
            print(f"  [INFO] Alert 확인: {alert.text}")
            alert.accept()
            time.sleep(1)
            return True
        except Exception:
            pass

        # 방법 3: 텍스트 기반 버튼 탐색
        for xpath in [
            "//button[contains(text(),'Yes')]",
            "//button[contains(text(),'OK')]",
            "//button[contains(text(),'はい')]",
            "//button[contains(text(),'확인')]",
        ]:
            try:
                btn = self.driver.find_element(By.XPATH, xpath)
                if btn.is_displayed():
                    btn.click()
                    print(f"  [OK] 확인 버튼 클릭: {xpath}")
                    time.sleep(0.5)
                    return True
            except NoSuchElementException:
                continue

        print(f"  [경고] Yes 확인 버튼을 찾지 못했습니다")
        return False

    # ── 하위 호환: 기존 search_listing / suspend_listing 인터페이스 유지 ──

    def search_listing(self, search_term: str) -> str | None:
        """차대번호로 수정 페이지 URL 반환 (기존 인터페이스 호환)"""
        return self._find_edit_url(search_term)

    def suspend_listing(self, listing_url: str) -> bool:
        """수정 페이지에서 삭제 처리 (기존 인터페이스 호환)"""
        return self._soft_delete(listing_url)

    def close(self):
        """드라이버 종료"""
        if self.driver:
            try:
                self.driver.quit()
                print("[OK] BeForward 드라이버 종료")
            except Exception:
                pass
            self.driver = None
        self.logged_in = False
