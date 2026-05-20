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
    UPLOAD_RESULT_COLUMN,
    PURCHASE_COLUMN,
    UPLOAD_DATE_COLUMN,
    UPLOAD_TIMESTAMP_COLUMN,
    SUSPENSION_COLUMN,
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
                'purchase': get_val(PURCHASE_COLUMN),
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

    def get_cycle_data(self) -> dict:
        """모니터링 사이클에 필요한 열을 6회 col_values 호출로 일괄 읽기.

        Returns:
            dict[int, dict]: row_num -> {encar_url, soldout_status, completed, vin, purchase, suspended}
        """
        try:
            encar_urls   = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            soldout_vals = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))
            completed    = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))
            vin_vals     = self.worksheet.col_values(self._col_to_num(VIN_COLUMN))
            purchase     = self.worksheet.col_values(self._col_to_num(PURCHASE_COLUMN))
            suspended    = self.worksheet.col_values(self._col_to_num(SUSPENSION_COLUMN))

            result = {}
            max_len = max(len(encar_urls), len(completed))
            for i in range(START_ROW - 1, max_len):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue
                result[row_num] = {
                    'encar_url':      encar_url,
                    'soldout_status': soldout_vals[i].strip() if i < len(soldout_vals) else "",
                    'completed':      completed[i].strip() if i < len(completed) else "",
                    'vin':            vin_vals[i].strip() if i < len(vin_vals) else "",
                    'purchase':       purchase[i].strip() if i < len(purchase) else "",
                    'suspended':      suspended[i].strip() if i < len(suspended) else "",
                }
            return result

        except Exception as e:
            print(f"[오류] 사이클 데이터 배치 읽기 실패: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def _parse_drive_link(self, formula_or_val: str) -> str:
        """셀 값 또는 =HYPERLINK() 수식에서 드라이브 URL 추출."""
        val = formula_or_val.strip()
        if not val:
            return ""
        if ("drive.google.com" in val or "docs.google.com" in val
                or "mangoworldcar.com" in val):
            return val
        if val.upper().startswith("=HYPERLINK("):
            m = re.search(r'=HYPERLINK\("([^"]+)"', val, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    def get_drive_links_batch(self) -> dict:
        """S열 전체에서 드라이브 링크를 단일 Sheets v4 API 호출로 추출.

        세 가지 경우 모두 처리:
        1) 리치텍스트 하이퍼링크 (셀 hyperlink 속성)
        2) =HYPERLINK() 수식 (formulaValue)
        3) 직접 URL 표시값 (formattedValue)

        Returns:
            dict[int, str]: row_num -> drive_link URL
        """
        try:
            spreadsheet = self.gc.open_by_key(SPREADSHEET_ID)
            resp = spreadsheet.client.request(
                'get',
                f'https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}',
                params={
                    'ranges': f"'{WORKSHEET_NAME}'!{DRIVE_LINK_COLUMN}:{DRIVE_LINK_COLUMN}",
                    'fields': 'sheets.data.rowData.values(hyperlink,formattedValue,userEnteredValue)',
                    'includeGridData': 'true',
                },
            )
            data = resp.json()
            result = {}
            sheets = data.get('sheets', [])
            if not sheets:
                return {}
            rows_data = sheets[0].get('data', [{}])[0].get('rowData', [])
            for i, row in enumerate(rows_data):
                values = row.get('values', [])
                if not values:
                    continue
                cell = values[0]
                row_num = i + 1

                # 1순위: 리치텍스트 hyperlink 속성
                hyperlink = (cell.get('hyperlink') or '').strip()
                if hyperlink:
                    result[row_num] = hyperlink
                    continue

                # 2순위: =HYPERLINK() 수식
                user_entered = cell.get('userEnteredValue', {})
                formula = (user_entered.get('formulaValue') or '').strip()
                if formula.upper().startswith('=HYPERLINK('):
                    m = re.search(r'=HYPERLINK\("([^"]+)"', formula, re.IGNORECASE)
                    if m:
                        result[row_num] = m.group(1).strip()
                        continue

                # 3순위: formattedValue 가 직접 URL
                formatted = (cell.get('formattedValue') or '').strip()
                if ('drive.google.com' in formatted or 'docs.google.com' in formatted
                        or 'mangoworldcar.com' in formatted):
                    result[row_num] = formatted

            return result

        except Exception as e:
            print(f"[오류] S열 드라이브 링크 배치 조회 실패: {e}")
            import traceback
            traceback.print_exc()
            return {}

    def get_upload_data(self) -> tuple:
        """업로드 대상 행 + 필요 데이터를 배치로 읽기 (per-row API 호출 제거).

        S열 드라이브 링크는 Sheets v4 API로 hyperlink 속성 / =HYPERLINK 수식 / 직접 URL 모두 한 번에 추출.

        Returns:
            tuple:
                [0] list[int]       - 업로드 대상 행 번호
                [1] list[dict]      - 제외된 항목 {'row', 'vin', 'reason'}
                [2] dict[int, dict] - row_num -> {encar_url, price, vin, drive_link}
        """
        try:
            encar_urls    = self.worksheet.col_values(self._col_to_num(ENCAR_LINK_COLUMN))
            completed     = self.worksheet.col_values(self._col_to_num(COMPLETED_COLUMN))
            date_values   = self.worksheet.col_values(self._col_to_num(UPLOAD_DATE_COLUMN))
            soldout_vals  = self.worksheet.col_values(self._col_to_num(SOLDOUT_COLUMN))
            purchase_vals = self.worksheet.col_values(self._col_to_num(PURCHASE_COLUMN))
            vin_vals      = self.worksheet.col_values(self._col_to_num(VIN_COLUMN))
            price_vals    = self.worksheet.col_values(self._col_to_num(PRICE_COLUMN))
            # S열: 리치텍스트 hyperlink + HYPERLINK 수식 + 직접 URL 모두 처리
            drive_links_map = self.get_drive_links_batch()

            yesterday = (datetime.now() - timedelta(days=1)).date()

            rows = []
            excluded = []
            row_data_map = {}

            for i in range(START_ROW - 1, len(encar_urls)):
                row_num = i + 1
                encar_url = encar_urls[i].strip() if i < len(encar_urls) else ""
                if not encar_url:
                    continue
                comp = completed[i].strip() if i < len(completed) else ""
                if comp.upper() in ("UPLOADED", "게시종료", "FAILED"):
                    continue
                vin = vin_vals[i].strip() if i < len(vin_vals) else ""
                soldout = soldout_vals[i].strip() if i < len(soldout_vals) else ""
                if "SOLD OUT" in soldout.upper():
                    excluded.append({'row': row_num, 'vin': vin, 'reason': 'SOLD OUT 제외'})
                    continue
                purchase = purchase_vals[i].strip() if i < len(purchase_vals) else ""
                if "매입완료" in purchase:
                    excluded.append({'row': row_num, 'vin': vin, 'reason': '매입완료 제외'})
                    continue
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
                    continue

                drive_link = drive_links_map.get(row_num, '')

                rows.append(row_num)
                row_data_map[row_num] = {
                    'encar_url':  encar_url,
                    'price':      price_vals[i].strip() if i < len(price_vals) else "",
                    'vin':        vin,
                    'drive_link': drive_link,
                }

            return rows, excluded, row_data_map

        except Exception as e:
            print(f"[오류] 업로드 데이터 배치 읽기 실패: {e}")
            import traceback
            traceback.print_exc()
            return [], [], {}

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

        조건: AI열=UPLOADED + (U열 SOLD OUT 또는 AH열 매입완료)
        AP열 채워져 있어도 매번 시도 (중복 처리 허용)
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

    def update_completed_status(self, row: int, status: str) -> bool:
        """Update COMPLETED column. Returns True on success, False on failure."""
        cell = f"{COMPLETED_COLUMN}{row}"
        ok = self.safe_update_with_retry(cell, status, max_retries=5)
        if ok:
            print(f"[OK] Row {row} | Updated COMPLETED: {status}")
        else:
            print(f"[오류] Row {row} | COMPLETED 갱신 최종 실패 (5회 재시도): {cell}='{status}'")
        return ok

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

    def update_upload_timestamp(self, row: int) -> bool:
        """업로드 성공 시각을 AD열에 기록. Returns True on success."""
        cell = f"{UPLOAD_TIMESTAMP_COLUMN}{row}"
        value = f"업로드 성공 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        ok = self.safe_update_with_retry(cell, value, max_retries=5)
        if ok:
            print(f"[OK] Row {row} | Updated AD: {value}")
        else:
            print(f"[경고] Row {row} | AD열 업로드 시각 기록 실패 (5회 재시도)")
        return ok

    def update_upload_result(self, row: int, result: str) -> bool:
        """업로드 결과를 AO열에 기록. (성공 시: '업로드 성공 (시각)', 실패 시: '실패')"""
        cell = f"{UPLOAD_RESULT_COLUMN}{row}"
        ok = self.safe_update_with_retry(cell, result, max_retries=5)
        if ok:
            print(f"[OK] Row {row} | Updated AO: {result}")
        else:
            print(f"[경고] Row {row} | AO열 결과 기록 실패 (5회 재시도)")
        return ok

    def update_suspension_status(self, row: int) -> bool:
        """게시종료 시각을 AP열에 기록. '게시종료 (YYYY-MM-DD HH:MM:SS)'."""
        cell = f"{SUSPENSION_COLUMN}{row}"
        value = f"게시종료 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        ok = self.safe_update_with_retry(cell, value, max_retries=5)
        if ok:
            print(f"[OK] Row {row} | Updated AP: {value}")
        else:
            print(f"[경고] Row {row} | AP열 게시종료 기록 실패 (5회 재시도)")
        return ok

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
            vin: 차대번호 (A열)
            status_label: '게시종료' 또는 '매입완료' (C열)

        시트 구조: A=차대번호 | B=SOLD OUT 날짜 | C=SOLD OUT 사유
        """
        ws = self._get_soldout_log_worksheet()
        if ws is None:
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [str(vin or "").strip(), timestamp, str(status_label or "").strip()]

        # 헤더가 없으면 1행에 헤더 추가 (1회성)
        try:
            first_row = ws.row_values(1)
            if not first_row:
                ws.update("A1:C1", [["차대번호", "SOLD OUT 날짜", "SOLD OUT 사유"]])
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
        last_exc = None
        for attempt in range(max_retries):
            try:
                self.worksheet.update(cell, [[value]])
                return True

            except gspread.exceptions.APIError as e:
                last_exc = e
                status = getattr(e.response, 'status_code', 0)
                if status in (429, 500, 503):
                    wait_time = min(2 ** attempt * 5, 60)  # 5, 10, 20, 40, 60s
                    print(f"[경고] Sheets API {status}, {wait_time}초 후 재시도 ({attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                print(f"[오류] Cell {cell} API 오류 (status={status}): {e}")
                return False

            except Exception as e:
                last_exc = e
                err_s = str(e).lower()
                if any(k in err_s for k in ('timeout', 'connection', 'reset', 'unavailable')):
                    wait_time = min(2 ** attempt * 5, 60)
                    print(f"[경고] Sheets 네트워크 오류, {wait_time}초 후 재시도 ({attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                print(f"[오류] Cell {cell} 업데이트 실패: {e}")
                return False

        print(f"[오류] Cell {cell} 갱신 최종 실패 ({max_retries}회): {last_exc}")
        return False
