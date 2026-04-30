"""
Centralized configuration for Encar SOLD OUT Monitoring System.
Defaults preserve the current local behavior, while Docker can override them
through environment variables.
"""
import os
from pathlib import Path


BASE_DIR = Path(__file__).parent


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# Google Sheets Configuration
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1Ovl_UFVXhBehKdqxJYVMF-87sG3jWHO13W4JDZHoVHU")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "[48H AUTO]비포워드")

# SOLD OUT 누적 로그용 별도 스프레드시트
SOLDOUT_LOG_SPREADSHEET_ID = os.getenv(
    "SOLDOUT_LOG_SPREADSHEET_ID",
    "1mHiPQDrYlR7YwTmt0YtYV86BCy1T5SKHwjWsWdVUoxo",
)
SOLDOUT_LOG_WORKSHEET_NAME = os.getenv("SOLDOUT_LOG_WORKSHEET_NAME", "")  # 빈값 = 첫 시트(gid=0)
SERVICE_ACCOUNT_FILE = os.getenv(
    "SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "adjustmentdata-51a7199ac3ba.json"),
)
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Column Mappings
ENCAR_LINK_COLUMN = "R"
SOLDOUT_COLUMN = "U"
CAR_NUMBER_COLUMN = "G"
PRICE_COLUMN = "P"
VIN_COLUMN = "AB"
DRIVE_LINK_COLUMN = "S"
COMPLETED_COLUMN = "AI"
FAIL_REASON_COLUMN = "AN"  # 업로드 실패 사유
PURCHASE_COLUMN = "AH"  # 매입완료 여부
UPLOAD_DATE_COLUMN = "Z"  # 입고 날짜 — 어제까지인 행만 업로드 대상
START_ROW = int(os.getenv("START_ROW", "1407"))

# Monitoring Settings
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "3600"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
PAGE_TIMEOUT_SECONDS = int(os.getenv("PAGE_TIMEOUT_SECONDS", "10"))
ERROR_RETRY_DELAY_SECONDS = int(os.getenv("ERROR_RETRY_DELAY_SECONDS", "60"))

# ByForward Configuration
BEFORWARD_LOGIN_URL = os.getenv(
    "BEFORWARD_LOGIN_URL",
    "https://external-vendor.beforward.jp/tempVehDetails/edit",
)
BEFORWARD_USERNAME = os.getenv("BEFORWARD_USERNAME", "echam@mangoworldcar.com")
BEFORWARD_PASSWORD = os.getenv("BEFORWARD_PASSWORD", "VJSXaPQR")

# Runtime Behavior
ENCAR_HEADLESS = _get_bool_env("ENCAR_HEADLESS", True)
BEFORWARD_HEADLESS = _get_bool_env("BEFORWARD_HEADLESS", False)
BEFORWARD_BROWSER = os.getenv("BEFORWARD_BROWSER", "chrome")  # 'chrome' or 'firefox'
UPLOAD_HOUR = int(os.getenv("UPLOAD_HOUR", "16"))

# Logging Configuration
LOG_DIR = BASE_DIR / "soldout_logs"
LOG_DIR.mkdir(exist_ok=True)

# SOLD OUT detection / redirect patterns
SOLDOUT_KEYWORDS = []
REDIRECT_ERROR_PATTERNS = []
