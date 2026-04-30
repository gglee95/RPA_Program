"""
BeForward 제조사 select 디버그 스크립트
- 로그인 후 폼 페이지 접속
- select 요소 목록 확인
"""
import asyncio
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD
import json

FORM_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"

class DebugTab:
    def __init__(self, driver):
        self._driver = driver

    @property
    def url(self):
        return self._driver.current_url

    def get(self, url):
        self._driver.get(url)

    def evaluate(self, script):
        return self._driver.execute_script(script)


def main():
    opts = Options()
    opts.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=opts)
    tab = DebugTab(driver)

    try:
        # 1. 로그인
        print(f"[1] 로그인 페이지: {BEFORWARD_LOGIN_URL}")
        tab.get(BEFORWARD_LOGIN_URL)
        time.sleep(2)

        print(f"    현재 URL: {tab.url}")

        if 'login' in tab.url.lower():
            tab.evaluate(f"""
                (function() {{
                    var e = document.querySelector('input[name="data[VendorUser][email]"]');
                    var p = document.querySelector('input[name="data[VendorUser][password]"]');
                    if (e) e.value = {json.dumps(BEFORWARD_USERNAME)};
                    if (p) p.value = {json.dumps(BEFORWARD_PASSWORD)};
                }})()
            """)
            time.sleep(0.5)
            driver.find_element("css selector", 'button[type="submit"]').click()
            time.sleep(3)
            print(f"    로그인 후 URL: {tab.url}")
        else:
            print("    이미 로그인 상태")

        # 2. 폼 페이지 접속
        print(f"\n[2] 폼 페이지 접속: {FORM_URL}")
        tab.get(FORM_URL)
        time.sleep(2)
        print(f"    현재 URL: {tab.url}")

        # 3. select 요소 전체 목록
        print("\n[3] 페이지의 모든 select 요소:")
        selects = tab.evaluate("""
            return JSON.stringify(Array.from(document.querySelectorAll('select')).map(function(s) {
                return {name: s.name, id: s.id, options_count: s.options.length};
            }));
        """)
        selects = json.loads(selects or '[]')
        if selects:
            for s in selects:
                print(f"    name='{s['name']}' id='{s['id']}' options={s['options_count']}")
        else:
            print("    [없음] select 요소가 전혀 없음!")

        # 4. 제조사 select 직접 확인
        print("\n[4] TempVehDetails[make_id] 직접 확인:")
        make_sel = tab.evaluate("""
            var s = document.querySelector('[name="TempVehDetails[make_id]"]');
            if (!s) return '없음';
            return 'tagName=' + s.tagName + ' options=' + s.options.length;
        """)
        print(f"    결과: {make_sel}")

        # 5. 페이지 타이틀 및 body 일부
        title = tab.evaluate("return document.title")
        print(f"\n[5] 페이지 타이틀: {title}")

        print("\n[완료] 브라우저를 닫으려면 Enter를 누르세요...")
        input()

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
