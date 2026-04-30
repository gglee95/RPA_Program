"""
Dedicated upload worker for BeForward listings.

Runs the upload phase immediately on startup, then waits until the configured
daily upload hour to run again.
"""
import sys
import time
from datetime import datetime

from config import ERROR_RETRY_DELAY_SECONDS, UPLOAD_HOUR
from encar_soldout_monitor import EncarSoldOutMonitor


UPLOAD_POLL_SECONDS = 60


def main():
    worker = EncarSoldOutMonitor()

    if not worker.setup():
        print("\n[FAIL] Setup failed, exiting...")
        sys.exit(1)

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

        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Upload worker stopping")
            worker._cleanup()
            worker.logger.log_info("Upload worker stopped")
            break

        except Exception as exc:
            worker.logger.log_error(0, "UPLOAD_WORKER_ERROR", str(exc))
            print(f"[ERROR] Upload worker error: {exc}")
            time.sleep(ERROR_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
