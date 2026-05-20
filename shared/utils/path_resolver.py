"""
Google 서비스 계정 인증 파일 경로 해석기.

우선순위:
  1. 환경변수 GOOGLE_SERVICE_ACCOUNT_FILE (절대경로)
  2. shared/credentials/ 아래 정식 위치
  3. Docker 컨테이너 기본 경로 /app/shared/credentials/
  4. CWD (현재 디렉토리) 폴백 — 기존 각 서브디렉토리 동작 유지
"""
import os
from pathlib import Path

_CREDS_FILENAME = "adjustmentdata-51a7199ac3ba.json"
_SHARED_CREDS = Path(__file__).parent.parent / "credentials" / _CREDS_FILENAME
_DOCKER_CREDS = Path("/app/shared/credentials") / _CREDS_FILENAME


def get_credentials_path() -> str:
    """서비스 계정 JSON 파일의 절대경로를 반환한다."""
    env_val = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if env_val and Path(env_val).exists():
        return env_val

    if _SHARED_CREDS.exists():
        return str(_SHARED_CREDS)

    if _DOCKER_CREDS.exists():
        return str(_DOCKER_CREDS)

    # 폴백: 호출자 CWD (기존 각 서브폴더에 credentials 파일이 있는 경우)
    cwd_path = Path.cwd() / _CREDS_FILENAME
    if cwd_path.exists():
        return str(cwd_path)

    raise FileNotFoundError(
        f"서비스 계정 파일을 찾을 수 없습니다. "
        f"GOOGLE_SERVICE_ACCOUNT_FILE 환경변수를 설정하거나 "
        f"{_SHARED_CREDS} 에 파일을 배치해 주세요."
    )


def get_credentials_path_safe(fallback: str = _CREDS_FILENAME) -> str:
    """파일이 없어도 예외를 발생시키지 않는 버전. 기존 동작 유지용."""
    try:
        return get_credentials_path()
    except FileNotFoundError:
        return fallback
