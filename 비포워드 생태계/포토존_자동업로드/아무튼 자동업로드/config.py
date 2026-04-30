"""Project-wide constants for the Mango Car RPA uploader (nodriver build)."""

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
HEADER_ROWS = 2  # rows 1-2 are merged/sub headers; data starts at row 3

# --- Mango Car URLs ---
BASE_URL = "https://mangoworldcar.com"
SIGN_IN_URL = f"{BASE_URL}/ko/sign-in"
CAR_CREATE_URL = f"{BASE_URL}/ko/car-normal-create"
CAR_LIST_URL = f"{BASE_URL}/ko/car-sell-list"

# --- Google Service Account (Sheets API write-back) ---
SERVICE_ACCOUNT_JSON = Path(__file__).resolve().parent / "adjustmentdata-51a7199ac3ba.json"
SHEET_NAME = "시트1"   # worksheet tab name inside the spreadsheet

# --- Filesystem ---
PROJECT_ROOT = Path(__file__).resolve().parent
# All state under user home in an ASCII path so Chromium spawn args don't
# contain non-ASCII characters (Windows cmd-line encoding issue).
STATE_DIR = Path.home() / ".mango_rpa"
DOWNLOADS_DIR = STATE_DIR / "downloads"
LOGS_DIR = STATE_DIR / "logs"
# Persistent profile for the nodriver Chrome instance — Google login cookies
# live here. Mango Car logins reuse the same browser but their cookies are
# explicitly cleared between rows.
PROFILE_DIR = STATE_DIR / "nd-profile"

# --- Spreadsheet column indices (0-based) ---
# New sheet layout (as of 2026-04-20): an extra 미션 column was added at G,
# shifting every column after F right by one vs. the original mapping.
COL = {
    "번호": 0,           # A
    "입고일": 1,          # B
    "셀러명": 2,          # C
    "브랜드": 3,          # D
    "차종": 4,           # E
    "세부차종": 5,        # F
    "미션": 6,           # G  ← NEW column (변속기)
    "연식": 7,           # H
    "인승": 8,           # I
    "유종": 9,           # J
    "A1": 10,           # K — VIN (차대번호) or license plate
    "실주행거리": 11,     # L
    "차량색상": 12,       # M
    "셀러수금가": 13,     # N
    "광고가": 14,        # O — price to upload
    "계정정보": 15,      # P — email\npassword
    # Options 9 columns Q~Y (16..24)
    "선루프": 16,        # Q
    "4WD": 17,           # R
    "가죽시트": 18,       # S
    "열선시트(앞좌석)": 19,  # T
    "통풍시트(앞좌석)": 20,  # U
    "후방카메라": 21,     # V
    "스마트키": 22,       # W
    "네비게이션": 23,     # X
    "에어컨": 24,        # Y
    "특이사항": 25,      # Z
    "검수": 26,          # AA
    "세차": 27,          # AB
    "진행상황": 28,      # AC
    "업로드 일자": 29,    # AD — empty = pending → upload target
    "구글드라이브": 30,   # AE
    "링크": 31,          # AF — filled after upload
    "비포워드 링크": 32,  # AG
    "비고": 33,          # AH
    "출차여부": 34,       # AI
    "판매여부": 35,       # AJ
    "업로드결과": 36,     # AK — 성공시 "업로드 성공", 실패시 상세 사유
}

OPTION_KEYS = [
    "선루프", "4WD", "가죽시트", "열선시트(앞좌석)", "통풍시트(앞좌석)",
    "후방카메라", "스마트키", "네비게이션", "에어컨",
]
ADDON_KEYS = ["검수", "세차"]

# Photo category folder names inside each Drive listing folder, in upload order.
# Each entry is a tuple of accepted folder name variants for that category —
# Drive folders sometimes use a "1. 외부" prefix and sometimes just "외부";
# "하부/차대" can be written with or without spaces around the slash.
PHOTO_CATEGORIES = [
    ("외부",     ["외부", "외관", "1. 외부", "1.외부", "1. 외관", "1.외관"]),
    ("내부",     ["내부", "내관", "2. 내부", "2.내부", "2. 내관", "2.내관"]),
    ("하부/차대", ["하부/차대", "하부 / 차대", "3. 하부 / 차대", "3. 하부/차대", "하부", "차대"]),
    ("엔진룸",   ["엔진룸", "4. 엔진룸", "4.엔진룸"]),
]

# Column letters for write-back after successful upload
COL_LETTER_UPLOAD_DATE = "AD"      # 업로드 일자 (idx 29)
COL_LETTER_LINK = "AF"             # 망고카 링크 (idx 31)
COL_LETTER_BEFORWARD_LINK = "AG"   # 비포워드 링크 (idx 32)
COL_LETTER_UPLOAD_RESULT = "AK"    # 업로드 결과 (idx 36)
COL_LETTER_VIN_ERROR = "AN"        # 차대번호 조회 실패 사유 (idx 39)
