"""
FAILED 상태 행 초기화 스크립트
AI 컬럼의 FAILED 값을 빈 값으로 리셋하여 재업로드 가능하게 합니다.
"""
from google_sheets_manager import GoogleSheetsManager
from config import START_ROW, COMPLETED_COLUMN
import time

def reset_failed_rows():
    sheets = GoogleSheetsManager()
    sheets.setup()

    # AI 컬럼 전체 읽기 (START_ROW부터)
    col_num = sheets._col_to_num(COMPLETED_COLUMN)
    all_values = sheets.worksheet.col_values(col_num)

    reset_count = 0
    for i, val in enumerate(all_values):
        row_num = i + 1
        if row_num < START_ROW:
            continue
        if val and 'FAILED' in val.upper():
            print(f"  Row {row_num}: '{val}' -> '' (리셋)")
            sheets.update_completed_status(row_num, "")
            reset_count += 1
            time.sleep(0.5)  # API rate limit

    print(f"\n[완료] 총 {reset_count}개 행 리셋 완료")

if __name__ == "__main__":
    reset_failed_rows()
