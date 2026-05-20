"""
비포워드 업로드 설정 (독립 실행용)
환경변수로 재정의 가능
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

SERVICE_ACCOUNT_FILE = os.getenv(
    "SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "adjustmentdata-51a7199ac3ba.json"),
)

BEFORWARD_LOGIN_URL = os.getenv(
    "BEFORWARD_LOGIN_URL",
    "https://external-vendor.beforward.jp/tempVehDetails/edit",
)
BEFORWARD_USERNAME = os.getenv("BEFORWARD_USERNAME", "joonsookang@mangoworldcar.com")
BEFORWARD_PASSWORD = os.getenv("BEFORWARD_PASSWORD", "k4ycwYk6")

BEFORWARD_HEADLESS = os.getenv("BEFORWARD_HEADLESS", "false").lower() in {"1", "true", "yes"}

# 재원표 경로
DOMESTIC_SPEC_FILE = str(BASE_DIR / "국산차 재원표.xlsx")
IMPORT_SPEC_FILE   = str(BASE_DIR / "수입차 재원표.xlsx")
