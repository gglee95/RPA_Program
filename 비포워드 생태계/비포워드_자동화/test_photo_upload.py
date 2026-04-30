"""
BeForward 사진 업로드 + 저장 버튼 전체 흐름 테스트
"""
import time
import os
import glob
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

USERNAME = "echam@mangoworldcar.com"
PASSWORD = "VJSXaPQR"
LOGIN_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"
LISTING_ID = "12782906"

# 테스트용 이미지 파일들 (최대 12개)
IMG_DIR = r"c:\Users\gglee\OneDrive\Desktop\비포워드_자동화\downloaded_images\row_1261\EXTERIOR"
images = sorted(glob.glob(os.path.join(IMG_DIR, "*.jpg")))[:12]
print(f"[INFO] 사용할 이미지: {len(images)}개")

options = Options()
options.add_argument('--window-size=1920,1080')
options.add_argument('--disable-blink-features=AutomationControlled')
driver = webdriver.Chrome(options=options)

# 1. 로그인
print("[1] 로그인...")
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
print(f"[2] 로그인 URL: {driver.current_url}")

# 2. 사진 페이지
driver.get(f"https://external-vendor.beforward.jp/photo/upload/{LISTING_ID}")
time.sleep(3)
print(f"[3] 현재 URL: {driver.current_url}")

# 3. 파일 input 구조 확인
before_info = driver.execute_script("""
    var inputs = document.querySelectorAll('input[type="file"]');
    return {
        count: inputs.length,
        names: Array.from(inputs).map(function(i) {
            return {name: i.name, id: i.id, multiple: i.multiple, accept: i.accept};
        })
    };
""")
print(f"[4] 파일 input 초기 상태: {before_info}")

# 4. 파일 업로드 (모든 input 보이게)
driver.execute_script("""
    document.querySelectorAll('input[type="file"]').forEach(function(inp) {
        inp.style.display = 'block';
        inp.style.visibility = 'visible';
        inp.style.opacity = '0.01';
        inp.style.position = 'absolute';
    });
""")

for i, img_path in enumerate(images):
    inputs = driver.find_elements(By.XPATH, '//*[@id="public_pane"]/ul/li/label//input[@type="file"]')
    if not inputs:
        inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
    if not inputs:
        print(f"  [경고] 파일 input 없음 - {i+1}번째 이미지 건너뜀")
        continue
    
    # 매번 visible 처리
    driver.execute_script("""
        document.querySelectorAll('input[type="file"]').forEach(function(inp) {
            inp.style.display = 'block';
            inp.style.visibility = 'visible';
        });
    """)
    
    fi = inputs[0]
    fi.send_keys(img_path)
    print(f"  [OK] 이미지 {i+1}/{len(images)}: {os.path.basename(img_path)}")
    time.sleep(0.5)
    
    # 업로드 후 파일 input 수 확인
    count_after = driver.execute_script("return document.querySelectorAll('input[type=\"file\"]').length")
    print(f"    -> 현재 file input 수: {count_after}")

# 5. 업로드 후 상태 확인
after_info = driver.execute_script("""
    var inputs = document.querySelectorAll('input[type="file"]');
    var thumbs = document.querySelectorAll('#public_pane img[src], #public_pane .thumb');
    var btn = document.evaluate('//*[@id="bulk_confirm_form"]/div/button', document, null,
        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    return {
        fileInputCount: inputs.length,
        thumbCount: thumbs.length,
        btnFound: !!btn,
        btnVisible: btn ? btn.offsetParent !== null : false,
        btnY: btn ? btn.getBoundingClientRect().top : null,
        pageHeight: document.body.scrollHeight,
        windowHeight: window.innerHeight
    };
""")
print(f"\n[5] 업로드 후 상태: {after_info}")

print("\n[6] 저장 버튼 클릭 시도 (ActionChains)...")
btn = driver.find_element(By.XPATH, '//*[@id="bulk_confirm_form"]/div/button')
driver.execute_script("arguments[0].scrollIntoView({block:'center'})", btn)
time.sleep(1)

# ActionChains
actions = ActionChains(driver)
actions.move_to_element(btn).click().perform()
print("[6] ActionChains 클릭 완료, 10초 대기...")
time.sleep(10)

final_url = driver.current_url
final_text = driver.execute_script("return document.body.innerText[:300]") if hasattr(driver, 'execute_script') else ""
print(f"[7] 클릭 후 URL: {final_url}")

input("Enter로 종료...")
driver.quit()
