@echo off
REM 망고카 자동 업로드 — 1회 실행 (스케줄러용)
REM 사용: schtasks /create 로 호출되거나, 수동 실행 가능

cd /d "%~dp0"

REM 로그 파일에 실행 시작 기록
echo === %date% %time% : run_once.cmd 시작 === >> "state\logs\scheduler.log" 2>&1

REM Docker Desktop 이 실행 중인지 확인
docker version >nul 2>&1
if errorlevel 1 (
    echo %date% %time% : ERROR Docker not running >> "state\logs\scheduler.log"
    exit /b 1
)

REM 컨테이너 실행 (이전 컨테이너 잔여물 제거 + 종료 후 자동 삭제)
docker compose run --rm uploader >> "state\logs\scheduler.log" 2>&1

echo === %date% %time% : run_once.cmd 종료 (exit=%errorlevel%) === >> "state\logs\scheduler.log"
exit /b %errorlevel%
