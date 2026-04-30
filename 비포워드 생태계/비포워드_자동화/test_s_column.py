"""S열 값 디버깅 - display value vs formula value 확인"""
import gspread
from google.oauth2.service_account import Credentials
from config import (
    SPREADSHEET_ID, WORKSHEET_NAME, SERVICE_ACCOUNT_FILE,
    SCOPES, DRIVE_LINK_COLUMN, START_ROW
)

creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
ws = gc.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)

# 테스트 행 (START_ROW 부터 3행)
for row in range(START_ROW, START_ROW + 3):
    cell = f"{DRIVE_LINK_COLUMN}{row}"

    # 1) display value (row_values 와 동일)
    display = ws.acell(cell).value
    print(f"Row {row} | display = '{display}'")

    # 2) formula value
    formula = ws.acell(cell, value_render_option='FORMULA').value
    print(f"Row {row} | formula = '{formula}'")

    # 3) unformatted value
    unformat = ws.acell(cell, value_render_option='UNFORMATTED_VALUE').value
    print(f"Row {row} | unformat = '{unformat}'")

    # 4) row_values 로 읽은 값
    row_vals = ws.row_values(row)
    s_idx = ord('S') - ord('A')  # 18
    s_val = row_vals[s_idx] if s_idx < len(row_vals) else '(범위초과)'
    print(f"Row {row} | row_values[{s_idx}] = '{s_val}'")
    print()
