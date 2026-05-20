"""
망고패키지 매물 업로드 자동화
- 스프레드시트: 망고패키지 등록/입력 V 2.1 (GID: 1403349305)
- 조건: AC열(계정정보) 있고, AM열(업로드일자) 비어있는 행
- I열: 구동방식/변속기/연료/승차인원/주행거리/핸들위치 구조화 텍스트
- J~S열: 차량 옵션 항목 (최대 10개)
- Y열: 구글 드라이브 이미지 폴더 링크
- Z열: 플랫폼 링크 (성공 시 기입)
- AB열: 광고가
- AC열: 계정정보 (이메일 줄바꿈 비밀번호)
- AI열: 판매 상태 (성공 시 '판매중')
- AL열: 업로드 실패 메모
- AM열: 업로드 완료일자 (성공 시 오늘 날짜)
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
from selenium.common.exceptions import StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager
import os
import re
import shutil
import sys
import time
import unicodedata
import zipfile
from datetime import datetime


def _normalize_raw(s: str) -> str:
    """매핑 키 비교 전 raw 값 정규화: NFKC + 모든 공백/제로폭/필러 제거."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    # 일반 공백, NBSP, zero-width, 한글 필러, 라인 구분자 등 모두 제거
    s = re.sub(r"[\s​‌‍﻿ㅤ ]+", "", s)
    return s


class MangoPackageUploader:
    # 스프레드시트 설정
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

    # 열 인덱스 (0-based)
    COL_MODEL       = 3   # D
    COL_YEAR        = 4   # E
    COL_COLOR       = 5   # F
    COL_CAR_NUMBER  = 6   # G
    COL_VIN         = 7   # H
    COL_DETAIL      = 8   # I  (구조화 텍스트)
    COL_OPT_START   = 9   # J  (옵션 시작)
    COL_OPT_END     = 18  # S  (옵션 끝, inclusive)
    COL_DRIVE_LINK   = 24  # Y  (구글 드라이브 이미지 폴더)
    COL_PLATFORM_URL = 25  # Z  (플랫폼 링크)
    COL_ADMIN_URL    = 26  # AA (어드민 링크)
    COL_PRICE        = 27  # AB (플랫폼 광고가 $)
    COL_ACCOUNT      = 28  # AC (이메일\n비밀번호)
    COL_STATUS       = 34  # AI (판매 상태)
    COL_FAIL_NOTE    = 37  # AL (업로드실패 메모)
    COL_UPLOAD_DATE  = 38  # AM (업로드일자)

    # 이미지 다운로드 폴더
    DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded_images")

    # 망고카 사이트
    BASE_URL   = "https://mangoworldcar.com/ko"
    CREATE_URL = "https://mangoworldcar.com/ko/car-normal-create"

    # VIN 3자리 제조사 코드 → 브랜드 (드롭다운 옵션 매칭용)
    VIN_BRAND_MAP = {
        "KMH": ["현대", "HYUNDAI"], "KMJ": ["현대", "HYUNDAI"],
        "KNA": ["기아", "KIA"], "KND": ["기아", "KIA"], "KNJ": ["기아", "KIA"],
        "KPT": ["쉐보레", "CHEVROLET", "GM"],
        "WAU": ["아우디", "AUDI"],
        "WBA": ["BMW", "비엠더블유"], "WBY": ["BMW"],
        "WVW": ["폭스바겐", "VOLKSWAGEN", "VW"], "WVG": ["폭스바겐", "VOLKSWAGEN"],
        "SAL": ["랜드로버", "LAND ROVER"],
        "VF1": ["르노", "RENAULT"], "VF3": ["르노", "RENAULT"],
        "WDD": ["메르세데스", "MERCEDES", "벤츠", "BENZ"],
        "JHM": ["혼다", "HONDA"], "1HG": ["혼다", "HONDA"],
        "JN1": ["닛산", "NISSAN"], "JTD": ["도요타", "TOYOTA"],
        "WP0": ["포르쉐", "PORSCHE"],
        "ZFF": ["페라리", "FERRARI"],
    }

    TRANSMISSION_MAPPING = {
        "자동": "AUTO", "수동": "MANUAL", "오토": "AUTO", "매뉴얼": "MANUAL",
        "AUTO": "AUTO", "MANUAL": "MANUAL", "CVT": "AUTO", "DCT": "AUTO",
        "AT": "AUTO", "MT": "MANUAL",
    }

    COLOR_MAPPING = {
        "흰색": "WHITE", "화이트": "WHITE", "백색": "WHITE",
        "검은색": "BLACK", "검정": "BLACK", "검정색": "BLACK", "블랙": "BLACK",
        "은색": "SILVER", "실버": "SILVER",
        "회색": "GRAY", "그레이": "GRAY", "쥐색": "GRAY",
        "파란색": "BLUE", "파랑": "BLUE", "블루": "BLUE", "청색": "BLUE",
        "빨간색": "RED", "빨강": "RED", "레드": "RED",
        "갈색": "BROWN", "브라운": "BROWN",
        "초록색": "GREEN", "초록": "GREEN", "그린": "GREEN", "녹색": "GREEN",
        "노란색": "YELLOW", "노랑": "YELLOW",
        "금색": "GOLD", "골드": "GOLD",
        "주황색": "ORANGE", "주황": "ORANGE", "오렌지": "ORANGE",
        "보라색": "PURPLE", "보라": "PURPLE", "퍼플": "PURPLE",
        "분홍색": "PINK", "분홍": "PINK", "핑크": "PINK",
        "남색": "NAVY", "네이비": "NAVY",
        "진주": "PEARL", "펄": "PEARL",
        "민트": "MINT",
        "기타": "ETC",
    }

    FUEL_MAPPING = {
        "가솔린": "가솔린", "휘발유": "가솔린",
        "디젤": "디젤", "경유": "디젤",
        "LPG": "LPG", "엘피지": "LPG",
        "하이브리드": "하이브리드",
        "전기": "전기",
        "수소": "수소",
        "기타": "기타",
    }

    DRIVE_MAPPING = {
        "2": "2WD", "2WD": "2WD", "2륜": "2WD", "FWD": "FWD", "RWD": "RWD",
        "4": "4WD", "4WD": "4WD", "4륜": "4WD", "AWD": "4WD",
    }

    def __init__(self):
        self.driver = None
        self.worksheet = None
        self.all_rows = []
        self.creds = None
        self.drive_links: dict[int, str] = {}  # row_idx → drive URL

    # ─────────────────────────────────────────────
    # 스프레드시트
    # ─────────────────────────────────────────────
    def setup_spreadsheet(self) -> bool:
        try:
            print("[진행] 스프레드시트 연결 중...")
            self.creds = Credentials.from_service_account_file(
                self.SERVICE_ACCOUNT_FILE, scopes=self.SCOPES
            )
            gc = gspread.authorize(self.creds)
            spreadsheet = gc.open_by_key(self.SPREADSHEET_ID)
            for sheet in spreadsheet.worksheets():
                if sheet.id == self.SHEET_GID:
                    self.worksheet = sheet
                    break
            if not self.worksheet:
                print("[오류] 시트를 찾을 수 없습니다")
                return False
            print(f"[OK] 스프레드시트 연결 성공: {self.worksheet.title}")
            self.all_rows = self.worksheet.get_all_values()
            self._fetch_w_column_links()
            return True
        except Exception as e:
            print(f"[오류] 스프레드시트 연결 실패: {e}")
            return False

    def _fetch_w_column_links(self) -> None:
        """Y열 전체 하이퍼링크를 Sheets API v4로 한 번에 가져옴"""
        try:
            print("[진행] Y열 사진 드라이브 링크 조회 중...")
            service = build("sheets", "v4", credentials=self.creds)
            result = service.spreadsheets().get(
                spreadsheetId=self.SPREADSHEET_ID,
                ranges=[f"'{self.worksheet.title}'!Y:Y"],
                fields="sheets(data(rowData(values(hyperlink,formattedValue,userEnteredValue))))"
            ).execute()

            row_data = (
                result.get("sheets", [{}])[0]
                .get("data", [{}])[0]
                .get("rowData", [])
            )
            for idx, row in enumerate(row_data):
                row_num = idx + 1  # 1-based
                if row_num < 2:    # 헤더 제외
                    continue
                values = row.get("values", [])
                if not values:
                    continue
                cell = values[0]

                # 1) hyperlink 필드
                link = cell.get("hyperlink", "")

                # 2) HYPERLINK 수식에서 추출
                if not link:
                    uev = cell.get("userEnteredValue", {})
                    formula = uev.get("formulaValue", "") if isinstance(uev, dict) else ""
                    if formula:
                        m = re.search(r'HYPERLINK\("([^"]+)"', formula)
                        if m:
                            link = m.group(1)

                # 3) formattedValue가 URL 형태이면 그대로 사용
                if not link:
                    fv = cell.get("formattedValue", "")
                    if fv and fv.startswith("http"):
                        link = fv

                if link and ("drive.google.com" in link or "docs.google.com" in link):
                    self.drive_links[row_num] = link

            print(f"[OK] Y열 링크 {len(self.drive_links)}개 확인 완료")
        except Exception as e:
            print(f"[경고] W열 링크 일괄 조회 실패: {e}. 행별 개별 조회로 대체합니다.")

    def _get_drive_link_for_row(self, row_idx: int) -> str:
        """row_idx 행의 드라이브 링크 반환 (캐시 우선).
        all_rows[0]이 헤더(1행)이므로 N행 데이터는 all_rows[N-1]."""
        if row_idx in self.drive_links:
            return self.drive_links[row_idx]
        # 캐시에 없으면 all_rows에서 직접 추출 시도
        idx = row_idx - 1
        row = self.all_rows[idx] if 0 <= idx < len(self.all_rows) else []
        val = row[self.COL_DRIVE_LINK].strip() if len(row) > self.COL_DRIVE_LINK else ""
        if val.startswith("http") and ("drive.google.com" in val or "docs.google.com" in val):
            return val
        return ""

    def get_pending_rows(self) -> list[dict]:
        """AC열(계정) 있고 AI열이 '판매중'이 아닌 행 반환"""
        pending = []
        for row_idx, row in enumerate(self.all_rows[1:], start=2):
            ac_val = row[self.COL_ACCOUNT] if len(row) > self.COL_ACCOUNT else ""
            ai_val = row[self.COL_STATUS] if len(row) > self.COL_STATUS else ""
            if not (ac_val and ac_val.strip()):
                continue
            if ai_val and ai_val.strip() == "판매중":
                continue
            pending.append({"row_idx": row_idx, "row": row})
        return pending

    def parse_account_info(self, aa_val: str) -> tuple[str, str]:
        """AA열 '이메일\n비밀번호' → (email, password)"""
        parts = aa_val.strip().splitlines()
        email = parts[0].strip() if len(parts) > 0 else ""
        password = parts[1].strip() if len(parts) > 1 else ""
        return email, password

    def parse_i_column(self, i_val: str) -> dict:
        """I열 구조화 텍스트 파싱"""
        result = {
            "sub_model": "",
            "drive_type": "",
            "transmission": "",
            "fuel": "",
            "seating": "",
            "mileage": "",
            "handle": "",
            "engine_displacement": "",
        }
        if not i_val or i_val.strip() == "해당없음":
            return result

        patterns = {
            "sub_model":            r"1\.\s*세부모델[ \t]*:[ \t]*([^\r\n]*)",
            "drive_type":           r"2\.\s*구동방식[ \t]*:[ \t]*([^\r\n]*)",
            "transmission":         r"3\.\s*변속기[ \t]*:[ \t]*([^\r\n]*)",
            "fuel":                 r"4\.\s*연료[ \t]*:[ \t]*([^\r\n]*)",
            "seating":              r"5\.\s*승차인원[ \t]*:[ \t]*([^\r\n]*)",
            "mileage":              r"6\.\s*주행거리[ \t]*:[ \t]*([^\r\n]*)",
            "handle":               r"7\.\s*핸들위치[ \t]*:[ \t]*([^\r\n]*)",
            "engine_displacement":  r"배기량[ \t]*:[ \t]*([^\r\n]*)",
        }
        for key, pattern in patterns.items():
            m = re.search(pattern, i_val)
            if m:
                result[key] = m.group(1).strip()

        return result

    def get_row_options(self, row: list) -> list[str]:
        """J~S열에서 옵션 이름 리스트 추출"""
        options = []
        for col_idx in range(self.COL_OPT_START, self.COL_OPT_END + 1):
            if col_idx < len(row):
                val = row[col_idx].strip()
                if val:
                    options.append(val)
        return options

    # ─────────────────────────────────────────────
    # 이미지 다운로드 / 업로드 / 정리
    # ─────────────────────────────────────────────
    def _extract_folder_id(self, drive_link: str) -> str:
        """드라이브 링크에서 폴더 ID 추출"""
        m = re.search(r"/folders/([a-zA-Z0-9_-]+)", drive_link)
        return m.group(1) if m else ""

    def _num_sort_key(self, path: str):
        name = os.path.splitext(os.path.basename(path))[0]
        parts = re.split(r'(\d+)', name)
        return [int(p) if p.isdigit() else p.lower() for p in parts]

    def _download_via_drive_api(self, folder_id: str, row_folder: str) -> list[str]:
        """Drive API로 폴더 내 이미지 전체 다운로드"""
        from googleapiclient.http import MediaIoBaseDownload
        img_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif"}
        img_mimes = {
            "image/jpeg", "image/png", "image/gif",
            "image/bmp", "image/webp", "image/heic", "image/heif",
        }
        try:
            drive_svc = build("drive", "v3", credentials=self.creds)
            files = []
            page_token = None
            while True:
                resp = drive_svc.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                files.extend(resp.get("files", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            img_files = [
                f for f in files
                if f.get("mimeType", "") in img_mimes
                or any(f["name"].lower().endswith(f".{e}") for e in img_exts)
            ]
            if not img_files:
                print(f"  [Drive API] 이미지 없음 (전체 {len(files)}개)")
                return []

            print(f"  [Drive API] 이미지 {len(img_files)}개 발견 (전체 {len(files)}개)")

            def _nkey(f):
                name = os.path.splitext(f["name"])[0]
                parts = re.split(r'(\d+)', name)
                return [int(p) if p.isdigit() else p.lower() for p in parts]
            img_files.sort(key=_nkey)

            downloaded = []
            for fi in img_files:
                dst = os.path.join(row_folder, fi["name"])
                try:
                    req = drive_svc.files().get_media(
                        fileId=fi["id"], supportsAllDrives=True
                    )
                    with open(dst, "wb") as fh:
                        dl = MediaIoBaseDownload(fh, req)
                        done = False
                        while not done:
                            _, done = dl.next_chunk()
                    downloaded.append(dst)
                except Exception as e:
                    print(f"  [경고] {fi['name']} 다운로드 실패: {e}")

            return downloaded
        except Exception as e:
            print(f"  [Drive API 실패] {e}")
            return []

    def download_images_via_api(self, drive_link: str, row_num: int) -> list[str]:
        """구글 드라이브 폴더에서 이미지 다운로드
        흐름: drive-main-page XPath 클릭 → 30초 대기 → ZIP 압축 해제 → 숫자순 정렬
        """
        if not drive_link:
            return []

        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        if os.path.exists(row_folder):
            shutil.rmtree(row_folder, ignore_errors=True)
        os.makedirs(row_folder, exist_ok=True)
        os.makedirs(self.DOWNLOAD_FOLDER, exist_ok=True)

        img_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif"}
        download_abs = os.path.abspath(self.DOWNLOAD_FOLDER)

        # ── Selenium 드라이버 (전용) ────────────────────────────
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
            dl_driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
            dl_driver.execute_cdp_cmd("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": download_abs,
            })

            print(f"  [드라이브 접속] {drive_link[:80]}")
            dl_driver.get(drive_link)
            time.sleep(5)

            pre_files = set(os.listdir(download_abs))

            # ── 1. "전체 다운로드" 버튼 클릭 ─────────────────────
            # 텍스트 기반 셀렉터 우선 (Drive UI 변경에 강함)
            DOWNLOAD_SELECTORS = [
                "//*[normalize-space(text())='전체 다운로드']",
                "//*[normalize-space(text())='Download all']",
                "//div[@role='button' and (contains(.,'전체 다운로드') or contains(.,'Download all'))]",
                "//*[contains(@aria-label,'전체 다운로드') or contains(@aria-label,'Download all')]",
                # 마지막 폴백: 절대 XPath
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
                    # 일반 클릭 → JS 클릭 → 부모 클릭 순서 시도
                    try:
                        btn.click()
                    except Exception:
                        try:
                            dl_driver.execute_script("arguments[0].click();", btn)
                        except Exception:
                            # 부모 요소 클릭 (텍스트 노드만 매칭됐을 때)
                            parent = dl_driver.execute_script(
                                "return arguments[0].parentElement;", btn)
                            dl_driver.execute_script("arguments[0].click();", parent)
                    print(f"  [OK] 다운로드 버튼 클릭 ({sel[:60]})")
                    clicked = True
                    break
                except Exception:
                    continue

            if not clicked:
                print("  [오류] 다운로드 버튼을 찾을 수 없습니다")
                return []

            # ── 2. ZIP 다운로드 대기 (30초) ────────────────────
            print("  [대기] ZIP 다운로드 30초 대기 중...")
            time.sleep(30)

            # 추가로 다운로드 진행 중인 파일 있으면 더 기다림 (최대 추가 60초)
            extra_end = time.time() + 60
            while time.time() < extra_end:
                in_prog = [f for f in os.listdir(download_abs)
                           if f.endswith(".crdownload") or f.endswith(".tmp")]
                if not in_prog:
                    break
                time.sleep(2)

            # ── 3. 새로 생긴 ZIP 파일 찾기 ──────────────────────
            cur_files = set(os.listdir(download_abs))
            new_zips = [
                f for f in cur_files - pre_files
                if f.lower().endswith(".zip")
            ]
            if not new_zips:
                print("  [경고] ZIP 파일을 찾을 수 없습니다")
                return []

            # 가장 최근 ZIP 선택
            zip_name = max(new_zips, key=lambda f: os.path.getmtime(os.path.join(download_abs, f)))
            zip_src = os.path.join(download_abs, zip_name)
            print(f"  [OK] ZIP 발견: {zip_name}")

            # ── 4. 압축 해제 ────────────────────────────────────
            try:
                zip_dst = os.path.join(row_folder, "downloaded.zip")
                shutil.move(zip_src, zip_dst)
                with zipfile.ZipFile(zip_dst, "r") as zf:
                    zf.extractall(row_folder)
                os.remove(zip_dst)
                print(f"  [OK] 압축 해제 완료")
            except Exception as e:
                print(f"  [오류] 압축 해제 실패: {e}")
                return []

            # ── 5. 이미지 수집 + 숫자순 정렬 ───────────────────
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

    def upload_images_to_form(self, image_files: list[str]) -> bool:
        """이미지 섹션의 file input에 이미지 경로 전송.
        못 찾으면 ValueError raise — 후속 단계에서 cascading 실패하지 않도록."""
        if not image_files:
            raise ValueError("업로드할 이미지가 없습니다")

        abs_paths = [os.path.abspath(f) for f in image_files]
        print(f"\n[이미지 업로드] {len(abs_paths)}개 파일 전송 시작")

        # 이미지 섹션 라벨이 보이면 뷰포트로 스크롤 (lazy-render 대비)
        try:
            labels = self.driver.find_elements(
                By.XPATH,
                "//*[contains(text(),'이미지') or contains(text(),'사진') "
                "or contains(text(),'Image') or contains(text(),'Photo')]"
            )
            for lbl in labels:
                if lbl.is_displayed():
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", lbl)
                    time.sleep(0.3)
                    break
        except Exception:
            pass

        # file input 폴링 (최대 10초) — accept=image 우선, 일반 file input 폴백
        file_input = None
        deadline = time.time() + 10
        while time.time() < deadline:
            file_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='file'][accept*='image']"
            )
            if not file_inputs:
                file_inputs = self.driver.find_elements(
                    By.CSS_SELECTOR, "input[type='file']"
                )
            if file_inputs:
                # 보이는 것 우선, 없으면 첫 번째 (file input은 보통 display:none)
                for fi in file_inputs:
                    try:
                        if fi.is_displayed():
                            file_input = fi
                            break
                    except Exception:
                        pass
                if not file_input:
                    file_input = file_inputs[0]
                break
            time.sleep(0.5)

        if not file_input:
            # 진단: 페이지 상태 덤프
            try:
                cur_url = self.driver.current_url
                title = (self.driver.title or "")[:100]
                print(f"   [진단] URL: {cur_url}")
                print(f"   [진단] Title: {title}")
                # 현재 보이는 헤딩
                h = self.driver.find_elements(By.XPATH, "//h1 | //h2 | //h3 | //h4")
                h_texts = [el.text.strip() for el in h
                           if el.is_displayed() and el.text.strip()][:8]
                print(f"   [진단] 헤딩: {h_texts}")
                # STEP/단계 표시
                step_texts = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(),'STEP') or contains(text(),'단계') "
                    "or contains(text(),'Step')]")
                visible_steps = [s.text.strip() for s in step_texts
                                 if s.is_displayed() and s.text.strip()][:5]
                print(f"   [진단] STEP 표시: {visible_steps}")
                # 모든 input 타입 분포
                all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
                input_types = [i.get_attribute("type") or "(없음)" for i in all_inputs]
                from collections import Counter
                print(f"   [진단] input 타입 분포: {dict(Counter(input_types))}")
                # 이미지 관련 키워드 라벨
                img_labels = self.driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(),'이미지') or contains(text(),'사진') "
                    "or contains(text(),'Image') or contains(text(),'업로드') "
                    "or contains(text(),'Upload')]")
                img_label_texts = [el.text.strip()[:50] for el in img_labels
                                   if el.is_displayed() and el.text.strip()][:8]
                print(f"   [진단] 이미지 관련 라벨: {img_label_texts}")
                # 보이는 버튼들
                btns = self.driver.find_elements(By.TAG_NAME, "button")
                btn_texts = [b.text.strip()[:30] for b in btns
                             if b.is_displayed() and b.text.strip()][:15]
                print(f"   [진단] 보이는 버튼: {btn_texts}")
                # iframe 여부
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                print(f"   [진단] iframe 개수: {len(iframes)}")
                # 스크린샷
                debug_dir = os.path.join(self.DOWNLOAD_FOLDER, "debug")
                os.makedirs(debug_dir, exist_ok=True)
                ss_path = os.path.join(
                    debug_dir,
                    f"image_step_missing_{int(time.time())}.png")
                self.driver.save_screenshot(ss_path)
                print(f"   [진단] 스크린샷 저장: {ss_path}")
            except Exception as diag_e:
                print(f"   [진단] 덤프 실패: {diag_e}")

            raise ValueError("이미지 file input 요소를 찾을 수 없음 (10초 대기 후)")

        try:
            file_input.send_keys("\n".join(abs_paths))
            print(f"[OK] {len(abs_paths)}개 이미지 전송 완료. 업로드 대기 중...")
            time.sleep(8)
            return True
        except Exception as e:
            raise ValueError(f"이미지 전송 실패: {e}")

    def cleanup_row_images(self, row_num: int) -> None:
        """행별 임시 다운로드 폴더 삭제"""
        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        try:
            if os.path.exists(row_folder):
                shutil.rmtree(row_folder)
                print(f"[OK] 임시 이미지 폴더 삭제: {row_folder}")
        except Exception as e:
            print(f"[경고] 임시 폴더 삭제 실패: {e}")

    def mark_upload_date(self, row_idx: int) -> bool:
        """AM열에 오늘 날짜 기입"""
        try:
            today = datetime.now().strftime("%Y. %m. %d")
            cell = f"AM{row_idx}"
            self.worksheet.update_acell(cell, today)
            print(f"[OK] {cell}에 업로드일자 '{today}' 기입 완료")
            return True
        except Exception as e:
            print(f"[오류] 업로드일자 기입 실패: {e}")
            return False

    def clear_row_marks(self, row_idx: int) -> None:
        """Z / AI / AL / AM 열을 비워 행을 재처리 가능 상태로 복원"""
        for col in ("Z", "AI", "AL", "AM"):
            try:
                self.worksheet.update_acell(f"{col}{row_idx}", "")
                print(f"[FORCE] {col}{row_idx} 비움")
            except Exception as e:
                print(f"[경고] {col}{row_idx} 비우기 실패: {e}")
        # all_rows 캐시 재로드
        try:
            self.all_rows = self.worksheet.get_all_values()
        except Exception as e:
            print(f"[경고] all_rows 재로드 실패: {e}")

    def mark_status_selling(self, row_idx: int) -> bool:
        """AI열에 '판매중' 기입 (업로드 성공 시)"""
        try:
            cell = f"AI{row_idx}"
            self.worksheet.update_acell(cell, "판매중")
            print(f"[OK] {cell}에 '판매중' 기입 완료")
            return True
        except Exception as e:
            print(f"[오류] 판매상태 기입 실패: {e}")
            return False

    def mark_car_urls(self, row_idx: int, detail_url: str) -> bool:
        """Z열(플랫폼 링크) 기입"""
        try:
            self.worksheet.update_acell(f"Z{row_idx}", detail_url)
            print(f"[OK] Z{row_idx}={detail_url}")
            return True
        except Exception as e:
            print(f"[오류] URL 기입 실패: {e}")
            return False

    def mark_upload_failed(self, row_idx: int, reason: str = "") -> bool:
        """AL열에 '업로드실패: {사유}' 형식으로 기록 (코드 버그/예외 등)"""
        try:
            cell = f"AL{row_idx}"
            reason = " ".join((reason or "").split())
            text = f"업로드실패: {reason}" if reason else "업로드실패"
            if len(text) > 60:
                text = text[:57] + "..."
            self.worksheet.update_acell(cell, text)
            print(f"[OK] {cell}에 '{text}' 기입")
            return True
        except Exception as e:
            print(f"[오류] 실패 표시 기입 실패: {e}")
            return False

    def mark_row_status(self, row_idx: int, status: str) -> bool:
        """AL열에 raw 상태 텍스트 기입 (프리픽스 없음).
        예: '이미등록된 차량', '차대번호 조회안됨'"""
        try:
            cell = f"AL{row_idx}"
            text = " ".join((status or "").split())
            if len(text) > 60:
                text = text[:57] + "..."
            self.worksheet.update_acell(cell, text)
            print(f"[OK] {cell}에 '{text}' 기입")
            return True
        except Exception as e:
            print(f"[오류] 상태 기입 실패: {e}")
            return False

    # ─────────────────────────────────────────────
    # 드라이버
    # ─────────────────────────────────────────────
    def setup_driver(self) -> None:
        chrome_options = Options()
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        )
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=chrome_options
        )
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
        print("[OK] Chrome 드라이버 초기화 완료")

    def close_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # ─────────────────────────────────────────────
    # 로그인
    # ─────────────────────────────────────────────
    def _dismiss_today_popup(self) -> None:
        """진입 시 뜨는 '오늘 하루 보지 않기' 팝업이 있으면 클릭하여 닫음"""
        try:
            btns = self.driver.find_elements(
                By.XPATH,
                "//button[contains(normalize-space(.),'오늘 하루 보지 않기')]",
            )
            for b in btns:
                if b.is_displayed():
                    self.driver.execute_script("arguments[0].click();", b)
                    print("[OK] '오늘 하루 보지 않기' 팝업 닫음")
                    time.sleep(0.5)
                    return
        except Exception as e:
            print(f"[정보] 팝업 닫기 스킵: {e}")

    def login(self, email: str, password: str) -> bool:
        try:
            print(f"\n[로그인] {email}")
            self.driver.get(self.BASE_URL)
            time.sleep(2)

            # 진입 팝업 닫기 ('오늘 하루 보지 않기')
            self._dismiss_today_popup()

            # 로그인 링크 클릭
            try:
                login_links = self.driver.find_elements(
                    By.XPATH, "//*[contains(text(),'로그인') or contains(text(),'Login')]"
                )
                for link in login_links:
                    if link.is_displayed():
                        link.click()
                        time.sleep(1)
                        break
            except Exception:
                pass

            wait = WebDriverWait(self.driver, 10)

            # 이메일 입력
            email_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_field.clear()
            email_field.send_keys(email)

            # 비밀번호 입력
            pw_field = self.driver.find_element(By.NAME, "password")
            pw_field.clear()
            pw_field.send_keys(password)

            # 로그인 버튼 클릭
            submit_btns = self.driver.find_elements(
                By.XPATH, "//button[@type='submit'] | //button[contains(text(),'로그인')]"
            )
            for btn in submit_btns:
                if btn.is_displayed():
                    btn.click()
                    break

            time.sleep(3)
            print(f"[OK] 로그인 완료 - URL: {self.driver.current_url}")
            return True

        except Exception as e:
            print(f"[오류] 로그인 실패: {e}")
            return False

    def logout(self) -> None:
        try:
            logout_btns = self.driver.find_elements(
                By.XPATH, "//*[contains(text(),'로그아웃') or contains(text(),'Logout')]"
            )
            for btn in logout_btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(1)
                    break
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # 폼 입력 헬퍼
    # ─────────────────────────────────────────────
    def _open_combobox(self, combo_element, field_name: str) -> bool:
        def options_visible():
            try:
                WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[@role='option'] | //*[@cmdk-item]")
                    )
                )
                return True
            except Exception:
                return False

        attempts = [
            ("js click", lambda: self.driver.execute_script("arguments[0].click();", combo_element)),
            ("native click", lambda: combo_element.click()),
            ("action click", lambda: ActionChains(self.driver).move_to_element(combo_element).click().perform()),
        ]
        for name, action in attempts:
            try:
                action()
                time.sleep(0.4)
                if options_visible():
                    print(f"[OK] {field_name} combobox 열림 ({name})")
                    return True
            except Exception as e:
                print(f"   [디버그] {field_name} combobox {name} 실패: {e}")
        return False

    def _select_option_from_open_combobox(self, option_value: str, field_name: str) -> bool:
        time.sleep(0.5)

        def try_click_option(pred):
            """pred(text) → bool. 재시도 3회 (stale 대응)."""
            for attempt in range(3):
                try:
                    opts = self.driver.find_elements(By.XPATH, "//div[@role='option']")
                    if attempt == 0 and opts:
                        print(f"   [디버그] {field_name} 가능 옵션: "
                              f"{[o.text.strip() for o in opts[:8]]}")
                    for opt in opts:
                        try:
                            txt = opt.text.strip()
                            if pred(txt):
                                try:
                                    ActionChains(self.driver).move_to_element(opt).click().perform()
                                except Exception:
                                    self.driver.execute_script("arguments[0].click();", opt)
                                print(f"[OK] {field_name} '{txt}' 선택")
                                return True
                        except StaleElementReferenceException:
                            break  # 이 iteration 재시도
                    return False  # 매칭 없음
                except Exception:
                    time.sleep(0.2)
            return False

        # 1. 정확한 텍스트
        if try_click_option(lambda t: t == option_value):
            return True
        # 2. 포함 매칭 (대소문자 무시)
        if try_click_option(lambda t: (option_value.upper() in t.upper()
                                       or t.upper() in option_value.upper())):
            return True
        # 3. 숫자 매칭
        if option_value.isdigit():
            if try_click_option(lambda t: "".join(filter(str.isdigit, t)) == option_value):
                return True

        self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        print(f"[경고] {field_name} '{option_value}' 매칭 실패")
        return False

    def click_combobox_and_select(self, xpath: str, option_value: str, field_name: str) -> bool:
        try:
            combo = self.driver.find_element(By.XPATH, xpath)
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", combo)
            time.sleep(0.3)
            if not self._open_combobox(combo, field_name):
                print(f"[경고] {field_name} combobox 열기 실패")
                return False
            return self._select_option_from_open_combobox(option_value, field_name)
        except Exception as e:
            print(f"[경고] {field_name} 선택 실패: {e}")
            return False

    def select_first_option(self, xpath: str, field_name: str) -> bool:
        try:
            combo = self.driver.find_element(By.XPATH, xpath)
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", combo)
            time.sleep(0.3)
            if not self._open_combobox(combo, field_name):
                return False
            time.sleep(0.3)
            options = self.driver.find_elements(By.XPATH, "//div[@role='option']")
            if options:
                text = options[0].text.strip()
                try:
                    options[0].click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", options[0])
                print(f"[OK] {field_name} '{text}' 선택 (첫 번째)")
                return True
            return False
        except Exception as e:
            print(f"[경고] {field_name} 첫 번째 옵션 선택 실패: {e}")
            return False

    # ─────────────────────────────────────────────
    # 차대번호로 차량 조회
    # ─────────────────────────────────────────────
    def input_vin_and_search(self, vin: str) -> bool:
        try:
            print(f"\n[차대번호 조회] '{vin}'")

            # 차대번호 탭 찾기: 텍스트 '차대번호' 포함 탭 우선, 없으면 tabs[0]
            tabs = self.driver.find_elements(By.XPATH, "//button[@role='tab']")
            vin_tab = None
            for t in tabs:
                try:
                    if "차대번호" in t.text and t.is_displayed():
                        vin_tab = t
                        break
                except Exception:
                    pass
            if vin_tab:
                vin_tab.click()
                print(f"[OK] 차대번호 탭 클릭 (텍스트: '{vin_tab.text}')")
                time.sleep(0.5)
            elif tabs:
                tabs[0].click()
                print(f"[OK] 탭[0] 클릭 (fallback: '{tabs[0].text}')")
                time.sleep(0.5)
            else:
                print("[경고] 탭을 찾지 못함")

            # VIN 입력 필드 찾기
            vin_input = None
            vin_xpaths = [
                "//input[@placeholder='차대번호를 입력해주세요']",
                "//input[@placeholder='VIN']",
                "//input[@placeholder='차대번호']",
                "//input[@id='vin']",
            ]
            for xp in vin_xpaths:
                try:
                    vin_input = self.driver.find_element(By.XPATH, xp)
                    break
                except Exception:
                    pass

            if not vin_input:
                # 탭 전환 후 활성화된 입력 필드 찾기
                try:
                    inputs = self.driver.find_elements(
                        By.XPATH, "//input[@type='text' and not(@disabled)]"
                    )
                    visible_inputs = [inp for inp in inputs if inp.is_displayed()]
                    if visible_inputs:
                        vin_input = visible_inputs[0]
                except Exception:
                    pass

            if not vin_input:
                print("[경고] VIN 입력 필드를 찾을 수 없습니다. 차량번호 탭으로 시도")
                return self._fallback_input_as_car_number(vin)

            vin_input.clear()
            vin_input.send_keys(vin)
            print(f"[OK] VIN '{vin}' 입력 완료")
            time.sleep(0.5)

            # 조회하기 버튼 클릭
            try:
                search_btn = self.driver.find_element(
                    By.XPATH, "//button[contains(.,'조회하기')]"
                )
                search_btn.click()
                print("[OK] 조회하기 버튼 클릭")
                time.sleep(4)
            except Exception as e:
                print(f"[경고] 조회하기 버튼 실패: {e}")

            # 확인/선택 다이얼로그 처리 — 이미 등록 여부 캡처
            if self._handle_confirm_dialogs():
                self._last_lookup_already_registered = True

            # 다이얼로그 후 폼 미로드 시 조회하기 재시도
            combos_check = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
            vis_check = [c for c in combos_check if c.is_displayed()]
            if len(vis_check) < 2:
                try:
                    search_btn2 = self.driver.find_element(
                        By.XPATH, "//button[contains(.,'조회하기')]"
                    )
                    search_btn2.click()
                    print("[OK] 조회하기 재클릭")
                    time.sleep(4)
                    if self._handle_confirm_dialogs():
                        self._last_lookup_already_registered = True
                except Exception:
                    pass

            # STEP 02 폼 로드 대기 (combobox 2개 이상 = 폼 로드됨)
            for _ in range(15):
                time.sleep(1)
                combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
                vis = [c for c in combos if c.is_displayed()]
                if len(vis) >= 2:
                    print(f"[OK] 폼 로드 확인 (combobox {len(vis)}개)")
                    break
            else:
                print("[경고] 폼 로드 대기 시간 초과 (combobox < 2)")
                return False

            return True

        except Exception as e:
            print(f"[오류] VIN 입력 실패: {e}")
            return False

    def input_car_number_and_search(self, car_number: str) -> bool:
        """차량번호(G열)로 차량 조회 — 48H AUTO 방식"""
        try:
            print(f"\n[차량번호 조회] '{car_number}'")

            # 차량번호 탭 클릭 (trigger-0 우선, 없으면 첫 번째 탭)
            tab_clicked = False
            try:
                for tab in self.driver.find_elements(
                    By.XPATH, "//button[contains(@id,'trigger-0')]"
                ):
                    if tab.is_displayed():
                        tab.click()
                        tab_clicked = True
                        print("[OK] 차량번호 탭 클릭 (trigger-0)")
                        time.sleep(0.5)
                        break
            except Exception:
                pass

            if not tab_clicked:
                tabs = self.driver.find_elements(By.XPATH, "//button[@role='tab']")
                if tabs:
                    tabs[0].click()
                    print(f"[OK] 차량번호 탭 클릭 (첫 번째 탭: '{tabs[0].text}')")
                    time.sleep(0.5)

            # 차량번호 입력 필드 찾기
            car_input = None
            for xp in [
                "//input[@id='license-plate']",
                "//input[@placeholder='차량번호 / 등록 제품 번호']",
                "//input[@type='text' and not(@disabled)]",
            ]:
                try:
                    el = self.driver.find_element(By.XPATH, xp)
                    if el.is_displayed():
                        car_input = el
                        break
                except Exception:
                    pass

            if not car_input:
                print("[경고] 차량번호 입력 필드를 찾을 수 없습니다")
                return False

            car_input.clear()
            car_input.send_keys(car_number)
            print(f"[OK] 차량번호 '{car_number}' 입력 완료")
            time.sleep(0.5)

            # 조회하기 버튼 클릭
            try:
                btn = self.driver.find_element(
                    By.XPATH, "//button[contains(.,'조회하기')]"
                )
                btn.click()
                print("[OK] 조회하기 버튼 클릭")
                time.sleep(4)
            except Exception as e:
                print(f"[경고] 조회하기 버튼 실패: {e}")

            # 확인/선택 다이얼로그 처리 — 이미 등록 여부 캡처
            if self._handle_confirm_dialogs():
                self._last_lookup_already_registered = True

            # STEP 02 폼 로드 대기 (combobox 2개 이상 = 폼 로드됨)
            for _ in range(15):
                time.sleep(1)
                combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
                vis = [c for c in combos if c.is_displayed()]
                if len(vis) >= 2:
                    print(f"[OK] 폼 로드 확인 (combobox {len(vis)}개)")
                    return True

            print("[경고] 폼 로드 대기 시간 초과 (combobox < 2)")
            return True  # 폼이 로드 안 돼도 계속 진행

        except Exception as e:
            print(f"[오류] 차량번호 조회 실패: {e}")
            return False

    def _fallback_input_as_car_number(self, value: str) -> bool:
        """차량번호 탭으로 폴백 - 값 입력 및 조회"""
        return self.input_car_number_and_search(value)

    def _is_search_form_loaded(self) -> bool:
        """차량 조회 후 STEP02 폼이 실제 로드됐는지 확인 (combobox 2개 이상)"""
        try:
            combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
            return sum(1 for c in combos if c.is_displayed()) >= 2
        except Exception:
            return False

    def _handle_confirm_dialogs(self, ss_prefix: str = "") -> bool:
        """조회 후 다이얼로그 처리. 이미 등록된 차량 감지 시 True 반환.
        role=dialog 내 버튼만 클릭하며, 오버레이가 없으면 즉시 종료."""
        already_registered = False
        for i in range(6):
            time.sleep(1.5)
            try:
                # role=dialog 오버레이 확인
                dialogs = self.driver.find_elements(By.XPATH, "//*[@role='dialog']")
                visible_dialogs = [d for d in dialogs if d.is_displayed()]
                if not visible_dialogs:
                    print(f"  [다이얼로그] {i} dialog 없음 - 종료")
                    break

                dialog_btns = self.driver.find_elements(
                    By.XPATH, "//*[@role='dialog']//button"
                )
                visible_d = [b for b in dialog_btns if b.is_displayed()]
                if not visible_d:
                    print(f"  [다이얼로그] {i} dialog 있으나 버튼 없음 - ESC 시도")
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                    break

                # "이미 등록된 차량" 텍스트 감지 → 플래그 설정
                dialog_texts = self.driver.find_elements(
                    By.XPATH, "//*[@role='dialog']//*[self::p or self::span or self::div]"
                )
                for dt in dialog_texts:
                    if "이미 등록" in (dt.text or ""):
                        already_registered = True
                        print("  [다이얼로그] 이미 등록된 차량 감지")
                        break

                # 확인/취소 버튼 중 '확인' 우선, 없으면 마지막 버튼
                confirm_btn = None
                for b in visible_d:
                    if b.text.strip() in ("확인", "OK", "선택"):
                        confirm_btn = b
                        break
                if not confirm_btn:
                    confirm_btn = visible_d[-1]

                texts = [b.text.strip()[:20] for b in visible_d]
                print(f"  [다이얼로그] {i} dialog 버튼: {texts} → '{confirm_btn.text.strip()}' 클릭")
                if ss_prefix:
                    try:
                        self.driver.save_screenshot(ss_prefix + f"_dialog{i}.png")
                    except Exception:
                        pass
                confirm_btn.click()
                time.sleep(1.5)

            except Exception as e:
                print(f"  [다이얼로그] {i} 예외: {e}")
                break
        return already_registered

    # ─────────────────────────────────────────────
    # 차량 상세 폼 입력
    # ─────────────────────────────────────────────
    def _find_combo_by_label(self, label_texts: list[str]) -> object:
        """라벨 텍스트로 근처 combobox 버튼 찾기"""
        for lbl in label_texts:
            # XPath 방식
            for xp in [
                f"//label[contains(normalize-space(.),'{lbl}')]"
                f"/following::button[@role='combobox'][1]",
                f"//label[contains(normalize-space(.),'{lbl}')]"
                f"/..//button[@role='combobox']",
                f"//*[contains(normalize-space(text()),'{lbl}')]"
                f"/following::button[@role='combobox'][1]",
            ]:
                try:
                    el = self.driver.find_element(By.XPATH, xp)
                    if el.is_displayed():
                        return el
                except Exception:
                    pass

            # JS: combobox를 포함하는 가장 작은 단일 컨테이너에서 라벨 텍스트 검색
            try:
                el = self.driver.execute_script("""
                    var lbl = arguments[0];
                    var combos = Array.from(document.querySelectorAll('button[role="combobox"]'));
                    for (var combo of combos) {
                        if (combo.offsetParent === null) continue;
                        var el = combo;
                        for (var d = 0; d < 6; d++) {
                            if (!el) break;
                            // 이 컨테이너에 combobox가 정확히 1개이면 단일 필드 컨테이너
                            var comboCount = el.querySelectorAll('button[role="combobox"]').length;
                            if (comboCount === 1 && el.textContent.includes(lbl)) {
                                return combo;
                            }
                            el = el.parentElement;
                        }
                    }
                    return null;
                """, lbl)
                if el:
                    try:
                        if el.is_displayed():
                            return el
                    except Exception:
                        pass
            except Exception:
                pass
        return None

    def _find_input_by_label(self, label_texts: list[str]) -> object:
        """라벨 텍스트로 근처 input 찾기"""
        for lbl in label_texts:
            for xp in [
                f"//label[contains(normalize-space(.),'{lbl}')]"
                f"/following::input[not(@type='hidden')][1]",
                f"//*[contains(normalize-space(text()),'{lbl}')]"
                f"/following::input[not(@type='hidden')][1]",
            ]:
                try:
                    el = self.driver.find_element(By.XPATH, xp)
                    if el.is_displayed():
                        return el
                except Exception:
                    pass
        return None

    def _fill_date_picker(self, year_val: str) -> bool:
        """최초 등록일 날짜 picker에서 {year}-01-01 선택"""
        try:
            target_year = int(year_val)
        except (ValueError, TypeError):
            print(f"[경고] 최초 등록일 연도 변환 실패: {year_val}")
            return False

        try:
            # 날짜 picker 버튼 찾기
            date_btns = self.driver.find_elements(
                By.XPATH,
                "//button[contains(normalize-space(.),'날짜를 선택')]"
                " | //label[contains(normalize-space(.),'최초 등록일') or contains(normalize-space(.),'등록일')]"
                "/following::button[not(@role='combobox') and not(@role='tab')][1]"
            )
            date_btn = next((b for b in date_btns if b.is_displayed()), None)
            if not date_btn:
                # 더 넓은 범위로 재시도
                date_btns2 = self.driver.find_elements(
                    By.XPATH,
                    "//button[contains(@class,'date') or contains(@aria-label,'date') or "
                    "contains(normalize-space(.),'날짜') or contains(normalize-space(.),'등록일')]"
                )
                date_btn = next((b for b in date_btns2 if b.is_displayed()), None)
            if not date_btn:
                print("[경고] 최초 등록일 picker 버튼 찾기 실패")
                return False

            print(f"  [디버그] 날짜picker 버튼 text='{date_btn.text[:30]}' 클릭")
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", date_btn)
            self.driver.execute_script("arguments[0].click();", date_btn)
            time.sleep(0.8)

            # hidden input[type=date]에 직접 값 설정 시도
            set_ok = self.driver.execute_script("""
                var inputs = document.querySelectorAll('input[type="date"]');
                var val = arguments[0];
                for (var inp of inputs) {
                    try {
                        var setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, val);
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                        return true;
                    } catch(e) {}
                }
                return false;
            """, f"{target_year}-01-01")
            if set_ok:
                print(f"[OK] 최초 등록일 JS 직접 설정: {target_year}-01-01")
                time.sleep(0.3)
                # 캘린더가 닫히지 않으면 ESC
                try:
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                except Exception:
                    pass
                return True

            # 전략 A: native <select> 요소로 연도/월 설정 (react-day-picker dropdown 모드)
            time.sleep(0.5)
            selected = False
            try:
                from selenium.webdriver.support.ui import Select as _Select
                year_sel = None
                month_sel = None
                for sel in self.driver.find_elements(By.XPATH, "//select"):
                    if not sel.is_displayed():
                        continue
                    opts = [o.text.strip() for o in sel.find_elements(By.TAG_NAME, "option")]
                    if str(target_year) in opts:
                        year_sel = sel
                    if any(m in opts for m in ["January", "1월", "Jan", "1"]):
                        month_sel = sel
                if year_sel:
                    _Select(year_sel).select_by_visible_text(str(target_year))
                    selected = True
                    print(f"[OK] 등록일(년도) native select: {target_year}")
                    time.sleep(0.3)
                if month_sel:
                    for m_txt in ["January", "1월", "Jan"]:
                        try:
                            _Select(month_sel).select_by_visible_text(m_txt)
                            print(f"[OK] 등록일(월) native select: {m_txt}")
                            break
                        except Exception:
                            pass
                    time.sleep(0.3)
                if selected:
                    # 1일 클릭
                    for day_xp in [
                        "//button[@name='day' and normalize-space(text())='1']",
                        "//*[@role='gridcell']//button[normalize-space(text())='1']",
                        "//button[normalize-space(text())='1' and not(@disabled)]",
                    ]:
                        for cell in self.driver.find_elements(By.XPATH, day_xp):
                            if cell.is_displayed():
                                self.driver.execute_script("arguments[0].click();", cell)
                                print(f"[OK] 최초 등록일 선택: {target_year}-01-01")
                                return True
            except Exception as _e:
                print(f"  [디버그] native select 방식 실패: {_e}")

            # 전략 B: 연도 드롭다운 버튼 (text='2026' 형태) 클릭 후 목표 연도 선택

            def find_year_btn():
                # 캘린더 연도 버튼: target_year 와 다른 연도를 표시하는 combobox
                # (cascade 연식 버튼은 target_year='2014'를 표시, 캘린더는 현재 표시 연도)
                return self.driver.execute_script("""
                    var targetYear = arguments[0];
                    var btns = Array.from(document.querySelectorAll('button'));
                    for (var b of btns) {
                        if (b.offsetParent === null) continue;
                        var t = (b.textContent||'').trim();
                        if (/^20\\d{2}$/.test(t) && t !== targetYear) return b;
                    }
                    // fallback: target_year 포함 모든 연도 버튼
                    for (var b of btns) {
                        if (b.offsetParent === null) continue;
                        var t = (b.textContent||'').trim();
                        if (/^20\\d{2}$/.test(t)) return b;
                    }
                    return null;
                """, str(target_year))

            def find_month_btn():
                return self.driver.execute_script("""
                    var btns = Array.from(document.querySelectorAll('button'));
                    var months = ['January','February','March','April','May','June',
                                  'July','August','September','October','November','December',
                                  '1월','2월','3월','4월','5월','6월','7월','8월','9월',
                                  '10월','11월','12월'];
                    for (var b of btns) {
                        if (b.offsetParent === null) continue;
                        var t = (b.textContent||'').trim();
                        if (months.indexOf(t) >= 0) return b;
                    }
                    return null;
                """)

            # 1) 연도 dropdown 버튼 클릭 후 목표 연도 선택
            year_btn = find_year_btn()
            if year_btn:
                print(f"  [디버그] 연도버튼 text='{year_btn.text}' 클릭")
                self.driver.execute_script("arguments[0].click();", year_btn)
                time.sleep(0.4)
                selected = self._select_option_from_open_combobox(str(target_year), "등록일(년도)")
                if not selected:
                    # Fallback A: native <select> 요소
                    try:
                        from selenium.webdriver.support.ui import Select as _Select
                        for sel in self.driver.find_elements(By.XPATH, "//select"):
                            if sel.is_displayed():
                                try:
                                    _Select(sel).select_by_visible_text(str(target_year))
                                    selected = True
                                    print(f"[OK] 등록일(년도) native select: {target_year}")
                                    break
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if not selected:
                    # Fallback B: 화면에 보이는 target_year 텍스트 요소 직접 클릭
                    for item in self.driver.find_elements(
                            By.XPATH, f"//*[normalize-space(text())='{target_year}']"):
                        try:
                            if item.is_displayed():
                                self.driver.execute_script("arguments[0].click();", item)
                                selected = True
                                print(f"[OK] 등록일(년도) 직접클릭: {target_year}")
                                break
                        except Exception:
                            pass
            else:
                print("[경고] 캘린더 연도 버튼 찾기 실패 — 연도 선택 불가")

            # 2) 연도 선택 후 캘린더가 닫혔을 수 있으므로 재확인/재오픈
            if selected:
                time.sleep(0.4)
                # 월 버튼이 없으면 날짜 picker 재클릭
                if not find_month_btn():
                    date_btns2 = self.driver.find_elements(
                        By.XPATH,
                        "//button[contains(normalize-space(.),'날짜를 선택')]"
                        " | //label[contains(normalize-space(.),'최초 등록일') or "
                        "contains(normalize-space(.),'등록일')]"
                        "/following::button[not(@role='combobox') and not(@role='tab')][1]"
                    )
                    for db in date_btns2:
                        if db.is_displayed():
                            self.driver.execute_script("arguments[0].click();", db)
                            time.sleep(0.8)
                            # 재오픈 후 다시 연도 선택
                            yb = find_year_btn()
                            if yb:
                                self.driver.execute_script("arguments[0].click();", yb)
                                time.sleep(0.4)
                                self._select_option_from_open_combobox(
                                    str(target_year), "등록일(년도) 재선택")
                                time.sleep(0.4)
                            break

                month_btn = find_month_btn()
                if month_btn:
                    self.driver.execute_script("arguments[0].click();", month_btn)
                    time.sleep(0.4)
                    for m_opt in ["January", "1월", "Jan"]:
                        if self._select_option_from_open_combobox(m_opt, "등록일(월)"):
                            break
                    time.sleep(0.3)

            # 3) 1일 클릭
            if selected:
                for day_xp in [
                    "//button[@name='day' and normalize-space(text())='1']",
                    "//*[@role='gridcell']//button[normalize-space(text())='1']",
                    "//button[contains(@class,'rdp-button') and normalize-space(text())='1']",
                    "//button[normalize-space(text())='1' and not(@disabled)]",
                ]:
                    day_els = self.driver.find_elements(By.XPATH, day_xp)
                    for cell in day_els:
                        if cell.is_displayed():
                            self.driver.execute_script("arguments[0].click();", cell)
                            print(f"[OK] 최초 등록일 선택: {target_year}-01-01")
                            return True

            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            print(f"[경고] 최초 등록일 선택 실패 (target={target_year})")
            return False

        except Exception as e:
            print(f"[경고] 최초 등록일 처리 실패: {e}")
            try:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            return False

    def _find_combo_by_probing(self, expected_options: list[str]) -> object:
        """미선택 combobox를 순서대로 열어 특정 옵션이 있으면 반환 (닫고 반환)"""
        combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
        unfilled = [c for c in combos
                    if c.is_displayed() and c.text.strip() in ("선택하세요", "")]
        for combo in unfilled:
            try:
                self.driver.execute_script("arguments[0].click();", combo)
                time.sleep(0.4)
                opts = self.driver.find_elements(By.XPATH, "//div[@role='option']")
                opt_texts = [o.text.strip() for o in opts if o.is_displayed()]
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.2)
                if any(e in opt_texts for e in expected_options):
                    print(f"   [프로브] combo 발견 (옵션: {opt_texts[:5]})")
                    return combo
            except Exception:
                try:
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                except Exception:
                    pass
        return None

    def _select_first_active_option(self, combo_el, field_name: str) -> bool:
        """combobox를 열고 첫 번째 실제 옵션 선택 ('선택 안함' 등 null 값 제외)"""
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", combo_el)
            time.sleep(0.2)
            if not self._open_combobox(combo_el, field_name):
                return False
            time.sleep(0.3)
            opts = self.driver.find_elements(By.XPATH, "//div[@role='option']")
            NULL_OPTS = ("", "선택하세요", "선택 안함", "N/A", "해당없음")
            # 우선: null-값 제외한 실제 옵션
            real = [o for o in opts if o.is_displayed() and o.text.strip()
                    and o.text.strip() not in NULL_OPTS]
            active = real if real else [o for o in opts if o.is_displayed()
                                        and o.text.strip() and o.text.strip() != "선택하세요"]
            if active:
                txt = active[0].text.strip()
                try:
                    ActionChains(self.driver).move_to_element(active[0]).click().perform()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", active[0])
                print(f"[OK] {field_name} '{txt}' 선택 (첫 번째 활성 옵션)")
                return True
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            return False
        except Exception as e:
            print(f"[경고] {field_name} 첫 옵션 선택 실패: {e}")
            return False

    def fill_car_cascade(self, year: str, vin: str,
                         model_name: str = "", sub_model_name: str = "") -> None:
        """연식 → 브랜드 → 모델 → 세부모델 → 등급 cascade 채우기.
        VIN 조회로 자동 채워진 필드는 그대로 두고, 비어 있으면 시트값으로 채움.
        모델/세부모델은 시트에서, 등급/세부등급은 VIN 자동채움 필수 (시트 미지원)."""
        # cascade 비활성화 placeholder (활성화된 '선택하세요' 제외)
        CASCADE_DISABLED = (
            "브랜드를 먼저 선택하세요", "모델을 먼저 선택하세요",
            "세부모델을 먼저 선택하세요", "등급을 먼저 선택하세요.",
        )
        EMPTY_PLACEHOLDERS = CASCADE_DISABLED + ("선택하세요", "선택 하세요", "")

        def _is_filled(combo) -> tuple[bool, str]:
            """combo가 실제 값으로 채워졌는지. (filled, current_text) 반환."""
            try:
                t = (combo.text or "").strip()
            except Exception:
                return False, ""
            if t and t not in EMPTY_PLACEHOLDERS:
                return True, t
            return False, t

        def _fill_cascade_field(labels: list[str], field_name: str,
                                value: str, value_source: str) -> None:
            """labels로 콤보를 찾아 활성화 대기 후 value로 선택.
            이미 채워져 있으면 통과. 빈 상태에서 value도 없으면 ValueError."""
            # 활성화 대기 (최대 6초)
            combo = None
            for _ in range(12):
                c = self._find_combo_by_label(labels)
                if c:
                    filled, cur = _is_filled(c)
                    if filled:
                        print(f"[OK] {field_name} 자동 채워짐: '{cur}'")
                        return
                    if cur not in CASCADE_DISABLED:
                        combo = c
                        break
                time.sleep(0.5)
            if not combo:
                raise ValueError(f"{field_name} 콤보 활성화 안 됨 — cascade 진행 불가")
            if not value:
                raise ValueError(
                    f"{field_name} 미선택 — VIN 자동채움 안 됨, {value_source} 필요")
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", combo)
            time.sleep(0.2)
            if not self._open_combobox(combo, field_name):
                raise ValueError(f"{field_name} 콤보 열기 실패")
            if not self._select_option_from_open_combobox(value, field_name):
                raise ValueError(
                    f"{field_name} 매칭 실패 — {value_source}='{value}'가 옵션에 없음")

        def wait_and_select(field_labels, field_name, value=None) -> bool:
            """라벨로 combo를 찾고 활성화될 때까지 대기 후 선택"""
            for _ in range(10):  # 최대 5초 대기
                combo = self._find_combo_by_label(field_labels)
                if not combo:
                    break
                try:
                    text = combo.text.strip()
                except Exception:
                    time.sleep(0.3)
                    continue
                if text not in CASCADE_DISABLED:
                    # 활성화됨 → 선택
                    if not value:
                        return True  # VIN 조회로 이미 채워진 값 유지
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", combo)
                    time.sleep(0.2)
                    if self._open_combobox(combo, field_name):
                        if self._select_option_from_open_combobox(value, field_name):
                            return True
                        print(f"[경고] {field_name} '{value}' 선택 실패 — 건너뜀")
                        # 열린 드롭다운 닫기
                        try:
                            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        except Exception:
                            pass
                    return False
                time.sleep(0.5)
            print(f"[경고] {field_name} cascade 활성화 대기 초과 또는 찾기 실패")
            return False

        # 연식
        if not wait_and_select(["연식", "년식"], "연식", year):
            # 라벨 실패 시 position-based fallback
            try:
                all_c = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
                vis = [c for c in all_c if c.is_displayed() and c.text.strip() == "선택하세요"]
                if vis:
                    if self._open_combobox(vis[0], "연식(fallback)"):
                        self._select_option_from_open_combobox(year, "연식(fallback)")
            except Exception:
                pass

        time.sleep(0.3)

        # 브랜드: VIN 조회로 자동 채워진 경우 skip, 비었으면 후보로 선택
        brand_candidates = []
        vin_prefix = vin[:3].upper() if vin else ""
        if vin_prefix in self.VIN_BRAND_MAP:
            brand_candidates = self.VIN_BRAND_MAP[vin_prefix]
        brand_combo = self._find_combo_by_label(["브랜드", "제조사", "메이커"])
        if not brand_combo:
            raise ValueError("브랜드 combobox 찾기 실패")
        filled, cur_brand = _is_filled(brand_combo)
        if filled:
            print(f"[OK] 브랜드 자동 채워짐: '{cur_brand}'")
        else:
            if not brand_candidates:
                raise ValueError(
                    f"브랜드 미선택 — VIN prefix '{vin_prefix}' 매핑 없음")
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", brand_combo)
            time.sleep(0.2)
            if not self._open_combobox(brand_combo, "브랜드"):
                raise ValueError("브랜드 combobox 열기 실패")
            selected = False
            for brand in brand_candidates:
                if self._select_option_from_open_combobox(brand, "브랜드"):
                    selected = True
                    break
            if not selected:
                raise ValueError(
                    f"브랜드 매칭 실패 — VIN 후보 {brand_candidates}가 옵션에 없음")
        time.sleep(1.0)  # 브랜드 선택 후 모델 리스트 로딩 대기

        # 모델 (D열) — VIN 자동채움 없으면 시트값으로 채움
        _fill_cascade_field(["모델", "Model"], "모델", model_name, "D열 모델명")
        time.sleep(0.6)

        # 세부모델 / 등급 / 세부등급: 입력하지 않음 (모두 옵셔널)
        _ = sub_model_name  # signature 유지

    def fill_car_details(self, detail: dict, color: str) -> None:
        """차량 상세 정보 입력 — 라벨 텍스트 기반 (절대 XPath 불사용)"""

        # 혹시 열린 날짜 picker / 오버레이 닫기
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.3)
        except Exception:
            pass

        # 연식/브랜드/모델/세부모델/등급 cascade 채우기
        year_val = detail.get("_year", "")
        vin_val = detail.get("_vin", "")
        model_name = (detail.get("_model", "") or "").strip()
        sub_model_name = (detail.get("sub_model", "") or "").strip()
        self.fill_car_cascade(year_val, vin_val, model_name, sub_model_name)
        time.sleep(0.5)

        # 배기량: VIN 입력 시 자동 채워지므로 건드리지 않음

        # 구동방식 — 매핑 실패 시 "2WD" 폴백 (검증된 동작)
        drive_raw = detail.get("drive_type", "")
        drive_val = _normalize_raw(drive_raw)
        drive_mapped = self.DRIVE_MAPPING.get(drive_val, "2WD")
        drive_combo = self._find_combo_by_label(["구동방식", "구동", "Drive"])
        if drive_combo:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", drive_combo)
                time.sleep(0.2)
                if self._open_combobox(drive_combo, "구동방식"):
                    self._select_option_from_open_combobox(drive_mapped, "구동방식")
            except Exception as e:
                print(f"[경고] 구동방식 선택 실패: {e}")
        else:
            print("[경고] 구동방식 combobox 찾기 실패")

        # 변속기 — 매핑 실패 시 에러
        trans_raw = detail.get("transmission", "")
        trans_val = _normalize_raw(trans_raw)
        trans_mapped = self.TRANSMISSION_MAPPING.get(trans_val, "")
        if not trans_mapped:
            raise ValueError(f"변속기 정보 부족/매핑실패 (raw={trans_raw!r}, norm={trans_val!r})")
        trans_combo = self._find_combo_by_label(["변속기", "Transmission"])
        if not trans_combo:
            raise ValueError("변속기 combobox 찾기 실패")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", trans_combo)
        time.sleep(0.2)
        if not self._open_combobox(trans_combo, "변속기"):
            raise ValueError("변속기 combobox 열기 실패")
        if not self._select_option_from_open_combobox(trans_mapped, "변속기"):
            raise ValueError(f"변속기 옵션 선택 실패 (mapped='{trans_mapped}')")

        # 연료
        fuel_raw = detail.get("fuel", "")
        fuel_val = _normalize_raw(fuel_raw)
        fuel_mapped = self.FUEL_MAPPING.get(fuel_val, fuel_val)
        fuel_combo = self._find_combo_by_label(["연료", "유종", "연료종류", "연료 종류", "Fuel"])
        if not fuel_combo:
            # 라벨 검색 실패 시 옵션 내용으로 식별
            fuel_combo = self._find_combo_by_probing(
                ["가솔린", "디젤", "LPG", "하이브리드", "전기", "수소"]
            )
        # 연료 — 매핑 실패 시 에러
        if not fuel_mapped:
            raise ValueError(f"연료 정보 부족/매핑실패 (raw={fuel_raw!r}, norm={fuel_val!r})")
        if not fuel_combo:
            raise ValueError("연료 combobox 찾기 실패")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", fuel_combo)
        time.sleep(0.2)
        if not self._open_combobox(fuel_combo, "연료"):
            raise ValueError("연료 combobox 열기 실패")
        if not self._select_option_from_open_combobox(fuel_mapped, "연료"):
            raise ValueError(f"연료 옵션 선택 실패 (mapped='{fuel_mapped}')")

        # 색상 (외장) — 매핑 실패 시 에러
        color_raw = color or ""
        color_norm = _normalize_raw(color_raw)
        color_mapped = self.COLOR_MAPPING.get(color_norm, "")
        if not color_mapped:
            for k, v in self.COLOR_MAPPING.items():
                if k in color_norm or color_norm in k:
                    color_mapped = v
                    break
        if not color_mapped:
            raise ValueError(f"색상 매핑실패 (raw={color_raw!r}, norm={color_norm!r})")
        color_combo = self._find_combo_by_label(["색상", "외장색상", "외장", "Color"])
        if not color_combo:
            raise ValueError("색상 combobox 찾기 실패")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", color_combo)
        time.sleep(0.2)
        if not self._open_combobox(color_combo, "색상"):
            raise ValueError("색상 combobox 열기 실패")
        if not self._select_option_from_open_combobox(color_mapped, "색상"):
            raise ValueError(f"색상 옵션 선택 실패 (mapped='{color_mapped}')")

        # 승차인원 — 시트에 숫자 없으면 에러
        seat_val = detail.get("seating", "").strip()
        seat_num = "".join(filter(str.isdigit, seat_val))
        if not seat_num:
            raise ValueError(f"승차인원 정보 부족 (raw='{seat_val}')")
        seat_combo = self._find_combo_by_label(["승차인원", "승차", "인승", "탑승"])
        if not seat_combo:
            raise ValueError("승차인원 combobox 찾기 실패")
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", seat_combo)
        time.sleep(0.2)
        if not self._open_combobox(seat_combo, "승차인원"):
            raise ValueError("승차인원 combobox 열기 실패")
        if not self._select_option_from_open_combobox(seat_num, "승차인원"):
            raise ValueError(f"승차인원 옵션 선택 실패 (val='{seat_num}')")

        # 차대번호 입력 필드
        vin_input = self._find_input_by_label(["차대번호", "VIN"])
        if not vin_input:
            # placeholder로도 시도
            try:
                vin_input = self.driver.find_element(
                    By.XPATH, "//input[contains(@placeholder,'차대번호')]"
                )
            except Exception:
                pass
        if vin_input:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", vin_input)
                vin_input.clear()
                vin_input.send_keys(detail.get("_vin", ""))
                print(f"[OK] 차대번호 '{detail.get('_vin','')}' 입력 완료")
                time.sleep(0.3)
            except Exception as e:
                print(f"[경고] 차대번호 입력 실패: {e}")
        else:
            print("[경고] 차대번호 입력 필드 찾기 실패")

        # 주행거리 — 한국 단위 처리 (7만km → 70000)
        mileage_val = detail.get("mileage", "").strip()
        mileage_clean = mileage_val.replace(",", "").replace(" ", "")
        man_match = re.search(r"(\d+(?:\.\d+)?)만", mileage_clean)
        if man_match:
            mileage_num = str(int(float(man_match.group(1)) * 10000))
        else:
            mileage_num = "".join(filter(str.isdigit, mileage_clean))
        if mileage_num:
            mileage_input = self._find_input_by_label(["주행거리", "마일리지"])
            if not mileage_input:
                try:
                    mileage_input = self.driver.find_element(
                        By.XPATH, "//input[contains(@placeholder,'주행거리') or contains(@placeholder,'km')]"
                    )
                except Exception:
                    pass
            if mileage_input:
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", mileage_input)
                    mileage_input.clear()
                    mileage_input.send_keys(mileage_num)
                    print(f"[OK] 주행거리 '{mileage_num}' 입력 완료")
                    time.sleep(0.3)
                except Exception as e:
                    print(f"[경고] 주행거리 입력 실패: {e}")
            else:
                print("[경고] 주행거리 입력 필드 찾기 실패")

        # 차량 위치 / 국가 선택 (대한민국)
        country_combo = self._find_combo_by_label(["차량 위치", "차량위치", "국가 선택", "국가", "원산지"])
        if country_combo:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", country_combo)
                time.sleep(0.3)
                if self._open_combobox(country_combo, "차량위치"):
                    self._select_option_from_open_combobox("대한민국", "차량위치")
                print("[OK] 차량 위치 '대한민국' 선택")
            except Exception as e:
                print(f"[경고] 차량 위치 입력 실패: {e}")
        else:
            print("[경고] 차량 위치 combobox 찾기 실패")

        # 차량 상태 (신차/중고차) — 있으면 중고차 선택
        condition_combo = self._find_combo_by_label(["차량 상태", "차량상태", "상태", "Condition"])
        if condition_combo:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", condition_combo)
                time.sleep(0.2)
                if self._open_combobox(condition_combo, "차량상태"):
                    if not self._select_option_from_open_combobox("중고", "차량상태"):
                        self._select_option_from_open_combobox("Used", "차량상태")
            except Exception as e:
                print(f"[경고] 차량상태 선택 실패: {e}")

        # 최초 등록일 (날짜 picker)
        year_val = detail.get("_year", "")
        if year_val:
            self._fill_date_picker(year_val)

        # 남은 빈 combobox 디버그 출력 (선택하세요 상태인 것)
        try:
            all_vis_combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
            empty_combos = [(i, c.text.strip()) for i, c in enumerate(all_vis_combos)
                            if c.is_displayed() and c.text.strip() in ("선택하세요", "", "날짜를 선택해주세요")]
            if empty_combos:
                print(f"  [디버그] fill 후 빈 combobox {len(empty_combos)}개: {empty_combos}")
        except Exception:
            pass

        # 주행거리 동의 체크박스 — shadcn/ui button[role=checkbox] 우선
        try:
            agree_el = self.driver.execute_script("""
                // shadcn/ui: button[role='checkbox'] 또는 input[type='checkbox']
                var candidates = Array.from(document.querySelectorAll(
                    'button[role="checkbox"], input[type="checkbox"]'));
                for (var c of candidates) {
                    if (c.offsetParent === null) continue;
                    // 부모 트리에서 '동의' 텍스트 찾기
                    var el = c;
                    for (var d = 0; d < 5; d++) {
                        if (el && el.textContent && el.textContent.includes('동의')) return c;
                        el = el ? el.parentElement : null;
                    }
                    // 다음 형제 확인
                    var sib = c.nextElementSibling;
                    if (sib && sib.textContent && sib.textContent.includes('동의')) return c;
                }
                // label[for] 방식
                var labels = document.querySelectorAll('label');
                for (var l of labels) {
                    if (l.textContent.includes('동의')) {
                        if (l.htmlFor) {
                            var el2 = document.getElementById(l.htmlFor);
                            if (el2) return el2;
                        }
                        return l.querySelector('button[role="checkbox"], input[type="checkbox"]') || l;
                    }
                }
                return null;
            """)
            if agree_el:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", agree_el)
                time.sleep(0.3)
                # 클릭 (ActionChains 우선)
                try:
                    ActionChains(self.driver).move_to_element(agree_el).click().perform()
                except Exception:
                    agree_el.click()
                time.sleep(0.3)
                # 체크 확인 (checked 속성 또는 data-state="checked" / aria-checked="true")
                is_checked = self.driver.execute_script("""
                    var el = arguments[0];
                    return el.checked ||
                           el.getAttribute('aria-checked') === 'true' ||
                           el.getAttribute('data-state') === 'checked';
                """, agree_el)
                if is_checked:
                    print("[OK] 주행거리 동의 체크박스 클릭 (체크됨)")
                else:
                    # 한 번 더
                    try:
                        agree_el.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", agree_el)
                    time.sleep(0.2)
                    print("[OK] 주행거리 동의 체크박스 재클릭")
            else:
                print("[경고] 주행거리 동의 체크박스 찾기 실패")
        except Exception as e:
            print(f"[경고] 주행거리 동의 체크박스 실패: {e}")

    # ─────────────────────────────────────────────
    # 차량 옵션 체크박스 선택
    # ─────────────────────────────────────────────
    def select_car_options(self, options: list[str]) -> None:
        """J~S열 옵션을 체크박스/버튼으로 선택"""
        if not options:
            return
        print(f"\n[옵션 선택] {options}")

        try:
            # 옵션 체크박스/라벨 찾기
            # 방법 1: label 텍스트와 매칭하여 input[type=checkbox] 클릭
            for opt_name in options:
                clicked = False

                # 라벨 텍스트로 체크박스 찾기
                try:
                    labels = self.driver.find_elements(
                        By.XPATH,
                        f"//label[contains(normalize-space(text()),'{opt_name}')]"
                        f" | //span[contains(normalize-space(text()),'{opt_name}')]"
                    )
                    for label in labels:
                        if label.is_displayed():
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block:'nearest'});", label
                            )
                            time.sleep(0.2)
                            try:
                                label.click()
                            except Exception:
                                self.driver.execute_script("arguments[0].click();", label)
                            print(f"[OK] 옵션 '{opt_name}' 선택 (라벨 클릭)")
                            clicked = True
                            break
                except Exception:
                    pass

                if not clicked:
                    # 버튼/div 형태 옵션 찾기
                    try:
                        opt_btns = self.driver.find_elements(
                            By.XPATH,
                            f"//*[contains(normalize-space(text()),'{opt_name}') "
                            f"and (self::button or self::div or self::li)]"
                        )
                        for btn in opt_btns:
                            if btn.is_displayed():
                                self.driver.execute_script(
                                    "arguments[0].scrollIntoView({block:'nearest'});", btn
                                )
                                time.sleep(0.2)
                                try:
                                    btn.click()
                                except Exception:
                                    self.driver.execute_script("arguments[0].click();", btn)
                                print(f"[OK] 옵션 '{opt_name}' 선택 (버튼)")
                                clicked = True
                                break
                    except Exception:
                        pass

                if not clicked:
                    print(f"[경고] 옵션 '{opt_name}' 선택 실패")

                time.sleep(0.2)

        except Exception as e:
            print(f"[경고] 옵션 선택 중 오류: {e}")

    # ─────────────────────────────────────────────
    # 가격 입력
    # ─────────────────────────────────────────────
    def input_price(self, price_raw: str) -> None:
        """AB열 광고가 입력 ($, 쉼표 제거 후 숫자만)"""
        if not price_raw or not price_raw.strip():
            return
        try:
            price_num = price_raw.replace("$", "").replace(",", "").replace(" ", "").strip()
            if not price_num:
                return

            print(f"\n[가격 입력] {price_raw} → {price_num}")

            price_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH,
                    '//*[@id="car-create-form"]/section[3]/section/div[1]/div/div[2]/input'))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", price_input)
            time.sleep(0.3)

            # React 폼: JS로 값 세팅 + change/input 이벤트 강제 발생
            self.driver.execute_script("""
                var input = arguments[0];
                var value = arguments[1];
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(input, value);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            """, price_input, price_num)
            time.sleep(0.3)

            # 기존 값이 남아있을 경우 send_keys로 덮어쓰기
            price_input.click()
            price_input.send_keys(Keys.CONTROL + "a")
            price_input.send_keys(price_num)

            print(f"[OK] 가격 '{price_num}' 입력 완료")

        except Exception as e:
            print(f"[경고] 가격 입력 실패: {e}")

    # ─────────────────────────────────────────────
    # 다음 버튼 처리
    # ─────────────────────────────────────────────
    def _find_next_button(self):
        """페이지의 '다음' 버튼 탐색"""
        # JS로 정확히 '다음' 텍스트인 버튼 찾기
        try:
            btn = self.driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i=0; i<buttons.length; i++) {
                    var b = buttons[i];
                    if (!b.offsetParent || b.disabled) continue;
                    var text = (b.textContent || '').trim();
                    if (text === '다음' || text === 'Next' || text === 'next') return b;
                }
                return null;
            """)
            if btn:
                return btn
        except Exception:
            pass

        # XPath 폴백
        for xp in [
            "//button[normalize-space(text())='다음']",
            "//button[contains(text(),'다음')]",
            "/html/body/main/div/div/div[3]/div[3]/button",
        ]:
            try:
                btns = self.driver.find_elements(By.XPATH, xp)
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        return b
            except Exception:
                pass
        return None

    def click_next_button(self, times: int = 1) -> bool:
        """다음 버튼을 n번 클릭"""
        for i in range(times):
            btn = self._find_next_button()
            if not btn:
                print(f"[경고] 다음 버튼을 찾을 수 없습니다 ({i+1}/{times})")
                return False
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", btn)
            print(f"[OK] 다음 버튼 클릭 ({i+1}/{times})")
            time.sleep(2)
        return True

    # ─────────────────────────────────────────────
    # 저장 및 게시정지
    # ─────────────────────────────────────────────
    def _find_save_button(self):
        """저장/접수 버튼 탐색 (없으면 None 반환)"""
        # 텍스트 기반 검색
        btns = self.driver.find_elements(
            By.XPATH,
            "//button[contains(.,'저장') or contains(.,'접수') or contains(.,'Save')]"
        )
        visible = [b for b in btns if b.is_displayed()]
        if visible:
            return visible[0]
        # 절대 XPath 폴백
        try:
            btn = self.driver.find_element(
                By.XPATH, "/html/body/main/div/div/div[3]/div[2]/button"
            )
            if btn.is_displayed():
                return btn
        except Exception:
            pass
        return None

    def _capture_form_errors(self) -> str:
        """폼 검증 에러 메시지 추출 (role=alert, error 클래스 등)"""
        try:
            xp = (
                "//*[@role='alert' or @aria-live='assertive' "
                "or contains(@class,'error') or contains(@class,'Error') "
                "or contains(@class,'invalid') or contains(@class,'helper-text')]"
            )
            elements = self.driver.find_elements(By.XPATH, xp)
            seen: list[str] = []
            for el in elements:
                try:
                    if not el.is_displayed():
                        continue
                    t = " ".join((el.text or "").split())
                    if 2 < len(t) < 120 and t not in seen:
                        seen.append(t)
                    if len(seen) >= 3:
                        break
                except Exception:
                    pass
            return " | ".join(seen)
        except Exception:
            return ""

    def submit_and_pause(self):
        """저장(접수) → 확인 팝업 처리 → 상세 URL 추출.
        반환: 성공 URL(str) | True(URL 없는 성공) | False(저장 실패).
              실패 사유는 self._submit_fail_reason에 저장."""
        import re as _re

        CONFIRM_KEYWORDS = ("확인", "OK", "네", "예", "등록", "저장", "완료", "Yes")
        DETAIL_PATH_RE = _re.compile(r"/car-detail/([^/?#\s]+)")
        BASE = "https://mangoworldcar.com/ko/car-detail/"

        def _extract_detail_url(url: str) -> str | None:
            if not url:
                return None
            m = DETAIL_PATH_RE.search(url)
            return f"{BASE}{m.group(1)}" if m else None

        self._submit_fail_reason: str | None = None

        try:
            # 저장 버튼이 없으면 이미지 섹션을 지나서 다음 화면으로 이동 시도
            save_btn = self._find_save_button()
            if not save_btn:
                print("[정보] 저장 버튼 없음 - 다음 버튼 클릭 후 재시도")
                self.click_next_button(1)
                time.sleep(2)
                save_btn = self._find_save_button()

            if not save_btn:
                print("[오류] 저장 버튼을 찾을 수 없습니다")
                self._submit_fail_reason = "저장버튼없음"
                return False

            # 1. 저장 버튼 클릭 — 추적용 상태 로그
            url_before_save = self.driver.current_url
            try:
                btn_text = (save_btn.text or "").strip()
                btn_html = save_btn.get_attribute("outerHTML") or ""
                print(f"[추적] 저장 버튼 텍스트='{btn_text}', HTML={btn_html[:200]}")
            except Exception:
                pass
            # 클릭 직전 폼 에러 미리 확인 (남아있는 검증 메시지)
            pre_err = self._capture_form_errors()
            if pre_err:
                print(f"[추적] 저장 직전 화면 에러 메시지: {pre_err}")

            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", save_btn)
            print("[OK] 저장 버튼 클릭")
            time.sleep(1)
            # 클릭 직후 폼 에러 확인
            post_err = self._capture_form_errors()
            if post_err:
                print(f"[추적] 저장 직후 화면 에러 메시지: {post_err}")

            # 2. 확인 팝업 처리 — 최대 10초간 dialog/modal/버튼 후보 폴링
            confirm_xpath = " | ".join(
                f"//button[contains(normalize-space(.),'{kw}')]"
                for kw in CONFIRM_KEYWORDS
            )
            confirm_clicked = False
            confirm_deadline = time.time() + 10
            while time.time() < confirm_deadline:
                try:
                    candidates = self.driver.find_elements(By.XPATH, confirm_xpath)
                    # dialog/modal 내부 버튼 우선
                    visible = [b for b in candidates if b.is_displayed() and b.is_enabled()]
                    if visible:
                        # 가능하면 modal 내부 버튼 우선 선택
                        modal_btns = [
                            b for b in visible
                            if b.find_elements(By.XPATH, "ancestor::*[@role='dialog' or contains(@class,'modal') or contains(@class,'Dialog')]")
                        ]
                        target = modal_btns[0] if modal_btns else visible[0]
                        label = (target.text or "").strip()
                        self.driver.execute_script("arguments[0].click();", target)
                        print(f"[OK] 저장 확인 버튼 클릭 ('{label}')")
                        confirm_clicked = True
                        time.sleep(2)
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            if not confirm_clicked:
                print("[정보] 확인 팝업 미감지 — 자동 진행")

            # 3. 저장 후 URL 변화 폴링 (최대 40초)
            poll_deadline = time.time() + 40
            last_url = self.driver.current_url
            while time.time() < poll_deadline:
                current_url = self.driver.current_url
                detail = _extract_detail_url(current_url)
                if detail:
                    print(f"[OK] 상세 URL 감지: {detail}")
                    return detail
                # 페이지 내 a[href*='car-detail'] 링크 탐색
                try:
                    links = self.driver.find_elements(By.XPATH, "//a[contains(@href,'car-detail')]")
                    for lnk in links:
                        href = lnk.get_attribute("href") or ""
                        detail = _extract_detail_url(href)
                        if detail:
                            print(f"[OK] 상세 URL (링크 탐색): {detail}")
                            return detail
                except Exception:
                    pass
                # URL이 저장 직전과 달라졌고 car-detail이 아니면 어드민/리스팅 페이지 가능
                if current_url != last_url:
                    last_url = current_url
                time.sleep(0.5)

            # 4. 최종 미발견 — 폼 검증 에러 유무로만 판정 (URL 미변경은 실패 신호 아님)
            err_msg = self._capture_form_errors()
            final_url = self.driver.current_url
            if err_msg:
                print(f"[실패] 폼 검증 에러 감지 — 저장 실패")
                print(f"   에러: {err_msg}")
                print(f"   저장 전 URL: {url_before_save}")
                print(f"   현재 URL:    {final_url}")
                self._submit_fail_reason = f"폼검증실패({err_msg})"
                return False

            # 폼 에러 없음 → 저장 성공으로 간주 (SPA 비동기 저장, URL 미변경 가능)
            print(f"[경고] 상세 URL 미감지 — 저장 성공으로 추정 (폼 에러 없음)")
            print(f"   저장 전 URL: {url_before_save}")
            print(f"   현재 URL:    {final_url}")
            return True

        except Exception as e:
            print(f"[오류] 저장 실패: {e}")
            import traceback
            traceback.print_exc()
            self._submit_fail_reason = f"예외({type(e).__name__})"
            return None

    # ─────────────────────────────────────────────
    # 메인 처리 루프
    # ─────────────────────────────────────────────
    def process_all(self, start_row: int = None, end_row: int = None) -> None:
        pending = self.get_pending_rows()

        # 행 범위 필터
        if start_row:
            pending = [p for p in pending if p["row_idx"] >= start_row]
        if end_row:
            pending = [p for p in pending if p["row_idx"] <= end_row]

        if not pending:
            print("[알림] 업로드할 행이 없습니다.")
            return

        print(f"\n[진행] 총 {len(pending)}개 행 업로드 예정")

        # 계정별로 그룹화
        account_groups: dict[str, list[dict]] = {}
        for item in pending:
            aa_val = item["row"][self.COL_ACCOUNT] if len(item["row"]) > self.COL_ACCOUNT else ""
            key = aa_val.strip()
            account_groups.setdefault(key, []).append(item)

        for account_key, items in account_groups.items():
            email, password = self.parse_account_info(account_key)
            if not email or not password:
                print(f"[건너뜀] 계정 정보 없음: {account_key[:30]}")
                continue

            print(f"\n{'='*70}")
            print(f"계정: {email} ({len(items)}개 행)")
            print(f"{'='*70}")

            # 드라이버 초기화 및 로그인
            self.close_driver()
            self.setup_driver()
            if not self.login(email, password):
                print(f"[오류] {email} 로그인 실패. 건너뜁니다.")
                for item in items:
                    self.mark_upload_failed(item["row_idx"], "로그인 실패")
                continue

            for item in items:
                row_idx = item["row_idx"]
                row = item["row"]

                print(f"\n{'─'*60}")
                print(f"[{row_idx}행] 처리 시작")

                current_step = "초기화"
                try:
                    # 데이터 추출
                    current_step = "데이터추출"
                    model      = row[self.COL_MODEL] if len(row) > self.COL_MODEL else ""
                    year       = row[self.COL_YEAR] if len(row) > self.COL_YEAR else ""
                    color      = row[self.COL_COLOR] if len(row) > self.COL_COLOR else ""
                    car_number = row[self.COL_CAR_NUMBER] if len(row) > self.COL_CAR_NUMBER else ""
                    vin        = row[self.COL_VIN] if len(row) > self.COL_VIN else ""
                    i_val      = row[self.COL_DETAIL] if len(row) > self.COL_DETAIL else ""
                    price_raw  = row[self.COL_PRICE] if len(row) > self.COL_PRICE else ""
                    options    = self.get_row_options(row)

                    print(f"  모델: {model} ({year}), 차량번호: {car_number}, VIN: {vin}")
                    print(f"  색상: {color}, 가격: {price_raw}")
                    print(f"  옵션: {options}")

                    # I열 파싱
                    current_step = "I열파싱"
                    detail = self.parse_i_column(i_val)
                    detail["_vin"] = vin
                    detail["_year"] = year
                    detail["_model"] = model  # D열 모델명 (cascade fill용)

                    # ── 이미지 미리 다운로드 (API) ──
                    # 사진 링크가 없거나 다운로드 결과가 0장이면 행 스킵
                    current_step = "이미지다운로드"
                    drive_link = self._get_drive_link_for_row(row_idx)
                    image_files: list[str] = []
                    if not drive_link:
                        reason = "Y열 사진 드라이브 링크 없음"
                        self.mark_upload_failed(row_idx, reason)
                        print(f"[실패] {row_idx}행: {reason}")
                        self.cleanup_row_images(row_idx)
                        continue

                    print(f"  드라이브: {drive_link[:60]}")
                    image_files = self.download_images_via_api(drive_link, row_idx)
                    if not image_files:
                        reason = "이미지 다운로드 0장(드라이브 비어있음/접근불가)"
                        self.mark_upload_failed(row_idx, reason)
                        print(f"[실패] {row_idx}행: {reason}")
                        self.cleanup_row_images(row_idx)
                        continue

                    # 1. 차량 등록 페이지 이동
                    current_step = "등록페이지진입"
                    self.driver.get(self.CREATE_URL)
                    time.sleep(3)

                    # 2. 차량번호 → 실패 시 VIN 폴백 (둘 다 실패하면 행 스킵)
                    _cn = car_number.strip()
                    _vin = vin.strip() if vin else ""
                    _cn_valid = bool(_cn) and _cn not in ("-", "N/A")
                    _vin_valid = bool(_vin) and _vin not in ("-", "N/A")

                    search_ok = False
                    already_registered = False
                    tried = []  # ["차량번호", "VIN"]

                    if _cn_valid:
                        current_step = "차량번호조회"
                        tried.append("차량번호")
                        self._last_lookup_already_registered = False
                        try:
                            ok = self.input_car_number_and_search(_cn)
                        except Exception as ex:
                            ok = False
                            print(f"[경고] 차량번호 조회 예외: {ex}")
                        if getattr(self, "_last_lookup_already_registered", False):
                            already_registered = True
                        elif ok and self._is_search_form_loaded():
                            search_ok = True
                        else:
                            print("[경고] 차량번호 조회 결과 폼 미로드")

                    if not search_ok and not already_registered and _vin_valid:
                        if _cn_valid:
                            print("[경고] 차량번호 조회 실패 — VIN으로 재시도")
                            try:
                                self.driver.get(self.CREATE_URL)
                                time.sleep(3)
                            except Exception:
                                pass
                        current_step = "VIN조회"
                        tried.append("VIN")
                        self._last_lookup_already_registered = False
                        try:
                            ok = self.input_vin_and_search(_vin)
                        except Exception as ex:
                            ok = False
                            print(f"[경고] VIN 조회 예외: {ex}")
                        if getattr(self, "_last_lookup_already_registered", False):
                            already_registered = True
                        elif ok and self._is_search_form_loaded():
                            search_ok = True
                        else:
                            print("[경고] VIN 조회 결과 폼 미로드")

                    # 분기: 이미 등록 / 조회 안됨 / 정상
                    if already_registered:
                        self.mark_row_status(row_idx, "이미등록된 차량")
                        print(f"[스킵] {row_idx}행: 이미등록된 차량")
                        self.cleanup_row_images(row_idx)
                        try:
                            self.driver.get(self.CREATE_URL)
                            time.sleep(2)
                        except Exception:
                            pass
                        continue

                    if not search_ok:
                        if not _cn_valid and not _vin_valid:
                            status = "차량번호/차대번호 없음"
                        elif tried == ["차량번호"]:
                            status = "차량번호 조회안됨"
                        elif tried == ["VIN"]:
                            status = "차대번호 조회안됨"
                        else:
                            status = "차량번호/차대번호 조회안됨"
                        self.mark_row_status(row_idx, status)
                        print(f"[스킵] {row_idx}행: {status}")
                        self.cleanup_row_images(row_idx)
                        try:
                            self.driver.get(self.CREATE_URL)
                            time.sleep(2)
                        except Exception:
                            pass
                        continue

                    # 3. 차량 상세 입력 (STEP 02 — 가격도 같은 페이지)
                    current_step = "상세입력"
                    self.fill_car_details(detail, color)
                    time.sleep(0.5)

                    # 4. 가격 입력 (STEP 02 — 다음 누르기 전)
                    current_step = "가격입력"
                    self.input_price(price_raw)
                    time.sleep(0.5)

                    # 5. STEP 02 완료 → STEP 03 (옵션 등록)
                    current_step = "STEP02→03"
                    self.click_next_button(1)
                    time.sleep(2)

                    # 6. STEP 03 옵션 선택 후 다음
                    current_step = "옵션선택"
                    self.select_car_options(options)
                    time.sleep(0.5)
                    current_step = "STEP03→04"
                    self.click_next_button(1)
                    time.sleep(2)

                    # 8. 이미지 업로드 (image_files는 위 검증에서 항상 1장 이상 보장)
                    current_step = "이미지업로드"
                    self.upload_images_to_form(image_files)
                    current_step = "이미지섹션통과"
                    self.click_next_button(1)

                    # 9. 저장 및 게시정지
                    current_step = "저장"
                    result = self.submit_and_pause()

                    # 10. 완료 표시 및 임시파일 정리
                    if result:
                        self.mark_upload_date(row_idx)
                        self.mark_status_selling(row_idx)
                        if isinstance(result, str):
                            self.mark_car_urls(row_idx, result)
                        print(f"[완료] {row_idx}행 업로드 성공")
                    else:
                        reason = getattr(self, "_submit_fail_reason", None) or (
                            "저장버튼없음" if result is False else "저장예외"
                        )
                        self.mark_upload_failed(row_idx, f"{current_step}({reason})")
                        print(f"[실패] {row_idx}행 업로드 실패: {reason}")

                    self.cleanup_row_images(row_idx)
                    time.sleep(2)

                except Exception as e:
                    err_tag = type(e).__name__.replace("Exception", "")
                    err_msg = str(e).splitlines()[0] if str(e) else ""
                    print(f"[오류] {row_idx}행 처리 중 예외: {e}")
                    import traceback
                    traceback.print_exc()
                    # ValueError 류는 메시지가 핵심, 그 외는 타입+메시지
                    if isinstance(e, ValueError) and err_msg:
                        reason = f"{current_step}: {err_msg}"
                    elif err_msg:
                        reason = f"{current_step}({err_tag}): {err_msg}"
                    else:
                        reason = f"{current_step}({err_tag})"
                    self.mark_upload_failed(row_idx, reason)
                    self.cleanup_row_images(row_idx)
                    try:
                        self.driver.get(self.CREATE_URL)
                        time.sleep(2)
                    except Exception:
                        pass

            # 계정 처리 완료 후 드라이버 종료
            self.close_driver()
            print(f"\n[완료] {email} 계정 처리 완료")
            time.sleep(2)

        print("\n" + "="*70)
        print("모든 계정 처리 완료")
        print("="*70)


def main():
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="망고패키지 매물 업로드 자동화")
    parser.add_argument("--row", type=int, help="단일 행만 처리 (start=end=N)")
    parser.add_argument("--start", type=int, help="시작 행")
    parser.add_argument("--end", type=int, help="끝 행")
    parser.add_argument("--force", action="store_true",
                        help="대상 행의 Z/AI/AL/AM을 비워 재처리")
    parser.add_argument("-y", "--yes", action="store_true", help="확인 프롬프트 생략")
    args, _ = parser.parse_known_args()

    print("\n" + "="*70)
    print("망고패키지 매물 업로드 자동화".center(70))
    print("="*70)

    uploader = MangoPackageUploader()
    if not uploader.setup_spreadsheet():
        print("[오류] 스프레드시트 연결 실패. 종료합니다.")
        return

    # 처리 범위 결정 — CLI 인자 우선, 없으면 대화식 입력
    if args.row is not None:
        start_row = end_row = args.row
    elif args.start is not None or args.end is not None:
        start_row = args.start
        end_row = args.end
    else:
        print("\n처리 범위 설정 (엔터 = 전체 자동 처리)")
        start_input = input("시작 행 번호 (비워두면 전체): ").strip()
        end_input = input("끝 행 번호 (비워두면 전체): ").strip()
        start_row = int(start_input) if start_input.isdigit() else None
        end_row = int(end_input) if end_input.isdigit() else None

    # --force: 대상 행의 마킹 초기화
    if args.force:
        if start_row is None or end_row is None:
            print("[오류] --force는 --row 또는 --start/--end와 함께 사용해야 합니다.")
            return
        print(f"\n[FORCE] {start_row}~{end_row}행 Z/AI/AL/AM 비우기")
        for r in range(start_row, end_row + 1):
            uploader.clear_row_marks(r)
        time.sleep(1)

    # 대기 중인 행 미리보기
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
        aa         = row[28] if len(row) > 28 else ""
        email      = aa.strip().splitlines()[0] if aa.strip() else ""
        print(f"  행 {p['row_idx']}: {model} | 차량번호:{car_number} | VIN:{vin} | {email}")

    if len(pending) > 10:
        print(f"  ... 외 {len(pending) - 10}개")

    if not args.yes:
        confirm = input("\n계속 진행하시겠습니까? (y/n): ").strip().lower()
        if confirm != "y":
            print("취소되었습니다.")
            return

    uploader.process_all(start_row=start_row, end_row=end_row)


if __name__ == "__main__":
    main()
