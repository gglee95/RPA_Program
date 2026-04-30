@echo off
cd /d "%~dp0"

echo [시작] 업로드 워커 실행...
start "비포워드 업로드" cmd /k ".venv\Scripts\python.exe beforward_upload_worker.py"

timeout /t 3 /nobreak >nul

echo [시작] 모니터링 워커 실행...
start "비포워드 모니터링" cmd /k ".venv\Scripts\python.exe beforward_monitor_worker.py"

echo [완료] 두 워커가 별도 창에서 실행 중입니다