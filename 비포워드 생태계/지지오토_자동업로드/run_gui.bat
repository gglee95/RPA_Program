@echo off
cd /d "%~dp0"
echo [1/2] Installing packages...
pip install -q -r requirements.txt
echo [2/2] Starting program...
python mango_upload_gui.py
pause
