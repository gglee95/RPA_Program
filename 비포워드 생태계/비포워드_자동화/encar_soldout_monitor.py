"""
Encar SOLD OUT Monitoring System - Main Orchestrator

1. Uploads new listings from Encar to ByForward
2. Monitors Encar listings every 30 minutes and automatically suspends
   corresponding ByForward listings when vehicles are sold.

Usage:
    python encar_soldout_monitor.py

Press Ctrl+C to stop the monitoring system.
"""
import time
import sys
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from datetime import datetime

from 엔카_크롤러 import EncarSeleniumCrawler
from 비포워드_crawling import BefowordCrawler

from config import (
    CHECK_INTERVAL_SECONDS,
    ERROR_RETRY_DELAY_SECONDS,
    ENCAR_HEADLESS,
    BEFORWARD_HEADLESS,
    UPLOAD_HOUR,
)
from google_sheets_manager import GoogleSheetsManager
from encar_soldout_checker import EncarSoldOutChecker
from beforward_suspension_manager import BeforwardSuspensionManager
from soldout_logger import SoldOutLogger


class EncarSoldOutMonitor:
    """Main monitoring system orchestrator"""

    def __init__(self):
        """Initialize monitoring system components"""
        self.sheets_manager = GoogleSheetsManager()
        self.encar_checker = EncarSoldOutChecker(headless=ENCAR_HEADLESS)
        self.beforward_manager = BeforwardSuspensionManager(headless=BEFORWARD_HEADLESS)
        self.logger = SoldOutLogger()
        self.cycle_count = 0
        self.encar_crawler = None  # For upload phase
        self.beforward_uploader = None  # For upload phase

    def setup(self) -> bool:
        """Setup all components

        Returns:
            bool: True if setup successful
        """
        print(f"\n{'='*70}")
        print("Encar SOLD OUT Monitoring System - Setup".center(70))
        print(f"{'='*70}\n")

        # Setup Google Sheets
        if not self.sheets_manager.setup():
            print("[오류] Google Sheets 설정 실패")
            return False

        # ByForward login will be done on-demand (first SOLD OUT detection)

        print("[OK] All components initialized successfully\n")
        return True

    def run_monitoring_cycle(self) -> tuple[int, int]:
        """Execute single monitoring cycle.

        Phase 1: UPLOADED 행 → 엔카 체크 → SOLD OUT 감지 시 U열 기록
        Phase 2: U열=SOLD OUT 행 → 비포워드 게시정지 → AI열=게시종료

        Returns:
            tuple: (rows_processed, listings_suspended)
        """
        rows_processed = 0
        listings_suspended = 0

        try:
            # ── Phase 1: 엔카 SOLD OUT 체크 → U열 기록 ───────────────────────────
            rows_to_monitor = self.sheets_manager.get_rows_to_monitor()

            if rows_to_monitor:
                print(f"[INFO] 엔카 체크 대상: {len(rows_to_monitor)}행")
                for row_num in rows_to_monitor:
                    try:
                        row_data = self.sheets_manager.batch_read_row(row_num)
                        encar_url = row_data.get('encar_url', '')
                        if not encar_url:
                            continue

                        print(f"\n[Row {row_num}] Checking: {encar_url[:60]}...")
                        soldout_result = self.encar_checker.check_with_retry(encar_url)
                        rows_processed += 1

                        if not soldout_result['is_soldout']:
                            print(f"[Row {row_num}] Still active ({soldout_result['detection_method']})")
                            continue

                        # SOLD OUT 감지 → U열 기록
                        print(f"[Row {row_num}] [!]  SOLD OUT detected!")
                        self.logger.log_soldout_detected(
                            row_num, encar_url, soldout_result['detection_method']
                        )
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.sheets_manager.update_soldout_status(row_num, timestamp)
                        time.sleep(1)

                    except Exception as e:
                        print(f"[Row {row_num}] [ERR] 엔카 체크 오류: {e}")
                        self.logger.log_error(row_num, "ENCAR_CHECK_ERROR", str(e))
                        import traceback
                        traceback.print_exc()
                        continue
            else:
                print("[INFO] 엔카 체크 대상 없음 (UPLOADED 행 없음)")

            # ── Phase 2: U열=SOLD OUT 행 → 비포워드 게시정지 ────────────────────
            rows_to_suspend = self.sheets_manager.get_rows_to_suspend()

            if not rows_to_suspend:
                print("[INFO] 게시정지 대상 없음")
                return (rows_processed, listings_suspended)

            print(f"[INFO] 게시정지 대상: {len(rows_to_suspend)}행")

            suspension_targets = []
            for row_num in rows_to_suspend:
                try:
                    row_data = self.sheets_manager.batch_read_row(row_num)
                    chassis_no = (row_data.get('vin') or row_data.get('car_number') or '').strip()
                    if not chassis_no:
                        print(f"[Row {row_num}] [WARN] VIN/차량번호 없음 - 건너뜀")
                        self.logger.log_warning(row_num, "No VIN or car number for suspension")
                        continue
                    # 매입완료 여부에 따라 SOLD OUT 로그 라벨 결정
                    purchase_val = ''
                    try:
                        purchase_val = self.sheets_manager.worksheet.acell(
                            f"AH{row_num}"
                        ).value or ''
                    except Exception:
                        purchase_val = ''
                    is_purchased = "매입완료" in purchase_val
                    soldout_label = "매입완료 SOLD OUT" if is_purchased else "SOLD OUT"
                    suspension_targets.append((row_num, chassis_no, soldout_label))
                except Exception as e:
                    print(f"[Row {row_num}] [ERR] Error: {e}")
                    self.logger.log_error(row_num, "ROW_PROCESSING_ERROR", str(e))

            if not suspension_targets:
                return (rows_processed, listings_suspended)

            if not self.beforward_manager.logged_in:
                print("[INFO] 비포워드 로그인 중...")
                login_ok = self.beforward_manager.login()
                if not login_ok:
                    for row_num, _, _ in suspension_targets:
                        self.logger.log_error(row_num, "LOGIN_FAILED", "ByForward login failed")
                    return (rows_processed, listings_suspended)

            chassis_numbers = [chassis_no for _, chassis_no, _ in suspension_targets]
            suspension_ok = self.beforward_manager.batch_unsellable_by_chassis(chassis_numbers)

            if not suspension_ok:
                for row_num, chassis_no, _ in suspension_targets:
                    self.logger.log_suspension_failed(row_num, chassis_no, "일괄 판매불가 처리 실패")
                return (rows_processed, listings_suspended)

            for row_num, chassis_no, soldout_label in suspension_targets:
                self.logger.log_suspension_success(row_num, chassis_no, "batch unsellable")
                self.sheets_manager.update_completed_status(row_num, "게시종료")
                # SOLD OUT 누적 로그 시트에 기록
                try:
                    self.sheets_manager.append_soldout_log(chassis_no, soldout_label)
                except Exception as e:
                    print(f"[Row {row_num}] [경고] SOLD OUT 로그 시트 기록 실패: {e}")
                listings_suspended += 1
                time.sleep(1)

            return (rows_processed, listings_suspended)

        except Exception as e:
            print(f"[오류] Monitoring cycle error: {e}")
            self.logger.log_error(0, "CYCLE_ERROR", str(e))
            import traceback
            traceback.print_exc()
            return (0, 0)

    def upload_new_listings(self) -> tuple[int, int]:
        """Upload new listings from Encar to ByForward

        Returns:
            tuple: (rows_processed, uploads_successful)
        """
        print(f"\n{'='*70}")
        print("1단계: 비포워드 매물 업로드 시작".center(70))
        print(f"{'='*70}\n")

        try:
            # Get rows that need uploading (COMPLETED가 빈값인 행만)
            all_rows, excluded_rows = self.sheets_manager.get_rows_to_upload()

            # 매입완료·SOLD OUT 제외 항목 엑셀 로그 기록
            for ex in excluded_rows:
                print(f"[Row {ex['row']}] [SKIP] {ex['reason']} (VIN: {ex['vin']})")
                self.logger.log_upload_fail_excel(ex['row'], '', ex['vin'], ex['reason'])

            if not all_rows:
                print("[INFO] 업로드할 매물이 없습니다.\n")
                return (0, 0)

            print(f"[INFO] {len(all_rows)}개 매물 업로드 시작...\n")

            # Initialize crawlers
            self.encar_crawler = EncarSeleniumCrawler(headless=ENCAR_HEADLESS)
            self.beforward_uploader = BefowordCrawler(headless=BEFORWARD_HEADLESS)

            # Login to ByForward once
            print("[INFO] 비포워드 로그인 중...")
            if not self.beforward_uploader.login():
                print("[오류] 비포워드 로그인 실패")
                return (0, 0)

            # Close any popups after login
            self._close_beforward_popups()

            rows_processed = 0
            uploads_successful = 0

            for row_num in all_rows:
                try:
                    row_data = self.sheets_manager.batch_read_row(row_num)
                    encar_url = row_data['encar_url']

                    if not encar_url:
                        continue

                    # Crawl Encar
                    car_info = self.encar_crawler.get_car_info(encar_url, include_options=True)

                    if not car_info:
                        print(f"[Row {row_num}] [ERR] 엔카 크롤링 실패: {encar_url[:60]}")
                        self.logger.log_diagnostic(row_num, '알수없음', '엔카_크롤링', '차량 정보 추출 실패 (페이지 로딩 오류 또는 URL 오류)')
                        self.logger.log_upload_fail_excel(row_num, '', '', '엔카 크롤링 실패')
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, '엔카 페이지를 열 수 없음 (URL 오류 또는 매물 삭제 가능)')
                        continue

                    if not car_info.car_type:
                        print(f"[Row {row_num}] [ERR] 엔카 차종명 추출 실패: {encar_url[:60]}")
                        self.logger.log_diagnostic(row_num, '알수없음', '엔카_크롤링', '차종명(car_type) 추출 실패 - 재원표 조회 불가')
                        self.logger.log_upload_fail_excel(row_num, '', '', '엔카 차종명 추출 실패')
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, '엔카에서 차종명을 찾지 못함')
                        continue

                    model_name = car_info.car_type

                    price_from_sheet = self._normalize_sheet_price(row_data.get('price', ''))
                    if not price_from_sheet:
                        print(f"[Row {row_num}] [ERR] P열 판매가격이 비어있거나 형식이 올바르지 않아 업로드 중단")
                        self.logger.log_diagnostic(row_num, model_name, '가격_확인', 'P열 판매가격 없음 또는 형식 오류')
                        self.logger.log_upload_fail_excel(row_num, model_name, '', 'P열 판매가격 없음 또는 형식 오류')
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, 'P열(판매가격) 비어있음 또는 형식 오류')
                        continue

                    upload_price = self._build_upload_price(price_from_sheet)
                    if not upload_price:
                        print(f"[Row {row_num}] [ERR] P열 가격으로 업로드 가격 계산 실패")
                        self.logger.log_diagnostic(row_num, model_name, '가격_계산', f'업로드 가격 계산 실패 (원본: {price_from_sheet})')
                        self.logger.log_upload_fail_excel(row_num, model_name, '', f'업로드 가격 계산 실패 (P열 원본값: {price_from_sheet})')
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, f'P열(판매가격) 계산 불가 (원본값: {price_from_sheet})')
                        continue

                    car_info.price = upload_price

                    vin_from_sheet = row_data['vin']
                    if not vin_from_sheet:
                        print(f"[Row {row_num}] [ERR] AB열 차대번호 없음 - 업로드 불가")
                        self.logger.log_diagnostic(row_num, model_name, 'AB열_차대번호', 'AB열이 비어있음 - 스프레드시트에 차대번호를 입력하세요')
                        self.logger.log_upload_fail_excel(row_num, model_name, '', 'AB열 차대번호 없음')
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, 'AB열(차대번호) 비어있음 - 시트에 차대번호 입력 필요')
                        continue
                    car_info.inspection_chassis_no = vin_from_sheet

                    # S열 구글 드라이브 링크(이미지 업로드용)
                    drive_link_raw = row_data.get('drive_link', '')
                    drive_link = drive_link_raw.strip() if drive_link_raw else ''
                    _known_link = ("drive.google.com" in drive_link or
                                   "docs.google.com" in drive_link or
                                   "mangoworldcar.com" in drive_link)
                    if drive_link and not _known_link:
                        fallback = self.sheets_manager.get_drive_link(row_num)
                        if fallback:
                            drive_link = fallback
                        elif drive_link.startswith('http'):
                            pass
                        else:
                            drive_link = ""
                    elif not drive_link:
                        drive_link = self.sheets_manager.get_drive_link(row_num)
                    if drive_link:
                        setattr(car_info, 'drive_link', drive_link)
                        setattr(car_info, 'sheet_row', row_num)
                    else:
                        print(f"[Row {row_num}] [경고] S열 드라이브 링크 없음")

                    upload_ok = self.beforward_uploader.fill_vehicle_data(car_info, auto_submit=True)
                    rows_processed += 1

                    listing_submitted = getattr(self.beforward_uploader, '_listing_submitted', False)
                    if upload_ok or listing_submitted:
                        listing_id = getattr(car_info, '_listing_id', '')
                        print(f"[Row {row_num}] [OK] {model_name} | ID={listing_id}")
                        self.logger.log_upload_result(row_num, model_name, True, listing_id=listing_id)
                        self.logger.log_upload_success_excel(row_num, model_name, vin_from_sheet, listing_id)
                        self.sheets_manager.update_completed_status(row_num, "UPLOADED")
                        self.sheets_manager.update_fail_reason(row_num, "")
                        downloads = getattr(self.beforward_uploader, '_last_downloaded_image_files', [])
                        if downloads:
                            self.beforward_uploader._cleanup_downloaded_images(downloads)
                            self.beforward_uploader._last_downloaded_image_files = []
                        uploads_successful += 1
                    else:
                        err_step = getattr(self.beforward_uploader, '_last_error_step', '') or '원인_미캡처(스크린샷 확인)'
                        err_cause = getattr(self.beforward_uploader, '_last_error_cause', '') or 'fill_vehicle_data가 False를 반환했으나 오류 단계가 기록되지 않음'
                        print(f"[Row {row_num}] [ERR] 업로드 실패 | 단계: {err_step} | 원인: {err_cause}")
                        self.logger.log_upload_result(row_num, model_name, False, step=err_step, cause=err_cause)
                        self.logger.log_upload_fail_excel(row_num, model_name, vin_from_sheet, f"{err_step}: {err_cause}")
                        self.sheets_manager.update_completed_status(row_num, "FAILED")
                        self.sheets_manager.update_fail_reason(row_num, self._friendly_fail_reason(err_step, err_cause))
                        downloads = getattr(self.beforward_uploader, '_last_downloaded_image_files', [])
                        if downloads:
                            self.beforward_uploader._cleanup_downloaded_images(downloads)
                            self.beforward_uploader._last_downloaded_image_files = []

                    time.sleep(2)  # Rate limiting

                except Exception as e:
                    print(f"[Row {row_num}] [ERR] 오류: {e}")
                    self.logger.log_error(row_num, "UPLOAD_ERROR", str(e))
                    import traceback
                    traceback.print_exc()
                    _exc_model = locals().get('model_name', '')
                    _exc_vin = locals().get('vin_from_sheet', '')
                    self.logger.log_upload_fail_excel(row_num, _exc_model, _exc_vin, f"예외 발생: {str(e)[:120]}")
                    self.sheets_manager.update_completed_status(row_num, "FAILED")
                    self.sheets_manager.update_fail_reason(row_num, f"시스템 오류: {str(e)[:120]}")

                    # 세션/탭 크래시 시 드라이버 재초기화
                    err_s = str(e).lower()
                    if any(k in err_s for k in ('invalid session id', 'session', 'crashed', 'disconnected', 'no such window')):
                        print(f"[INFO] Chrome 세션 복구 중...")
                        try:
                            self.beforward_uploader.close()
                        except Exception:
                            pass
                        time.sleep(2)
                        self.beforward_uploader._setup_driver()
                        if not self.beforward_uploader.login():
                            print(f"[오류] 재로그인 실패 - 업로드 중단")
                            break

                    continue

            print(f"\n{'='*70}")
            print(f"업로드 완료: {uploads_successful}/{rows_processed}")
            print(f"{'='*70}\n")

            return (rows_processed, uploads_successful)

        except Exception as e:
            print(f"[오류] Upload phase error: {e}")
            self.logger.log_error(0, "UPLOAD_PHASE_ERROR", str(e))
            import traceback
            traceback.print_exc()
            return (0, 0)

        finally:
            # Close upload crawlers
            if self.encar_crawler:
                self.encar_crawler.close()
            if self.beforward_uploader:
                self.beforward_uploader.close()

    def run_continuous(self):
        """Run continuous monitoring loop (every 30 minutes)

        - 모니터링: 매 30분마다 UPLOADED 행의 엔카 링크 확인 → SOLD OUT → 게시 정지
        - 업로드: 매일 16시에 1회 실행 (빈값 행 → 비포워드 업로드 → UPLOADED)
        """
        print(f"\n{'='*70}")
        print("Encar → ByForward 자동화 시스템".center(70))
        print(f"{'='*70}\n")

        self.logger.log_system_start()

        # 시작 시 즉시 1회 업로드 실행
        print("\n[STARTUP] 초기 업로드 실행")
        self._run_upload_phase()

        # 시작 시 즉시 1회 모니터링 실행
        print("\n[STARTUP] 초기 모니터링 실행")
        self.cycle_count += 1
        rows_processed, listings_suspended = self.run_monitoring_cycle()
        print(f"\n[Cycle {self.cycle_count}] 완료: {rows_processed}행 확인 | {listings_suspended}건 게시 정지")
        self.logger.log_cycle_end(self.cycle_count, rows_processed, listings_suspended)

        last_upload_date = datetime.now().strftime("%Y-%m-%d")

        print(f"\n{'='*70}")
        print("SOLD OUT 모니터링 시작".center(70))
        print(f"{'='*70}")
        print(f"  모니터링 주기: {CHECK_INTERVAL_SECONDS // 60}분")
        print(f"  업로드 시간: 매일 {UPLOAD_HOUR}시")
        print(f"  Press Ctrl+C to stop\n")

        while True:
            try:
                self.cycle_count += 1
                now = datetime.now()

                print(f"\n{'='*70}")
                print(f"[Cycle {self.cycle_count}] {now.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*70}\n")

                self.logger.log_cycle_start(self.cycle_count)

                # ── 매일 16시 업로드 체크 ──
                today = now.strftime("%Y-%m-%d")
                if now.hour >= UPLOAD_HOUR and last_upload_date != today:
                    print(f"[UPLOAD] {UPLOAD_HOUR}시 업로드 시작")
                    self._run_upload_phase()
                    last_upload_date = today

                # ── SOLD OUT 모니터링 ──
                rows_processed, listings_suspended = self.run_monitoring_cycle()

                print(f"\n[Cycle {self.cycle_count}] 완료: {rows_processed}행 확인 | {listings_suspended}건 게시 정지")

                self.logger.log_cycle_end(self.cycle_count, rows_processed, listings_suspended)

                # Wait for next cycle
                wait_minutes = CHECK_INTERVAL_SECONDS // 60
                print(f"[INFO] 다음 사이클까지 {wait_minutes}분 대기...\n")
                time.sleep(CHECK_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print(f"\n\n{'='*70}")
                print("SHUTDOWN".center(70))
                print(f"{'='*70}\n")
                self._cleanup()
                self.logger.log_system_shutdown()
                print("\n[OK] Goodbye!\n")
                break

            except Exception as e:
                self.logger.log_error(0, "SYSTEM_ERROR", str(e))
                print(f"\n[오류] System error in cycle {self.cycle_count}: {e}")
                import traceback
                traceback.print_exc()
                print(f"\n[INFO] {ERROR_RETRY_DELAY_SECONDS // 60}분 후 재시도...")
                time.sleep(ERROR_RETRY_DELAY_SECONDS)

    def _run_upload_phase(self):
        """업로드 실행 (upload_new_listings 래퍼)"""
        try:
            rows_uploaded, uploads_successful = self.upload_new_listings()
            if rows_uploaded > 0:
                print(f"\n[UPLOAD] 결과: {uploads_successful}/{rows_uploaded} 성공\n")
            else:
                print("[UPLOAD] 업로드할 매물 없음\n")
        except Exception as e:
            print(f"[UPLOAD] 업로드 오류: {e}")
            self.logger.log_error(0, "UPLOAD_PHASE_ERROR", str(e))

    def _close_beforward_popups(self):
        """Close any popups on ByForward page"""
        try:
            if self.beforward_uploader:
                self.beforward_uploader.close_popups()
                print("[INFO] 팝업 닫기 완료")
        except Exception as e:
            print(f"[경고] 팝업 처리 중 오류: {e}")

    @staticmethod
    def _friendly_fail_reason(step: str, cause: str) -> str:
        """비포워드 업로드 실패 단계/원인을 비전공자용 짧은 한글 메시지로 변환."""
        step = (step or '').strip()
        cause = (cause or '').strip()

        # 폼 검증 실패: 비포워드 화면이 띄운 첫 에러 메시지(보통 "OO은(는) 필수입니다")를 그대로 노출
        if step == '폼_저장_검증':
            tail = cause.replace('validation 오류:', '').strip()
            first = tail.split(';')[0].strip() if tail else ''
            return f"필수 입력값 오류: {first}" if first else "필수 입력값 오류 (비포워드 폼 검증 실패)"

        if step == '재원표_조회':
            # cause 예: "재원표에 모델 없음: 'XXX' - ..."
            if "'" in cause:
                model = cause.split("'")[1] if cause.count("'") >= 2 else ''
                return f"재원표에 차종 없음: {model}" if model else "재원표에 차종 없음"
            return "재원표에 차종 없음 (엑셀 재원표에 차종 추가 필요)"

        if step == '제조사_선택':
            return "제조사를 비포워드 목록에서 찾지 못함"

        if step == '모델_선택':
            return f"모델을 비포워드 목록에서 찾지 못함 ({cause[:60]})" if cause else "모델 선택 실패"

        if step == 'listing_ID_추출':
            return "저장은 됐으나 매물 ID를 찾지 못함 (수동 확인 필요)"

        if step == '폼_저장':
            return f"저장 단계 오류: {cause[:80]}" if cause else "저장 단계 오류"

        if step == '폼_입력_중_예외':
            return f"폼 입력 중 오류: {cause[:80]}" if cause else "폼 입력 중 오류"

        # 알 수 없는 단계
        if step and cause:
            return f"{step}: {cause[:100]}"
        return step or cause or "알 수 없는 오류"

    @staticmethod
    def _normalize_sheet_price(raw_value) -> str:
        """Convert spreadsheet P-column price to an integer string by truncating decimals."""
        if raw_value is None:
            return ""

        cleaned = str(raw_value).strip()
        if not cleaned:
            return ""

        cleaned = cleaned.replace(",", "")
        cleaned = re.sub(r"[^\d.]", "", cleaned)
        if not cleaned:
            return ""

        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            return ""

        truncated = value.quantize(Decimal("1"), rounding=ROUND_DOWN)
        return str(int(truncated))

    @staticmethod
    def _build_upload_price(base_price: str) -> str:
        """P열 가격에 구간별 마크업을 더해 업로드 가격 반환.

        스프레드시트 공식: J2 - IF(J2<=1000,263, IF(J2<=1500,278, ... J2*0.05))
        → P열에 이미 공식 결과가 있으므로, 동일 구간표의 값을 다시 더해 원가 복원 후 업로드.

        P <= 1000  : +263
        P <= 1500  : +278
        P <= 2000  : +283
        P <= 3000  : +303
        P <= 5000  : +358
        P <= 6000  : +388
        P <= 7000  : +410
        P <= 8000  : +439
        P <= 10000 : +495
        P <= 15000 : +630
        P <= 20000 : +739
        P >  20000 : +P*5%
        """
        if not base_price:
            return ""

        try:
            base_value = Decimal(str(base_price))
        except InvalidOperation:
            return ""

        if base_value <= Decimal("1000"):
            markup = Decimal("263")
        elif base_value <= Decimal("1500"):
            markup = Decimal("278")
        elif base_value <= Decimal("2000"):
            markup = Decimal("283")
        elif base_value <= Decimal("3000"):
            markup = Decimal("303")
        elif base_value <= Decimal("5000"):
            markup = Decimal("358")
        elif base_value <= Decimal("6000"):
            markup = Decimal("388")
        elif base_value <= Decimal("7000"):
            markup = Decimal("410")
        elif base_value <= Decimal("8000"):
            markup = Decimal("439")
        elif base_value <= Decimal("10000"):
            markup = Decimal("495")
        elif base_value <= Decimal("15000"):
            markup = Decimal("630")
        elif base_value <= Decimal("20000"):
            markup = Decimal("739")
        else:
            markup = (base_value * Decimal("0.05")).quantize(Decimal("1"), rounding=ROUND_DOWN)

        final_price = (base_value + markup).quantize(Decimal("1"), rounding=ROUND_DOWN)
        return str(int(final_price))

    def _cleanup(self):
        """Clean shutdown - close all drivers"""
        try:
            print("[INFO] Closing browser drivers...")

            if hasattr(self, 'encar_crawler') and self.encar_crawler:
                self.encar_crawler.close()
                print("[OK] Encar crawler closed")

            if hasattr(self, 'beforward_uploader') and self.beforward_uploader:
                self.beforward_uploader.close()
                print("[OK] ByForward uploader closed")

            if hasattr(self, 'encar_checker') and self.encar_checker:
                self.encar_checker.close()
                print("[OK] Encar checker closed")

            if hasattr(self, 'beforward_manager') and self.beforward_manager:
                self.beforward_manager.close()
                print("[OK] ByForward manager closed")

            print("[OK] Cleanup complete")

        except Exception as e:
            print(f"[WARNING] Cleanup error: {e}")


def main():
    """Main entry point"""
    monitor = EncarSoldOutMonitor()

    # Setup
    if not monitor.setup():
        print("\n[실패] Setup failed, exiting...")
        sys.exit(1)

    # Run continuous monitoring
    monitor.run_continuous()


if __name__ == "__main__":
    main()
