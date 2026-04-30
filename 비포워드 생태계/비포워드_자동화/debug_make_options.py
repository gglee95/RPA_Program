"""
BeForward 제조사 Select2 옵션 목록 + 시트 E열 값 비교
"""
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD
import gspread
from google.oauth2.service_account import Credentials
from config import SPREADSHEET_ID, WORKSHEET_NAME, SERVICE_ACCOUNT_FILE, SCOPES, START_ROW

FORM_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"

def get_sheet_makes():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    # E열 값 읽기
    e_values = ws.col_values(5)  # E열 = 5번째
    makes = []
    for i, val in enumerate(e_values):
        row = i + 1
        if row < START_ROW:
            continue
        if val.strip():
            makes.append((row, val.strip()))
        if len(makes) >= 10:
            break
    return makes

def main():
    print("[1] 시트 E열 제조사 샘플 읽는 중...")
    sheet_makes = get_sheet_makes()
    print(f"    E열 샘플 ({len(sheet_makes)}개):")
    for row, make in sheet_makes:
        print(f"      Row {row}: '{make}'")

    print(f"\n[2] BeForward 로그인...")
    opts = Options()
    opts.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=opts)

    try:
        driver.get(BEFORWARD_LOGIN_URL)
        time.sleep(2)

        if 'login' in driver.current_url.lower():
            driver.execute_script(f"""
                var e = document.querySelector('input[name="data[VendorUser][email]"]');
                var p = document.querySelector('input[name="data[VendorUser][password]"]');
                if (e) e.value = {json.dumps(BEFORWARD_USERNAME)};
                if (p) p.value = {json.dumps(BEFORWARD_PASSWORD)};
            """)
            driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
            time.sleep(3)

        print(f"    로그인 후 URL: {driver.current_url}")

        print(f"\n[3] 폼 페이지 접속...")
        driver.get(FORM_URL)
        time.sleep(2)

        # Select2 컨테이너 클릭해서 드롭다운 열기
        print(f"\n[4] Select2 제조사 드롭다운 열기...")
        container = driver.find_element(By.XPATH, '//*[@id="select2-make-id-container"]')
        container.click()
        time.sleep(0.5)

        # 검색창 찾기
        search_input = driver.find_element(By.CSS_SELECTOR, '.select2-search__field')

        # 검색어 없이 전체 옵션 가져오기
        options = driver.find_elements(By.CSS_SELECTOR, '.select2-results__option')
        bf_makes = [o.text.strip() for o in options if o.text.strip()]
        print(f"    드롭다운 옵션 ({len(bf_makes)}개):")
        for m in bf_makes[:30]:
            print(f"      '{m}'")
        if len(bf_makes) > 30:
            print(f"      ... (이하 {len(bf_makes)-30}개 생략)")

        # ESC 닫기
        search_input.send_keys('\x1b')
        time.sleep(0.3)

        # E열 값으로 검색 테스트
        print(f"\n[5] E열 값으로 검색 테스트:")
        for row, make in sheet_makes[:5]:
            container = driver.find_element(By.XPATH, '//*[@id="select2-make-id-container"]')
            container.click()
            time.sleep(0.4)
            search_input = driver.find_element(By.CSS_SELECTOR, '.select2-search__field')
            search_input.clear()
            search_input.send_keys(make.split()[0])
            time.sleep(0.5)
            results = driver.find_elements(By.CSS_SELECTOR, '.select2-results__option')
            result_texts = [r.text.strip() for r in results if r.text.strip()]
            print(f"      Row {row} E열='{make}' → 검색결과: {result_texts[:5]}")
            search_input.send_keys('\x1b')
            time.sleep(0.3)

        print("\n[완료] Enter 누르면 종료...")
        input()

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
