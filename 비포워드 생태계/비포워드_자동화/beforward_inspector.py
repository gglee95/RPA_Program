"""
비포워드 포털 UI 진단 스크립트
- 로그인 후 페이지의 모든 입력 요소를 출력해서 셀렉터 파악
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

try:
    import chromedriver_autoinstaller
    chromedriver_autoinstaller.install()
except Exception:
    pass

from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD


def inspect_page(driver, label=""):
    """현재 페이지의 모든 입력 요소 출력"""
    print(f"\n{'='*60}")
    print(f"[{label}] URL: {driver.current_url}")
    print(f"{'='*60}")

    # 모든 input 요소
    inputs = driver.find_elements(By.TAG_NAME, 'input')
    print(f"\n■ INPUT 요소 ({len(inputs)}개):")
    for i, el in enumerate(inputs):
        name = el.get_attribute('name') or ''
        id_ = el.get_attribute('id') or ''
        type_ = el.get_attribute('type') or ''
        placeholder = el.get_attribute('placeholder') or ''
        value = el.get_attribute('value') or ''
        visible = el.is_displayed()
        print(f"  [{i}] type={type_:<10} name={name:<25} id={id_:<20} placeholder={placeholder:<20} value={value[:20]:<20} visible={visible}")

    # select 요소
    selects = driver.find_elements(By.TAG_NAME, 'select')
    print(f"\n■ SELECT 요소 ({len(selects)}개):")
    for i, el in enumerate(selects):
        name = el.get_attribute('name') or ''
        id_ = el.get_attribute('id') or ''
        visible = el.is_displayed()
        options = el.find_elements(By.TAG_NAME, 'option')
        option_texts = [o.text[:15] for o in options[:5]]
        print(f"  [{i}] name={name:<25} id={id_:<20} visible={visible} options={option_texts}")

    # textarea 요소
    textareas = driver.find_elements(By.TAG_NAME, 'textarea')
    print(f"\n■ TEXTAREA 요소 ({len(textareas)}개):")
    for i, el in enumerate(textareas):
        name = el.get_attribute('name') or ''
        id_ = el.get_attribute('id') or ''
        visible = el.is_displayed()
        print(f"  [{i}] name={name:<25} id={id_:<20} visible={visible}")

    # 버튼 요소
    buttons = driver.find_elements(By.TAG_NAME, 'button')
    print(f"\n■ BUTTON 요소 ({len(buttons)}개):")
    for i, el in enumerate(buttons):
        text = el.text.strip()[:30] or ''
        type_ = el.get_attribute('type') or ''
        class_ = el.get_attribute('class') or ''
        visible = el.is_displayed()
        print(f"  [{i}] type={type_:<10} text={text:<30} class={class_[:30]:<30} visible={visible}")

    # 링크 중 주요한 것
    links = driver.find_elements(By.TAG_NAME, 'a')
    print(f"\n■ 주요 LINK ({min(len(links), 20)}개, 최대 20개):")
    for i, el in enumerate(links[:20]):
        text = el.text.strip()[:30] or ''
        href = el.get_attribute('href') or ''
        if text or href:
            print(f"  [{i}] text={text:<30} href={href[:60]}")


def main():
    options = Options()
    # headless=False로 실제 브라우저 보이게
    options.add_argument('--window-size=1400,900')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)

    try:
        # 1. 로그인 페이지 분석
        print(f"\n접속 중: {BEFORWARD_LOGIN_URL}")
        driver.get(BEFORWARD_LOGIN_URL)
        time.sleep(3)

        inspect_page(driver, "로그인 페이지")

        # 2. 로그인 시도
        print("\n\n로그인 시도 중...")
        try:
            # email 입력 (실제 필드명: data[VendorUser][email])
            email_field = driver.find_element(By.NAME, 'data[VendorUser][email]')
            email_field.clear()
            email_field.send_keys(BEFORWARD_USERNAME)
            print(f"  이메일 입력 완료")

            # password 입력 (실제 필드명: data[VendorUser][password])
            pw = driver.find_element(By.NAME, 'data[VendorUser][password]')
            pw.clear()
            pw.send_keys(BEFORWARD_PASSWORD)
            print("  패스워드 입력 완료")

            # submit
            try:
                btn = driver.find_element(By.XPATH, "//button[@type='submit']")
                btn.click()
                print("  로그인 버튼 클릭")
            except Exception:
                try:
                    btn = driver.find_element(By.XPATH, "//input[@type='submit']")
                    btn.click()
                except Exception:
                    pass

            time.sleep(3)
            print(f"  로그인 후 URL: {driver.current_url}")

        except Exception as e:
            print(f"  로그인 중 오류: {e}")

        # 3. 로그인 후 페이지 분석
        inspect_page(driver, "로그인 후 페이지")

        # 4. 매물 등록/목록 페이지 탐색
        # 현재 페이지의 네비게이션 링크 확인
        print("\n\n[사용자 확인 필요]")
        print("브라우저에서 매물 등록 페이지로 직접 이동 후 Enter를 누르세요...")
        input()

        inspect_page(driver, "매물 등록 페이지")

        print("\n\n진단 완료!")
        print("위 정보를 바탕으로 비포워드_crawling.py와 beforward_suspension_manager.py를 수정하세요.")
        print("\n브라우저를 닫으려면 Enter를 누르세요...")
        input()

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
