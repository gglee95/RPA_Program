"""
Dedicated monitoring worker for Encar sold-out checks.

Runs the monitoring cycle immediately on startup, then repeats on the
configured interval.
"""
import sys
import time
from datetime import datetime

from config import CHECK_INTERVAL_SECONDS, ERROR_RETRY_DELAY_SECONDS, LOG_DIR
from encar_soldout_monitor import EncarSoldOutMonitor


class _Tee:
    """stdout을 콘솔과 txt 파일 양쪽에 동시 출력."""
    def __init__(self, filepath):
        self._file = open(filepath, 'a', encoding='utf-8')
        self._stdout = sys.__stdout__

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)
        self._file.flush()

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        self._file.close()


def main():
    log_path = LOG_DIR / f"monitor_{datetime.now().strftime('%Y%m%d')}.txt"
    tee = _Tee(log_path)
    sys.stdout = tee

    print(f"\n[LOG] 로그 파일: {log_path}")

    worker = EncarSoldOutMonitor()

    if not worker.setup():
        print("\n[FAIL] Setup failed, exiting...")
        sys.stdout = sys.__stdout__
        tee.close()
        sys.exit(1)

    print("\n" + "=" * 70)
    print("BeForward Monitor Worker".center(70))
    print("=" * 70 + "\n")

    worker.logger.log_system_start()

    while True:
        try:
            worker.cycle_count += 1
            now = datetime.now()

            print(f"\n{'=' * 70}")
            print(f"[Cycle {worker.cycle_count}] {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'=' * 70}\n")

            worker.logger.log_cycle_start(worker.cycle_count)
            rows_processed, listings_suspended = worker.run_monitoring_cycle()

            print(
                f"\n[Cycle {worker.cycle_count}] "
                f"Done: checked {rows_processed} rows | suspended {listings_suspended} listings"
            )
            worker.logger.log_cycle_end(
                worker.cycle_count,
                rows_processed,
                listings_suspended,
            )

            print(
                f"[INFO] Waiting {CHECK_INTERVAL_SECONDS // 60} minutes "
                f"for the next monitoring cycle"
            )
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Monitor worker stopping")
            worker._cleanup()
            worker.logger.log_system_shutdown()
            break

        except Exception as exc:
            worker.logger.log_error(0, "MONITOR_WORKER_ERROR", str(exc))
            print(f"[ERROR] Monitor worker error: {exc}")
            time.sleep(ERROR_RETRY_DELAY_SECONDS)

    sys.stdout = sys.__stdout__
    tee.close()


if __name__ == "__main__":
    main()
