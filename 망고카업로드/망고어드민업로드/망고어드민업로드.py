"""
망고 어드민 매물 업로드 자동화
- 어드민: https://adminv2.mangoworldcar.com/cars/create
- 스프레드시트: 망고패키지 등록/입력 V 2.1 (GID: 1403349305)
- 조건: AA열(계정정보) 있고, AB열(업로드일자) 비어있는 행
- 고정 어드민 계정: admin@mangoworldcar.com / mango8802!
"""
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
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
import time
import zipfile
from datetime import datetime


class MangoAdminUploader:
    # ── 어드민 계정 ───────────────────────────────────────────
    ADMIN_EMAIL    = "admin@mangoworldcar.com"
    ADMIN_PASSWORD = "mango8802!"
    ADMIN_URL      = "https://adminv2.mangoworldcar.com"
    CREATE_URL     = "https://adminv2.mangoworldcar.com/cars/create"

    # ── 스프레드시트 ─────────────────────────────────────────
    SPREADSHEET_ID = "1yHN0UM8Rr_CmMjz5fI3CEdhQjHM7VQIaqitWPRIGR8E"
    SHEET_GID      = 1403349305
    SERVICE_ACCOUNT_FILE = os.path.join(
        os.path.dirname(__file__),
        "..", "망고카 오토", "adjustmentdata-51a7199ac3ba.json"
    )
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    # ── 열 인덱스 (0-based) ───────────────────────────────────
    COL_MODEL        = 3   # D  모델명
    COL_YEAR         = 4   # E  연식
    COL_COLOR        = 5   # F  색상
    COL_CAR_NUMBER   = 6   # G  차량번호
    COL_VIN          = 7   # H  차대번호
    COL_DETAIL       = 8   # I  옵션사항 (구동/변속/연료/배기량 구조화 텍스트)
    COL_OPT_START    = 9   # J  옵션1
    COL_OPT_END      = 18  # S  옵션10
    COL_MILEAGE      = 19  # T  주행거리
    COL_SEATING      = 20  # U  승차인승
    COL_PHOTO_LINK   = 24  # Y  사진 (구글 드라이브 링크)
    COL_PLATFORM_URL = 25  # Z  플랫폼 링크 (망고카 상세 URL) ← 업로드 조건
    COL_ADMIN_URL    = 26  # AA 어드민 링크 ← 업로드 완료 후 기록
    COL_PRICE        = 27  # AB 플랫폼 광고가 ($)
    COL_ACCOUNT      = 28  # AC 계정정보
    COL_UPLOAD_DATE  = 29  # AD 업로드일자

    DOWNLOAD_FOLDER = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "downloaded_images"
    )

    # ── 매핑 테이블 ───────────────────────────────────────────
    COLOR_MAPPING = {
        "흰색": "WHITE", "화이트": "WHITE", "백색": "WHITE",
        "검은색": "BLACK", "검정": "BLACK", "검정색": "BLACK", "블랙": "BLACK",
        "은색": "SILVER", "실버": "SILVER",
        "회색": "GRAY", "그레이": "GRAY", "쥐색": "GRAY",
        "파란색": "BLUE", "블루": "BLUE", "청색": "BLUE",
        "빨간색": "RED", "레드": "RED",
        "갈색": "BROWN", "브라운": "BROWN",
        "초록색": "GREEN", "그린": "GREEN", "녹색": "GREEN",
        "노란색": "YELLOW", "노랑": "YELLOW",
        "금색": "GOLD", "골드": "GOLD",
        "주황색": "ORANGE", "오렌지": "ORANGE",
        "보라색": "PURPLE", "퍼플": "PURPLE",
        "분홍색": "PINK", "핑크": "PINK",
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
        "가솔린/LPG": "가솔린/LPG",
        "가솔린/CNG": "가솔린/CNG",
        "기타": "기타",
    }

    DRIVE_MAPPING = {
        "2": "2WD", "2WD": "2WD", "2륜": "2WD", "FWD": "2WD", "RWD": "2WD",
        "4": "4WD", "4WD": "4WD", "4륜": "4WD", "AWD": "4WD",
    }

    TRANSMISSION_MAPPING = {
        "자동": "AUTO", "오토": "AUTO", "AUTO": "AUTO", "CVT": "AUTO",
        "DCT": "AUTO", "AT": "AUTO",
        "수동": "MANUAL", "매뉴얼": "MANUAL", "MANUAL": "MANUAL", "MT": "MANUAL",
    }

    # 어드민 옵션 버튼 전체 목록
    ADMIN_OPTIONS = {
        "내/외관": [
            "전동시트(뒷좌석)", "고스트 도어 클로징", "LED 헤드램프",
            "통풍시트(앞좌석)", "무선도어 잠금장치", "ECM 룸미러",
            "전동시트(운전석)", "통풍시트(뒷좌석)", "스티어링 휠 리모컨",
            "열선시트(뒷좌석)", "패들 시프트", "메모리 시트(운전석)",
            "선루프", "전동시트(동승석)", "가죽시트", "루프랙",
            "파워 윈도우", "HID 헤드램프", "전동접이 사이드 미러",
            "열선스티어링", "4WD", "파워 전동 트렁크", "알루미늄휠",
            "파워 스티어링 휠", "파워 도어록", "메모리시트(동승석)", "열선시트(앞좌석)",
        ],
        "편의/기타": [
            "하이패스", "헤드업 디스플레이(HUD)", "CD 플레이어",
            "뒷좌석 AV 모니터", "전동 조절 스티어링 휠", "USB 단자",
            "블루투스", "오토홀드", "네비게이션", "에어컨", "스마트키",
            "앞좌석 AV 모니터",
        ],
    }

    # 스프레드시트 옵션 → 어드민 버튼 매핑 (다른 표기 대응)
    OPTION_ALIAS = {
        "전동시트 뒷좌석": "전동시트(뒷좌석)",
        "전동시트 앞좌석": "전동시트(운전석)",
        "전동시트 운전석": "전동시트(운전석)",
        "전동시트 동승석": "전동시트(동승석)",
        "통풍시트 앞좌석": "통풍시트(앞좌석)",
        "통풍시트 운전석": "통풍시트(앞좌석)",
        "통풍시트 뒷좌석": "통풍시트(뒷좌석)",
        "열선시트 앞좌석": "열선시트(앞좌석)",
        "열선시트 뒷좌석": "열선시트(뒷좌석)",
        "메모리시트 운전석": "메모리 시트(운전석)",
        "메모리시트 동승석": "메모리시트(동승석)",
        "LED램프": "LED 헤드램프",
        "HID램프": "HID 헤드램프",
        "HUD": "헤드업 디스플레이(HUD)",
        "후방카메라": "",  # 없음
        "후방 카메라": "",
    }

    VIN_BRAND_MAP = {
        "KMH": "현대", "KMJ": "현대",
        "KNA": "기아", "KND": "기아", "KNJ": "기아",
        "KPT": "쉐보레",
        "WAU": "아우디",
        "WBA": "BMW", "WBY": "BMW",
        "WVW": "폭스바겐", "WVG": "폭스바겐",
        "SAL": "랜드로버",
        "VF1": "르노코리아(삼성)", "VF3": "르노코리아(삼성)",
        "WDD": "벤츠",
        "JHM": "혼다", "1HG": "혼다",
        "JN1": "닛산", "JTD": "도요타",
        "WP0": "포르쉐",
        "ZFF": "페라리",
    }

    def __init__(self):
        self.driver = None
        self.worksheet = None
        self.all_rows = []
        self.creds = None
        self.drive_links: dict[int, str] = {}

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
            print(f"[OK] 스프레드시트 연결: {self.worksheet.title}")
            self.all_rows = self.worksheet.get_all_values()
            self._fetch_w_column_links()
            return True
        except Exception as e:
            print(f"[오류] 스프레드시트 연결 실패: {e}")
            return False

    def _fetch_w_column_links(self) -> None:
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
                row_num = idx + 1
                if row_num < 2:
                    continue
                values = row.get("values", [])
                if not values:
                    continue
                cell = values[0]
                link = cell.get("hyperlink", "")
                if not link:
                    uev = cell.get("userEnteredValue", {})
                    formula = uev.get("formulaValue", "") if isinstance(uev, dict) else ""
                    if formula:
                        m = re.search(r'HYPERLINK\("([^"]+)"', formula)
                        if m:
                            link = m.group(1)
                if not link:
                    fv = cell.get("formattedValue", "")
                    if fv and fv.startswith("http"):
                        link = fv
                if link and ("drive.google.com" in link or "docs.google.com" in link):
                    self.drive_links[row_num] = link
            print(f"[OK] W열 링크 {len(self.drive_links)}개")
        except Exception as e:
            print(f"[경고] W열 링크 조회 실패: {e}")

    def _get_drive_link_for_row(self, row_idx: int) -> str:
        if row_idx in self.drive_links:
            return self.drive_links[row_idx]
        row = self.all_rows[row_idx - 2] if row_idx - 2 < len(self.all_rows) else []
        val = row[self.COL_PHOTO_LINK].strip() if len(row) > self.COL_PHOTO_LINK else ""
        return val if val.startswith("http") else ""

    def get_pending_rows(self) -> list[dict]:
        """Z열(플랫폼 링크) 있고, AA열(어드민 링크) 없는 행 → 어드민 업로드 대상"""
        pending = []
        for row_idx, row in enumerate(self.all_rows[1:], start=2):
            z_val = row[self.COL_PLATFORM_URL] if len(row) > self.COL_PLATFORM_URL else ""
            aa_val = row[self.COL_ADMIN_URL] if len(row) > self.COL_ADMIN_URL else ""
            if z_val and z_val.strip() and (not aa_val or not aa_val.strip()):
                pending.append({"row_idx": row_idx, "row": row})
        return pending

    def parse_i_column(self, i_val: str) -> dict:
        result = {
            "sub_model": "", "drive_type": "", "transmission": "",
            "fuel": "", "seating": "", "mileage": "",
            "handle": "", "engine_displacement": "",
        }
        if not i_val or i_val.strip() == "해당없음":
            return result
        patterns = {
            "sub_model":           r"1\.\s*세부모델[ \t]*:[ \t]*([^\r\n]*)",
            "drive_type":          r"2\.\s*구동방식[ \t]*:[ \t]*([^\r\n]*)",
            "transmission":        r"3\.\s*변속기[ \t]*:[ \t]*([^\r\n]*)",
            "fuel":                r"4\.\s*연료[ \t]*:[ \t]*([^\r\n]*)",
            "seating":             r"5\.\s*승차인원[ \t]*:[ \t]*([^\r\n]*)",
            "mileage":             r"6\.\s*주행거리[ \t]*:[ \t]*([^\r\n]*)",
            "handle":              r"7\.\s*핸들위치[ \t]*:[ \t]*([^\r\n]*)",
            "engine_displacement": r"배기량[ \t]*:[ \t]*([^\r\n]*)",
        }
        for key, pattern in patterns.items():
            m = re.search(pattern, i_val)
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

    def _parse_price(self, price_raw: str) -> str:
        """가격 문자열 → 숫자 문자열 (소수점 제거, $기호 제거)"""
        if not price_raw:
            return "0"
        s = re.sub(r"[^\d.]", "", price_raw.strip())
        try:
            return str(int(float(s))) if s else "0"
        except ValueError:
            return "0"

    def _parse_mileage(self, mileage_raw: str) -> str:
        """주행거리 파싱: '5만' → '50000', '50,000km' → '50000'"""
        if not mileage_raw:
            return ""
        s = mileage_raw.strip()
        # '5만', '5만km' 형태
        m = re.search(r"([\d.]+)\s*만", s)
        if m:
            return str(int(float(m.group(1)) * 10000))
        # 숫자만
        digits = "".join(filter(str.isdigit, re.sub(r'[,.]', '', s)))
        return digits if digits else ""

    # ─────────────────────────────────────────────
    # 이미지 다운로드
    # ─────────────────────────────────────────────
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

            # 숫자 정렬
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

    def download_images_via_drive(self, drive_link: str, row_num: int) -> list[str]:
        """구글 드라이브 폴더에서 이미지 다운로드 (data-id 개별 다운로드)"""
        if not drive_link:
            return []
        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        if os.path.exists(row_folder):
            shutil.rmtree(row_folder, ignore_errors=True)
        os.makedirs(row_folder, exist_ok=True)
        os.makedirs(self.DOWNLOAD_FOLDER, exist_ok=True)

        fid_match = re.search(r'/folders/([a-zA-Z0-9_-]+)', drive_link)

        dl_driver = None
        try:
            download_abs = os.path.abspath(self.DOWNLOAD_FOLDER)
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

            img_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif"}

            # ── 파일 ID + 이름 목록 추출 (JS) ───────────────────
            folder_id_raw = fid_match.group(1) if fid_match else ""
            file_data = dl_driver.execute_script("""
                var folderID = arguments[0];
                var seen = new Set();
                var results = [];

                // 방법 1: c-wiz[data-id] 또는 div[data-id] 중 파일 ID
                document.querySelectorAll('[data-id]').forEach(function(el){
                    var id = el.getAttribute('data-id');
                    if(!id || seen.has(id) || id === folderID) return;
                    if(id.length < 20 || !/^[a-zA-Z0-9_-]+$/.test(id)) return;
                    seen.add(id);
                    // 파일명 추출: aria-label, data-tooltip, 자식 span 등
                    var name = el.getAttribute('aria-label') || el.getAttribute('data-tooltip') || '';
                    // "1.jpg 파일 더보기" → "1.jpg" 추출
                    var m = name.match(/^(.+?\\.\\w{2,5})(?:\\s|$)/);
                    if(m) name = m[1].trim();
                    else {
                        // 자식 요소에서 파일명 찾기
                        var child = el.querySelector('[data-tooltip], [title]');
                        if(child) name = child.getAttribute('data-tooltip') || child.title || '';
                    }
                    results.push({id: id, name: name});
                });

                // 방법 2: jsname 또는 data-filename 속성
                document.querySelectorAll('[data-filename]').forEach(function(el){
                    var name = el.getAttribute('data-filename');
                    var parent = el.closest('[data-id]');
                    var id = parent ? parent.getAttribute('data-id') : null;
                    if(id && !seen.has(id) && id !== folderID && id.length >= 20){
                        seen.add(id);
                        results.push({id: id, name: name || ''});
                    }
                });

                return results;
            """, folder_id_raw)

            # 이름에 이미지 확장자 있는 것만
            img_file_data = [
                f for f in (file_data or [])
                if any(f.get("name","").lower().endswith(f".{e}") for e in img_exts)
            ]
            # 이름 없어도 ID 있으면 포함 (이름 모르는 경우)
            no_name_data = [
                f for f in (file_data or [])
                if f.get("id") and not f.get("name")
            ]

            print(f"  [드라이브] 전체 data-id 항목: {len(file_data or [])}, "
                  f"이미지 파일명 확인: {len(img_file_data)}, 이름 없음: {len(no_name_data)}")

            # 이름 확인된 이미지 없으면 → 전체 ID로 시도
            candidate_data = img_file_data if img_file_data else (file_data or [])

            downloaded = []
            pre_files = set(os.listdir(download_abs))

            if candidate_data:
                # 다운로드 URL로 각각 트리거
                print(f"  [개별다운] {len(candidate_data)}개 다운로드 시도...")
                for fi in candidate_data:
                    fid_val = fi["id"]
                    dl_url = (
                        f"https://drive.google.com/uc"
                        f"?export=download&id={fid_val}&confirm=t"
                    )
                    try:
                        dl_driver.execute_script(
                            f"window.open('{dl_url}', '_blank');"
                        )
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"  [경고] {fid_val} 다운로드 시작 실패: {e}")

                # 다운로드 완료 대기 (최대 120초, 10초 안정화)
                end_time = time.time() + 120
                no_crd_since = None
                last_count = -1
                while time.time() < end_time:
                    cur_files = set(os.listdir(download_abs))
                    in_progress = [f for f in cur_files
                                   if f.endswith(".crdownload") or f.endswith(".tmp")]
                    done_imgs = [
                        f for f in cur_files - pre_files
                        if not f.endswith(".crdownload") and not f.endswith(".tmp")
                        and not f.startswith("row_")
                        and any(f.lower().endswith(f".{e}") for e in img_exts)
                    ]
                    if not in_progress and len(done_imgs) > 0:
                        if len(done_imgs) == last_count:
                            if no_crd_since is None:
                                no_crd_since = time.time()
                            elif time.time() - no_crd_since >= 10:
                                break
                        else:
                            no_crd_since = None
                    else:
                        no_crd_since = None
                    last_count = len(done_imgs)
                    time.sleep(1.5)

                # 완료 파일 수집 → row_folder로 이동
                cur_files = set(os.listdir(download_abs))
                for fn in sorted(cur_files - pre_files):
                    if fn.endswith(".crdownload") or fn.endswith(".tmp") or fn.startswith("row_"):
                        continue
                    if any(fn.lower().endswith(f".{e}") for e in img_exts):
                        src = os.path.join(download_abs, fn)
                        fdst = os.path.join(row_folder, fn)
                        shutil.move(src, fdst)
                        downloaded.append(fdst)
                print(f"  [개별다운 완료] {len(downloaded)}개")

            # 다운로드가 안 됐으면 → Ctrl+A + ZIP 폴백
            if not downloaded:
                print("  [폴백] Ctrl+A + ZIP 다운로드 시도")
                pre_files2 = set(os.listdir(download_abs))
                try:
                    # 파일 그리드에 포커스 후 Ctrl+A
                    focused = dl_driver.execute_script("""
                        var grid = document.querySelector('[role="grid"], [role="listbox"], [role="list"]');
                        if(grid){ grid.focus(); return true; }
                        return false;
                    """)
                    time.sleep(0.3)
                    ActionChains(dl_driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
                    time.sleep(2)
                    for _ in range(5):
                        time.sleep(1)
                        btns = dl_driver.find_elements(By.XPATH,
                            "//button[@aria-label='다운로드' or @aria-label='Download']")
                        vis = [b for b in btns if b.is_displayed()]
                        if vis:
                            dl_driver.execute_script("arguments[0].click();", vis[-1])
                            print("  [OK] 다운로드 버튼 클릭")
                            break
                except Exception as e:
                    print(f"  [경고] Ctrl+A 폴백 실패: {e}")

                # ZIP 대기
                print("  [대기] ZIP 다운로드 대기...")
                time.sleep(5)
                end_time = time.time() + 180
                no_crd_since = None
                while time.time() < end_time:
                    in_progress = [f for f in os.listdir(download_abs)
                                   if f.endswith(".crdownload") or f.endswith(".tmp")]
                    new_zips = [f for f in set(os.listdir(download_abs)) - pre_files2
                                if f.lower().endswith(".zip") and not f.endswith(".crdownload")]
                    if not in_progress and new_zips:
                        if no_crd_since is None:
                            no_crd_since = time.time()
                        elif time.time() - no_crd_since >= 5:
                            break
                    else:
                        no_crd_since = None
                    time.sleep(2)

                # ZIP 해제
                for fn in sorted(os.listdir(download_abs),
                                 key=lambda f: os.path.getmtime(os.path.join(download_abs, f)),
                                 reverse=True):
                    if fn in pre_files2 or fn.startswith("row_"):
                        continue
                    fp = os.path.join(download_abs, fn)
                    if fn.lower().endswith(".zip"):
                        try:
                            dst_zip = os.path.join(row_folder, "downloaded.zip")
                            shutil.move(fp, dst_zip)
                            with zipfile.ZipFile(dst_zip, "r") as zf:
                                zf.extractall(row_folder)
                            for root, _, files in os.walk(row_folder):
                                for f2 in files:
                                    if f2 == "downloaded.zip":
                                        continue
                                    if any(f2.lower().endswith(f".{e}") for e in img_exts):
                                        downloaded.append(os.path.join(root, f2))
                            os.remove(dst_zip)
                            print(f"  [ZIP 해제] {len(downloaded)}개")
                        except Exception as e:
                            print(f"  [오류] ZIP 처리 실패: {e}")
                        break

            # 숫자 정렬
            downloaded.sort(key=self._num_sort_key)
            print(f"  [순서] {[os.path.basename(f) for f in downloaded[:15]]}"
                  f"{'...' if len(downloaded) > 15 else ''}")
            print(f"[OK] 이미지 {len(downloaded)}개 다운로드 완료")
            return downloaded

        except Exception as e:
            print(f"[오류] 이미지 다운로드 실패: {e}")
            import traceback; traceback.print_exc()
            return []
        finally:
            if dl_driver:
                try:
                    dl_driver.quit()
                except Exception:
                    pass

    def cleanup_row_images(self, row_num: int) -> None:
        row_folder = os.path.join(self.DOWNLOAD_FOLDER, f"row_{row_num}")
        try:
            if os.path.exists(row_folder):
                shutil.rmtree(row_folder)
        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Selenium 드라이버
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
    # 어드민 로그인
    # ─────────────────────────────────────────────
    def login(self) -> bool:
        try:
            print(f"\n[로그인] {self.ADMIN_EMAIL}")
            self.driver.get(f"{self.ADMIN_URL}/sign-in")
            time.sleep(2)

            wait = WebDriverWait(self.driver, 10)
            email_field = wait.until(EC.presence_of_element_located((By.NAME, "email")))
            email_field.clear()
            email_field.send_keys(self.ADMIN_EMAIL)

            pw_field = self.driver.find_element(By.XPATH, "//input[@type='password']")
            pw_field.clear()
            pw_field.send_keys(self.ADMIN_PASSWORD)

            # 로그인 버튼
            for xp in [
                "//button[contains(text(),'Login')]",
                "//button[contains(text(),'로그인')]",
                "//button[@type='submit']",
                "//button",
            ]:
                try:
                    btns = self.driver.find_elements(By.XPATH, xp)
                    vis = [b for b in btns if b.is_displayed()]
                    if vis:
                        vis[0].click()
                        break
                except Exception:
                    pass

            time.sleep(3)
            # 로그인 성공 확인
            if "/sign-in" in self.driver.current_url:
                print(f"[오류] 로그인 실패 (URL: {self.driver.current_url})")
                return False
            print(f"[OK] 로그인 완료 - {self.driver.current_url}")
            return True

        except Exception as e:
            print(f"[오류] 로그인 실패: {e}")
            return False

    # ─────────────────────────────────────────────
    # 폼 헬퍼
    # ─────────────────────────────────────────────
    def _open_combobox(self, combo_el, field_name: str) -> bool:
        def options_visible():
            try:
                WebDriverWait(self.driver, 1).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//div[@role='option'] | //li[@role='option']")
                    )
                )
                return True
            except Exception:
                return False

        for name, action in [
            ("js click", lambda: self.driver.execute_script("arguments[0].click();", combo_el)),
            ("native click", lambda: combo_el.click()),
            ("action click", lambda: ActionChains(self.driver).move_to_element(combo_el).click().perform()),
        ]:
            try:
                action()
                time.sleep(0.4)
                if options_visible():
                    return True
            except Exception:
                pass
        return False

    def _select_option_from_open_combobox(self, option_value: str, field_name: str) -> bool:
        time.sleep(0.4)

        def try_click(pred):
            for attempt in range(3):
                try:
                    opts = self.driver.find_elements(
                        By.XPATH, "//div[@role='option'] | //li[@role='option']"
                    )
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
                            break
                    return False
                except Exception:
                    time.sleep(0.2)
            return False

        if try_click(lambda t: t == option_value):
            return True
        if try_click(lambda t: option_value.upper() in t.upper() or t.upper() in option_value.upper()):
            return True
        if option_value.isdigit():
            if try_click(lambda t: "".join(filter(str.isdigit, t)) == option_value):
                return True

        self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        print(f"[경고] {field_name} '{option_value}' 매칭 실패")
        return False

    def _set_native_select_by_label(self, label_text: str, option_value: str, field_name: str) -> bool:
        """라벨 텍스트로 select 찾아 값 설정 (React 이벤트 발생, 빈 옵션 스킵)"""
        try:
            result = self.driver.execute_script("""
                var lbl = arguments[0];
                var val = arguments[1];
                // 라벨 텍스트 포함 컨테이너에서 select 찾기
                var selects = Array.from(document.querySelectorAll('select'));
                var sel = null;
                for(var s of selects){
                    if(s.offsetParent===null) continue;
                    var el = s;
                    for(var d=0; d<6; d++){
                        if(!el) break;
                        var clone = el.cloneNode(true);
                        clone.querySelectorAll('select,input,button,textarea').forEach(function(e){e.remove();});
                        if(clone.textContent.includes(lbl)){ sel=s; break; }
                        el = el.parentElement;
                    }
                    if(sel) break;
                }
                if(!sel) return null;
                // 옵션 매칭 (빈 옵션 스킵, 정확 매칭 우선)
                var valUp = val.trim().toUpperCase();
                for(var pass=0; pass<2; pass++){
                    for(var i=0; i<sel.options.length; i++){
                        var optTxt = sel.options[i].text.trim();
                        var optVal = sel.options[i].value.trim();
                        if(!optTxt) continue; // 빈 옵션 스킵
                        var tUp = optTxt.toUpperCase();
                        var vUp = optVal.toUpperCase();
                        var match = pass===0
                            ? (tUp === valUp || vUp === valUp)
                            : (tUp.includes(valUp) || vUp.includes(valUp));
                        if(match){
                            var nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLSelectElement.prototype, 'value').set;
                            nativeSetter.call(sel, sel.options[i].value);
                            sel.dispatchEvent(new Event('change', {bubbles:true}));
                            sel.dispatchEvent(new Event('input', {bubbles:true}));
                            return optTxt;
                        }
                    }
                }
                return null;
            """, label_text, option_value)
            if result:
                print(f"[OK] {field_name} '{result}' 선택 (native select, label='{label_text}')")
                time.sleep(0.3)
                return True
            print(f"[경고] {field_name} native select 실패 (label='{label_text}', val='{option_value}')")
            return False
        except Exception as e:
            print(f"[경고] {field_name} native select 오류: {e}")
            return False

    def _set_select_via_combobox(self, combo_index: int, option_value: str, field_name: str) -> bool:
        """visible combobox 목록에서 index 번째 combobox 클릭해 옵션 선택"""
        try:
            combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
            vis = [c for c in combos if c.is_displayed()]
            if combo_index >= len(vis):
                print(f"[경고] {field_name} combo[{combo_index}] 없음")
                return False
            combo = vis[combo_index]
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", combo)
            time.sleep(0.3)
            if not self._open_combobox(combo, field_name):
                return False
            return self._select_option_from_open_combobox(option_value, field_name)
        except Exception as e:
            print(f"[경고] {field_name} combobox 선택 실패: {e}")
            return False

    def _fill_text_input_by_name(self, name: str, value: str, field_name: str) -> bool:
        """input[name=...] 에 값 입력"""
        try:
            inp = self.driver.find_element(By.CSS_SELECTOR, f"input[name='{name}']")
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", inp)
            inp.clear()
            # React 이벤트 발생을 위해 JS setter 사용
            self.driver.execute_script("""
                var inp = arguments[0];
                var val = arguments[1];
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
            """, inp, value)
            print(f"[OK] {field_name} '{value}' 입력")
            return True
        except Exception as e:
            # 이름 없는 input에 JS로 직접 채우기
            print(f"[경고] {field_name} input[name={name!r}] 실패: {e}")
            return False

    def _fill_text_input_by_label(self, label_text: str, value: str, field_name: str) -> bool:
        """라벨로 input 찾아 값 입력 (최대 4단계, 가장 가까운 매칭 우선)"""
        try:
            inp = self.driver.execute_script("""
                var lbl = arguments[0];
                var inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"])'));
                var bestInp = null, bestDepth = 999;
                for(var inp of inputs){
                    if(inp.offsetParent===null) continue;
                    var el = inp;
                    for(var d=0; d<4; d++){
                        if(!el) break;
                        var clone = el.cloneNode(true);
                        clone.querySelectorAll('input,button,select,textarea').forEach(function(e){e.remove();});
                        if(clone.textContent.includes(lbl)){
                            if(d < bestDepth){ bestDepth=d; bestInp=inp; }
                            break;
                        }
                        el = el.parentElement;
                    }
                }
                return bestInp;
            """, label_text)
            if not inp:
                return False
            self.driver.execute_script("""
                var inp = arguments[0];
                var val = arguments[1];
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
            """, inp, value)
            print(f"[OK] {field_name} '{value}' 입력 (라벨='{label_text}')")
            return True
        except Exception as e:
            print(f"[경고] {field_name} 라벨 input 실패: {e}")
            return False

    # ─────────────────────────────────────────────
    # VIN 조회
    # ─────────────────────────────────────────────
    def input_vin_and_search(self, vin: str) -> bool:
        try:
            print(f"\n[VIN 조회] '{vin}'")
            self.driver.execute_script("window.scrollTo(0,0);")
            time.sleep(0.5)

            VIN_INPUT_XPATH     = "//*[@id='car-create-form']/section[1]/div[2]/div/div[2]/input"
            VIN_CONTAINER_XPATH = "//*[@id='car-create-form']/section[1]/div[2]/div/div[2]"

            # 1) input 클릭 후 VIN 값 입력
            vin_input = self.driver.find_element(By.XPATH, VIN_INPUT_XPATH)
            self.driver.execute_script("arguments[0].click();", vin_input)
            time.sleep(0.2)
            self.driver.execute_script("""
                var inp = arguments[0]; var val = arguments[1];
                var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input',  {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
            """, vin_input, vin)
            print(f"[OK] VIN '{vin}' 입력")
            time.sleep(0.3)

            # 2) container 클릭 → radix 팝업 열기
            container = self.driver.find_element(By.XPATH, VIN_CONTAINER_XPATH)
            self.driver.execute_script("arguments[0].click();", container)
            print("[OK] VIN container 클릭")
            time.sleep(0.5)

            # 3) 조회하기 버튼 클릭
            #    radix 팝업은 portal로 렌더링되므로 car-create-form 바깥에 있을 수 있음
            #    button[2] = 조회하기 (button[1] = 취소)
            search_btn = None
            for xp in [
                "//button[normalize-space(.)='조회하기']",
                "//button[contains(.,'조회하기')]",
                "//button[contains(.,'조회')]",
            ]:
                try:
                    btns = self.driver.find_elements(By.XPATH, xp)
                    vis = [b for b in btns if b.is_displayed()]
                    if vis:
                        search_btn = vis[0]
                        print(f"[OK] 조회하기 버튼 찾음: XPath={xp!r}")
                        break
                except Exception:
                    pass

            if search_btn:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", search_btn)
                time.sleep(0.2)
                self.driver.execute_script("arguments[0].click();", search_btn)
                print("[OK] 조회하기 클릭")
                time.sleep(4)
            else:
                print("[경고] 조회하기 버튼 없음 — 버튼 목록:")
                all_btns = self.driver.find_elements(By.TAG_NAME, "button")
                for b in all_btns:
                    if b.is_displayed():
                        print(f"  버튼: '{b.text[:40]!r}'")

            # 다이얼로그 처리
            self._handle_dialogs()

            return True

        except Exception as e:
            print(f"[오류] VIN 조회 실패: {e}")
            return False

    def _handle_dialogs(self) -> None:
        for _ in range(6):
            time.sleep(1.5)
            dialogs = self.driver.find_elements(By.XPATH, "//*[@role='dialog']")
            vis_d = [d for d in dialogs if d.is_displayed()]
            if not vis_d:
                break
            btns = self.driver.find_elements(By.XPATH, "//*[@role='dialog']//button")
            vis_b = [b for b in btns if b.is_displayed()]
            if not vis_b:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                break
            # '확인' 우선, 없으면 마지막
            confirm = next((b for b in vis_b if b.text.strip() in ("확인", "OK")), vis_b[-1])
            print(f"  [다이얼로그] '{confirm.text.strip()}' 클릭")
            confirm.click()
            time.sleep(1)

    # ─────────────────────────────────────────────
    # 모델명 매칭 헬퍼
    # ─────────────────────────────────────────────
    # 영문 모델명 키워드 → 어드민 한글 모델명
    MODEL_KEYWORD_MAP = {
        "TUCSON": "투싼", "TUCS": "투싼",
        "SANTAFE": "싼타페", "SANTA FE": "싼타페", "SANTAF": "싼타페",
        "GRANDEUR": "그랜저", "GRAND": "그랜저",
        "SONATA": "쏘나타",
        "AVANTE": "아반떼", "ELANTRA": "아반떼",
        "STAREX": "스타렉스",
        "PORTER": "포터",
        "GENESIS": "제네시스",
        "IONIQ": "아이오닉", "IONIC": "아이오닉",
        "KONA": "코나",
        "PALISADE": "팰리세이드",
        "NEXO": "넥쏘",
        "VELOSTER": "벨로스터",
        "ACCENT": "엑센트",
        "VENUE": "베뉴",
        "STARIA": "스타리아",
        "CASPER": "캐스퍼",
        "SPORTAGE": "스포티지",
        "SORENTO": "쏘렌토",
        "CARNIVAL": "카니발",
        "STINGER": "스팅어",
        "MOHAVE": "모하비",
        "TELLURIDE": "텔루라이드",
        "MORNING": "모닝",
        "RAY": "레이",
        "PRIDE": "프라이드",
        "K5": "K5", "K7": "K7", "K8": "K8", "K9": "K9",
        "K3": "K3",
        "NIRO": "니로",
        "EV6": "EV6", "EV9": "EV9",
        "TIGUAN": "티구안",
        "GOLF": "골프",
        "PASSAT": "파사트",
        "BEETLE": "비틀",
        "TOUAREG": "투아렉",
        "A4": "A4", "A5": "A5", "A6": "A6", "A7": "A7", "A8": "A8",
        "Q3": "Q3", "Q5": "Q5", "Q7": "Q7", "Q8": "Q8",
        "C CLASS": "C클래스", "CCLASS": "C클래스",
        "E CLASS": "E클래스", "ECLASS": "E클래스",
        "S CLASS": "S클래스", "SCLASS": "S클래스",
        "GLC": "GLC", "GLE": "GLE", "GLS": "GLS",
        "3 SERIES": "3시리즈", "3SERIES": "3시리즈",
        "5 SERIES": "5시리즈", "5SERIES": "5시리즈",
        "7 SERIES": "7시리즈", "X3": "X3", "X5": "X5",
        "EVOQUE": "이보크",
        "DISCOVERY": "디스커버리",
        "RANGE ROVER": "레인지로버",
        "SPARK": "스파크", "CRUZE": "크루즈", "MALIBU": "말리부",
        "CAPTIVA": "캡티바", "TRAX": "트랙스", "EQUINOX": "이쿼녹스",
        "SM3": "SM3", "SM5": "SM5", "SM6": "SM6", "SM7": "SM7",
        "QM3": "QM3", "QM5": "QM5", "QM6": "QM6",
    }

    def _match_model_name(self, model_raw: str, available_options: list[str]) -> str:
        """D열 모델명으로 어드민 옵션 중 가장 근접한 것 반환. 못 찾으면 빈 문자열."""
        if not model_raw or not available_options:
            return ""

        model_up = model_raw.upper().replace("-", " ").replace("_", " ")

        # 1. 어드민 옵션 텍스트와 직접 비교 (포함 여부)
        for opt in available_options:
            opt_up = opt.upper()
            if opt_up in model_up or model_up in opt_up:
                return opt

        # 2. 키워드 맵으로 한글 변환 후 비교
        for keyword, korean in self.MODEL_KEYWORD_MAP.items():
            if keyword in model_up:
                for opt in available_options:
                    if korean in opt or opt in korean:
                        return opt

        # 3. 단어 단위 부분 매칭 (모델명의 각 단어가 옵션에 포함되는지)
        words = [w for w in model_up.split() if len(w) >= 3]
        for word in words:
            for opt in available_options:
                if word in opt.upper():
                    return opt

        return ""

    # ─────────────────────────────────────────────
    # 차량 정보 입력
    # ─────────────────────────────────────────────
    def fill_car_cascade(self, vin: str, model_name: str = "") -> bool:
        """VIN으로 브랜드 추정, D열 모델명으로 모델 선택. 실패 시 예외 발생."""
        brand = self.VIN_BRAND_MAP.get(vin[:3].upper(), "")
        if not brand:
            raise ValueError(f"VIN '{vin[:3]}' 브랜드 매핑 없음 — VIN_BRAND_MAP에 추가 필요")

        print(f"\n[브랜드/모델 cascade] VIN→브랜드='{brand}', 모델명='{model_name}'")

        # 브랜드 combobox (index 0)
        combos = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
        vis = [c for c in combos if c.is_displayed()]
        if not vis:
            raise RuntimeError("브랜드 combobox 없음")

        brand_combo = vis[0]
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", brand_combo)
        time.sleep(0.3)
        if not self._open_combobox(brand_combo, "브랜드"):
            raise RuntimeError("브랜드 combobox 열기 실패")
        if not self._select_option_from_open_combobox(brand, "브랜드"):
            raise RuntimeError(f"브랜드 '{brand}' 선택 실패")

        # 브랜드 선택 후 DOM 갱신 대기
        time.sleep(1.5)

        # 모델 combobox (index 1) — DOM 재탐색
        combos2 = self.driver.find_elements(By.XPATH, "//button[@role='combobox']")
        vis2 = [c for c in combos2 if c.is_displayed()]
        if len(vis2) < 2:
            raise RuntimeError("모델 combobox 없음 (브랜드 선택 후 cascade 로드 실패)")

        model_combo = vis2[1]
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", model_combo)
        if not self._open_combobox(model_combo, "모델"):
            raise RuntimeError("모델 combobox 열기 실패")

        time.sleep(0.5)
        # 옵션 텍스트 JS로 수집 (stale 방지)
        opt_texts = self.driver.execute_script("""
            return Array.from(document.querySelectorAll('[role="option"]'))
                .filter(function(o){ return o.offsetParent!==null && o.textContent.trim(); })
                .map(function(o){ return o.textContent.trim(); });
        """)
        real_opts = [t for t in opt_texts if t not in ("", "선택안함")]

        if not real_opts:
            raise RuntimeError(f"모델 옵션 없음 (브랜드='{brand}')")

        print(f"   [디버그] 모델 옵션: {real_opts}")

        # 모델명으로 매칭
        matched = self._match_model_name(model_name, real_opts)
        if not matched:
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            raise ValueError(
                f"모델 매칭 실패 — D열='{model_name}', 어드민옵션={real_opts}\n"
                f"  → MODEL_KEYWORD_MAP에 매핑 추가 필요"
            )

        if not self._select_option_from_open_combobox(matched, "모델"):
            raise RuntimeError(f"모델 '{matched}' 선택 실패")

        return True

    def _set_input_value(self, inp_el, value: str) -> None:
        """React controlled input에 값 설정"""
        self.driver.execute_script("""
            var inp=arguments[0], val=arguments[1];
            var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            setter.call(inp, val);
            inp.dispatchEvent(new Event('input',{bubbles:true}));
            inp.dispatchEvent(new Event('change',{bubbles:true}));
            inp.dispatchEvent(new Event('blur',{bubbles:true}));
        """, inp_el, value)

    def fill_car_vin_field(self, vin: str) -> None:
        """cascade 후 폼 내 *차대번호 입력 필드 채우기"""
        INPUT_XPATH = "//*[@id='car-create-form']/section[1]/div[2]/div[3]/div[1]/input[1]"
        try:
            inp = self.driver.find_element(By.XPATH, INPUT_XPATH)
            cur = inp.get_attribute("value") or ""
            if cur == vin:
                print(f"[OK] 차대번호 이미 '{vin}' 입력됨")
                return
            self._set_input_value(inp, vin)
            print(f"[OK] 차대번호 폼 필드 '{vin}' 입력")
        except Exception as e:
            print(f"[경고] 차대번호 폼 필드 없음: {e}")

    def fill_car_details(self, year: str, color: str, detail: dict, vin: str = "") -> None:
        """연식, 색상, 구동방식, 변속기, 연료, 승차인원, 주행거리, 배기량 입력"""
        print("\n[차량 상세 입력]")

        # 차대번호 폼 필드 (검색 후 별도 입력 필요)
        if vin:
            self.fill_car_vin_field(vin)

        # 연식
        if year:
            self._fill_text_input_by_name("modelYear", year, "연식")

        # 구동방식
        drive_raw = detail.get("drive_type", "")
        drive_val = self.DRIVE_MAPPING.get(drive_raw.upper(), self.DRIVE_MAPPING.get(drive_raw, ""))
        if drive_val:
            if not self._set_native_select_by_label("*구동방식", drive_val, "구동방식"):
                self._set_select_via_combobox(5, drive_val, "구동방식")

        # 변속기
        trans_raw = detail.get("transmission", "")
        trans_val = self.TRANSMISSION_MAPPING.get(trans_raw.upper(),
                    self.TRANSMISSION_MAPPING.get(trans_raw, ""))
        if trans_val:
            if not self._set_native_select_by_label("*변속기", trans_val, "변속기"):
                self._set_select_via_combobox(6, trans_val, "변속기")

        # 연료
        fuel_raw = detail.get("fuel", "")
        fuel_val = self.FUEL_MAPPING.get(fuel_raw, fuel_raw)
        if fuel_val:
            if not self._set_native_select_by_label("*연료 종류", fuel_val, "연료"):
                self._set_select_via_combobox(7, fuel_val, "연료")

        # 색상
        color_upper = color.upper().strip()
        color_val = self.COLOR_MAPPING.get(color, color_upper)
        if color_val:
            if not self._set_native_select_by_label("*색상", color_val, "색상"):
                self._set_select_via_combobox(8, color_val, "색상")

        # 승차인원
        seating_raw = detail.get("seating", "")
        if seating_raw:
            seat_str = re.sub(r"[^\d]", "", seating_raw)
            seat_val = f"{seat_str}명" if seat_str else seating_raw
            if not self._set_native_select_by_label("*승차 인원", seat_val, "승차인원"):
                self._set_select_via_combobox(9, seat_val, "승차인원")

        # 주행거리
        mileage_raw = detail.get("mileage", "")
        mileage_val = self._parse_mileage(mileage_raw)
        if mileage_val:
            self._fill_text_input_by_name("driveDistance", mileage_val, "주행거리")

        # 배기량
        displacement_raw = detail.get("engine_displacement", "")
        if displacement_raw:
            disp_digits = re.sub(r"[^\d]", "", displacement_raw)
            if disp_digits:
                self._fill_text_input_by_name("displacement", disp_digits, "배기량")

    def fill_price(self, price_raw: str) -> None:
        """차량 광고가$ 입력"""
        price_val = self._parse_price(price_raw)
        if not price_val or price_val == "0":
            return
        print(f"\n[가격 입력] ${price_val}")

        PRICE_XPATH = "//*[@id='car-create-form']/section[3]/div[2]/div[1]/div[1]/div[1]/input[1]"
        try:
            inp = self.driver.find_element(By.XPATH, PRICE_XPATH)
            self._set_input_value(inp, price_val)
            print(f"[OK] 광고가$ '{price_val}' 입력")
        except Exception as e:
            print(f"[경고] 가격 입력 실패: {e}")

    def select_options(self, options: list[str]) -> None:
        """옵션 토글 버튼 클릭"""
        if not options:
            return
        print(f"\n[옵션 선택] {options}")

        # 어드민 옵션 버튼 전체 목록 평탄화
        all_admin_opts = []
        for opts in self.ADMIN_OPTIONS.values():
            all_admin_opts.extend(opts)

        for option in options:
            # alias 변환
            target = self.OPTION_ALIAS.get(option, option)
            if not target:
                print(f"  [건너뜀] '{option}' → 어드민에 없는 옵션")
                continue

            # 버튼 텍스트로 찾기
            try:
                btn = self.driver.execute_script("""
                    var target = arguments[0];
                    var btns = Array.from(document.querySelectorAll('button[type="button"]'));
                    for(var b of btns){
                        if(b.offsetParent===null) continue;
                        if(b.textContent.trim() === target) return b;
                    }
                    // 부분 매칭
                    for(var b of btns){
                        if(b.offsetParent===null) continue;
                        if(b.textContent.trim().includes(target) || target.includes(b.textContent.trim()))
                            return b;
                    }
                    return null;
                """, target)

                if btn:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    time.sleep(0.2)
                    self.driver.execute_script("arguments[0].click();", btn)
                    print(f"  [OK] 옵션 '{target}' 선택")
                    time.sleep(0.2)
                else:
                    print(f"  [경고] 옵션 '{target}' 버튼 없음")
            except Exception as e:
                print(f"  [오류] 옵션 '{option}' 선택 실패: {e}")

    def upload_images(self, image_files: list[str]) -> bool:
        """이미지 파일 업로드 (hidden file input에 직접 전송)"""
        if not image_files:
            return False
        try:
            abs_paths = [os.path.abspath(f) for f in image_files]
            print(f"\n[이미지 업로드] {len(abs_paths)}개")

            # hidden file input (accept=image/*) 활성화 후 전송
            file_inputs = self.driver.find_elements(
                By.CSS_SELECTOR, "input[type='file'][accept*='image']"
            )
            if not file_inputs:
                file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")

            if not file_inputs:
                print("[경고] file input 없음")
                return False

            # display:none 해제 (JS)
            file_input = file_inputs[0]
            self.driver.execute_script(
                "arguments[0].style.display='block'; arguments[0].style.visibility='visible';",
                file_input
            )
            time.sleep(0.3)

            file_input.send_keys("\n".join(abs_paths))
            print(f"[OK] 이미지 {len(abs_paths)}개 전송 완료. 업로드 대기 중...")
            time.sleep(8)
            return True

        except Exception as e:
            print(f"[오류] 이미지 업로드 실패: {e}")
            return False

    def submit_form(self) -> str:
        """폼 제출 후 등록된 차량 URL 반환"""
        try:
            print("\n[폼 제출]")
            current_url = self.driver.current_url

            # 저장/등록 버튼 찾기
            save_btn = None
            for xp in [
                "//button[contains(text(),'등록')]",
                "//button[contains(text(),'저장')]",
                "//button[contains(text(),'Submit')]",
                "//button[@type='submit']",
            ]:
                try:
                    btns = self.driver.find_elements(By.XPATH, xp)
                    vis = [b for b in btns if b.is_displayed()]
                    if vis:
                        # 마지막 버튼 (보통 폼 아래쪽에 위치)
                        save_btn = vis[-1]
                        print(f"  저장 버튼 발견: '{save_btn.text[:30]}'")
                        break
                except Exception:
                    pass

            if not save_btn:
                print("[경고] 저장 버튼 없음")
                return ""

            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", save_btn)
            time.sleep(5)

            # 다이얼로그 처리
            self._handle_dialogs()
            time.sleep(2)

            new_url = self.driver.current_url
            print(f"[OK] 제출 완료 - URL: {new_url}")
            return new_url if new_url != current_url else ""

        except Exception as e:
            print(f"[오류] 폼 제출 실패: {e}")
            return ""

    # ─────────────────────────────────────────────
    # 스프레드시트 결과 기록
    # ─────────────────────────────────────────────
    def mark_upload_date(self, row_idx: int) -> bool:
        try:
            today = datetime.now().strftime("%Y. %m. %d")
            self.worksheet.update_acell(f"AD{row_idx}", today)
            print(f"[OK] AD{row_idx} = '{today}'")
            return True
        except Exception as e:
            print(f"[오류] 업로드일자 기입 실패: {e}")
            return False

    def mark_admin_url(self, row_idx: int, result_url: str) -> bool:
        try:
            if result_url:
                self.worksheet.update_acell(f"AA{row_idx}", result_url)
                print(f"[OK] AA{row_idx} = '{result_url}'")
            return True
        except Exception as e:
            print(f"[오류] URL 기입 실패: {e}")
            return False

    def mark_upload_failed(self, row_idx: int) -> bool:
        try:
            self.worksheet.update_acell(f"AD{row_idx}", "업로드실패")
            return True
        except Exception as e:
            print(f"[오류] 실패 표시 실패: {e}")
            return False

    # ─────────────────────────────────────────────
    # 메인 업로드 플로우
    # ─────────────────────────────────────────────
    def upload_one_row(self, row_idx: int, row: list) -> bool:
        model     = row[self.COL_MODEL]       if len(row) > self.COL_MODEL       else ""
        year      = row[self.COL_YEAR]        if len(row) > self.COL_YEAR        else ""
        color     = row[self.COL_COLOR]       if len(row) > self.COL_COLOR       else ""
        vin       = row[self.COL_VIN]         if len(row) > self.COL_VIN         else ""
        i_val     = row[self.COL_DETAIL]      if len(row) > self.COL_DETAIL      else ""
        price_raw = row[self.COL_PRICE]       if len(row) > self.COL_PRICE       else ""
        mileage_t = row[self.COL_MILEAGE]     if len(row) > self.COL_MILEAGE     else ""
        seating_u = row[self.COL_SEATING]     if len(row) > self.COL_SEATING     else ""
        options   = self.get_row_options(row)
        detail    = self.parse_i_column(i_val)

        # T열(주행거리), U열(승차인원)이 있으면 I열 파싱 값 덮어쓰기
        if mileage_t.strip():
            detail["mileage"] = mileage_t.strip()
        if seating_u.strip():
            detail["seating"] = seating_u.strip()

        print(f"\n{'='*60}")
        print(f"행 {row_idx}: {model} ({year}) VIN={vin}")
        print(f"  색상={color}, 가격={price_raw}")
        print(f"  구동={detail.get('drive_type')}, 변속={detail.get('transmission')}")
        print(f"  연료={detail.get('fuel')}, 주행={detail.get('mileage')}, 승차={detail.get('seating')}")
        print(f"  옵션: {options}")

        # 이미지 다운로드 (Y열 사진 링크)
        drive_link = self._get_drive_link_for_row(row_idx)
        image_files = []
        if drive_link:
            print(f"\n[이미지 다운로드] {drive_link[:60]}")
            image_files = self.download_images_via_drive(drive_link, row_idx)
            print(f"  → {len(image_files)}개")
        else:
            print("[알림] Y열 사진 링크 없음 - 이미지 없이 진행")

        try:
            # create 페이지 이동
            print(f"\n[create 이동] {self.CREATE_URL}")
            self.driver.get(self.CREATE_URL)
            time.sleep(3)

            # VIN 조회
            self.input_vin_and_search(vin)
            time.sleep(1)

            # Cascade (브랜드→모델)
            self.fill_car_cascade(vin, model)
            time.sleep(0.5)

            # 상세 정보 입력
            self.fill_car_details(year, color, detail, vin)
            time.sleep(0.5)

            # 가격
            self.fill_price(price_raw)
            time.sleep(0.5)

            # 옵션
            self.select_options(options)
            time.sleep(0.5)

            # 이미지 업로드
            if image_files:
                self.upload_images(image_files)

            # 제출
            result_url = self.submit_form()

            # 결과 기록
            self.mark_admin_url(row_idx, result_url)
            self.mark_upload_date(row_idx)
            return True

        except Exception as e:
            print(f"[오류] 업로드 실패 (행 {row_idx}): {e}")
            import traceback; traceback.print_exc()
            self.mark_upload_failed(row_idx)
            return False
        finally:
            self.cleanup_row_images(row_idx)

    def run(self) -> None:
        """전체 실행"""
        print("=" * 60)
        print("망고 어드민 업로드 시작")
        print("=" * 60)

        if not self.setup_spreadsheet():
            return

        pending = self.get_pending_rows()
        if not pending:
            print("[알림] 업로드 대기 행 없음")
            return

        print(f"\n대기 행: {len(pending)}개")
        for p in pending:
            r = p["row"]
            print(f"  행 {p['row_idx']}: "
                  f"{r[self.COL_MODEL] if len(r)>self.COL_MODEL else ''} "
                  f"VIN={r[self.COL_VIN] if len(r)>self.COL_VIN else ''}")

        self.setup_driver()
        try:
            if not self.login():
                print("[오류] 로그인 실패")
                return

            for item in pending:
                self.upload_one_row(item["row_idx"], item["row"])
                time.sleep(2)

        finally:
            self.close_driver()

        print("\n[완료] 전체 업로드 완료")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    uploader = MangoAdminUploader()
    uploader.run()
