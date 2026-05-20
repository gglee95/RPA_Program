@echo off
REM RPA Central — 현황 대시보드 (더블클릭용 진입점)
REM 바탕화면/시작메뉴에 이 파일의 바로가기를 만들어두면 편함.

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "bin\rpa_status.ps1"
