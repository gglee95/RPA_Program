# RPA Central — 통합 CLI 디스패처
#
# 사용:
#   rpa                       대시보드 (등록된 모든 작업 현황)
#   rpa list                  작업 한 줄 요약 목록
#   rpa run <name>            즉시 실행 (Windows Task Scheduler 통해)
#   rpa stop <name>           실행 중인 작업 중단
#   rpa logs <name>           최근 로그 파일 마지막 80줄
#   rpa enable <name>         스케줄 활성화
#   rpa disable <name>        스케줄 비활성화
#   rpa add                   새 작업 등록 (대화형 마법사)
#   rpa remove <name>         등록 해제 (Task Scheduler 항목도 같이 삭제)
#   rpa help                  도움말
#
# 한 단어 명령으로 모든 작업 가능.

param(
    [string]$Command = "status",
    [string]$Target  = ""
)

. "$PSScriptRoot\rpa_common.ps1"

$OutputEncoding = [System.Text.Encoding]::UTF8
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Show-Help {
    Write-Host ""
    Write-Host "RPA Central — 통합 자동화 관리 CLI" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  rpa                       대시보드 (등록된 모든 작업)"
    Write-Host "  rpa list                  작업 한 줄 요약 목록"
    Write-Host "  rpa run <name>            즉시 실행"
    Write-Host "  rpa stop <name>           실행 중단"
    Write-Host "  rpa logs <name>           최근 로그 80줄"
    Write-Host "  rpa enable <name>         스케줄 켜기"
    Write-Host "  rpa disable <name>        스케줄 끄기"
    Write-Host "  rpa add                   새 작업 등록 (마법사)"
    Write-Host "  rpa remove <name>         등록 해제"
    Write-Host "  rpa help                  이 도움말"
    Write-Host ""
}

function Need-Target($cmd) {
    if (-not $Target) {
        Write-Host "사용법: rpa $cmd <name>" -ForegroundColor Red
        Write-Host "등록된 작업:" -ForegroundColor Yellow
        Get-RpaJobs | ForEach-Object { Write-Host "  - $($_.name)" }
        exit 1
    }
    $job = Get-RpaJob -Name $Target
    if (-not $job) {
        Write-Host "작업 없음: $Target" -ForegroundColor Red
        exit 1
    }
    return $job
}

switch ($Command.ToLower()) {

    "status" {
        $env:RPA_NO_PAUSE = "1"
        & "$PSScriptRoot\rpa_status.ps1"
    }

    "list" {
        $jobs = @(Get-RpaJobs)
        if ($jobs.Count -eq 0) {
            Write-Host "(등록된 작업 없음)"
            return
        }
        Write-Host ""
        Write-Host ("{0,-20} {1,-25} {2,-20} {3}" -f "NAME", "DISPLAY", "SCHEDULE", "LAST") -ForegroundColor Cyan
        Write-Host ("─" * 90) -ForegroundColor DarkGray
        foreach ($j in $jobs) {
            $last = if ($j.last_result) { "$($j.last_result.status)" } else { "-" }
            Write-Host ("{0,-20} {1,-25} {2,-20} {3}" -f $j.name, $j.display_name, $j.schedule_human, $last)
        }
        Write-Host ""
    }

    "run" {
        $job = Need-Target "run"
        if ($job.task_scheduler_name) {
            Start-ScheduledTask -TaskName $job.task_scheduler_name
            Write-Host "실행 시작: $($job.task_scheduler_name)" -ForegroundColor Green
        } else {
            Write-Host "이 작업은 Task Scheduler 등록이 없습니다. 수동 실행 명령을 사용하세요." -ForegroundColor Yellow
        }
    }

    "stop" {
        $job = Need-Target "stop"
        if ($job.task_scheduler_name) {
            Stop-ScheduledTask -TaskName $job.task_scheduler_name -ErrorAction SilentlyContinue
            Write-Host "중단 요청: $($job.task_scheduler_name)" -ForegroundColor Green
        }
        # 추가로 실행 중인 Python/Chrome 도 종료할지 묻기
        $running = Get-Process | Where-Object { $_.Name -like "python*" -or $_.Name -like "chrome*" }
        if ($running) {
            Write-Host ""
            Write-Host "현재 실행 중인 프로세스: Python $((($running | Where-Object {$_.Name -like 'python*'}).Count)) 개 / Chrome $((($running | Where-Object {$_.Name -like 'chrome*'}).Count)) 개" -ForegroundColor Yellow
            $ans = Read-Host "이 프로세스들도 모두 종료할까요? (y/N)"
            if ($ans -eq "y" -or $ans -eq "Y") {
                $running | Stop-Process -Force -Confirm:$false
                Write-Host "프로세스 정리 완료" -ForegroundColor Green
            }
        }
    }

    "logs" {
        $job = Need-Target "logs"
        if (-not $job.log_dir -or -not (Test-Path $job.log_dir)) {
            Write-Host "로그 디렉토리 없음: $($job.log_dir)" -ForegroundColor Red
            exit 1
        }
        $latest = Get-ChildItem -Path $job.log_dir -Filter "*.log" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $latest) {
            Write-Host "로그 파일 없음" -ForegroundColor Yellow
            exit 0
        }
        Write-Host "📄 $($latest.FullName)" -ForegroundColor Cyan
        Write-Host "  마지막 80줄:" -ForegroundColor DarkGray
        Write-Host ""
        Get-Content -Path $latest.FullName -Tail 80 -Encoding utf8
    }

    "enable" {
        $job = Need-Target "enable"
        if ($job.task_scheduler_name) {
            Enable-ScheduledTask -TaskName $job.task_scheduler_name | Out-Null
            Write-Host "스케줄 켜짐: $($job.task_scheduler_name)" -ForegroundColor Green
        }
    }

    "disable" {
        $job = Need-Target "disable"
        if ($job.task_scheduler_name) {
            Disable-ScheduledTask -TaskName $job.task_scheduler_name | Out-Null
            Write-Host "스케줄 꺼짐: $($job.task_scheduler_name)" -ForegroundColor Yellow
        }
    }

    "add" {
        Write-Host ""
        Write-Host "새 RPA 작업 등록 마법사" -ForegroundColor Cyan
        Write-Host ""
        $name        = Read-Host "내부 이름 (영문/숫자/_, 예: my_uploader)"
        if (-not $name) { Write-Host "취소"; exit 0 }
        $display     = Read-Host "표시 이름 (예: 내 업로드 프로그램)"
        $description = Read-Host "설명 (선택, Enter로 건너뜀)"
        $projectDir  = Read-Host "프로젝트 디렉토리 절대경로"
        $logDir      = Read-Host "로그 디렉토리 절대경로 (선택)"
        $taskName    = Read-Host "Windows Task Scheduler 작업명 (선택, 미입력 시 수동 실행만)"
        $schedHuman  = Read-Host "스케줄 표시 문구 (예: '매일 10:30')"

        & "$PSScriptRoot\rpa_register.ps1" `
            -Name $name -DisplayName $display -Description $description `
            -ProjectDir $projectDir -LogDir $logDir `
            -TaskName $taskName -ScheduleHuman $schedHuman
        Write-Host ""
        Write-Host "등록 완료. 확인: rpa list" -ForegroundColor Green
    }

    "remove" {
        $job = Need-Target "remove"
        $ans = Read-Host "정말 '$($job.name)' 을 등록 해제할까요? (Task Scheduler 항목도 같이 삭제됨) [y/N]"
        if ($ans -ne "y" -and $ans -ne "Y") { Write-Host "취소"; return }
        if ($job.task_scheduler_name) {
            try {
                Unregister-ScheduledTask -TaskName $job.task_scheduler_name -Confirm:$false -ErrorAction Stop
                Write-Host "Task Scheduler 항목 삭제: $($job.task_scheduler_name)" -ForegroundColor Green
            } catch {
                Write-Host "Task Scheduler 삭제 실패: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        Remove-Item $job._JobFile -Force
        Write-Host "등록 해제 완료: $($job.name)" -ForegroundColor Green
    }

    "help"   { Show-Help }
    "-h"     { Show-Help }
    "--help" { Show-Help }
    "/?"     { Show-Help }

    default {
        Write-Host "알 수 없는 명령: $Command" -ForegroundColor Red
        Show-Help
        exit 1
    }
}
