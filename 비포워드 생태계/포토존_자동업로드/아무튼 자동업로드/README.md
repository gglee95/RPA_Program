# 망고카 매물 자동 업로드 RPA (브라우저 자동화 전용)

스프레드시트의 미업로드 매물을 망고월드카(mangoworldcar.com)에 셀러 계정별로
자동 등록한다. **구글 API 키 없이** Playwright만으로 동작.

## 아키텍처 한눈에

| 단계 | 방식 |
|---|---|
| 시트 읽기 | 공개 CSV export URL HTTP GET (인증 불필요) |
| 드라이브 사진 다운로드 | Playwright (영구 프로파일) → 폴더 우클릭 다운로드 → ZIP 풀기 |
| 망고카 업로드 | Playwright (행마다 새 컨텍스트) → 로그인/조회/입력/사진/제출 |
| 시트 AC, AE 갱신 | Playwright (영구 프로파일) → 시트 UI 직접 조작 |

영구 프로파일(`./.pw-profile-google/`)은 한 번만 구글 로그인하면 이후 세션이 유지된다. 망고카 셀러 계정은 행마다 다르므로 항상 새 컨텍스트로 분리된다.

## 요구 사항

- Python 3.11+

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

## 첫 실행

```bash
python upload_mangocar.py --row 88 --dry-run
```

처음 실행하면 Chromium 창이 열리고 시트로 이동하는데, 구글 로그인 페이지가 나오면 콘솔에서 안내 메시지를 보고 **창에서 직접 구글 로그인을 완료한 뒤 콘솔에서 Enter** 키를 누르면 다음 단계로 진행된다. 이후 실행부터는 자동으로 시트에 들어간다.

## 실행 옵션

```bash
# 모든 미업로드 행 처리 (실제 업로드)
python upload_mangocar.py --all

# 특정 행만 (시트의 1-based 행 번호)
python upload_mangocar.py --row 88

# 제출 직전까지만 (브라우저로 폼 상태 검수, 시트도 갱신 안 함)
python upload_mangocar.py --row 88 --dry-run

# 헤드리스 (창 숨김) — 첫 구글 로그인은 창이 떠야 하므로 디버깅 끝난 후에만
python upload_mangocar.py --all --headless
```

## 포토존 + 비포워드 연속 업로드

망고카 업로드 후 같은 행을 비포워드에도 올리는 운영용 엔트리:
대상은 AG열(비포워드 링크)에 `비포워드 업로드 요망` 이라고 적힌 행만 처리한다.

```bash
# 특정 행: 포토존/망고카 업로드 → 비포워드 업로드 → 시트 기록
python upload_photozone_beforward.py --row 192

# 여러 행 (현재 작업 대상 예시)
python upload_photozone_beforward.py --rows 189,190

# 전체 pending 행
python upload_photozone_beforward.py --all

# 망고카는 이미 성공했고 AF열 링크와 AG열 요청 문구가 있는 행의 비포워드만 재시도
python upload_photozone_beforward.py --row 192 --beforward-only

# 비포워드 폼 채우기까지만 확인
python upload_photozone_beforward.py --row 192 --beforward-only --dry-run
```

기록 규칙:

- 망고카 성공 시 AF(망고카 링크), AK(망고카 업로드 결과) 기록
- 비포워드 성공 시 AG(비포워드 매물 링크) 기록
- 비포워드 업로드 로그는 AL에 기록

## 디렉토리 구조

```
.
├── upload_mangocar.py         # 메인 엔트리
├── sheet_client.py            # CSV 읽기 + Playwright 시트 쓰기
├── mango_uploader.py          # 망고카 업로드 자동화
├── drive_downloader.py        # 드라이브 폴더 ZIP 다운로드 + 압축 해제
├── config.py                  # 시트 ID, URL, 컬럼 인덱스 상수
├── requirements.txt
├── .pw-profile-google/        # 구글 로그인 세션이 저장되는 영구 프로파일 (gitignore)
├── downloads/                 # 매물별 임시 사진 폴더
└── logs/                      # 실행 로그 (run_YYYYMMDD_HHMMSS.log)
```

## 행 처리 규칙

- **업로드 대상**: AC(업로드 일자) 컬럼이 비어있는 행
- **SKIP** 조건:
  - O열 계정정보가 비어있음
  - J열(차대번호/차량번호)이 형식 불일치 또는 비어있음 (17자 영숫자 VIN 또는 한국 번호판 `123가4567` 외)
  - N열(광고가)이 비어있음
  - VIN이 이미 등록되어 있음 ("이미 등록된 차량입니다" 모달 → 확인 후 스킵)
- **계정 분리**: 매 행마다 새 ephemeral 망고카 컨텍스트 → 셀러 간 세션 누수 없음

## 사진 폴더 규칙

각 매물의 구글 드라이브 폴더 안에 다음 4개 서브폴더가 있어야 함 (없는 카테고리는 0장으로 처리):

```
1. 외부
2. 내부
3. 하부 / 차대
4. 엔진룸
```

폴더 통째로 ZIP 다운로드 → 자동 압축 해제 → 카테고리별로 정렬된 파일명 순으로 망고카에 업로드.

## 첫 실행 절차 (사용자와 함께)

1. `python upload_mangocar.py --row 88 --dry-run`
2. 콘솔 안내에 따라 Chromium 창에서 구글 로그인 (1회)
3. 시트가 보이면 콘솔 Enter → 자동으로 88행 데이터 읽기 → 드라이브 ZIP 다운 → 망고카 로그인 → STEP 01 조회까지 진행
4. STEP 02 화면에서 멈추면 함께 폼을 보면서 변속기/배기량 등 누락 필드 처리와 셀렉터를 확정 → `mango_uploader.py:fill_step02` 보강
5. 같은 행을 dry-run 없이 실행해 실제 등록 → 시트 AC, AE 자동 갱신 확인
6. 검증 완료 후 `--all` 일괄 실행

## 주의 / 한계

- STEP 02 폼의 정확한 셀렉터는 첫 실행 시 사용자와 함께 확정 필요
- 동일 셀러 계정이 연속으로 등장할 때 너무 빠르게 로그인 반복 시 CAPTCHA 가능성 → 매 행 사이 1.5초 버퍼
- 구글 시트가 "링크가 있는 모든 사용자(보기)" 이상으로 공개되어 있어야 CSV 읽기가 동작함
- 영구 프로파일에 구글 세션이 저장되므로 `.pw-profile-google/`는 절대 git에 커밋하지 말 것 (.gitignore 처리됨)
