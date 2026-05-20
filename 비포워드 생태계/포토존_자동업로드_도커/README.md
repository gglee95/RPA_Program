# 망고카 자동 업로드 — Docker 버전

호스트 버전과 동일한 기능을 Docker 컨테이너에서 실행할 수 있도록 패키징한 버전.

## 디렉토리 구조

```
포토존_자동업로드_도커/
├── Dockerfile              # Python 3.12 + Chromium + 한글 폰트
├── docker-compose.yml      # 실행 정의 (볼륨/환경변수)
├── .dockerignore
├── app/                    # 컨테이너에 복사되는 애플리케이션 코드
│   ├── config.py           # 호스트 버전과 차이: 경로를 env 기반으로
│   ├── upload_mangocar.py
│   ├── mango_uploader.py
│   ├── drive_downloader.py
│   ├── sheet_client.py
│   ├── google_session.py
│   ├── beforward_bridge.py
│   └── requirements.txt
├── secrets/                # 호스트 전용 (.gitignore 처리)
│   └── service_account.json   ← 본인이 직접 배치
└── state/                  # 호스트 전용. 영속화 디렉토리
    ├── nd-profile/         # 구글 로그인된 Chrome 프로필
    ├── downloads/
    └── logs/
```

## 사전 준비

### 1. 서비스 계정 JSON 배치

호스트 버전에서 쓰는 `adjustmentdata-51a7199ac3ba.json` 파일을 복사해서 다음 위치에 배치:

```
포토존_자동업로드_도커/secrets/service_account.json
```

### 2. Google 로그인된 Chrome 프로필 부트스트랩 (중요)

컨테이너 안의 Chromium은 GUI 없이 헤드리스로만 동작합니다. Google 첫 로그인은 컨테이너에서 직접 못 하므로, **호스트의 이미 로그인된 nd-profile 을 복사**해서 마운트합니다.

```powershell
# 호스트 nd-profile 을 docker 상태 디렉토리로 복사
Copy-Item -Recurse `
    "$env:USERPROFILE\.mango_rpa\nd-profile" `
    "C:\Users\gglee\Desktop\RPA_Program\비포워드 생태계\포토존_자동업로드_도커\state\nd-profile"
```

복사 직후 `state/nd-profile/SingletonLock` 같은 잠금 파일이 있으면 삭제하세요 (Chrome 잠금 잔여물).

### 3. Docker Desktop 실행

Windows에서는 Docker Desktop 이 실행 중이어야 합니다.

## 빌드

```bash
cd "포토존_자동업로드_도커"
docker compose build
```

빌드 시 chromium + 한글 폰트 설치로 5~10분 정도 걸릴 수 있습니다.

## 실행

### 전체 pending 행 처리

```bash
docker compose run --rm uploader
```

### 특정 행 처리

```bash
docker compose run --rm uploader python upload_mangocar.py --row 148
```

### 범위 처리

```bash
docker compose run --rm uploader python upload_mangocar.py --rows 180-200
```

### Dry run (제출 직전까지만)

```bash
docker compose run --rm uploader python upload_mangocar.py --row 148 --dry-run
```

## 로그

호스트에서 직접 확인 가능:

```
state/logs/run_YYYYMMDD_HHMMSS.log
```

## 호스트 버전과의 차이점

| 항목 | 호스트 | Docker |
|------|--------|--------|
| Chrome 경로 | `C:\Program Files\Google\Chrome\Application\chrome.exe` | `/usr/bin/chromium` (env `CHROME_BIN`) |
| 상태 디렉토리 | `%USERPROFILE%\.mango_rpa\` | `/state` (env `MANGO_STATE_DIR`) → 호스트의 `./state` |
| 서비스 계정 JSON | `app/adjustmentdata-51a7199ac3ba.json` | `/secrets/service_account.json` (env `SERVICE_ACCOUNT_JSON`) |
| Headless | 옵션 (`--headless`) | 강제 켜짐 |
| no_sandbox | 미지정 | 강제 켜짐 (Chromium-in-Docker 필수) |
| 타임존 | 시스템 | `TZ=Asia/Seoul` (Dockerfile) |
| 인코딩 | Windows cp949 fallback | `C.UTF-8` |

## 알려진 제약 / 주의사항

1. **첫 Google 로그인은 호스트에서 만들어야 함** — 위의 "프로필 부트스트랩" 단계 필수.
2. **헤드리스 탐지 가능성** — 망고카가 헤드리스 브라우저 탐지하면 차단될 가능성. 호스트 버전과 동작 비교 필요.
3. **Chromium 버전이 호스트 Chrome 과 다름** — 셀렉터/CSS 동작이 미세하게 다를 수 있음. 첫 실행 시 검증 필요.
4. **시트의 Drive 폴더 권한** — 컨테이너의 Chrome 도 호스트와 같은 Google 계정으로 로그인되어 있어야 Drive 접근 가능.
