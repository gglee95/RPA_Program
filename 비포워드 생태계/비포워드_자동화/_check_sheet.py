from google_sheets_manager import GoogleSheetsManager
from config import START_ROW, ENCAR_LINK_COLUMN, SOLDOUT_COLUMN, COMPLETED_COLUMN

sheets = GoogleSheetsManager()
sheets.setup()

encar_urls = sheets.worksheet.col_values(sheets._col_to_num(ENCAR_LINK_COLUMN))
soldout_values = sheets.worksheet.col_values(sheets._col_to_num(SOLDOUT_COLUMN))
completed_values = sheets.worksheet.col_values(sheets._col_to_num(COMPLETED_COLUMN))

print(f"START_ROW: {START_ROW}")
print()

max_len = max(len(encar_urls), len(completed_values))
for i in range(START_ROW - 1, max_len):
    row_num = i + 1
    url = encar_urls[i].strip() if i < len(encar_urls) else ""
    soldout = soldout_values[i].strip() if i < len(soldout_values) else ""
    completed = completed_values[i].strip() if i < len(completed_values) else ""
    if url or completed:
        print(f"Row {row_num} | AI={completed:12s} | U={soldout:20s} | R={url[:70]}")
