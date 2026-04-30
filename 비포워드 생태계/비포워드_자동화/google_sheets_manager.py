"""
Google Sheets integration for Encar SOLD OUT Monitoring System
Handles reading/writing data from [48H AUTO] worksheet
"""
import gspread
import re
from google.oauth2.service_account import Credentials
import time
from datetime import datetime, timedelta
from config import (
    SPREADSHEET_ID,
    WORKSHEET_NAME,
    SERVICE_ACCOUNT_FILE,
    SCOPES,
    ENCAR_LINK_COLUMN,
    SOLDOUT_COLUMN,
    CAR_NUMBER_COLUMN,
    PRICE_COLUMN,
    VIN_COLUMN,
    DRIVE_LINK_COLUMN,
    COMPLETED_COLUMN,
    FAIL_REASON_COLUMN,
    PURCHASE_COLUMN,
    UPLOAD_DATE_COLUMN,
    START_ROW,
    SOLDOUT_LOG_SPREADSHEET_ID,
    SOLDOUT_LOG_WORKSHEET_NAME,
)


class GoogleSheetsManager:
    """Google Sheets read/write operations with batch optimization"""

    def __init__(self):
        """Initialize Google Sheets manager"""
        self.gc = None
        self.worksheet = None
        self.creds = None
        self.soldout_log_worksheet = None

    def setup(self) -> bool:
        """Authenticate and connect to Google Sheets

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"\n{'='*60}")
            print("Google Sheets 연결 중...".center(60))
            print(f"{'='*60}\n")

            # Service account authentication
            self.creds = Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE,
                scopes=SCOPES
            )

            # Connect to Google Sheets
            self.gc = gspread.authorize(self.creds)
            spreadsheet = self.gc.open_by_key(SPREADSHEET_ID)

            # Try to find worksheet (with/without brackets)
            try:
                self.worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
            except gspread.exceptions.WorksheetNotFound:
                # Try alternative names
                candidates = []
                if WORKSHEET_NAME.startswith("[") and WORKSHEET_NAME.endswith("]"):
                    candidates.append(WORKSHEET_NAME[1:-1])
                else:
                    candidates.append(f"[{WORKSHEET_NAME}]")

                for candidate in candidates:
                    try:
                        self.worksheet = spreadsheet.worksheet(candidate)
                        print(f"[INFO] Found worksheet: {candidate}")
                        break
                    except gspread.exceptions.WorksheetNotFound:
                        continue

                if not self.worksheet:
                    available = [ws.title for ws in spreadsheet.worksheets()]
                    print(f"[오류] 시트를 찾을 수 없습니다. 사용 가능: {available}")
                    return False

            print(f"[OK] Google Sheets 연결 성공")
            print(f"  시트 이름: {WORKSHEET_NAME}")
            print(f"  시작 행: {START_ROW}\n")

            return True

        except FileNotFoundError:
            print(f"[오류] 서비스 계정 파일을 찾을 수 없습니다: {SERVICE_ACCOUNT_FILE}")
            return False

        except Exception as e:
            print(f"[오류] Google Sheets 연결 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def batch_read_row(self, row: int) -> dict:
        """Read entire row data in single API call (망고카 오토.py pattern)

        Args:
            row: Row number to read

        Returns:
            dict: Row data with keys: encar_url, soldout_status, car_number, vin, completed
        """
        last_exc = None
        for _attempt in range(4):  # 최대 4회 (0, 5, 15, 45초 대기)
            try:
                row_values = self.worksheet.row_values(row)
                break
            except Exception as e:
                last_exc = e
                err_str = str(e)
                if any(code in err_str for code in ('503', '500', '429', 'unavailable', 'Internal error')):
                    wait = 5 * (3 ** _attempt)
                    print(f"[경고] Row {row} API 오류 ({err_str[:60]}), {wait}초 후 재시도...")
                    time.sleep(wait)
                else:
                    break
        else:
            print(f"[경고] Row {row} 읽기 최종 실패: {last_exc}")
            return {'encar_url': '', 'soldout_status': '', 'car_number': '',
                    'price': '', 'vin': '', 'drive_link': '', 'completed': ''}

        try:

            # Column letter to 0-based index converter
            def col_to_idx(col_str):
                """Convert column letter(s) to 0-based index
                A=0, B=1, ..., Z=25, AA=26, AB=27, etc.
                """
                idx = 0
                for c in col_str.upper():
                    idx = idx * 26 + (ord(c) - ord('A') + 1)
                return idx - 1

            # Helper to safely get value
            def get_val(col_str):
                idx = col_to_idx(col_str)
                if idx < len(row_values):
                    return str(row_values[idx]).strip()
                return ""

            # drive_link는 HYPERLINK 수식일 수 있으므로 get_drive_link()로 별도 추출
            drive_link_display = get_val(DRIVE_LINK_COLUMN)
            if 'drive.google.com' in drive_link_display or 'docs.google.com' in drive_link_display:
                drive_link = drive_link_display
            else:
                drive_link = self.get_drive_link(row)

            return {
                'encar_url': get_val(ENCAR_LINK_COLUMN),
                'soldout_status': get_val(SOLDOUT_COLUMN),
                'car_number': get_val(CAR_NUMBER_COLUMN),
                'price': get_val(PRICE_COLUMN),
                'vin': get_val(VIN_COLUMN),
                'drive_link': drive_link,
                'completed': get_val(COMPLETED_COLUMN),
            }

        except Exception as e:
            print(f"[경고] Row {row} 읽기 실패: {e}")
            return {
                'encar_url': '',
                'soldout_status': '',
                'car_number': '',
                'price': '',
                'vin': '',
                'drive_link': '',
                'completed': '',
            }

    def get_all_monitored_rows(self) -> list[int]:
        """Get list of row numbers to monitor (하위 호환용 - 업로드+모니터링 전체)

        Returns:
            list[int]: Row numbers with Encar URLs (not yet completed)
        """
        try:
            encar_urls = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            soldout_values = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))
            completed_values = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))

            rows = []
            for i in range(START_ROW - 1, len(encar_urls)):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue
                soldout_status = soldout_values[i].strip() if i < len(soldout_values) else ""
                if "SOLD OUT" in soldout_status.upper():
                    continue
                completed = completed_values[i].strip() if i < len(completed_values) else ""
                if completed.upper() == "TRUE":
                    continue
                rows.append(row_num)
            return rows

        except Exception as e:
            print(f"[오류] 모니터링 대상 행 가져오기 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_rows_to_upload(self) -> tuple[list[int], list[dict]]:
        """업로드 대상 행 (COMPLETED가 빈값인 행만, Z열 날짜 <= 어제)

        Returns:
            tuple:
                [0] list[int]  - 업로드 대상 행 번호
                [1] list[dict] - 매입완료/SOLD OUT으로 제외된 항목
                                 각 항목: {'row': int, 'vin': str, 'reason': str}
        """
        try:
            encar_urls = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            completed_values = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))
            date_values = self.worksheet.col_values(self._col_to_num(UPLOAD_DATE_COLUMN))
            soldout_values = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))
            purchase_values = self.worksheet.col_values(self._col_to_num(PURCHASE_COLUMN))
            vin_values = self.worksheet.col_values(self._col_to_num(VIN_COLUMN))

            yesterday = (datetime.now() - timedelta(days=1)).date()

            rows = []
            excluded = []
            for i in range(START_ROW - 1, len(encar_urls)):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue
                completed = completed_values[i].strip() if i < len(completed_values) else ""
                # UPLOADED·게시종료·FAILED는 제외 (로그 불필요)
                if completed.upper() in ("UPLOADED", "게시종료", "FAILED"):
                    continue
                vin = vin_values[i].strip() if i < len(vin_values) else ""
                # U열 SOLD OUT → 제외 + 로그
                soldout = soldout_values[i].strip() if i < len(soldout_values) else ""
                if "SOLD OUT" in soldout.upper():
                    excluded.append({'row': row_num, 'vin': vin, 'reason': 'SOLD OUT 제외'})
                    continue
                # AH열 매입완료 → 제외 + 로그
                purchase = purchase_values[i].strip() if i < len(purchase_values) else ""
                if "매입완료" in purchase:
                    excluded.append({'row': row_num, 'vin': vin, 'reason': '매입완료 제외'})
                    continue
                # Z열 날짜 필터: 반드시 어제까지 등록된 행만 처리 (빈값은 제외)
                raw_date = date_values[i].strip() if i < len(date_values) else ""
                if not raw_date:
                    print(f"[Row {row_num}] [SKIP] Z열 날짜 없음")
                    continue
                row_date = None
                for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
                            "%y.%m.%d", "%y-%m-%d", "%y/%m/%d"):
                    try:
                        row_date = datetime.strptime(raw_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if row_date is None:
                    print(f"[Row {row_num}] [SKIP] Z열 날짜 파싱 실패: '{raw_date}'")
                    continue
                if row_date > yesterday:
                    continue  # 오늘 또는 미래 날짜 → 건너뜀
                rows.append(row_num)
            return rows, excluded

        except Exception as e:
            print(f"[오류] 업로드 대상 행 가져오기 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_rows_to_monitor(self) -> list[int]:
        """모니터링 대상 행 (COMPLETED="UPLOADED"인 행만)

        Returns:
            list[int]: 업로드 완료 후 SOLD OUT 감시 중인 행 번호 리스트
        """
        try:
            encar_urls = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            completed_values = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))
            soldout_values = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))

            rows = []
            for i in range(START_ROW - 1, len(encar_urls)):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue
                completed = completed_values[i].strip() if i < len(completed_values) else ""
                if completed.upper() != "UPLOADED":
                    continue
                # U열에 이미 SOLD OUT 기록된 행은 스킵
                soldout_status = soldout_values[i].strip() if i < len(soldout_values) else ""
                if "SOLD OUT" in soldout_status.upper():
                    continue
                rows.append(row_num)
            return rows

        except Exception as e:
            print(f"[오류] 모니터링 대상 행 가져오기 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_rows_to_suspend(self) -> list[int]:
        """판매중지 대상 행 조회.

        조건 (둘 중 하나):
        - AI열=UPLOADED + U열에 SOLD OUT 포함
        - AI열=UPLOADED + AH열에 "매입완료" 포함
        """
        try:
            encar_urls = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            completed_values = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))
            soldout_values = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))
            purchase_values = self.worksheet.col_values(self._col_to_num(PURCHASE_COLUMN))

            rows = []
            for i in range(START_ROW - 1, len(encar_urls)):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue

                completed = completed_values[i].strip() if i < len(completed_values) else ""
                if completed.upper() != "UPLOADED":
                    continue

                soldout_status = soldout_values[i].strip() if i < len(soldout_values) else ""
                purchase_status = purchase_values[i].strip() if i < len(purchase_values) else ""

                is_soldout = "SOLD OUT" in soldout_status.upper()
                is_purchased = "매입완료" in purchase_status

                if not (is_soldout or is_purchased):
                    continue

                rows.append(row_num)

            return rows

        except Exception as e:
            print(f"[오류] 판매중지 대상 조회 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_drive_link(self, row: int) -> str:
        """Get Google Drive link from DRIVE_LINK_COLUMN.
        셀에 걸린 하이퍼링크 URL도 추출 (텍스트는 '평가링크'이지만 URL이 붙어있는 경우)
        """
        try:
            cell = f"{DRIVE_LINK_COLUMN}{row}"

            # 1) Display value 가 직접 URL인 경우
            display_val = self.worksheet.acell(cell).value or ""
            display_val = str(display_val).strip()
            if "drive.google.com" in display_val or "docs.google.com" in display_val:
                return display_val

            # 2) =HYPERLINK() 수식인 경우
            formula_val = self.worksheet.acell(cell, value_render_option='FORMULA').value or ""
            formula_val = str(formula_val).strip()
            if formula_val.upper().startswith("=HYPERLINK("):
                m = re.search(r'=HYPERLINK\("([^"]+)"', formula_val, re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            if "drive.google.com" in formula_val or "docs.google.com" in formula_val:
                return formula_val

            # 3) 셀에 걸린 리치 텍스트 하이퍼링크 (Sheets API로 직접 조회)
            try:
                spreadsheet = self.gc.open_by_key(SPREADSHEET_ID)
                col_num = self._col_to_num(DRIVE_LINK_COLUMN)
                resp = spreadsheet.client.request(
                    'get',
                    f'https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}',
                    params={
                        'ranges': f"'{WORKSHEET_NAME}'!{cell}",
                        'fields': 'sheets.data.rowData.values.hyperlink',
                        'includeGridData': 'true',
                    }
                )
                data = resp.json()
                sheets = data.get('sheets', [])
                if sheets:
                    rows_data = sheets[0].get('data', [{}])[0].get('rowData', [])
                    if rows_data:
                        values = rows_data[0].get('values', [])
                        if values:
                            hyperlink = values[0].get('hyperlink', '')
                            if hyperlink:
                                print(f"  [OK] S열 하이퍼링크 추출: {hyperlink[:80]}")
                                return hyperlink
            except Exception as e2:
                print(f"  [DEBUG] 하이퍼링크 API 조회 실패: {e2}")

            return ""
        except Exception as e:
            print(f"[경고] Row {row} 드라이브 링크 추출 실패: {e}")
            return ""

    def _col_to_num(self, col_str: str) -> int:
        """Convert column letter to 1-based column number

        Args:
            col_str: Column letter (A, B, ..., AA, AB, etc.)

        Returns:
            int: 1-based column number
        """
        num = 0
        for c in col_str.upper():
            num = num * 26 + (ord(c) - ord('A') + 1)
        return num

    def update_soldout_status(self, row: int, timestamp: str):
        """Update SOLDOUT column with timestamp

        Args:
            row: Row number
            timestamp: Timestamp string
        """
        try:
            cell = f"{SOLDOUT_COLUMN}{row}"
            value = f"SOLD OUT ({timestamp})"
            self.worksheet.update(cell, [[value]])
            print(f"[OK] Row {row} | Updated SOLDOUT: {value}")

        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429:  # Quota exceeded
                print("[경고] API quota exceeded, waiting 10 seconds...")
                time.sleep(10)
                # Retry once
                self.worksheet.update(cell, [[value]])
            else:
                raise

        except Exception as e:
            print(f"[오류] Row {row} SOLDOUT 업데이트 실패: {e}")

    def update_completed_status(self, row: int, status: str):
        """Update COMPLETED column

        Args:
            row: Row number
            status: "TRUE" or "FALSE"
        """
        try:
            cell = f"{COMPLETED_COLUMN}{row}"
            self.worksheet.update(cell, [[status]])
            print(f"[OK] Row {row} | Updated COMPLETED: {status}")

        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429:  # Quota exceeded
                print("[경고] API quota exceeded, waiting 10 seconds...")
                time.sleep(10)
                # Retry once
                self.worksheet.update(cell, [[status]])
            else:
                raise

        except Exception as e:
            print(f"[오류] Row {row} COMPLETED 업데이트 실패: {e}")

    def update_fail_reason(self, row: int, reason: str):
        """Update FAIL_REASON column (AN). Pass empty string to clear on success."""
        try:
            cell = f"{FAIL_REASON_COLUMN}{row}"
            value = (reason or "").strip()
            if len(value) > 500:
                value = value[:497] + "..."
            self.worksheet.update(cell, [[value]])
            if value:
                print(f"[OK] Row {row} | Updated FAIL_REASON: {value[:80]}")

        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429:
                print("[경고] API quota exceeded, waiting 10 seconds...")
                time.sleep(10)
                self.worksheet.update(cell, [[value]])
            else:
                print(f"[오류] Row {row} FAIL_REASON 업데이트 실패: {e}")

        except Exception as e:
            print(f"[오류] Row {row} FAIL_REASON 업데이트 실패: {e}")

    def _get_soldout_log_worksheet(self):
        """SOLD OUT 누적 로그 워크시트 핸들 획득 (lazy)."""
        if self.soldout_log_worksheet is not None:
            return self.soldout_log_worksheet
        try:
            spreadsheet = self.gc.open_by_key(SOLDOUT_LOG_SPREADSHEET_ID)
            if SOLDOUT_LOG_WORKSHEET_NAME:
                ws = spreadsheet.worksheet(SOLDOUT_LOG_WORKSHEET_NAME)
            else:
                ws = spreadsheet.sheet1  # gid=0 첫 시트
            self.soldout_log_worksheet = ws
            return ws
        except Exception as e:
            print(f"[경고] SOLD OUT 로그 시트 열기 실패: {e}")
            return None

    def append_soldout_log(self, vin: str, status_label: str) -> bool:
        """SOLD OUT 누적 로그 시트에 한 행 추가.

        Args:
            vin: 차대번호 (B열)
            status_label: 'SOLD OUT' 또는 '매입완료 SOLD OUT' (C열)

        시트 구조: A=시간 | B=차대번호 | C=상태
        """
        ws = self._get_soldout_log_worksheet()
        if ws is None:
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp, str(vin or "").strip(), str(status_label or "").strip()]

        # 헤더가 없으면 1행에 헤더 추가 (1회성)
        try:
            first_row = ws.row_values(1)
            if not first_row:
                ws.update("A1:C1", [["시간", "차대번호", "상태"]])
        except Exception:
            pass

        for attempt in range(3):
            try:
                ws.append_row(row, value_input_option="USER_ENTERED")
                print(f"[OK] SOLD OUT 로그 기록: {row}")
                return True
            except gspread.exceptions.APIError as e:
                if getattr(e, "response", None) is not None and e.response.status_code == 429:
                    wait = 2 ** attempt
                    print(f"[경고] 로그 시트 quota, {wait}초 후 재시도")
                    time.sleep(wait)
                    continue
                print(f"[오류] SOLD OUT 로그 기록 실패: {e}")
                return False
            except Exception as e:
                print(f"[오류] SOLD OUT 로그 기록 실패: {e}")
                return False
        return False

    def safe_update_with_retry(self, cell: str, value: str, max_retries: int = 3):
        """Update cell with exponential backoff retry

        Args:
            cell: Cell reference (e.g., "N852")
            value: Value to write
            max_retries: Maximum retry attempts
        """
        for attempt in range(max_retries):
            try:
                self.worksheet.update(cell, [[value]])
                return True

            except gspread.exceptions.APIError as e:
                if e.response.status_code == 429:  # Quota exceeded
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8...
                    print(f"[경고] API quota exceeded, waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    if attempt < max_retries - 1:
                        continue
                    else:
                        print(f"[오류] API quota exceeded after {max_retries} retries")
                        return False
                else:
                    raise

            except Exception as e:
                print(f"[오류] Cell {cell} 업데이트 실패: {e}")
                return False

        return False
