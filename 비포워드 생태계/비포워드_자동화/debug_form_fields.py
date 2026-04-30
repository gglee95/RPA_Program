"""BeForward 폼 필드 구조 확인 + 연식 옵션 확인"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD

options = Options()
options.add_argument('--window-size=1920,1080')
driver = webdriver.Chrome(options=options)

try:
    # 로그인
    driver.get(BEFORWARD_LOGIN_URL)
    time.sleep(2)

    if 'login' in driver.current_url.lower():
        driver.find_element(By.CSS_SELECTOR, 'input[name="data[VendorUser][email]"]').send_keys(BEFORWARD_USERNAME)
        driver.find_element(By.CSS_SELECTOR, 'input[name="data[VendorUser][password]"]').send_keys(BEFORWARD_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        time.sleep(3)

    print(f"[URL] {driver.current_url}")

    # 폼으로 이동
    FORM_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"
    if driver.current_url != FORM_URL:
        driver.get(FORM_URL)
        time.sleep(2)

    print(f"[폼 URL] {driver.current_url}")

    # 모든 input/select name 수집
    elems = driver.find_elements(By.CSS_SELECTOR, 'input[name], select[name], textarea[name]')
    print(f"\n[폼 필드 목록] ({len(elems)}개):")
    for e in elems:
        tag = e.tag_name
        name = e.get_attribute('name')
        etype = e.get_attribute('type') or ''
        val = e.get_attribute('value') or ''
        print(f"  {tag}[{etype}] name={name!r:50s} value={val[:30]!r}")

    # 연식 select 옵션 확인
    print("\n[연식 select 옵션 샘플]:")
    for sel_name in ['TempVehDetails[registration_year]', 'TempVehDetails[manufacture_year]']:
        try:
            sel = driver.find_element(By.CSS_SELECTOR, f'[name="{sel_name}"]')
            opts = sel.find_elements(By.TAG_NAME, 'option')
            print(f"  {sel_name}: {len(opts)}개 옵션")
            for o in opts[:5]:
                print(f"    value={o.get_attribute('value')!r} text={o.text!r}")
        except Exception as e:
            print(f"  {sel_name}: 없음 ({e})")

    # AUDI 선택 후 필드 변화 확인
    print("\n[AUDI 선택 후 필드 확인...]")
    try:
        container = driver.find_element(By.XPATH, '//*[@id="select2-make-id-container"]')
        container.click()
        time.sleep(0.5)
        search = driver.find_element(By.CSS_SELECTOR, '.select2-search__field')
        search.send_keys('AUDI')
        time.sleep(1)
        opts = driver.find_elements(By.CSS_SELECTOR, '.select2-results__option')
        for o in opts:
            if 'AUDI' in o.text.upper():
                o.click()
                print(f"  AUDI 선택 완료")
                break
        time.sleep(2)
    except Exception as e:
        print(f"  AUDI 선택 실패: {e}")

    # AUDI 선택 후 연식 옵션
    for sel_name in ['TempVehDetails[registration_year]', 'TempVehDetails[manufacture_year]']:
        try:
            sel = driver.find_element(By.CSS_SELECTOR, f'[name="{sel_name}"]')
            opts = sel.find_elements(By.TAG_NAME, 'option')
            print(f"\n  [{sel_name}] AUDI 선택 후: {len(opts)}개")
            for o in opts[:8]:
                print(f"    value={o.get_attribute('value')!r} text={o.text!r}")
        except Exception as e:
            print(f"  {sel_name} 없음: {e}")

    # CBM 필드 확인
    print("\n[CBM 필드 확인]:")
    for fname in ['TempVehDetails[length]', 'TempVehDetails[width]', 'TempVehDetails[height]',
                  'TempVehDetails[m3]', 'TempVehDetails[mileage]', 'TempVehDetails[chassis_no]',
                  'TempVehDetails[engine_capacity]']:
        try:
            el = driver.find_element(By.CSS_SELECTOR, f'[name="{fname}"]')
            print(f"  OK: {fname} (type={el.tag_name})")
        except:
            print(f"  MISS: {fname}")

    input("\n[완료] 창을 확인 후 Enter...")
finally:
    driver.quit()
