"""
제조사 선택 후 모델 select 구조 전체 확인
+ 모델 change 이벤트 발생 후 연료/미션/색상 select 채워지는지 확인
"""
import time
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from config import BEFORWARD_LOGIN_URL, BEFORWARD_USERNAME, BEFORWARD_PASSWORD

FORM_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"

FUEL_CSS  = '#bulk_confirm_form div > div > div:first-child table:nth-of-type(3) tr:nth-child(6) select'
TRANS_CSS = '#bulk_confirm_form div > div > div:first-child table:nth-of-type(3) tr:nth-child(8) select'
COLOR_CSS = '#bulk_confirm_form div > div > div:first-child table:nth-of-type(3) tr:nth-child(10) select'

def get_select_options(driver, css):
    return driver.execute_script(f"""
        var sel = document.querySelector({json.dumps(css)});
        if (!sel) return null;
        return Array.from(sel.options).map(o => o.text);
    """)

def print_key_selects(driver, label):
    print(f"\n[{label}] 연료/미션/색상 select 상태:")
    for name, css in [('연료', FUEL_CSS), ('미션', TRANS_CSS), ('색상', COLOR_CSS)]:
        opts = get_select_options(driver, css)
        if opts is None:
            print(f"  {name}: 요소 없음")
        else:
            print(f"  {name}: {len(opts)}개 → {opts[:5]}")

def main():
    opts = Options()
    opts.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=opts)

    try:
        # 로그인
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

        driver.get(FORM_URL)
        time.sleep(3)
        print(f"[URL] {driver.current_url}")
        print(f"[bulk_confirm_form 존재] {driver.execute_script('return !!document.querySelector(\"#bulk_confirm_form\")')}")

        # ── 1단계: 폼 초기 상태 ──
        print_key_selects(driver, "초기 상태")

        # 모든 select 목록
        result = driver.execute_script("""
            return JSON.stringify(Array.from(document.querySelectorAll('select')).map(function(s) {
                return {name: s.name, id: s.id, options_count: s.options.length};
            }));
        """)
        selects = json.loads(result)
        print(f"\n[전체 select 목록] ({len(selects)}개):")
        for s in selects:
            print(f"  name='{s['name']}' id='{s['id']}' options={s['options_count']}")

        # ── 2단계: 제조사 선택 ──
        print("\n[LAND ROVER 제조사 선택 중...]")
        driver.find_element(By.XPATH, '//*[@id="select2-make-id-container"]').click()
        time.sleep(0.5)
        search = driver.find_element(By.CSS_SELECTOR, '.select2-search__field')
        search.send_keys('LAND')
        time.sleep(1)
        for el in driver.find_elements(By.CSS_SELECTOR, '.select2-results__option'):
            if 'LAND ROVER' in el.text.upper():
                el.click()
                break
        time.sleep(2)
        print("[OK] LAND ROVER 선택 완료")
        print_key_selects(driver, "make 선택 후")

        # model-id 옵션 확인
        model_opts = driver.execute_script("""
            var s = document.querySelector('[name="TempVehDetails[model_id]"]') || document.getElementById('model-id');
            if (!s) return null;
            return Array.from(s.options).map(o => ({text: o.text, value: o.value}));
        """)
        if model_opts:
            print(f"\n[model-id] {len(model_opts)}개 옵션:")
            for o in model_opts[:10]:
                print(f"  value={o['value']!r} text={o['text']!r}")
        else:
            print("\n[model-id] 없음 또는 옵션 0개")

        # ── 3단계: 첫 번째 모델 선택 + change 이벤트 ──
        print("\n[첫 번째 모델 선택 + change 이벤트 발생...]")
        result = driver.execute_script("""
            var sel = document.querySelector('[name="TempVehDetails[model_id]"]');
            if (!sel || sel.options.length <= 1) return 'no_options';
            var opt = Array.from(sel.options).find(o => o.value && o.value !== '');
            if (!opt) return 'no_valid_option';
            sel.value = opt.value;
            ['input','change'].forEach(function(ev) {
                sel.dispatchEvent(new Event(ev, {bubbles: true}));
            });
            return opt.text;
        """)
        print(f"  선택된 모델: {result!r}")

        # 2차 AJAX 완료 대기 (최대 10초)
        print("  2차 AJAX 완료 대기 중...")
        for i in range(20):
            time.sleep(0.5)
            cnt = driver.execute_script(f"""
                var sel = document.querySelector({json.dumps(FUEL_CSS)});
                return sel ? sel.options.length : 0;
            """)
            if cnt and int(cnt) > 1:
                print(f"  → {i*0.5+0.5:.1f}초 후 연료 옵션 {cnt}개 로드 완료!")
                break
        else:
            print("  → 10초 후에도 연료 옵션 로드 안 됨")

        # ── 4단계: 최종 상태 ──
        print_key_selects(driver, "model change 이벤트 후")

        print("\n[완료] Enter 누르면 종료...")
        input()

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
