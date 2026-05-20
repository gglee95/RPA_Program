"""Project-wide constants for the Mango Car RPA uploader — Docker build.

차이점 (vs. 호스트 버전):
- STATE_DIR, SERVICE_ACCOUNT_JSON 경로를 환경변수로 오버라이드 가능
- 컨테이너 기본값은 /state, /secrets/service_account.json
"""

import os
from pathlib import Path

# --- Google Sheet ---
SHEET_ID = "1Z3u44ymJyfPYfo-mTiPwGzb7HxgSypuevm3Bdmmse18"
SHEET_GID = 0
SHEET_EDIT_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid={SHEET_GID}#gid={SHEET_GID}"
)
SHEET_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
)
HEADER_ROWS = 2

# --- Mango Car URLs ---
BASE_URL = "https://mangoworldcar.com"
SIGN_IN_URL = f"{BASE_URL}/ko/sign-in"
CAR_CREATE_URL = f"{BASE_URL}/ko/car-normal-create"
CAR_LIST_URL = f"{BASE_URL}/ko/car-sell-list"

# --- Google Service Account ---
# 우선순위: 환경변수 SERVICE_ACCOUNT_JSON > 컨테이너 기본 경로
SERVICE_ACCOUNT_JSON = Path(
    os.environ.get("SERVICE_ACCOUNT_JSON", "/secrets/service_account.json")
)
SHEET_NAME = "시트1"

# --- Filesystem ---
PROJECT_ROOT = Path(__file__).resolve().parent
# 우선순위: 환경변수 MANGO_STATE_DIR > 컨테이너 기본 /state
STATE_DIR = Path(os.environ.get("MANGO_STATE_DIR", "/state"))
DOWNLOADS_DIR = STATE_DIR / "downloads"
LOGS_DIR = STATE_DIR / "logs"
PROFILE_DIR = STATE_DIR / "nd-profile"

# --- Spreadsheet column indices (0-based) ---
COL = {
    "번호": 0, "입고일": 1, "셀러명": 2, "브랜드": 3, "차종": 4, "세부차종": 5,
    "미션": 6, "연식": 7, "인승": 8, "유종": 9,
    "A1": 10, "실주행거리": 11, "차량색상": 12, "셀러수금가": 13, "광고가": 14,
    "계정정보": 15,
    "선루프": 16, "4WD": 17, "가죽시트": 18, "열선시트(앞좌석)": 19,
    "통풍시트(앞좌석)": 20, "후방카메라": 21, "스마트키": 22, "네비게이션": 23, "에어컨": 24,
    "특이사항": 25, "검수": 26, "세차": 27,
    "진행상황": 28, "업로드 일자": 29, "구글드라이브": 30, "링크": 31,
    "비포워드 링크": 32, "비고": 33, "출차여부": 34, "판매여부": 35,
    "업로드결과": 36,
}

OPTION_KEYS = [
    "선루프", "4WD", "가죽시트", "열선시트(앞좌석)", "통풍시트(앞좌석)",
    "후방카메라", "스마트키", "네비게이션", "에어컨",
]
ADDON_KEYS = ["검수", "세차"]

PHOTO_CATEGORIES = [
    ("외부",     ["외부", "외관", "1. 외부", "1.외부", "1. 외관", "1.외관"]),
    ("내부",     ["내부", "내관", "2. 내부", "2.내부", "2. 내관", "2.내관"]),
    ("하부/차대", ["하부/차대", "하부 / 차대", "3. 하부 / 차대", "3. 하부/차대", "하부", "차대"]),
    ("엔진룸",   ["엔진룸", "4. 엔진룸", "4.엔진룸"]),
]

COL_LETTER_UPLOAD_DATE = "AD"
COL_LETTER_LINK = "AF"
COL_LETTER_BEFORWARD_LINK = "AG"
COL_LETTER_UPLOAD_RESULT = "AK"
COL_LETTER_VIN_ERROR = "AL"
