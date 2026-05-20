# RPA 작업 등록 헬퍼
#
# 사용 1) JSON 파일로 등록:
#   .\rpa_register.ps1 -JobFile "C:\...\mango_uploader.job.json"
#
# 사용 2) 인라인 파라미터로 등록:
#   .\rpa_register.ps1 -Name "mango_uploader" `
#                      -DisplayName "망고카 자동 업로드" `
#                      -ProjectDir "C:\...\포토존_자동업로드" `
#                      -LogDir     "C:\Users\gglee\.mango_rpa\logs" `
#                      -TaskName   "MangoUploadDaily"
#
# 등록 후 ~/.rpa_central/jobs/<name>.json 에 저장됨.

[CmdletBinding(DefaultParameterSetName = "Inline")]
param(
    [Parameter(ParameterSetName = "FromFile", Mandatory)][string]$JobFile,
    [Parameter(ParameterSetName = "Inline",   Mandatory)][string]$Name,
    [Parameter(ParameterSetName = "Inline")][string]$DisplayName = $Name,
    [Parameter(ParameterSetName = "Inline")][string]$Description = "",
    [Parameter(ParameterSetName = "Inline", Mandatory)][string]$ProjectDir,
    [Parameter(ParameterSetName = "Inline")][string]$LogDir = "",
    [Parameter(ParameterSetName = "Inline")][string]$TaskName = "",
    [Parameter(ParameterSetName = "Inline")][string]$ScheduleHuman = ""
)

. "$PSScriptRoot\rpa_common.ps1"

if ($PSCmdlet.ParameterSetName -eq "FromFile") {
    if (-not (Test-Path $JobFile)) { throw "JobFile 없음: $JobFile" }
    $job = Get-Content $JobFile -Raw -Encoding utf8 | ConvertFrom-Json
} else {
    $job = [PSCustomObject]@{
        name                  = $Name
        display_name          = $DisplayName
        description           = $Description
        project_dir           = $ProjectDir
        log_dir               = $LogDir
        task_scheduler_name   = $TaskName
        schedule_human        = $ScheduleHuman
        registered_at         = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    }
}

Save-RpaJob -Job $job
Write-Host "등록됨: $($job.name) -> $((Get-RpaJob -Name $job.name)._JobFile)"
