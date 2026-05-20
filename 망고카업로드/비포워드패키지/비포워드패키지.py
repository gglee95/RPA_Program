"""
비포워드 매물 업로드 자동화
- 스프레드시트: 망고패키지와 동일 (GID: 1403349305)
- 조건: AC열(계정정보) 있고 AN열(업로드일자) 비어있는 행
- Y열: 구글 드라이브 이미지 폴더 링크
- AL열: 업로드 실패 메모
- AN열: 업로드 완료일자
- 비포워드 사이트: external-vendor.beforward.jp
- 계정: 고정 (config.py 기준 - echam@mangoworldcar.com / VJSXaPQR)
"""
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime


class BeforwardPackageUploader:
    # ── 스프레드시트 ──────────────────────────────────────
    SPREADSHEET_ID = "1yHN0UM8Rr_CmMjz5fI3CEdhQjHM7VQIaqitWPRIGR8E"
    SHEET_GID = 1403349305
    SERVICE_ACCOUNT_FILE = os.path.join(
        os.path.dirname(__file__),
        "..", "망고카 오토", "adjustmentdata-51a7199ac3ba.json"
    )
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # ── 열 인덱스 (0-based) ──────────────────────────────
    COL_MODEL       = 3   # D
    COL_YEAR        = 4   # E
    COL_COLOR       = 5   # F
    COL_CAR_NUMBER  = 6   # G
    COL_VIN         = 7   # H
    COL_DETAIL      = 8   # I  (구조화 텍스트)
    COL_OPT_START   = 9   # J  (옵션 시작)
    COL_OPT_END     = 18  # S  (옵션 끝)
    COL_DRIVE_LINK  = 24  # Y  (구글 드라이브 이미지 폴더)
    COL_PRICE       = 27  # AB (광고가 $)
    COL_ACCOUNT     = 28  # AC (계정 - 트리거 용도)
    COL_FAIL_NOTE   = 37  # AL (업로드실패 메모)
    COL_UPLOAD_DATE = 39  # AN (업로드일자)

    # ── 비포워드 ──────────────────────────────────────────
    BEFORWARD_LOGIN_URL = "https://external-vendor.beforward.jp/tempVehDetails/edit"
    BEFORWARD_USERNAME  = "echam@mangoworldcar.com"
    BEFORWARD_PASSWORD  = "VJSXaPQR"

    # ── 매핑 테이블 ───────────────────────────────────────
    # I열 연료 → 비포워드 옵션 텍스트
    FUEL_MAPPING = {
        "가솔린": "Petrol", "휘발유": "Petrol",
        "디젤": "Diesel", "경유": "Diesel",
        "LPG": "LPG", "엘피지": "LPG",
        "하이브리드": "Hybrid",
        "전기": "EV", "EV": "EV",
        "수소": "Hydrogen",
    }
    # I열 변속기 → 비포워드 옵션
    TRANSMISSION_MAPPING = {
        "자동": "AT", "오토": "AT", "AUTO": "AT", "AT": "AT",
        "CVT": "AT", "DCT": "AT",
        "수동": "MT", "매뉴얼": "MT", "MANUAL": "MT", "MT": "MT",
    }
    # F열 색상 → 비포워드 색상 옵션 (한글)
    COLOR_MAPPING = {
        "흰색": "White", "화이트": "White", "백색": "White", "진주": "White", "펄": "White",
        "검은색": "Black", "검정": "Black", "블랙": "Black",
        "은색": "Silver", "실버": "Silver",
        "회색": "Gray", "그레이": "Gray",
        "파란색": "Blue", "블루": "Blue", "청색": "Blue", "남색": "Blue", "네이비": "Blue",
        "빨간색": "Red", "레드": "Red",
        "갈색": "Brown", "브라운": "Brown",
        "초록색": "Green", "그린": "Green", "녹색": "Green",
        "노란색": "Yellow", "노랑": "Yellow",
        "금색": "Gold", "골드": "Gold",
        "주황색": "Orange", "오렌지": "Orange",
        "보라색": "Purple", "퍼플": "Purple",
    }
    # I열 구동방식 → 비포워드 라디오 value (예시: 1=2WD, 3=4WD)
    DRIVE_TYPE_MAPPING = {
        "2": "1", "2WD": "1", "FWD": "1", "RWD": "1", "전륜": "1", "후륜": "1",
        "4": "3", "4WD": "3", "AWD": "3", "4륜": "3",
    }
    # 차종(D열) 키워드 → 4WD 판정
    AWD_KEYWORDS = ["AWD", "4WD", "QUATTRO", "콰트로", "4MATIC", "4매틱",
                    "4MOTION", "4모션", "XDRIVE"]
    # 차종(D열) 키워드 → Body Type
    BODY_TYPE_MAP = {
        "SUV": ["SUV", "싼타페", "투싼", "스포티지", "소렌토", "코나", "셀토스",
                "티볼리", "팰리세이드", "모하비", "베라크루즈", "QM", "트레일블레이저",
                "이쿼녹스", "캐스퍼", "스토닉", "니로", "아이오닉5", "EV6", "넥쏘",
                "렉스턴", "코란도", "액티언", "TIGUAN", "투아렉", "Q3", "Q5", "Q7",
                "X1", "X3", "X5", "X6", "X7", "GLA", "GLB", "GLC", "GLE", "GLS",
                "CR-V", "RAV4", "RANGE", "DISCOVERY", "EVOQUE", "CAYENNE", "MACAN"],
        "Minivan": ["스타렉스", "카니발", "그랜드스타렉스", "카렌스", "올란도",
                    "스타리아", "TOURAN", "ODYSSEY", "ALPHARD", "SIENNA"],
        "Truck": ["봉고", "포터", "마이티", "트럭", "화물", "PICKUP", "픽업"],
        "Hatchback": ["i30", "i20", "i10", "프라이드", "해치", "MINI", "POLO",
                      "GOLF", "A3", "1시리즈", "DEMIO"],
        "Wagon": ["투어링", "왜건", "SW", "WAGON", "AVANT"],
        "Coupe": ["쿠페", "COUPE", "RC", "GR쿠페", "M2", "M4", "M8", "CL", "GT"],
        "Van": ["밴", "VAN"],
        "Sedan": ["세단", "SEDAN",
                  "소나타", "그랜저", "아반떼", "엑센트", "제네시스", "ELANTRA", "ACCENT",
                  "SONATA", "GRANDEUR", "GENESIS", "EQUUS", "에쿠스", "에반떼",
                  "K3", "K5", "K7", "K8", "K9", "FORTE", "OPTIMA", "CADENZA",
                  "SM3", "SM5", "SM6", "SM7",
                  "A1", "A3", "A4", "A5", "A6", "A7", "A8",
                  "3시리즈", "5시리즈", "6시리즈", "7시리즈", "320", "330", "520", "530", "740",
                  "C클래스", "E클래스", "S클래스", "A클래스", "CLA", "CLS",
                  "ES", "GS", "IS", "LS",
                  "CAMRY", "COROLLA", "AVALON", "ACCORD", "CIVIC",
                  "ALTIMA", "MAXIMA", "SENTRA", "MALIBU", "임팔라", "IMPALA"],
    }
    # Body type별 CBM 치수 (cm 단위)
    CBM_DEFAULTS = {
        "SUV":       (470, 190, 175),
        "Minivan":   (500, 195, 185),
        "Truck":     (500, 180, 180),
        "Hatchback": (420, 175, 150),
        "Wagon":     (470, 180, 155),
        "Coupe":     (450, 180, 140),
        "Van":       (500, 185, 195),
        "Sedan":     (470, 180, 150),
    }
    # VIN 3자리 → 제조사 키워드 (드롭다운에서 검색용)
    VIN_BRAND_MAP = {
        "KMH": "Hyundai", "KMJ": "Hyundai", "KMF": "Hyundai",
        "KNA": "Kia", "KND": "Kia", "KNJ": "Kia",
        "KPT": "Chevrolet", "KL1": "Chevrolet", "KL5": "Chevrolet",
        "WAU": "Audi",
        "WBA": "BMW", "WBS": "BMW", "WBY": "BMW",
        "WVW": "Volkswagen", "WV1": "Volkswagen", "WV2": "Volkswagen",
        "WVG": "Volkswagen", "WV3": "Volkswagen",
        "SAL": "Land Rover",
        "VF1": "Renault", "VF3": "Renault",
        "WDD": "Mercedes-Benz", "WDC": "Mercedes-Benz", "WDB": "Mercedes-Benz",
        "JHM": "Honda", "1HG": "Honda",
        "JN1": "Nissan", "JTD": "Toyota", "JT2": "Toyota",
        "WP0": "Porsche",
        "ZFF": "Ferrari",
    }

    # ── 이미지 다운로드 폴더 ──────────────────────────────
    DOWNLOAD_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "downloaded_images"
    )

    # ─────────────────────────────────────────────────────
    def __init__(self):
        self.driver = None
        self.gc = None
        self.worksheet = None
        self.creds = None
        self.all_rows = []

    # ─────────────────────────────────────────────────────
    # 스프레드시트 연결
    # ─────────────────────────────────────────────────────
    def setup_spreadsheet(self) -> bool:
        try:
            self.creds = Credentials.from_service_account_file(
                self.SERVICE_ACCOUNT_FILE, scopes=self.SCOPES
            )
            self.gc = gspread.authorize(self.creds)
            sh = self.gc.open_by_key(self.SPREADSHEET_ID)

            # GID로 worksheet 찾기
            self.worksheet = None
            for ws in sh.worksheets():
                if ws.id == self.SHEET_GID:
                    self.worksheet = ws
                    break
            if not self.worksheet:
                print(f"[오류] GID={self.SHEET_GID} 워크시트를 찾을 수 없습니다")
                return False

            self.all_rows = self.worksheet.get_all_values()
            print(f"[OK] 스프레드시트 연결: {self.worksheet.title} ({len(self.all_rows)}행)")
            return True
        except Exception as e:
            print(f"[오류] 스프레드시트 연결 실패: {e}")
            return False

    # ─────────────────────────────────────────────────────
    # 펜딩 행 조회
    # ─────────────────────────────────────────────────────
    def get_pending_rows(self) -> list[dict]:
        """AC열(계정) 있고 AN열(업로드일자) 없는 행 반환"""
        pending = []
        for row_idx, row in enumerate(self.all_rows[1:], start=2):
            ac_val = row[self.COL_ACCOUNT] if len(row) > self.COL_ACCOUNT else ""
            am_val = row[self.COL_UPLOAD_DATE] if len(row) > self.COL_UPLOAD_DATE else ""
            if ac_val and ac_val.strip() and (not am_val or not am_val.strip()):
                pending.append({"row_idx": row_idx, "row": row})
        return pending

    # ─────────────────────────────────────────────────────
    # 구글 드라이브 링크
    # ─────────────────────────────────────────────────────
    def _get_drive_link_for_row(self, row_idx: int) -> str:
        """Y열 셀에서 하이퍼링크 URL 추출 (formula 우선, 텍스트 폴백)"""
        try:
            cell = self.worksheet.cell(row_idx, self.COL_DRIVE_LINK + 1,
                                       value_render_option="FORMULA")
            formula = cell.value or ""
            m = re.search(r'HYPERLINK\("([^"]+)"', formula)
            if m:
                return m.group(1)
        except Exception:
            pass
        try:
            row = self.all_rows[row_idx - 1]
            return row[self.COL_DRIVE_LINK] if len(row) > self.COL_DRIVE_LINK else ""
        except Exception:
            return ""

    @staticmethod
    def _num_sort_key(path: str):
        name = os.path.splitext(os.path.basename(path))[0]
        parts = re.split(r'(\d+)', name)
        return [int(p) if p.isdigit() else p.lower() for p in parts]

    # ─────────────────────────────────────────────────────
    # 이미지 다운로드 (Drive 폴더 → "전체 다운로드" 클릭 → ZIP)
    # ─────────────────────────────────────────────────────
    def download_images(self, drive_link: str, row_num: int) -> list[str]:
        if not drive_link:
            return []

        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        if os.path.exists(row_folder):
            shutil.rmtree(row_folder, ignore_errors=True)
        os.makedirs(row_folder, exist_ok=True)
        os.makedirs(self.DOWNLOAD_FOLDER, exist_ok=True)

        img_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif"}
        download_abs = os.path.abspath(self.DOWNLOAD_FOLDER)

        dl_driver = None
        try:
            opts = Options()
            opts.add_experimental_option("prefs", {
                "download.default_directory": download_abs,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": False,
                "safebrowsing.disable_download_protection": True,
            })
            opts.add_argument("--disable-gpu")
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--window-size=1920,1080")
            opts.add_argument("--disable-blink-features=AutomationControlled")
            opts.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
            )
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            opts.add_experimental_option("useAutomationExtension", False)
            dl_driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=opts
            )
            dl_driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": download_abs,
            })

            print(f"  [드라이브 접속] {drive_link[:80]}")
            dl_driver.get(drive_link)
            time.sleep(5)

            pre_files = set(os.listdir(download_abs))

            # "전체 다운로드" 버튼 클릭
            DOWNLOAD_SELECTORS = [
                "//*[normalize-space(text())='전체 다운로드']",
                "//*[normalize-space(text())='Download all']",
                "//div[@role='button' and (contains(.,'전체 다운로드') or contains(.,'Download all'))]",
                "//*[contains(@aria-label,'전체 다운로드') or contains(@aria-label,'Download all')]",
                '//*[@id="drive-main-page"]/div/div[3]/div[1]/div/div/div/div[2]/div/div[2]/div/div/div[2]/div/div[1]',
            ]
            clicked = False
            for sel in DOWNLOAD_SELECTORS:
                try:
                    elements = WebDriverWait(dl_driver, 15).until(
                        lambda d: d.find_elements(By.XPATH, sel)
                    )
                    vis = [e for e in elements if e.is_displayed()]
                    if not vis:
                        continue
                    btn = vis[0]
                    dl_driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.3)
                    try:
                        btn.click()
                    except Exception:
                        dl_driver.execute_script("arguments[0].click();", btn)
                    print(f"  [OK] 다운로드 버튼 클릭")
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                print("  [오류] 다운로드 버튼을 찾을 수 없습니다")
                return []

            # ZIP 다운로드 대기 (30초 + 추가 60초)
            print("  [대기] ZIP 다운로드 30초 대기 중...")
            time.sleep(30)
            extra_end = time.time() + 60
            while time.time() < extra_end:
                in_prog = [f for f in os.listdir(download_abs)
                           if f.endswith(".crdownload") or f.endswith(".tmp")]
                if not in_prog:
                    break
                time.sleep(2)

            # ZIP 파일 찾기
            cur_files = set(os.listdir(download_abs))
            new_zips = [f for f in cur_files - pre_files
                        if f.lower().endswith(".zip")]
            if not new_zips:
                print("  [경고] ZIP 파일을 찾을 수 없습니다")
                return []
            zip_name = max(new_zips,
                           key=lambda f: os.path.getmtime(os.path.join(download_abs, f)))
            zip_src = os.path.join(download_abs, zip_name)
            print(f"  [OK] ZIP 발견: {zip_name}")

            # 압축 해제
            try:
                zip_dst = os.path.join(row_folder, "downloaded.zip")
                shutil.move(zip_src, zip_dst)
                with zipfile.ZipFile(zip_dst, "r") as zf:
                    zf.extractall(row_folder)
                os.remove(zip_dst)
                print("  [OK] 압축 해제 완료")
            except Exception as e:
                print(f"  [오류] 압축 해제 실패: {e}")
                return []

            # 이미지 수집 + 숫자순 정렬
            downloaded = []
            for root, _, fs in os.walk(row_folder):
                for f in fs:
                    if any(f.lower().endswith(f".{e}") for e in img_exts):
                        downloaded.append(os.path.join(root, f))
            downloaded.sort(key=self._num_sort_key)

            print(f"  [순서] {[os.path.basename(f) for f in downloaded[:10]]}"
                  f"{'...' if len(downloaded) > 10 else ''}")
            print(f"[OK] 총 {len(downloaded)}개 이미지 다운로드 완료")
            return downloaded
        except Exception as e:
            print(f"[오류] 이미지 다운로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            if dl_driver:
                try:
                    dl_driver.quit()
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────
    # 시트 결과 기입
    # ─────────────────────────────────────────────────────
    def mark_upload_date(self, row_idx: int) -> bool:
        try:
            today = datetime.now().strftime("%Y. %m. %d")
            cell = f"AN{row_idx}"
            self.worksheet.update_acell(cell, today)
            print(f"[OK] {cell}에 업로드일자 '{today}' 기입 완료")
            return True
        except Exception as e:
            print(f"[오류] 업로드일자 기입 실패: {e}")
            return False

    def mark_upload_failed(self, row_idx: int, reason: str = "업로드실패") -> bool:
        try:
            cell = f"AL{row_idx}"
            self.worksheet.update_acell(cell, reason)
            print(f"[OK] {cell}에 '{reason}' 기입")
            return True
        except Exception as e:
            print(f"[오류] 실패 표시 기입 실패: {e}")
            return False

    # ─────────────────────────────────────────────────────
    # 드라이버
    # ─────────────────────────────────────────────────────
    def setup_driver(self) -> None:
        options = Options()
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=ko-KR,ko")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )

    def close_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ─────────────────────────────────────────────────────
    # 비포워드 로그인
    # ─────────────────────────────────────────────────────
    def login_beforward(self) -> bool:
        try:
            print(f"\n[로그인] {self.BEFORWARD_USERNAME}")
            self.driver.get(self.BEFORWARD_LOGIN_URL)
            time.sleep(2)

            # 이미 로그인된 상태라면 폼 페이지로 이동됨
            if "login" not in self.driver.current_url.lower():
                print("[OK] 이미 로그인 상태")
                return True

            # 로그인 폼 입력
            try:
                email_input = self.driver.find_element(
                    By.CSS_SELECTOR, 'input[name="data[VendorUser][email]"]'
                )
                pw_input = self.driver.find_element(
                    By.CSS_SELECTOR, 'input[name="data[VendorUser][password]"]'
                )
                email_input.clear()
                email_input.send_keys(self.BEFORWARD_USERNAME)
                pw_input.clear()
                pw_input.send_keys(self.BEFORWARD_PASSWORD)

                submit = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                submit.click()
                time.sleep(3)

                if "login" in self.driver.current_url.lower():
                    print("[오류] 비포워드 로그인 실패 (URL에 login 잔존)")
                    return False
                print("[OK] 비포워드 로그인 성공")
                return True
            except Exception as e:
                print(f"[오류] 로그인 폼 입력 실패: {e}")
                return False
        except Exception as e:
            print(f"[오류] 로그인 중 오류: {e}")
            return False

    # ─────────────────────────────────────────────────────
    # 데이터 파싱 헬퍼
    # ─────────────────────────────────────────────────────
    def parse_i_column(self, i_val: str) -> dict:
        """I열 구조화 텍스트 파싱 (번호 유무 무관)"""
        result = {
            "drive_type": "", "transmission": "", "fuel": "",
            "seating": "", "mileage": "", "handle": "",
            "engine_displacement": "",
        }
        if not i_val or i_val.strip() == "해당없음":
            return result
        patterns = {
            "drive_type":          r"구동방식[ \t]*:[ \t]*([^\r\n]*)",
            "transmission":        r"변속기[ \t]*:[ \t]*([^\r\n]*)",
            "fuel":                r"연료[ \t]*:[ \t]*([^\r\n]*)",
            "seating":             r"승차인원[ \t]*:[ \t]*([^\r\n]*)",
            "mileage":             r"주행거리[ \t]*:[ \t]*([^\r\n]*)",
            "handle":              r"핸들위치[ \t]*:[ \t]*([^\r\n]*)",
            "engine_displacement": r"배기량[ \t]*:[ \t]*([^\r\n]*)",
        }
        for key, pat in patterns.items():
            m = re.search(pat, i_val)
            if m:
                result[key] = m.group(1).strip()
        return result

    def get_row_options(self, row: list) -> list[str]:
        options = []
        for col_idx in range(self.COL_OPT_START, self.COL_OPT_END + 1):
            if col_idx < len(row):
                val = row[col_idx].strip()
                if val:
                    options.append(val)
        return options

    @staticmethod
    def _normalize_price(price_raw: str) -> str:
        """$1,234 → 1234"""
        if not price_raw:
            return ""
        return re.sub(r"[^\d]", "", price_raw)

    @staticmethod
    def _extract_digits(s: str) -> str:
        return re.sub(r"[^\d]", "", s or "")

    # ─────────────────────────────────────────────────────
    # 폼 입력 헬퍼 (Selenium 기반)
    # ─────────────────────────────────────────────────────
    def _fill_text_by_name(self, name: str, value: str, label: str = "") -> bool:
        if not value:
            return False
        try:
            ok = self.driver.execute_script("""
                var inp = document.querySelector('[name="' + arguments[0] + '"]');
                if (!inp) return false;
                inp.scrollIntoView({block:'center'});
                inp.value = arguments[1];
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            """, name, value)
            if ok:
                print(f"    [OK] {label or name} = {value}")
            return bool(ok)
        except Exception as e:
            print(f"    [경고] {label or name} 입력 실패: {e}")
            return False

    def _fill_text_by_id(self, elem_id: str, value: str, label: str = "") -> bool:
        if not value:
            return False
        try:
            ok = self.driver.execute_script("""
                var inp = document.getElementById(arguments[0]);
                if (!inp) return false;
                inp.scrollIntoView({block:'center'});
                inp.value = arguments[1];
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            """, elem_id, value)
            if ok:
                print(f"    [OK] {label or elem_id} = {value}")
            return bool(ok)
        except Exception:
            return False

    def _select_by_text(self, name: str, text: str, label: str = "") -> bool:
        """select 요소에서 텍스트 일치(혹은 부분 일치) 옵션 선택"""
        if not text:
            return False
        try:
            ok = self.driver.execute_script("""
                var sel = document.querySelector('[name="' + arguments[0] + '"]');
                if (!sel) return null;
                var target = arguments[1].toLowerCase();
                // 1차: 정확 일치
                var opt = Array.from(sel.options).find(o => o.text.trim().toLowerCase() === target);
                // 2차: 부분 일치
                if (!opt) opt = Array.from(sel.options).find(o => o.text.toLowerCase().includes(target));
                if (!opt) return null;
                sel.value = opt.value;
                sel.dispatchEvent(new Event('change', {bubbles:true}));
                return opt.text;
            """, name, text)
            if ok:
                print(f"    [OK] {label or name} = {ok}")
                return True
        except Exception:
            pass
        return False

    def _dump_select_options(self, name: str, label: str = "") -> None:
        """select 옵션 텍스트 덤프 (매칭 실패 시 진단용)"""
        try:
            opts = self.driver.execute_script("""
                var sel = document.querySelector('[name="' + arguments[0] + '"]');
                if (!sel) return null;
                return Array.from(sel.options).map(o => o.text.trim());
            """, name)
            if opts is None:
                print(f"    [진단] {label or name} 요소 없음")
            else:
                print(f"    [진단] {label or name} 옵션({len(opts)}): {opts[:30]}")
        except Exception as e:
            print(f"    [진단] {label or name} 덤프 실패: {e}")

    def _select_by_text_multi(self, name: str, candidates: list[str], label: str = "") -> str:
        """여러 텍스트 후보로 select 시도. 성공한 후보 반환, 실패 시 빈 문자열."""
        for cand in candidates:
            if not cand:
                continue
            if self._select_by_text(name, cand, label):
                return cand
        return ""

    def _select_by_value(self, name: str, value: str, label: str = "") -> bool:
        if not value:
            return False
        try:
            ok = self.driver.execute_script("""
                var sel = document.querySelector('[name="' + arguments[0] + '"]');
                if (!sel) return false;
                sel.value = arguments[1];
                sel.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            """, name, value)
            if ok:
                print(f"    [OK] {label or name} (value) = {value}")
            return bool(ok)
        except Exception:
            return False

    def _click_radio_by_name(self, name: str, value: str, label: str = "") -> bool:
        try:
            ok = self.driver.execute_script("""
                var inputs = document.querySelectorAll('input[name="' + arguments[0] + '"]');
                for (var i = 0; i < inputs.length; i++) {
                    if (inputs[i].value === arguments[1]) {
                        inputs[i].click();
                        return true;
                    }
                }
                return false;
            """, name, value)
            if ok:
                print(f"    [OK] {label or name} 라디오 = {value}")
            return bool(ok)
        except Exception:
            return False

    def _click_xpath_if_exists(self, xpath: str, label: str = "") -> bool:
        try:
            els = self.driver.find_elements(By.XPATH, xpath)
            for el in els:
                if el.is_displayed():
                    self.driver.execute_script("arguments[0].click();", el)
                    if label:
                        print(f"    [OK] {label} 클릭")
                    return True
        except Exception:
            pass
        return False

    # ─────────────────────────────────────────────────────
    # 비포워드 매물 등록
    # ─────────────────────────────────────────────────────
    def upload_listing(self, row_idx: int, row: list, image_files: list[str]) -> bool:
        """비포워드 매물 등록 폼 입력 → 저장 → 이미지 업로드"""
        try:
            # 데이터 추출
            model      = (row[self.COL_MODEL] if len(row) > self.COL_MODEL else "").strip()
            year       = (row[self.COL_YEAR] if len(row) > self.COL_YEAR else "").strip()
            color      = (row[self.COL_COLOR] if len(row) > self.COL_COLOR else "").strip()
            car_number = (row[self.COL_CAR_NUMBER] if len(row) > self.COL_CAR_NUMBER else "").strip()
            vin        = (row[self.COL_VIN] if len(row) > self.COL_VIN else "").strip()
            i_val      = row[self.COL_DETAIL] if len(row) > self.COL_DETAIL else ""
            price_raw  = (row[self.COL_PRICE] if len(row) > self.COL_PRICE else "").strip()

            detail = self.parse_i_column(i_val)
            options = self.get_row_options(row)

            print(f"  모델: {model} ({year}), 차량번호: {car_number}, VIN: {vin}")
            print(f"  색상: {color}, 가격: {price_raw}")
            print(f"  파싱: {detail}")
            print(f"  옵션: {options}")

            # ── 필수 데이터 검증 ─────────────────────────
            if not model: raise ValueError("D열(모델) 누락")
            if not year:  raise ValueError("E열(연식) 누락")
            if not color: raise ValueError("F열(색상) 누락")
            if not vin:   raise ValueError("H열(VIN) 누락")
            if not i_val: raise ValueError("I열(세부정보) 누락")
            if not price_raw: raise ValueError("AB열(가격) 누락")

            # 1. 등록 폼으로 이동
            self.driver.get(self.BEFORWARD_LOGIN_URL)
            time.sleep(3)
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "bulk_confirm_form"))
                )
            except Exception:
                raise RuntimeError(
                    f"폼(#bulk_confirm_form) 로드 실패 — URL: {self.driver.current_url[:80]}"
                )

            # 2. 제조사 선택 (VIN 3자리 기반)
            vin_prefix = vin[:3].upper()
            if vin_prefix not in self.VIN_BRAND_MAP:
                raise ValueError(f"VIN_BRAND_MAP 미매핑: VIN 3자리 '{vin_prefix}'")
            brand_keyword = self.VIN_BRAND_MAP[vin_prefix]
            if not self._select_by_text("TempVehDetails[make_id]", brand_keyword, "제조사"):
                raise RuntimeError(f"제조사 select 실패: '{brand_keyword}'")
            time.sleep(1.5)  # 모델 옵션 로드 대기

            # 3. 모델 선택 (D열 모델명 기반 - 부분 일치)
            model_clean = re.sub(r"\(.*?\)", "", model).strip()
            model_ok = False
            for name in ("TempVehDetails[model_id]", "TempVehDetails[model_code]"):
                if self._select_by_text(name, model_clean, "모델"):
                    model_ok = True
                    break
            if not model_ok:
                raise RuntimeError(f"모델 select 실패: '{model_clean}'")

            # 4. 모델년도 / 제조년월 (연도 + 가능하면 월)
            year_digits = self._extract_digits(year)
            if len(year_digits) < 4:
                raise ValueError(f"E열 연도 추출 실패: '{year}'")
            yr = year_digits[:4]
            if not self._select_by_value("TempVehDetails[registration_year]", yr, "모델년도"):
                raise RuntimeError(f"모델년도 select 실패: {yr}")
            if not self._select_by_value("TempVehDetails[manufacture_year]", yr, "제조년월"):
                raise RuntimeError(f"제조년월 select 실패: {yr}")
            # 월: "2015. 06", "2015-06", "2015/06", "201506" 등에서 추출
            month_match = re.search(r"\d{4}[^\d]*(\d{1,2})", year)
            if month_match:
                mo = month_match.group(1).zfill(2)
                self._select_by_value("TempVehDetails[registration_month]", mo, "모델월")
                self._select_by_value("TempVehDetails[manufacture_month]", mo, "제조월")
            elif len(year_digits) >= 6:
                mo = year_digits[4:6]
                self._select_by_value("TempVehDetails[registration_month]", mo, "모델월")
                self._select_by_value("TempVehDetails[manufacture_month]", mo, "제조월")

            # 5. Body type 분류 + CBM 치수 (풀백 없음)
            body_type = self._get_body_type(model)
            if body_type not in self.CBM_DEFAULTS:
                raise ValueError(f"CBM_DEFAULTS 미매핑: '{body_type}'")
            dl, dw, dh = self.CBM_DEFAULTS[body_type]
            m3 = round(dl * dw * dh / 1_000_000, 3)
            print(f"  [Body] {body_type} → {dl}x{dw}x{dh} ({m3} m³)")
            self._fill_text_by_name("TempVehDetails[length]", str(dl), "길이(cm)")
            self._fill_text_by_name("TempVehDetails[width]",  str(dw), "너비(cm)")
            self._fill_text_by_name("TempVehDetails[height]", str(dh), "높이(cm)")
            self._fill_text_by_name("TempVehDetails[m3]",     str(m3), "M3")
            # 차량 타입 select (영문/한글 변형 시도)
            BODY_TYPE_CANDIDATES = {
                "Sedan":     ["Sedan", "세단", "SEDAN", "Saloon"],
                "SUV":       ["SUV", "Sport Utility", "Crossover", "SUV / Crossover"],
                "Hatchback": ["Hatchback", "해치백", "Hatch"],
                "Wagon":     ["Wagon", "왜건", "Estate", "Station Wagon"],
                "Coupe":     ["Coupe", "쿠페", "Coupé"],
                "Minivan":   ["Minivan", "미니밴", "MPV", "Mini Van"],
                "Van":       ["Van", "밴", "Cargo Van", "Commercial Van"],
                "Truck":     ["Truck", "트럭", "Pickup", "픽업"],
            }
            candidates = BODY_TYPE_CANDIDATES.get(body_type, [body_type])
            type_ok = False
            for name in ("TempVehDetails[type_id]", "TempVehDetails[type_2_id]"):
                if self._select_by_text_multi(name, candidates, "차량타입"):
                    type_ok = True
                    break
            if not type_ok:
                # 진단: 가능한 옵션 출력
                for name in ("TempVehDetails[type_id]", "TempVehDetails[type_2_id]"):
                    self._dump_select_options(name, "차량타입")
                raise RuntimeError(
                    f"차량 타입 select 실패: '{body_type}' (후보 시도: {candidates})"
                )

            # 6. 차대번호 (VIN)
            if not self._fill_text_by_name("TempVehDetails[chassis_no]", vin, "차대번호"):
                raise RuntimeError("차대번호 입력 실패")

            # 7. 주행거리
            mileage = self._extract_digits(detail.get("mileage", ""))
            if not mileage:
                raise ValueError("I열에서 주행거리 추출 실패")
            self._fill_text_by_name("TempVehDetails[mileage]", mileage, "주행거리")

            # 8. 배기량 — I열에 항목 없음, 있으면만 입력 (현재 데이터 미제공)
            engine = self._extract_digits(detail.get("engine_displacement", ""))
            if engine:
                self._fill_text_by_name("TempVehDetails[engine_capacity]", engine, "배기량")

            # 9. 연료
            fuel_raw = detail.get("fuel", "")
            if not fuel_raw:
                raise ValueError("I열에서 연료 추출 실패")
            if fuel_raw not in self.FUEL_MAPPING:
                raise ValueError(f"FUEL_MAPPING 미매핑: '{fuel_raw}'")
            fuel_bf = self.FUEL_MAPPING[fuel_raw]
            if not self._select_by_text("TempVehDetails[fuel_id]", fuel_bf, "연료"):
                raise RuntimeError(f"연료 select 실패: '{fuel_bf}'")

            # 10. 변속기
            trans_raw = detail.get("transmission", "")
            if not trans_raw:
                raise ValueError("I열에서 변속기 추출 실패")
            if trans_raw not in self.TRANSMISSION_MAPPING:
                raise ValueError(f"TRANSMISSION_MAPPING 미매핑: '{trans_raw}'")
            trans_bf = self.TRANSMISSION_MAPPING[trans_raw]
            if not self._select_by_text("TempVehDetails[transmission_id]", trans_bf, "변속기"):
                raise RuntimeError(f"변속기 select 실패: '{trans_bf}'")

            # 11. 핸들 — 좌핸들(2) 고정 (한국 시장)
            self._click_radio_by_name("TempVehDetails[steering]", "2", "핸들(좌)")

            # 12. 문 개수 — 4 고정 (재원표 없음)
            try:
                self._select_by_value("TempVehDetails[doors]", "4", "문개수")
            except Exception:
                self._fill_text_by_name("TempVehDetails[doors]", "4", "문개수")

            # 13. 구동방식 (풀백 없음)
            drive_raw = detail.get("drive_type", "").upper()
            if drive_raw and drive_raw in self.DRIVE_TYPE_MAPPING:
                drive_val = self.DRIVE_TYPE_MAPPING[drive_raw]
            else:
                # 모델명 AWD 키워드 보조 판정 (풀백 아님 — 확정 키워드만)
                model_upper = model.upper()
                if any(kw in model_upper for kw in self.AWD_KEYWORDS):
                    drive_val = "3"
                else:
                    raise ValueError(
                        f"구동방식 판정 실패: I열 '{drive_raw}' 미매핑, 모델 AWD 키워드 없음"
                    )
            if not self._click_radio_by_name("TempVehDetails[drive_type]", drive_val, "구동방식"):
                raise RuntimeError(f"구동방식 라디오 클릭 실패: value={drive_val}")

            # 14. 색상 (풀백 없음)
            if color not in self.COLOR_MAPPING:
                raise ValueError(f"COLOR_MAPPING 미매핑: '{color}'")
            color_bf = self.COLOR_MAPPING[color]
            if not self._select_by_text("TempVehDetails[ext_color_id]", color_bf, "색상"):
                raise RuntimeError(f"색상 select 실패: '{color_bf}'")

            # 15. 좌석수 (풀백 없음)
            seats = self._extract_digits(detail.get("seating", ""))
            if not seats:
                raise ValueError("I열에서 좌석수 추출 실패")
            self._fill_text_by_name("TempVehDetails[seats]", seats, "좌석수")

            # 16. 가격 (풀백 없음)
            price_num = self._normalize_price(price_raw)
            if not price_num:
                raise ValueError(f"가격 정규화 실패: '{price_raw}'")
            if not self._fill_text_by_id("trade-price-input", price_num, "가격"):
                if not self._fill_text_by_name("TempVehDetails[trade_price_input]", price_num, "가격(name)"):
                    raise RuntimeError("가격 입력 실패")
            # 할인가 = 0
            self._fill_text_by_name("TempVehDetails[available_discount]", "0", "할인가")

            # 17. 재고 위치 - KOREA
            self._select_by_text("TempVehDetails[stock_place_id]", "KOREA", "재고위치")

            # 18. 필수 동의 체크 (compensation agree)
            self._click_xpath_if_exists('//*[@id="chk-compensation-agree"]', "보상동의")

            # 19. 옵션 체크박스 (J~S열 + 필수)
            MANDATORY = ["에어컨", "파워핸들", "파워 윈도우", "에어백", "ABS", "AM/FM 라디오"]
            all_opts = list(options)
            for m in MANDATORY:
                if m not in all_opts:
                    all_opts.append(m)
            self._check_options(all_opts)

            # 20. 저장 버튼 클릭
            print("  [INFO] 저장 버튼 클릭")
            saved = self.driver.execute_script("""
                var btn = document.evaluate(
                    '/html/body/div[2]/div[1]/div/div/div/div/div/div/div/input',
                    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                if (btn) {
                    btn.removeAttribute('disabled');
                    btn.scrollIntoView({block:'center'});
                    btn.click();
                    return true;
                }
                var sels = ['#bulk_confirm_form input[type="submit"]',
                            '#bulk_confirm_form button',
                            'button[type="submit"]',
                            'input[type="submit"]'];
                for (var i = 0; i < sels.length; i++) {
                    var b = document.querySelector(sels[i]);
                    if (b) {
                        b.removeAttribute('disabled');
                        b.scrollIntoView({block:'center'});
                        b.click();
                        return true;
                    }
                }
                return false;
            """)
            if not saved:
                print("  [오류] 저장 버튼 찾기 실패")
                return False

            # 21. 저장 완료 대기 (URL 변경 또는 photo/upload 리다이렉트)
            listing_id = self._wait_and_extract_listing_id(timeout=30)
            print(f"  [INFO] 저장 후 URL: {self.driver.current_url[:100]}")

            if not listing_id:
                errs = self.driver.execute_script("""
                    var msgs = [];
                    document.querySelectorAll('.error, .text-danger, [class*="error"]').forEach(function(el) {
                        if (el.offsetParent !== null && el.textContent.trim())
                            msgs.push(el.textContent.trim().substring(0, 80));
                    });
                    return msgs;
                """) or []
                if errs:
                    print(f"  [오류] 폼 validation: {'; '.join(errs[:3])}")
                else:
                    print("  [오류] listing ID 추출 실패")
                return False

            print(f"  [OK] listing ID: {listing_id}")

            # 22. 이미지 업로드 + 23. 컨디션 시트 처리
            is_4wd = drive_val == "3"
            if image_files:
                ok = self._upload_images_and_condition(listing_id, image_files, is_4wd)
                if not ok:
                    print("  [경고] 이미지 업로드/컨디션 처리 실패 — 매물 저장은 성공")
            else:
                print("  [정보] 이미지 없음 — 이미지 단계 건너뜀")
                # 이미지가 없어도 컨디션 페이지는 처리
                self._fill_condition_sheet(listing_id, is_4wd)

            return True
        except Exception as e:
            print(f"[오류] 매물 등록 중 예외: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ─────────────────────────────────────────────────────
    # 옵션 체크
    # ─────────────────────────────────────────────────────
    def _check_options(self, options: list[str]) -> None:
        """옵션 라벨에 매칭되는 체크박스를 체크"""
        if not options:
            return
        print(f"  [옵션] {len(options)}개 매칭 시도")
        for opt in options:
            try:
                clicked = self.driver.execute_script("""
                    var target = arguments[0].toLowerCase().trim();
                    var labels = document.querySelectorAll('label');
                    for (var i = 0; i < labels.length; i++) {
                        var t = labels[i].textContent.toLowerCase().trim();
                        if (!t) continue;
                        if (t === target || t.includes(target) || target.includes(t)) {
                            var cb = null;
                            if (labels[i].htmlFor) cb = document.getElementById(labels[i].htmlFor);
                            if (!cb) cb = labels[i].querySelector('input[type="checkbox"], input[type="radio"]');
                            if (cb && !cb.checked) {
                                cb.click();
                                return true;
                            }
                            if (cb && cb.checked) return true;
                        }
                    }
                    return false;
                """, opt)
                if clicked:
                    print(f"    [OK] 옵션: {opt}")
            except Exception:
                pass

    # ─────────────────────────────────────────────────────
    # Body Type 분류
    # ─────────────────────────────────────────────────────
    def _get_body_type(self, model: str) -> str:
        if not model:
            raise ValueError("모델명 없음 — body type 판정 불가")
        upper = model.upper()
        for body, keywords in self.BODY_TYPE_MAP.items():
            for kw in keywords:
                if kw.upper() in upper:
                    return body
        raise ValueError(f"BODY_TYPE_MAP에 매칭되는 키워드 없음: '{model}'")

    # ─────────────────────────────────────────────────────
    # listing_id 추출 (URL → 페이지 내 링크 → DOM 탐색)
    # ─────────────────────────────────────────────────────
    def _wait_and_extract_listing_id(self, timeout: int = 30) -> str:
        """저장 직후 URL이나 페이지에서 listing_id 추출"""
        for _ in range(timeout):
            time.sleep(1)
            cur = self.driver.current_url
            for pat in (r"/edit/(\d+)", r"/photo/upload/(\d+)",
                        r"/ConditionsSheet/[^/]+/(\d+)", r"id=(\d+)"):
                m = re.search(pat, cur)
                if m:
                    return m.group(1)
            if "edit/" in cur.lower() or "photo/upload" in cur.lower():
                # URL은 바뀌었지만 ID 패턴이 다른 경우 — 페이지 내 검색으로 폴백
                break

        # 폴백 1: 페이지 내 a[href]에서 ID 추출
        try:
            href_id = self.driver.execute_script("""
                var links = document.querySelectorAll('a[href*="/edit/"], a[href*="/photo/upload/"]');
                for (var i = 0; i < links.length; i++) {
                    var m = links[i].href.match(/\\/(?:edit|photo\\/upload)\\/(\\d+)/);
                    if (m) return m[1];
                }
                return '';
            """)
            if href_id:
                return str(href_id)
        except Exception:
            pass

        # 폴백 2: 페이지 내 data-id 속성
        try:
            data_id = self.driver.execute_script("""
                var el = document.querySelector('[data-listing-id], [data-id]');
                return el ? (el.getAttribute('data-listing-id') || el.getAttribute('data-id')) : '';
            """)
            if data_id and data_id.isdigit():
                return str(data_id)
        except Exception:
            pass

        return ""

    # ─────────────────────────────────────────────────────
    # 이미지 업로드 + 컨디션 시트 (저장 후 전체 흐름)
    # ─────────────────────────────────────────────────────
    def _upload_images_and_condition(self, listing_id: str, image_files: list[str], is_4wd: bool) -> bool:
        ok_img = self._upload_images(listing_id, image_files)
        if not ok_img:
            return False
        # 이미지 저장이 끝나면 자동으로 condition page로 이동할 수 있음
        time.sleep(3)
        return self._fill_condition_sheet(listing_id, is_4wd)

    def _upload_images(self, listing_id: str, image_files: list[str]) -> bool:
        """photo/upload/{id}로 이동 → file input에 send_keys → 저장"""
        try:
            photo_url = f"https://external-vendor.beforward.jp/photo/upload/{listing_id}"
            print(f"  [이미지] {photo_url}")
            self.driver.get(photo_url)
            time.sleep(3)

            abs_paths = [os.path.abspath(p) for p in image_files if os.path.exists(p)]
            if not abs_paths:
                print("  [경고] 업로드할 이미지 파일 없음")
                return False

            # file input 찾기 (#public_pane 우선)
            file_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, '#public_pane input[type="file"]'
            )
            if not file_inputs:
                file_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, 'input[type="file"]'
                )
            if not file_inputs:
                print("  [경고] file input 요소 찾기 실패")
                return False

            # hidden input 가시화
            self.driver.execute_script("""
                document.querySelectorAll('input[type="file"]').forEach(function(inp) {
                    inp.style.display = 'block';
                    inp.style.visibility = 'visible';
                });
            """)

            file_input = file_inputs[0]
            file_input.send_keys("\n".join(abs_paths))
            print(f"  [OK] {len(abs_paths)}개 이미지 전송, 썸네일 생성 대기 중...")

            # 썸네일 생성 대기 (최대 60초, 카운트 변화 안정화)
            prev_count = 0
            stable = 0
            for tick in range(60):
                time.sleep(1)
                try:
                    cnt = self.driver.execute_script("""
                        var pane = document.querySelector('#public_pane');
                        if (!pane) return 0;
                        return pane.querySelectorAll('li img, li.uploaded, li[data-id]').length;
                    """) or 0
                except Exception:
                    cnt = 0
                if cnt == prev_count:
                    if cnt > 0:
                        stable += 1
                        if stable >= 3:
                            break
                else:
                    stable = 0
                    prev_count = cnt
            print(f"  [INFO] 썸네일 {prev_count}개 감지")

            # 이미지 저장 버튼 클릭 (#bulk_confirm_form/div/button 우선)
            saved = self.driver.execute_script("""
                var btn = document.evaluate(
                    '//*[@id="bulk_confirm_form"]/div/button',
                    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                if (btn) {
                    btn.removeAttribute('disabled');
                    btn.scrollIntoView({block:'center'});
                    btn.click();
                    return true;
                }
                var sels = [
                    '#public_pane input[type="submit"]',
                    '#public_pane button[type="submit"]',
                    'input[type="submit"][value*="Save"]',
                    'button[type="submit"]',
                ];
                for (var i = 0; i < sels.length; i++) {
                    var b = document.querySelector(sels[i]);
                    if (b && b.offsetParent !== null) {
                        b.scrollIntoView({block:'center'});
                        b.click();
                        return true;
                    }
                }
                return false;
            """)
            if not saved:
                print("  [경고] 이미지 저장 버튼 찾기 실패")
                return False

            print("  [OK] 이미지 저장 버튼 클릭")

            # URL 변경 or 저장 버튼 사라짐 대기 (최대 60초)
            pre_url = self.driver.current_url
            for _ in range(60):
                time.sleep(1)
                cur = self.driver.current_url
                if cur != pre_url:
                    print(f"  [OK] 이미지 저장 완료 → {cur[:80]}")
                    return True
                # 저장 버튼 사라졌는지
                btns = self.driver.find_elements(By.XPATH, '//*[@id="bulk_confirm_form"]/div/button')
                if not btns:
                    print("  [OK] 이미지 저장 완료 (버튼 사라짐)")
                    return True
            print("  [경고] 이미지 저장 완료 대기 시간 초과")
            return True
        except Exception as e:
            print(f"  [오류] 이미지 업로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ─────────────────────────────────────────────────────
    # 컨디션 시트 (부식 NO + 구동방식 + 저장)
    # ─────────────────────────────────────────────────────
    def _fill_condition_sheet(self, listing_id: str, is_4wd: bool) -> bool:
        try:
            # 컨디션 페이지로 이동 (이미지 저장 후 자동 이동 안 된 경우)
            cur = self.driver.current_url
            if "conditionssheet" not in cur.lower():
                cond_url = f"https://external-vendor.beforward.jp/ConditionsSheet/edit/{listing_id}"
                print(f"  [컨디션] {cond_url}")
                self.driver.get(cond_url)
                time.sleep(3)

            # 부식 NO: div[1]/button[1]
            corrosion_xp = '//*[@id="condition-form"]/div[1]/div/div[1]/div/button[1]'
            self._click_xpath_if_exists(corrosion_xp, "부식 NO")
            time.sleep(0.5)

            # 구동방식: div[11]/button[1] (4WD) 또는 button[3] (없음)
            drive_xp = (f'//*[@id="condition-form"]/div[1]/div/div[11]/div/button[1]'
                        if is_4wd
                        else f'//*[@id="condition-form"]/div[1]/div/div[11]/div/button[3]')
            self._click_xpath_if_exists(drive_xp, "4륜" if is_4wd else "구동방식(없음)")
            time.sleep(0.5)

            # 저장 버튼
            saved = self.driver.execute_script("""
                var XPATHS = [
                    '//*[@id="condition-form"]/div[2]/div/button',
                    '//button[@type="submit"]',
                    '//input[@type="submit"]',
                ];
                for (var i = 0; i < XPATHS.length; i++) {
                    var btn = document.evaluate(XPATHS[i], document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (btn && btn.offsetParent !== null) {
                        btn.removeAttribute('disabled');
                        btn.scrollIntoView({block:'center'});
                        btn.click();
                        return true;
                    }
                }
                return false;
            """)
            if saved:
                print("  [OK] 컨디션 시트 저장 버튼 클릭")
                time.sleep(3)
                return True
            print("  [경고] 컨디션 시트 저장 버튼 찾기 실패")
            return False
        except Exception as e:
            print(f"  [오류] 컨디션 시트 처리 실패: {e}")
            return False

    # ─────────────────────────────────────────────────────
    # 임시 파일 정리
    # ─────────────────────────────────────────────────────
    def cleanup_row_images(self, row_num: int) -> None:
        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        try:
            if os.path.exists(row_folder):
                shutil.rmtree(row_folder, ignore_errors=True)
                print(f"[OK] 임시 이미지 폴더 삭제: row_{row_num}")
        except Exception as e:
            print(f"[경고] 임시 폴더 삭제 실패: {e}")

    # ─────────────────────────────────────────────────────
    # 메인 실행
    # ─────────────────────────────────────────────────────
    def process_all(self, start_row: int = None, end_row: int = None) -> None:
        pending = self.get_pending_rows()
        if start_row:
            pending = [p for p in pending if p["row_idx"] >= start_row]
        if end_row:
            pending = [p for p in pending if p["row_idx"] <= end_row]

        if not pending:
            print("[알림] 업로드할 행이 없습니다.")
            return

        print(f"\n[진행] 총 {len(pending)}개 행 업로드 예정")

        # 드라이버 + 로그인 (고정 계정 1회만)
        self.setup_driver()
        if not self.login_beforward():
            print("[오류] 비포워드 로그인 실패. 종료합니다.")
            for item in pending:
                self.mark_upload_failed(item["row_idx"], "비포워드 로그인 실패")
            self.close_driver()
            return

        for item in pending:
            row_idx = item["row_idx"]
            row = item["row"]
            print(f"\n{'─'*60}")
            print(f"[{row_idx}행] 처리 시작")

            try:
                # 이미지 다운로드 (Y열)
                drive_link = self._get_drive_link_for_row(row_idx)
                image_files = []
                if drive_link:
                    print(f"  드라이브: {drive_link[:60]}")
                    image_files = self.download_images(drive_link, row_idx)
                else:
                    print("  [경고] Y열 드라이브 링크 없음")

                # 비포워드 매물 등록
                success = self.upload_listing(row_idx, row, image_files)

                if success:
                    self.mark_upload_date(row_idx)
                    print(f"[완료] {row_idx}행 업로드 성공")
                else:
                    self.mark_upload_failed(row_idx)
                    print(f"[실패] {row_idx}행 업로드 실패")

                self.cleanup_row_images(row_idx)
                time.sleep(2)
            except Exception as e:
                print(f"[오류] {row_idx}행 처리 중 예외: {e}")
                import traceback
                traceback.print_exc()
                self.mark_upload_failed(row_idx, f"예외: {str(e)[:80]}")
                self.cleanup_row_images(row_idx)

        self.close_driver()
        print("\n모든 행 처리 완료")


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("\n" + "=" * 70)
    print("비포워드 매물 업로드 자동화".center(70))
    print("=" * 70)

    uploader = BeforwardPackageUploader()
    if not uploader.setup_spreadsheet():
        print("[오류] 스프레드시트 연결 실패. 종료합니다.")
        return

    print("\n처리 범위 설정 (엔터 = 전체 자동 처리)")
    start_input = input("시작 행 번호 (비워두면 전체): ").strip()
    end_input = input("끝 행 번호 (비워두면 전체): ").strip()

    start_row = int(start_input) if start_input.isdigit() else None
    end_row = int(end_input) if end_input.isdigit() else None

    pending = uploader.get_pending_rows()
    if start_row:
        pending = [p for p in pending if p["row_idx"] >= start_row]
    if end_row:
        pending = [p for p in pending if p["row_idx"] <= end_row]

    print(f"\n[확인] 업로드 대기 행: {len(pending)}개")
    for p in pending[:10]:
        row = p["row"]
        model      = row[3] if len(row) > 3 else ""
        car_number = row[6] if len(row) > 6 else ""
        vin        = row[7] if len(row) > 7 else ""
        print(f"  행 {p['row_idx']}: {model} | 차량번호:{car_number} | VIN:{vin}")
    if len(pending) > 10:
        print(f"  ... 외 {len(pending) - 10}개")

    confirm = input("\n계속 진행하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("취소되었습니다.")
        return

    uploader.process_all(start_row=start_row, end_row=end_row)


if __name__ == "__main__":
    main()
