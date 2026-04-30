"""
BeForward 사진 업로드 페이지 구조 직접 확인 스크립트
"""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

USERNAME = "echam@mangoworldcar.com"
PASSWORD = "VJSXaPQR"
LOGIN_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"
LISTING_ID = "12782906"  # 최근 생성된 리스팅

options = Options()
options.add_argument('--window-size=1920,1080')
options.add_argument('--disable-blink-features=AutomationControlled')

driver = webdriver.Chrome(options=options)

# 1. 로그인
print("[1] 로그인 중...")
driver.get(LOGIN_URL)
time.sleep(2)

if 'login' in driver.current_url.lower():
    driver.execute_script(f"""
        var e = document.querySelector('input[name="data[VendorUser][email]"]');
        var p = document.querySelector('input[name="data[VendorUser][password]"]');
        if (e) e.value = '{USERNAME}';
        if (p) p.value = '{PASSWORD}';
    """)
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    time.sleep(3)

print(f"[2] 로그인 후 URL: {driver.current_url}")

# 2. 사진 업로드 페이지
photo_url = f"https://external-vendor.beforward.jp/photo/upload/{LISTING_ID}"
print(f"[3] 사진 페이지 이동: {photo_url}")
driver.get(photo_url)
time.sleep(3)

print(f"[4] 현재 URL: {driver.current_url}")

# 3. 페이지 구조 확인
info = driver.execute_script("""
    var btn = document.evaluate('//*[@id="bulk_confirm_form"]/div/button', document, null,
        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    var fileInputs = document.querySelectorAll('input[type="file"]');
    var iframes = document.querySelectorAll('iframe');
    var form = document.querySelector('#bulk_confirm_form');
    return {
        btnFound: !!btn,
        btnText: btn ? btn.textContent.trim() : null,
        btnType: btn ? btn.type : null,
        btnDisabled: btn ? btn.disabled : null,
        btnVisible: btn ? (btn.offsetParent !== null) : false,
        btnRect: btn ? JSON.stringify(btn.getBoundingClientRect()) : null,
        fileInputCount: fileInputs.length,
        iframeCount: iframes.length,
        formFound: !!form,
        formAction: form ? form.action : null,
        formMethod: form ? form.method : null,
        title: document.title
    };
""")

print("\n=== 페이지 구조 ===")
for k, v in info.items():
    print(f"  {k}: {v}")

# 4. 저장 버튼 클릭 시도 (Selenium native)
if info.get('btnFound'):
    print("\n[5] 저장 버튼 Selenium click 시도...")
    btn = driver.find_element(By.XPATH, '//*[@id="bulk_confirm_form"]/div/button')
    
    # scroll to button
    driver.execute_script("arguments[0].scrollIntoView({block:'center'})", btn)
    time.sleep(0.5)
    
    # ActionChains click (마우스 이동 후 클릭)
    from selenium.webdriver.common.action_chains import ActionChains
    actions = ActionChains(driver)
    actions.move_to_element(btn).click().perform()
    print("[5] ActionChains 클릭 완료")
    
    time.sleep(5)
    # 클릭 후 페이지 상태
    body_text = driver.execute_script("return document.body.innerText.substring(0, 500)")
    print(f"[6] 클릭 후 페이지 텍스트:\n{body_text}")
else:
    print("\n[경고] 저장 버튼 없음 - 이미지 없이 접근했거나 페이지 문제")

input("\n[Enter] 브라우저 닫기...")
driver.quit()
