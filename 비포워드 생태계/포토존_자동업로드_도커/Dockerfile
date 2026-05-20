# 망고카 자동 업로드 컨테이너 이미지
# Python 3.12 + Chromium + 한글 폰트 + KST 타임존.

FROM python:3.12-slim

# ── 시스템 의존성: Chromium, 한글 폰트, 로케일 ─────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        tzdata \
        ca-certificates \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── 타임존 / 인코딩 ─────────────────────────────────────────────────
ENV TZ=Asia/Seoul \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── nodriver / chromium 설정 ────────────────────────────────────────
# nodriver는 시스템 chromium 을 자동 탐지하지만, 명시적으로 지정하면 안정적.
ENV CHROME_BIN=/usr/bin/chromium

# 상태 디렉토리 (볼륨 마운트 지점)
ENV MANGO_STATE_DIR=/state
RUN mkdir -p /state /secrets

WORKDIR /app

# ── Python deps ─────────────────────────────────────────────────────
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── 애플리케이션 코드 ───────────────────────────────────────────────
COPY app/ ./

# 기본 명령: --all 모드로 전체 pending 행 처리
# docker run / compose 에서 command 로 오버라이드 가능 (예: --row 148)
CMD ["python", "upload_mangocar.py", "--all"]
