@echo off
REM RPA Central GUI 런처 — pythonw.exe 로 띄워서 콘솔 창 없이 GUI만 표시

REM 시스템 Python 우선 사용 (tkinter 빌트인)
set PYW=C:\Users\gglee\AppData\Local\Programs\Python\Python312\pythonw.exe

if not exist "%PYW%" (
    REM 폴백: 시스템 PATH 의 pythonw
    set PYW=pythonw.exe
)

start "" "%PYW%" "%~dp0gui\rpa_gui.py"
