"""
RPA_Program 통합 실행기

사용법:
    python main.py <서비스명>

서비스 목록:
    beforward-monitor   BeForward 판매완료 모니터 (30분 주기 무한 루프)
    beforward-upload    BeForward 일일 업로드 워커 (16:00 자동 실행)
    beforward-main      BeForward 수동 일괄 업로드 (Befoword.py)
    mango-beforward     망고카 → BeForward 자동 업로드 (지지오토)
    offer-check         해외영업 오퍼 검수 자동화 (멀티사이트 크롤러)
    k-car               K-Car 경매 크롤러
    inquiry-log         문의 로그 대시보드 API → Sheets 동기화

예시:
    python main.py beforward-monitor
    python main.py offer-check
"""
import sys
import os
import runpy
import argparse
from pathlib import Path

ROOT = Path(__file__).parent

SERVICES = {
    "beforward-monitor": {
        "cwd": ROOT / "비포워드 생태계" / "비포워드_자동화",
        "module": "beforward_monitor_worker",
        "description": "BeForward 판매완료 모니터 (30분 주기)",
    },
    "beforward-upload": {
        "cwd": ROOT / "비포워드 생태계" / "비포워드_자동화",
        "module": "beforward_upload_worker",
        "description": "BeForward 일일 업로드 워커 (16:00)",
    },
    "beforward-main": {
        "cwd": ROOT / "비포워드 생태계" / "비포워드_자동화",
        "module": "encar_soldout_monitor",
        "description": "BeForward 업로드+모니터 통합 실행",
    },
    "mango-beforward": {
        "cwd": ROOT / "비포워드 생태계" / "지지오토_자동업로드",
        "module": "mango_to_beforward",
        "description": "망고카(지지오토) → BeForward 자동 업로드",
    },
    "offer-check": {
        "cwd": ROOT / "스프레드시트" / "offfer_check_autoupload",
        "module": "docker_main",
        "description": "해외영업 오퍼 검수 자동화 (엔카/차차차/망고카)",
    },
    "k-car": {
        "cwd": ROOT / "스프레드시트" / "k-car",
        "module": "crawler",
        "description": "K-Car 경매 크롤러 (Playwright)",
    },
    "inquiry-log": {
        "cwd": ROOT / "스프레드시트" / "문의로그대시보드_자동업로드_API",
        "module": "upload_to_sheets_API",
        "description": "문의 로그 API → Google Sheets 동기화",
    },
}


def list_services():
    print("\n사용 가능한 서비스:")
    print("-" * 55)
    for name, info in SERVICES.items():
        print(f"  {name:<22}  {info['description']}")
    print()


def run_service(name: str):
    svc = SERVICES[name]
    cwd = svc["cwd"]

    if not cwd.exists():
        print(f"[오류] 서비스 디렉토리를 찾을 수 없습니다: {cwd}", file=sys.stderr)
        sys.exit(1)

    print(f"[RPA] 서비스 시작: {name}")
    print(f"[RPA] 디렉토리: {cwd}")
    print(f"[RPA] 모듈: {svc['module']}")
    print("-" * 55)

    os.chdir(cwd)
    sys.path.insert(0, str(cwd))
    runpy.run_module(svc["module"], run_name="__main__", alter_sys=True)


def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="RPA_Program 통합 실행기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            f"  {k:<22}  {v['description']}" for k, v in SERVICES.items()
        ),
    )
    parser.add_argument(
        "service",
        nargs="?",
        choices=list(SERVICES.keys()),
        help="실행할 서비스 이름",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="사용 가능한 서비스 목록 출력",
    )

    args = parser.parse_args()

    if args.list or args.service is None:
        list_services()
        if args.service is None and not args.list:
            parser.print_help()
        return

    run_service(args.service)


if __name__ == "__main__":
    main()
