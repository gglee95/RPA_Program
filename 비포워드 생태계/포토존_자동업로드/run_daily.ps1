# 망고카 자동 업로드 — 매일 1회 실행 (Windows Task Scheduler용)
#
# 사용:
#   직접 실행: powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_daily.ps1
#   스케줄러: schtasks 또는 Register-ScheduledTask 가 이 파일을 호출
#
# 동작:
#   1. 프로젝트의 venv Python 으로 upload_mangocar.py --all --headless 실행
#   2. 실행 시작/종료 시각을 state\logs\scheduler.log 에 기록
#   3. 본 스크립트는 stdout/stderr 를 그대로 흘려보냄 (로깅은 파이썬이 직접 함)

$ErrorActionPreference = "Continue"

$ProjectDir   = "C:\Users\gglee\Desktop\RPA_Program\비포워드 생태계\포토존_자동업로드"
$Python       = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$Script       = Join-Path $ProjectDir "아무튼 자동업로드\upload_mangocar.py"
$LogDir       = Join-Path $env:USERPROFILE ".mango_rpa\logs"
$SchedLog     = Join-Path $LogDir "scheduler.log"
$NotifyScript = "C:\Users\gglee\Desktop\RPA_Program\rpa_central\bin\rpa_notify.ps1"
$JobName      = "mango_uploader"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') : run_daily.ps1 시작 ===" |
    Out-File -Append -FilePath $SchedLog -Encoding utf8

# RPA Central 에 시작 알림
if (Test-Path $NotifyScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NotifyScript `
        -JobName $JobName -Status "start" | Out-Null
}

# Python venv 가 없으면 즉시 에러 기록 후 종료
if (-not (Test-Path $Python)) {
    "ERROR: Python venv not found at $Python" |
        Out-File -Append -FilePath $SchedLog -Encoding utf8
    if (Test-Path $NotifyScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NotifyScript `
            -JobName $JobName -Status "fail" -Detail "Python venv 없음: $Python" | Out-Null
    }
    exit 1
}

# 업로드 실행 — stdout/stderr 는 파이썬이 자체 로그 파일에 기록
# 헤드리스 모드는 망고카 로그인이 안 되는 문제가 있어 현재 비활성화.
# (재활성화 시 마지막에 --headless 플래그 추가)
& $Python $Script --all
$exitCode = $LASTEXITCODE

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') : run_daily.ps1 종료 (exit=$exitCode) ===" |
    Out-File -Append -FilePath $SchedLog -Encoding utf8

# 최근 로그 파일에서 결과 요약 추출 (SUCCESS/SKIP/FAIL 카운트)
$summary = "exit=$exitCode"
$latestLog = Get-ChildItem -Path $LogDir -Filter "run_*.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latestLog) {
    $content = Get-Content $latestLog.FullName -Encoding utf8
    $success = ($content | Select-String "^\d{4}-\d{2}-\d{2}.+행\s+\d+\s+SUCCESS").Count
    $skip    = ($content | Select-String "^\d{4}-\d{2}-\d{2}.+행\s+\d+\s+SKIP").Count
    $fail    = ($content | Select-String "^\d{4}-\d{2}-\d{2}.+행\s+\d+\s+FAIL").Count
    $summary = "성공 $success, SKIP $skip, FAIL $fail"
}

# RPA Central 에 종료 알림
if (Test-Path $NotifyScript) {
    $status = if ($exitCode -eq 0) { "success" } else { "fail" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $NotifyScript `
        -JobName $JobName -Status $status -Detail $summary | Out-Null
}

exit $exitCode
