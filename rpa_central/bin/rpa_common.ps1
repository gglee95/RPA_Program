# RPA Central — 공용 헬퍼 함수
#
# 다른 rpa_*.ps1 스크립트가 dot-source 해서 사용:
#   . "$PSScriptRoot\rpa_common.ps1"

$Script:RpaCentralRoot = Join-Path $env:USERPROFILE ".rpa_central"
$Script:RpaJobsDir     = Join-Path $RpaCentralRoot "jobs"
$Script:RpaNotifyLog   = Join-Path $RpaCentralRoot "notifications.log"

# 디렉토리 보장
New-Item -ItemType Directory -Force -Path $RpaJobsDir | Out-Null

function Get-RpaJobs {
    <#
    .SYNOPSIS
        등록된 모든 RPA 작업 JSON 을 객체 리스트로 반환.
    #>
    Get-ChildItem -Path $Script:RpaJobsDir -Filter "*.json" -ErrorAction SilentlyContinue |
        ForEach-Object {
            try {
                $obj = Get-Content $_.FullName -Raw -Encoding utf8 | ConvertFrom-Json
                $obj | Add-Member -NotePropertyName _JobFile -NotePropertyValue $_.FullName -Force
                $obj
            } catch {
                Write-Warning "JSON 파싱 실패: $($_.FullName) — $($_.Exception.Message)"
            }
        }
}

function Get-RpaJob {
    <#
    .SYNOPSIS
        이름으로 단일 RPA 작업 로드.
    #>
    param([Parameter(Mandatory)][string]$Name)
    $path = Join-Path $Script:RpaJobsDir "$Name.json"
    if (-not (Test-Path $path)) { return $null }
    $obj = Get-Content $path -Raw -Encoding utf8 | ConvertFrom-Json
    $obj | Add-Member -NotePropertyName _JobFile -NotePropertyValue $path -Force
    return $obj
}

function Save-RpaJob {
    <#
    .SYNOPSIS
        RPA 작업 JSON 을 저장 (덮어쓰기).
    #>
    param([Parameter(Mandatory)][object]$Job)
    $name = $Job.name
    if (-not $name) { throw "Job 객체에 name 필드가 필요합니다." }
    $jobsDir = Join-Path $env:USERPROFILE ".rpa_central\jobs"
    New-Item -ItemType Directory -Force -Path $jobsDir | Out-Null
    $path = Join-Path $jobsDir "$name.json"
    $clone = $Job | Select-Object -ExcludeProperty _JobFile
    $json = $clone | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($path, $json, [System.Text.UTF8Encoding]::new($false))
}

function Show-RpaToast {
    <#
    .SYNOPSIS
        Windows 시스템 트레이 풍선 알림. 외부 모듈 없이 .NET WinForms 사용.
    .NOTES
        Windows 10 부터는 Action Center 로 들어감. 항상 시스템 트레이 아이콘이
        1개 뜨고, 5초 후 자동 사라짐.
    #>
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet("Info", "Warning", "Error")][string]$Icon = "Info"
    )
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $notify = New-Object System.Windows.Forms.NotifyIcon
    $notify.Icon = switch ($Icon) {
        "Warning" { [System.Drawing.SystemIcons]::Warning }
        "Error"   { [System.Drawing.SystemIcons]::Error }
        default   { [System.Drawing.SystemIcons]::Information }
    }
    $notify.BalloonTipIcon  = [System.Windows.Forms.ToolTipIcon]::$Icon
    $notify.BalloonTipTitle = $Title
    $notify.BalloonTipText  = $Message
    $notify.Visible = $true
    $notify.ShowBalloonTip(5000)
    # 짧게 sleep 후 처분 — 안 그러면 풍선이 안 나옴
    Start-Sleep -Milliseconds 200
}

function Write-RpaNotifyLog {
    <#
    .SYNOPSIS
        알림 로그에 1줄 추가.
    #>
    param(
        [Parameter(Mandatory)][string]$JobName,
        [Parameter(Mandatory)][string]$Status,
        [string]$Detail = ""
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  [$JobName]  $Status  $Detail" |
        Out-File -Append -FilePath $Script:RpaNotifyLog -Encoding utf8
}

function Get-TaskSchedulerInfo {
    <#
    .SYNOPSIS
        Windows Task Scheduler 작업 정보 조회. 없으면 $null.
    #>
    param([Parameter(Mandatory)][string]$TaskName)
    try {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        return [PSCustomObject]@{
            Exists       = $true
            State        = [string]$t.State
            NextRunTime  = $info.NextRunTime
            LastRunTime  = $info.LastRunTime
            LastResult   = $info.LastTaskResult
        }
    } catch {
        return [PSCustomObject]@{ Exists = $false }
    }
}
