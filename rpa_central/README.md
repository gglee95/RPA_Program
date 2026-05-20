# RPA Central — 통합 관리 프레임워크

여러 RPA 프로그램의 등록 / 현황 확인 / 알림을 한 곳에서 관리.

## 구조

```
RPA_Program/rpa_central/        ← 코드 (이 폴더)
├── rpa.cmd                     ← 더블클릭 진입점 (현황 대시보드)
├── bin/
│   ├── rpa_common.ps1          ← 공용 함수
│   ├── rpa_status.ps1          ← 현황 대시보드
│   ├── rpa_notify.ps1          ← 알림 (트레이 풍선 + 로그)
│   └── rpa_register.ps1        ← 작업 등록

~/.rpa_central/                 ← 상태 데이터 (자동 생성)
├── jobs/
│   └── <job_name>.json         ← 등록된 작업 정보
└── notifications.log           ← 알림 기록
```

## 작업 JSON 스키마

```json
{
  "name": "mango_uploader",
  "display_name": "망고카 자동 업로드",
  "description": "...",
  "project_dir": "C:\\...\\포토존_자동업로드",
  "log_dir": "C:\\Users\\gglee\\.mango_rpa\\logs",
  "task_scheduler_name": "MangoUploadDaily",
  "schedule_human": "매일 10:30",
  "registered_at": "2026-05-19T14:30:00",
  "last_run": "2026-05-19T14:21:05",
  "last_result": { "status": "success", "detail": "성공 5, SKIP 800, FAIL 3" }
}
```

## 사용법

### 현황 대시보드 보기

가장 자주 쓰는 동작. `rpa.cmd` 더블클릭 → 콘솔에 모든 작업 상태 표시.

또는:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bin\rpa_status.ps1
```

표시 내용:
- 등록된 작업 목록 (이름, 프로젝트, 스케줄, 다음/마지막 실행)
- 작업별 마지막 결과
- 작업별 최근 로그 파일 3개
- 현재 실행 중 Python/Chrome 프로세스 수
- 최근 알림 10건
- 자주 쓰는 명령 치트시트

### 새 작업 등록

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File bin\rpa_register.ps1 `
    -Name "my_program" `
    -DisplayName "내 프로그램" `
    -Description "이러이러한 일 함" `
    -ProjectDir "C:\Users\gglee\Desktop\RPA_Program\my_program" `
    -LogDir "C:\Users\gglee\.my_program\logs" `
    -TaskName "MyProgramDaily" `
    -ScheduleHuman "매일 09:00"
```

### RPA 프로그램이 자기 상태를 알림

각 RPA 프로그램이 시작/종료 시 호출:

```powershell
# 시작 시
powershell -NoProfile -ExecutionPolicy Bypass -File bin\rpa_notify.ps1 `
    -JobName "mango_uploader" -Status start

# 성공 종료 시
powershell -NoProfile -ExecutionPolicy Bypass -File bin\rpa_notify.ps1 `
    -JobName "mango_uploader" -Status success -Detail "성공 5, SKIP 800"

# 실패 시
powershell -NoProfile -ExecutionPolicy Bypass -File bin\rpa_notify.ps1 `
    -JobName "mango_uploader" -Status fail -Detail "에러 메시지"
```

호출 시:
1. 시스템 트레이 풍선 알림 표시
2. `~/.rpa_central/notifications.log` 에 기록
3. (success/fail 한해서) 작업 JSON 의 `last_run`/`last_result` 업데이트

## 새 RPA 프로그램 추가 절차 (참고)

1. RPA 프로그램 코드 작성
2. Windows Task Scheduler 에 작업 등록 (선택)
3. `rpa_register.ps1` 로 RPA Central 에 등록
4. RPA 스크립트 시작/종료 시 `rpa_notify.ps1` 호출 추가
5. `rpa.cmd` 더블클릭해서 등록되었는지 확인

## 바탕화면 바로가기 만들기 (수동)

1. `rpa.cmd` 우클릭 → "바로가기 만들기"
2. 바로가기를 바탕화면으로 이동
3. 이름 변경: "RPA 현황"
4. 우클릭 → 속성 → 아이콘 변경 (선택)
