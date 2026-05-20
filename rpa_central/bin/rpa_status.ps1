# RPA 작업 현황 대시보드
#
# 사용: 더블클릭 (rpa.cmd 통해서) 또는
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File rpa_status.ps1

. "$PSScriptRoot\rpa_common.ps1"

# UTF-8 출력 강제 — 콘솔에서 한글 깨짐 방지
$OutputEncoding = [System.Text.Encoding]::UTF8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$jobs = @(Get-RpaJobs)

Write-Host ""
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " RPA Central — 등록된 작업 현황" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "등록 작업: $($jobs.Count) 개"
Write-Host "현재 시각: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

if ($jobs.Count -eq 0) {
    Write-Host "  (등록된 작업 없음)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "새 작업 등록: rpa_register.ps1 -Name ... -ProjectDir ..." -ForegroundColor DarkGray
    return
}

foreach ($job in $jobs) {
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "■ $($job.display_name)" -ForegroundColor White
    Write-Host "  이름        : $($job.name)"
    if ($job.description) {
        Write-Host "  설명        : $($job.description)"
    }
    Write-Host "  프로젝트    : $($job.project_dir)"

    # Task Scheduler 정보
    if ($job.task_scheduler_name) {
        $sched = Get-TaskSchedulerInfo -TaskName $job.task_scheduler_name
        if ($sched.Exists) {
            Write-Host "  스케줄      : $($job.schedule_human) (Task: $($job.task_scheduler_name))"
            Write-Host "  스케줄상태  : $($sched.State)"
            Write-Host "  다음실행    : $($sched.NextRunTime)"
            Write-Host "  마지막실행  : $($sched.LastRunTime)  (exit=$($sched.LastResult))"
        } else {
            Write-Host "  스케줄      : ⚠️  등록 안됨 (Task: $($job.task_scheduler_name))" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  스케줄      : (수동 실행만)"
    }

    # 작업 JSON 의 마지막 실행 결과
    if ($job.last_run) {
        $resultStr = if ($job.last_result) {
            "$($job.last_result.status) — $($job.last_result.detail)"
        } else { "(unknown)" }
        Write-Host "  마지막결과  : $($job.last_run)  $resultStr"
    }

    # 최근 로그 파일 (있으면 마지막 3개)
    if ($job.log_dir -and (Test-Path $job.log_dir)) {
        $recentLogs = Get-ChildItem -Path $job.log_dir -Filter "*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 3
        if ($recentLogs) {
            Write-Host "  최근로그    :"
            foreach ($lg in $recentLogs) {
                $sizeKb = [math]::Round($lg.Length / 1024, 1)
                $ts = $lg.LastWriteTime.ToString("yyyy-MM-dd HH:mm")
                $sizeStr = [string]$sizeKb + " KB"
                Write-Host ("                " + $ts + "  " + $lg.Name + "  (" + $sizeStr + ")")
            }
        }
    }
    Write-Host ""
}

# 실행 중인 RPA 프로세스 감지
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[ 현재 실행 중인 Python / Chrome 프로세스 ]" -ForegroundColor Cyan
$procs = Get-Process | Where-Object { $_.Name -like "python*" -or $_.Name -like "chrome*" }
if ($procs) {
    $py = ($procs | Where-Object { $_.Name -like "python*" }).Count
    $ch = ($procs | Where-Object { $_.Name -like "chrome*" }).Count
    Write-Host "  Python : $py 개"
    Write-Host "  Chrome : $ch 개"
} else {
    Write-Host "  (없음)"
}
Write-Host ""

# 최근 알림 10건
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[ 최근 알림 10건 ]" -ForegroundColor Cyan
if (Test-Path $Script:RpaNotifyLog) {
    Get-Content -Path $Script:RpaNotifyLog -Tail 10 -Encoding utf8 | ForEach-Object {
        Write-Host "  $_"
    }
} else {
    Write-Host "  (알림 기록 없음)"
}
Write-Host ""

# 명령 치트시트
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "[ 자주 쓰는 명령 ]" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask MangoUploadDaily          # 스케줄 확인"
Write-Host "  Start-ScheduledTask MangoUploadDaily        # 즉시 실행"
Write-Host "  Unregister-ScheduledTask MangoUploadDaily   # 삭제"
Write-Host "  rpa_central\bin\rpa_register.ps1 -Name ...  # 새 작업 등록"
Write-Host ""

# 콘솔이 닫히지 않게 대기 — 더블클릭으로 실행됐을 때 결과 볼 수 있도록
if ($Host.Name -eq "ConsoleHost" -and -not $env:RPA_NO_PAUSE) {
    Write-Host ""
    Write-Host "아무 키나 누르면 닫힙니다..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
