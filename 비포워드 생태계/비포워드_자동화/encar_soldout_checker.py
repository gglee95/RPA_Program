"""
Encar SOLD OUT detection module
크롤링 성공 여부로 SOLD OUT 판단:
  - get_car_info() 성공(CarInfo 반환) → 활성 매물
  - get_car_info() 실패(None 반환)   → SOLD OUT
"""
import time
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By

from 엔카_crawling import EncarSeleniumCrawler
from config import MAX_RETRIES, PAGE_TIMEOUT_SECONDS


SOLDOUT_BUTTON_XPATH = '//*[@id="wrap"]/div/div[1]/div[2]/div[2]/div/div/div[2]/div/button'
PRICE_XPATH = '//*[@id="wrap"]/div/div[1]/div[1]/div[5]/div/div[1]/div[1]/p'


class EncarSoldOutChecker:
    """Encar SOLD OUT 상태 체커 - 지정 XPath 기반"""

    def __init__(self, headless: bool = True):
        self.crawler = EncarSeleniumCrawler(headless=headless)
        self.crawler.setup_driver()

        if self.crawler.driver:
            self.crawler.driver.set_page_load_timeout(PAGE_TIMEOUT_SECONDS)

    def check_soldout(self, url: str) -> dict:
        """엔카 링크 접속 후 지정 XPath 버튼 존재 여부로 SOLD OUT 판정

        Args:
            url: Encar listing URL

        Returns:
            dict: {
                'is_soldout': bool,
                'detection_method': str,
                'message': str
            }
        """
        try:
            self.crawler.driver.get(url)
            time.sleep(2)

            soldout_buttons = self.crawler.driver.find_elements(By.XPATH, SOLDOUT_BUTTON_XPATH)
            visible_buttons = [btn for btn in soldout_buttons if btn.is_displayed()]

            if visible_buttons:
                return {
                    'is_soldout': True,
                    'detection_method': 'soldout_button_xpath',
                    'message': 'SOLD OUT 버튼 XPath 확인'
                }

            # 가격 영역에 "(계약중)" 텍스트 감지
            try:
                price_els = self.crawler.driver.find_elements(By.XPATH, PRICE_XPATH)
                for el in price_els:
                    if el.is_displayed():
                        price_text = (el.text or '').strip()
                        if '계약중' in price_text:
                            return {
                                'is_soldout': True,
                                'detection_method': 'contract_in_progress',
                                'message': f'가격 영역 (계약중) 감지: {price_text}'
                            }
            except Exception:
                pass

            return {
                'is_soldout': False,
                'detection_method': 'soldout_button_not_found',
                'message': 'SOLD OUT 버튼 XPath 없음'
            }

        except TimeoutException:
            return {
                'is_soldout': False,
                'detection_method': 'timeout',
                'message': 'Page load timeout - 활성으로 간주'
            }

        except Exception as e:
            return {
                'is_soldout': False,
                'detection_method': 'error',
                'message': f'오류 발생 - 활성으로 간주: {str(e)}'
            }

    def check_with_retry(self, url: str, max_retries: int = MAX_RETRIES) -> dict:
        """재시도 포함 SOLD OUT 체크

        Args:
            url: Encar listing URL
            max_retries: 최대 재시도 횟수

        Returns:
            dict: Detection result
        """
        for attempt in range(max_retries):
            try:
                result = self.check_soldout(url)

                if result['detection_method'] == 'timeout':
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[재시도] Timeout - {wait_time}초 후 재시도...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return result

                return result

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[재시도] 오류 - {wait_time}초 후 재시도...")
                    time.sleep(wait_time)
                    continue
                else:
                    return {
                        'is_soldout': False,
                        'detection_method': 'error',
                        'message': f'{max_retries}회 재시도 후 오류: {str(e)}'
                    }

        return {
            'is_soldout': False,
            'detection_method': 'error',
            'message': '알 수 없는 오류'
        }

    def close(self):
        """브라우저 드라이버 종료"""
        if self.crawler and self.crawler.driver:
            self.crawler.close()


# 테스트
if __name__ == "__main__":
    print("\n=== Encar SOLD OUT Checker Test ===\n")

    checker = EncarSoldOutChecker(headless=False)

    test_url = "https://fem.encar.com/cars/detail/40083049"
    print(f"Testing URL: {test_url}\n")

    result = checker.check_with_retry(test_url)

    print(f"\nResult:")
    print(f"  SOLD OUT: {result['is_soldout']}")
    print(f"  Method: {result['detection_method']}")
    print(f"  Message: {result['message']}")

    checker.close()
