"""
비포워드 자동화 메인 실행 파일

엔카 및 KB차차차 크롤링 기능을 실행합니다.
"""
from 엔카_crawling import EncarSeleniumCrawler
from 비포워드_crawling import BefowordCrawler


def crawl_encar(url: str):
    """엔카 차량 정보 크롤링 (옵션 매핑 포함)

    Args:
        url: 엔카 차량 상세 페이지 URL
    """
    print("\n" + "=" * 60)
    print("엔카 크롤링 시작 (옵션 매핑 포함)".center(60))
    print("=" * 60 + "\n")

    crawler = EncarSeleniumCrawler(headless=True)
    

    try:
        # 차량 정보 크롤링 (옵션 포함)
        car_info = crawler.get_car_info(url, include_options=True)

        if car_info:
            # 정보 출력 (매핑된 옵션만 표시)
            car_info.print_info()

            # 매핑된 옵션 리스트 추출
            if car_info.options:
                mapped_options = [opt for opt in car_info.options if opt.mapped_name]
                print(f"\n비포워드 매핑 가능한 옵션: {len(mapped_options)}개")
                print("-" * 60)
                for opt in mapped_options:
                    print(f"  - {opt.mapped_name}")
                print("-" * 60)

            return car_info
        else:
            print("\n[경고] 차량 정보를 가져올 수 없습니다.")
            return None

    finally:
        crawler.close()


def upload_to_befoword(car_info) -> bool:
    """엔카 차량 정보를 비포워드에 자동 등록

    Args:dl
        car_info: CarInfo 객체 (엔카에서 크롤링한 데이터)

    Returns:
        성공 여부
    """
    print("\n" + "=" * 60)
    print("비포워드 매물 등록 시작".center(60))
    print("=" * 60 + "\n")

    crawler = BefowordCrawler(headless=False)  # 브라우저 보이게

    try:
        # 1. 비포워드 로그인
        if not crawler.login():
            print("\n[실패] 비포워드 로그인 실패")
            return False

        # 2. 차량 정보 자동 입력
        if not crawler.fill_vehicle_data(car_info):
            print("\n[실패] 차량 정보 입력 실패")
            return False

        print("\n[OK] 비포워드 매물 등록 완료!")
        print("브라우저에서 입력 내용을 확인하고 저장 버튼을 눌러주세요.")

        # 사용자가 확인할 수 있도록 대기
        print("\n종료하려면 Enter를 누르세요...")
        input()

        return True

    except Exception as e:
        print(f"\n[오류] 비포워드 업로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        crawler.close()


def main():
    """메인 실행 함수"""
    print("\n" + "=" * 60)
    print("비포워드 자동화 시스템".center(60))
    print("=" * 60 + "\n")

    # 테스트 URL (실제 사용 시 사용자 입력 또는 파라미터로 받음)
    test_url = "https://fem.encar.com/cars/detail/40083049"

    print(f"테스트 URL: {test_url}\n")

    # 1. 엔카 크롤링 실행
    car_info = crawl_encar(test_url)

    if car_info:
        # 2. 비포워드 업로드 여부 확인
        print("\n비포워드에 매물을 등록하시겠습니까? (y/n): ", end="")
        response = input().strip().lower()

        if response == 'y':
            # 3. 비포워드 자동 등록
            upload_to_befoword(car_info)
        else:
            print("\n비포워드 업로드를 건너뜁니다.")

    print("\n" + "=" * 60)
    print("작업 완료".center(60))
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
