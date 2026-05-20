# RPA 알림 헬퍼 — 각 RPA 작업이 자기 상태를 알릴 때 호출
#
# 사용:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File rpa_notify.ps1 `
#       -JobName "mango_uploader" -Status "start"
#
#   ... -Status "success" -Detail "성공 5, SKIP 800, FAIL 3"
#   ... -Status "fail"    -Detail "RuntimeError: ..."
#
# 동작:
#   1. 시스템 트레이 풍선 알림 표시
#   2. ~/.rpa_central/notifications.log 에 기록
#   3. 작업 JSON 의 last_run / last_result 업데이트 (status 가 success/fail 일 때)

param(
    [Parameter(Mandatory)][string]$JobName,
    [Parameter(Mandatory)][ValidateSet("start", "success", "fail")][string]$Status,
    [string]$Detail = ""
)

. "$PSScriptRoot\rpa_common.ps1"

$icon, $title, $message = switch ($Status) {
    "start"   { "Info",    "RPA 시작",       "[$JobName] 실행 시작" }
    "success" { "Info",    "RPA 완료",       "[$JobName] $Detail" }
    "fail"    { "Error",   "RPA 실패",       "[$JobName] $Detail" }
}

Show-RpaToast -Title $title -Message $message -Icon $icon
Write-RpaNotifyLog -JobName $JobName -Status $Status -Detail $Detail

# 작업 JSON 의 last_run/last_result 업데이트
if ($Status -in @("success", "fail")) {
    $job = Get-RpaJob -Name $JobName
    if ($job) {
        $job | Add-Member -NotePropertyName last_run -NotePropertyValue (Get-Date -Format "yyyy-MM-ddTHH:mm:ss") -Force
        $job | Add-Member -NotePropertyName last_result -NotePropertyValue ([PSCustomObject]@{
            status = $Status
            detail = $Detail
        }) -Force
        Save-RpaJob -Job $job
    }
}
