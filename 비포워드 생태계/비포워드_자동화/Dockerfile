FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BINARY=/usr/bin/chromium \
    FIREFOX_BINARY=/usr/bin/firefox-esr \
    ENCAR_HEADLESS=true \
    BEFORWARD_HEADLESS=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    firefox-esr \
    fonts-noto-cjk \
    ca-certificates \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/soldout_logs

CMD ["python", "beforward_monitor_worker.py"]
