"""
Dedicated upload worker for BeForward listings.

Runs the upload phase immediately on startup, then waits until the configured
daily upload hour to run again.
"""
import sys
import time
import atexit
import signal
from datetime import datetime

from config import ERROR_RETRY_DELAY_SECONDS, UPLOAD_HOUR
from encar_soldout_monitor import EncarSoldOutMonitor


UPLOAD_POLL_SECONDS = 60


def main():
    worker = EncarSoldOutMonitor()

    if not worker.setup():
        print("\n[FAIL] Setup failed, exiting...")
        sys.exit(1)

    # 정상 종료·크래시·강제 종료 모두 cleanup 보장
    atexit.register(worker._cleanup)

    def _signal_handler(signum, _frame):
        print(f"\n[SHUTDOWN] Signal {signum} 수신 — 종료 중...")
        sys.exit(0)  # atexit 호출됨

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print("\n" + "=" * 70)
    print("BeForward Upload Worker".center(70))
    print("=" * 70 + "\n")

    worker.logger.log_info("Upload worker started")

    print("[STARTUP] Initial upload run")
    worker._run_upload_phase()

    last_upload_date = datetime.now().strftime("%Y-%m-%d")

    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")

            if now.hour >= UPLOAD_HOUR and last_upload_date != today:
                print(f"[UPLOAD] Starting daily upload for {today} at hour {UPLOAD_HOUR}")
                worker._run_upload_phase()
                last_upload_date = today

            time.sleep(UPLOAD_POLL_SECONDS)

        except (KeyboardInterrupt, SystemExit):
            print("\n[SHUTDOWN] Upload worker stopping")
            worker.logger.log_info("Upload worker stopped")
            break  # atexit가 _cleanup() 호출

        except Exception as exc:
            worker.logger.log_error(0, "UPLOAD_WORKER_ERROR", str(exc))
            print(f"[ERROR] Upload worker error: {exc}")
            time.sleep(ERROR_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
