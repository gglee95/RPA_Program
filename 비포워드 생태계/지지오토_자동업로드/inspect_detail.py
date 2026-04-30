"""상세 페이지 HTML 구조 파악용 진단 스크립트"""
import time
from pathlib import Path
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

OUT = Path(__file__).parent
LOGIN_URL = "https://adminv2.mangoworldcar.com"
DETAIL_URL = "https://mangoworldcar.com/ko/car-detail/MGC_260420_10002009"

def make_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--lang=ko-KR")
    return uc.Chrome(options=opts, version_main=None)

def login(driver):
    driver.get(LOGIN_URL)
    time.sleep(2)
    driver.save_screenshot(str(OUT / "d_login.png"))

    id_el = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.XPATH,
            "//input[@placeholder='ID' or @name='email' or @name='id' or @name='username']")))
    id_el.clear()
    id_el.send_keys("admin@mangoworldcar.com")

    pw = driver.find_element(By.XPATH, "//input[@type='password']")
    pw.clear()
    pw.send_keys("mango8802!")

    btn = driver.find_element(By.XPATH,
        "//button[text()='Login' or @type='submit']")
    btn.click()
    time.sleep(3)
    print("로그인 완료. URL:", driver.current_url)

driver = make_driver()
try:
    login(driver)

    driver.get(DETAIL_URL)
    time.sleep(4)
    driver.save_screenshot(str(OUT / "d_detail.png"))

    # HTML 저장
    html = driver.page_source
    with open(str(OUT / "d_detail.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("HTML 저장 완료:", len(html), "bytes")

    # 테이블 구조 확인
    rows = driver.find_elements(By.XPATH, "//table//tr")
    print(f"\n테이블 행: {len(rows)}개")
    for i, r in enumerate(rows[:5]):
        print(f"  행{i}: {r.text[:100]}")

    # dl/dt/dd
    dts = driver.find_elements(By.TAG_NAME, "dt")
    print(f"\ndt 태그: {len(dts)}개")
    for dt in dts[:10]:
        print(f"  dt: {dt.text}")

    # 모든 텍스트 있는 div/span 클래스명 샘플
    els = driver.find_elements(By.XPATH, "//*[@class and text()]")
    classes = set()
    for el in els[:200]:
        cls = el.get_attribute("class")
        if cls:
            classes.update(cls.split())
    print(f"\n사용된 클래스 중 info/spec/car/detail 포함:")
    for c in sorted(classes):
        if any(k in c.lower() for k in ["info","spec","car","detail","price","name","title"]):
            print(f"  .{c}")

finally:
    time.sleep(2)
    driver.quit()
