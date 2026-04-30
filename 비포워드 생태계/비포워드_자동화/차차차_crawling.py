from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from dataclasses import dataclass
from typing import Optional
import time
import urllib.parse


@dataclass
class CarInfo:
    """차량 정보를 담는 데이터 클래스"""
    # 기본 차량 정보
    manufacturer: Optional[str] = None  # 제조사
    model: Optional[str] = None  # 모델명
    vehicle_number: Optional[str] = None  # 차량번호
    vin: Optional[str] = None  # 차대번호
    year_month: Optional[str] = None
    mileage: Optional[str] = None
    displacement: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    seating_capacity: Optional[str] = None
    price: Optional[str] = None

    # 차량 상태 정보
    seizure: Optional[str] = None  # 압류
    mortgage: Optional[str] = None  # 저당
    insurance_accident: Optional[str] = None  # 보험사고
    total_loss: Optional[str] = None  # 전손이력
    flood_damage: Optional[str] = None  # 침수이력
    usage_history: Optional[str] = None  # 용도이력
    owner_changes: Optional[str] = None  # 소유자변경

    # 판매자 정보
    company_name: Optional[str] = None
    seller_name: Optional[str] = None
    seller_contact: Optional[str] = None
    seller_address: Optional[str] = None

    # 성능점검 정보
    inspection_record: Optional[str] = None

    def print_info(self) -> None:
        """차량 정보를 포맷팅하여 출력"""
        print("\n" + "=" * 60)
        print("차량 정보".center(60))
        print("=" * 60)

        print(f"\n[ 가격 정보 ]")
        print(f"  가격: {self.price or 'N/A'}")

        print(f"\n[ 차량 기본 정보 ]")
        print(f"  제조사: {self.manufacturer or 'N/A'}")
        print(f"  모델명: {self.model or 'N/A'}")
        print(f"  차량번호: {self.vehicle_number or 'N/A'}")
        print(f"  차대번호: {self.vin or 'N/A'}")
        print(f"  연식: {self.year_month or 'N/A'}")
        print(f"  주행거리: {self.mileage or 'N/A'}")

        print(f"\n[ 차량 상세 정보 ]")
        print(f"  배기량: {self.displacement or 'N/A'}")
        print(f"  연료: {self.fuel_type or 'N/A'}")
        print(f"  변속기: {self.transmission or 'N/A'}")
        print(f"  색상: {self.color or 'N/A'}")
        print(f"  인승: {self.seating_capacity or 'N/A'}")

        print(f"\n[ 차량 상태 정보 ]")
        print(f"  압류: {self.seizure or 'N/A'}")
        print(f"  저당: {self.mortgage or 'N/A'}")
        print(f"  보험사고: {self.insurance_accident or 'N/A'}")
        print(f"  전손이력: {self.total_loss or 'N/A'}")
        print(f"  침수이력: {self.flood_damage or 'N/A'}")
        print(f"  용도이력: {self.usage_history or 'N/A'}")
        print(f"  소유자변경: {self.owner_changes or 'N/A'}")

        print(f"\n[ 기타 정보 ]")
        print(f"  지역: {self.location or 'N/A'}")

        print("\n[ 판매자 정보 ]")
        print(f"  업체명: {self.company_name or 'N/A'}")
        print(f"  판매자명: {self.seller_name or 'N/A'}")
        print(f"  연락처: {self.seller_contact or 'N/A'}")
        print(f"  주소: {self.seller_address or 'N/A'}")

        print(f"\n[ 성능점검 정보 ]")
        print(f"  성능점검기록부: {self.inspection_record or 'N/A'}")

        print("=" * 60 + "\n")


class KBChaChaChaCrawler:
    """Selenium을 사용한 KB차차차 크롤러"""
    
    # 타임아웃 상수
    DEFAULT_WAIT_TIMEOUT = 5   # 기본 대기 시간 (초)
    PAGE_LOAD_TIMEOUT = 10     # 페이지 로드 최대 시간 (초)
    
    def __init__(self, headless: bool = False):
        self.driver = None
        self.headless = headless
        self.is_mobile = False  # 모바일 페이지 여부
        
    def setup_driver(self) -> None:
        """Chrome 드라이버 설정 및 초기화"""
        chrome_options = self._create_chrome_options()
        self.driver = webdriver.Chrome(options=chrome_options)
        
        # 페이지 로드 타임아웃 설정
        self.driver.set_page_load_timeout(self.PAGE_LOAD_TIMEOUT)
        
        print("Chrome 드라이버가 초기화되었습니다.")
    
    def _create_chrome_options(self) -> Options:
        """Chrome 옵션 생성"""
        chrome_options = Options()
        
        # 페이지 로드 전략 설정 (DOM만 로드되면 진행)
        chrome_options.page_load_strategy = 'eager'
        
        if self.headless:
            chrome_options.add_argument('--headless')
        
        # 성능 최적화 옵션
        performance_options = [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--window-size=1920,1080',
            '--blink-settings=imagesEnabled=false',  # 이미지 비활성화
            '--disable-extensions',
            '--disable-infobars',
            '--disable-notifications',
            '--disable-popup-blocking',
        ]
        
        for option in performance_options:
            chrome_options.add_argument(option)
        
        # User-Agent 설정
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )
        
        return chrome_options
    
    def _convert_to_pc_url(self, mobile_url: str) -> str:
        """모바일 URL을 PC URL로 변환"""
        if "m.kbchachacha.com" in mobile_url:
            # 모바일 URL을 PC URL로 변환
            pc_url = mobile_url.replace("m.kbchachacha.com", "www.kbchachacha.com")
            pc_url = pc_url.replace("/public/web/car/", "/public/car/")
            print(f"모바일 URL을 PC URL로 변환: {pc_url}")
            return pc_url
        return mobile_url
    
    def _is_mobile_url(self, url: str) -> bool:
        """모바일 URL인지 확인"""
        return "m.kbchachacha.com" in url
        
    def _extract_basic_info(self, wait: WebDriverWait) -> dict:
        """KB차차차 기본 차량 정보 추출"""
        print("\n[ 기본 차량 정보 추출 중... ]")

        vehicle_info = {}

        try:
            if self.is_mobile:
                return self._extract_basic_info_mobile(wait)
            else:
                return self._extract_basic_info_pc(wait)

        except Exception as e:
            print(f"[경고] 기본 차량 정보 추출 실패: {e}")
            import traceback
            traceback.print_exc()
            return vehicle_info

    def _extract_basic_info_pc(self, wait: WebDriverWait) -> dict:
        """PC 버전 기본 차량 정보 추출"""
        vehicle_info = {}

        # 1. 가격 정보 추출
        price_xpath = "//dt[text()='판매가격']/following-sibling::dd/strong"
        price_element = wait.until(EC.presence_of_element_located((By.XPATH, price_xpath)))
        price_text = price_element.text.strip()

        # 가격에서 숫자만 추출 (예: '1,150만원' -> '1150')
        if price_text:
            price = ''.join(c for c in price_text.split('만원')[0] if c.isdigit() or c == ',')
            price = price.replace(',', '')
            vehicle_info['price'] = price

        # 2. 차량명 (차량번호 + 제조사 + 모델) 추출
        car_name_xpath = "//strong[@class='car-buy-name']"
        car_name_element = wait.until(EC.presence_of_element_located((By.XPATH, car_name_xpath)))
        car_name_text = car_name_element.text.replace('\n', ' ').strip()

        # 차량번호와 제조사/모델 분리 (예: "(374마6535)아우디 NEW A6 40 TDI 콰트로 프리미엄 C7(15~)")
        if '(' in car_name_text and ')' in car_name_text:
            vehicle_number = car_name_text.split('(')[1].split(')')[0]
            vehicle_info['vehicle_number'] = vehicle_number

            # 제조사와 모델 분리
            model_part = car_name_text.split(')')[1].strip()
            # 첫 번째 단어가 제조사
            parts = model_part.split(' ', 1)
            if len(parts) > 0:
                vehicle_info['manufacturer'] = parts[0]
            if len(parts) > 1:
                vehicle_info['model'] = parts[1]

        # 3. 테이블에서 차량 상세 정보 추출
        # 연식
        year_xpath = "//th[contains(text(), '연식')]/following-sibling::td"
        year_element = self.driver.find_element(By.XPATH, year_xpath)
        year_text = year_element.text.strip()
        # '16년03월(16년형)' -> '2016'
        if '(' in year_text:
            year_text = year_text.split('(')[0]
        # "XX년" 형식에서 XX 추출하여 4자리 연도로 변환
        import re
        match = re.search(r'(\d{2})년', year_text)
        if match:
            year = match.group(1)
            vehicle_info['year_month'] = '20' + year  # 2014, 2015 등
        else:
            vehicle_info['year_month'] = year_text

        # 주행거리
        mileage_xpath = "//th[contains(text(), '주행거리')]/following-sibling::td"
        mileage_element = self.driver.find_element(By.XPATH, mileage_xpath)
        mileage_text = mileage_element.text.strip()
        # '231,000km' -> '231000'
        mileage = ''.join(c for c in mileage_text if c.isdigit() or c == ',').replace(',', '')
        vehicle_info['mileage'] = mileage

        # 연료
        fuel_xpath = "//th[contains(text(), '연료')]/following-sibling::td"
        fuel_element = self.driver.find_element(By.XPATH, fuel_xpath)
        vehicle_info['fuel_type'] = fuel_element.text.strip()

        # 변속기
        transmission_xpath = "//th[contains(text(), '변속기')]/following-sibling::td"
        transmission_element = self.driver.find_element(By.XPATH, transmission_xpath)
        vehicle_info['transmission'] = transmission_element.text.strip()

        # 색상
        try:
            color_xpath = "//th[contains(text(), '색상')]/following-sibling::td"
            color_element = self.driver.find_element(By.XPATH, color_xpath)
            vehicle_info['color'] = color_element.text.strip()
        except:
            vehicle_info['color'] = ""

        # 압류
        try:
            seizure_xpath = "//th[contains(text(), '압류')]/following-sibling::td"
            seizure_element = self.driver.find_element(By.XPATH, seizure_xpath)
            seizure_text = seizure_element.text.strip()
            vehicle_info['seizure'] = seizure_text if seizure_text else "없음"
        except:
            vehicle_info['seizure'] = ""

        # 저당
        try:
            mortgage_xpath = "//th[contains(text(), '저당')]/following-sibling::td"
            mortgage_element = self.driver.find_element(By.XPATH, mortgage_xpath)
            mortgage_text = mortgage_element.text.strip()
            vehicle_info['mortgage'] = mortgage_text if mortgage_text else "없음"
        except:
            vehicle_info['mortgage'] = ""

        # 배기량 (있을 경우)
        try:
            displacement_xpath = "//th[contains(text(), '배기량')]/following-sibling::td"
            displacement_element = self.driver.find_element(By.XPATH, displacement_xpath)
            displacement_text = displacement_element.text.strip()
            displacement = ''.join(c for c in displacement_text if c.isdigit())
            vehicle_info['displacement'] = displacement
        except:
            vehicle_info['displacement'] = ""

        # 지역 정보 (판매자 위치에서 추출)
        try:
            location_xpath = "//span[@class='place-add']"
            location_element = self.driver.find_element(By.XPATH, location_xpath)
            vehicle_info['location'] = location_element.text.strip()
        except:
            vehicle_info['location'] = ""

        print("[OK] 기본 차량 정보 추출 완료")
        return vehicle_info

    def _extract_vehicle_status_info(self, wait: WebDriverWait) -> dict:
        """KB차차차 차량 상태 정보 추출 (보험사고, 전손이력, 침수이력 등)"""
        print("\n[ 차량 상태 정보 추출 중... ]")

        status_info = {}

        try:
            if self.is_mobile:
                return self._extract_vehicle_status_info_mobile(wait)
            else:
                return self._extract_vehicle_status_info_pc(wait)

        except Exception as e:
            print(f"[경고] 차량 상태 정보 추출 실패: {e}")
            import traceback
            traceback.print_exc()
            return status_info

    def _extract_vehicle_status_info_pc(self, wait: WebDriverWait) -> dict:
        """PC 버전 차량 상태 정보 추출"""
        status_info = {}

        # 전손이력
        try:
            total_loss_xpath = "//dt[contains(text(), '전손이력')]/following-sibling::dd"
            total_loss_element = self.driver.find_element(By.XPATH, total_loss_xpath)
            total_loss_text = total_loss_element.text.strip()
            status_info['total_loss'] = total_loss_text if total_loss_text else "없음"
        except:
            status_info['total_loss'] = ""

        # 침수이력
        try:
            flood_xpath = "//dt[contains(text(), '침수이력')]/following-sibling::dd"
            flood_element = self.driver.find_element(By.XPATH, flood_xpath)
            flood_text = flood_element.text.strip()
            status_info['flood_damage'] = flood_text if flood_text else "없음"
        except:
            status_info['flood_damage'] = ""

        # 용도이력
        try:
            usage_xpath = "//dt[contains(text(), '용도이력')]/following-sibling::dd"
            usage_element = self.driver.find_element(By.XPATH, usage_xpath)
            usage_text = usage_element.text.strip()
            status_info['usage_history'] = usage_text if usage_text else "없음"
        except:
            status_info['usage_history'] = ""

        # 소유자변경
        try:
            owner_xpath = "//dt[contains(text(), '소유자변경')]/following-sibling::dd"
            owner_element = self.driver.find_element(By.XPATH, owner_xpath)
            owner_text = owner_element.text.strip()
            status_info['owner_changes'] = owner_text if owner_text else "0회"
        except:
            status_info['owner_changes'] = ""

        # 보험사고정보
        try:
            accident_xpath = "//span[@class='fs-16' and contains(text(), '보험사고정보')]/following-sibling::span[@class='link-arrow']"
            accident_element = self.driver.find_element(By.XPATH, accident_xpath)
            accident_text = accident_element.text.strip()
            status_info['insurance_accident'] = accident_text if accident_text else "없음"
        except:
            status_info['insurance_accident'] = "없음"

        print("[OK] 차량 상태 정보 추출 완료")
        return status_info

    def _extract_seller_info(self, wait: WebDriverWait) -> dict:
        """KB차차차 판매자 정보 추출"""
        print("\n[ 판매자 정보 추출 중... ]")

        seller_info = {}

        try:
            if self.is_mobile:
                return self._extract_seller_info_mobile(wait)
            else:
                return self._extract_seller_info_pc(wait)

        except Exception as e:
            print(f"[경고] 판매자 정보 추출 실패: {e}")
            import traceback
            traceback.print_exc()
            return seller_info

    def _extract_seller_info_pc(self, wait: WebDriverWait) -> dict:
        """PC 버전 판매자 정보 추출"""
        seller_info = {}

        # 판매자명
        try:
            seller_name_xpath = "//span[@class='name']"
            seller_name_element = self.driver.find_element(By.XPATH, seller_name_xpath)
            seller_name_text = seller_name_element.text.strip()
            # '신지환 딜러' -> '신지환'
            if ' 딜러' in seller_name_text:
                seller_info['seller_name'] = seller_name_text.replace(' 딜러', '').strip()
            else:
                seller_info['seller_name'] = seller_name_text
        except:
            seller_info['seller_name'] = ""

        # 연락처
        try:
            contact_xpath = "//div[@class='dealer-tel-num']"
            contact_element = self.driver.find_element(By.XPATH, contact_xpath)
            seller_info['seller_contact'] = contact_element.text.strip()
        except:
            seller_info['seller_contact'] = ""

        # 상사명
        try:
            company_xpath = "//p[contains(text(), '상사명')]"
            company_element = self.driver.find_element(By.XPATH, company_xpath)
            company_text = company_element.text.strip()
            # '상사명 : (주)골드상사' -> '(주)골드상사'
            if ':' in company_text:
                seller_info['company_name'] = company_text.split(':')[1].strip()
            else:
                seller_info['company_name'] = company_text
        except:
            seller_info['company_name'] = ""

        # 주소
        try:
            address_xpath = "//p[contains(text(), '주소')]"
            address_element = self.driver.find_element(By.XPATH, address_xpath)
            address_text = address_element.text.strip()
            # '주소 : 경기 안산시 단원구 풍전로 53 (원곡동)' -> '경기 안산시 단원구 풍전로 53 (원곡동)'
            if ':' in address_text:
                seller_info['seller_address'] = address_text.split(':')[1].strip()
            else:
                seller_info['seller_address'] = address_text
        except:
            seller_info['seller_address'] = ""

        print("[OK] 판매자 정보 추출 완료")
        return seller_info

    def _extract_inspection_info(self) -> dict:
        """KB차차차 성능점검 정보 추출 및 차대번호 추출"""
        print("\n[ 성능점검 정보 추출 중... ]")

        result = {
            'inspection_record': "없음",
            'vin': ""
        }

        try:
            if self.is_mobile:
                return self._extract_inspection_info_mobile()
            else:
                return self._extract_inspection_info_pc()

        except Exception as e:
            print(f"[경고] 성능점검 정보 추출 실패: {e}")
            import traceback
            traceback.print_exc()
            return result

    def _extract_inspection_info_pc(self) -> dict:
        """PC 버전 성능점검 정보 추출"""
        result = {
            'inspection_record': "없음",
            'vin': ""
        }

        inspection_url = None

        # btnCarCheckView1 버튼의 data-link-url 속성에서 검사 링크 추출
        try:
            btn_element = self.driver.find_element(By.ID, "btnCarCheckView1")
            inspection_url = btn_element.get_attribute('data-link-url')
            if inspection_url:
                print(f"  성능점검기록부 링크 발견")
        except:
            print("  성능점검기록부 링크를 찾을 수 없습니다.")

        if inspection_url:
            result['inspection_record'] = "있음"
            print(f"  성능점검기록부 URL: {inspection_url}")

            # 성능점검 페이지에서 차대번호 추출
            vin = self._extract_vin_from_inspection_page(inspection_url)
            if vin:
                result['vin'] = vin
                print(f"  차대번호: {vin}")

        print("[OK] 성능점검 정보 추출 완료")
        return result

    def _safe_print(self, msg: str) -> None:
        """Windows 콘솔 인코딩 문제를 방지하는 안전한 print"""
        try:
            print(msg)
        except (UnicodeEncodeError, OSError):
            try:
                print(msg.encode('ascii', errors='replace').decode('ascii'))
            except:
                pass

    def _extract_vin_from_inspection_page(self, inspection_url: str) -> str:
        """성능점검 페이지에서 차대번호 추출"""
        import time

        main_window = None
        new_tab_opened = False

        try:
            self._safe_print("  [VIN] Step 1: Saving main window handle")
            main_window = self.driver.current_window_handle
            original_handles = set(self.driver.window_handles)

            # 빈 탭을 먼저 열고, 그 다음 navigate (page_load_timeout 문제 방지)
            self._safe_print("  [VIN] Step 2: Opening blank new tab")
            self.driver.execute_script("window.open('about:blank', '_blank');")
            time.sleep(1)

            # 새 탭으로 전환
            new_handles = set(self.driver.window_handles)
            new_tab = (new_handles - original_handles)

            if not new_tab:
                self._safe_print("  [VIN] ERROR: New tab not found")
                return ""

            new_tab_handle = new_tab.pop()
            self.driver.switch_to.window(new_tab_handle)
            new_tab_opened = True
            self._safe_print("  [VIN] Step 3: Switched to new tab")

            # page_load_timeout을 늘려서 리다이렉트 대기
            original_timeout = self.PAGE_LOAD_TIMEOUT
            self.driver.set_page_load_timeout(30)

            try:
                self._safe_print(f"  [VIN] Step 4: Navigating to inspection URL")
                self.driver.get(inspection_url)
                self._safe_print(f"  [VIN] Step 5: Page loaded, current URL: {self.driver.current_url}")
            except TimeoutException:
                self._safe_print("  [VIN] Step 4: Page load timeout - trying to extract anyway")
            except Exception as nav_e:
                self._safe_print(f"  [VIN] Step 4: Navigation error: {type(nav_e).__name__}")

            # 타임아웃 복원
            self.driver.set_page_load_timeout(original_timeout)

            # 리다이렉트 + DOM 렌더링 대기
            time.sleep(5)

            self._safe_print(f"  [VIN] Step 6: Final URL: {self.driver.current_url}")

            # 차대번호 추출 (th→td 텍스트 방식)
            vin = ""

            try:
                vin_element = self.driver.find_element(
                    By.XPATH, "//th[contains(text(), '\ucc28\ub300\ubc88\ud638')]/following-sibling::td"
                )
                vin = vin_element.text.strip()
                if vin:
                    self._safe_print(f"  [VIN] Found: {vin}")
            except Exception as e:
                self._safe_print(f"  [VIN] Not found: {type(e).__name__}")

            # 새 탭 닫기
            self.driver.close()
            new_tab_opened = False
            self._safe_print("  [VIN] Step 7: Closed new tab")

            # 메인 윈도우로 돌아가기
            self.driver.switch_to.window(main_window)
            self._safe_print("  [VIN] Step 8: Back to main window")

            return vin

        except Exception as e:
            error_type = type(e).__name__
            try:
                error_msg = str(e)
            except:
                error_msg = "unknown"
            self._safe_print(f"  [VIN] CRITICAL ERROR: {error_type}: {error_msg}")

            # 에러 발생 시에도 메인 윈도우로 돌아가기
            try:
                if new_tab_opened:
                    self.driver.close()
            except:
                pass
            try:
                if main_window:
                    self.driver.switch_to.window(main_window)
            except:
                pass

            return ""
    
    def get_car_info(self, url: str) -> Optional[CarInfo]:
        """KB차차차 모든 차량 정보 추출"""
        if not self.driver:
            self.setup_driver()

        try:
            # 모바일 URL인지 확인하고 처리
            if self._is_mobile_url(url):
                print("모바일 URL이 감지되었습니다.")
                self.is_mobile = True
                # 모바일 URL을 PC URL로 변환 시도
                pc_url = self._convert_to_pc_url(url)
                if pc_url != url:
                    print(f"PC URL로 변환하여 접속: {pc_url}")
                    url = pc_url
                    self.is_mobile = False  # PC URL로 접속했으므로 모바일 플래그 해제
            else:
                self.is_mobile = False

            self._print_crawling_header(url)

            # 페이지 로드
            self.driver.get(url)
            wait = WebDriverWait(self.driver, self.DEFAULT_WAIT_TIMEOUT)

            # 페이지 로드 대기
            import time
            time.sleep(0.5)  # 페이지가 완전히 로드될 때까지 대기

            # 1. 기본 차량 정보 추출
            basic_info = self._extract_basic_info(wait)
            if not basic_info:
                print("[경고] 기본 차량 정보 추출 실패")
                return None

            # 2. 차량 상태 정보 추출 (보험사고, 전손이력 등)
            status_info = self._extract_vehicle_status_info(wait)

            # 3. 판매자 정보 추출
            seller_info = self._extract_seller_info(wait)

            # 4. 성능점검 정보 추출
            inspection_info = self._extract_inspection_info()

            # 5. 모든 정보 통합
            all_info = {**basic_info, **status_info, **seller_info, **inspection_info}
            car_info = CarInfo(**all_info)

            print("\n[OK] 모든 정보 추출 완료")
            return car_info

        except TimeoutException:
            print("[경고] 요소를 찾는데 시간이 초과되었습니다.")
            return None
        except Exception as e:
            print(f"[경고] 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _print_crawling_header(self, url: str) -> None:
        """크롤링 시작 헤더 출력"""
        print(f"\n{'='*60}")
        print(f"차량 정보 크롤링 시작".center(60))
        print(f"{'='*60}")
        print(f"URL: {url}")
        print(f"모바일 페이지: {'예' if self.is_mobile else '아니오'}\n")
    
    def close(self) -> None:
        """드라이버 종료"""
        if self.driver:
            self.driver.quit()
            print("\n[OK] 드라이버가 종료되었습니다.")


def main():
    """메인 실행 함수"""
    start_time = time.time()

    print(f"\n{'='*60}")
    print("크롤링 시작".center(60))
    print(f"{'='*60}\n")

    # 테스트 URL (모바일과 PC URL 모두 테스트 가능)
    urls = [
        "https://www.kbchachacha.com/public/car/detail.kbc?carSeq=27666401",  # PC URL
        "https://m.kbchachacha.com/public/web/car/detail.kbc?carSeq=27649040"  # 모바일 URL
    ]

    crawler = KBChaChaChaCrawler(headless=True)

    try:
        for i, url in enumerate(urls, 1):
            print(f"\n{'='*60}")
            print(f"차량 {i}/{len(urls)} 크롤링 중...")
            print(f"{'='*60}")

            car_info = crawler.get_car_info(url)

            if car_info:
                car_info.print_info()
            else:
                print("\n[경고] 차량 정보를 가져올 수 없습니다.")

        # 크롤링 완료 시점 측정
        crawling_time = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"순수 크롤링 시간: {crawling_time:.2f}초 ({crawling_time/60:.2f}분)")
        print(f"{'='*60}")

    finally:
        # 드라이버 종료 시간 측정
        close_start = time.time()
        crawler.close()
        close_time = time.time() - close_start

        # 전체 시간 출력
        total_time = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"드라이버 종료 시간: {close_time:.2f}초")
        print(f"총 실행 시간: {total_time:.2f}초 ({total_time/60:.2f}분)")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()