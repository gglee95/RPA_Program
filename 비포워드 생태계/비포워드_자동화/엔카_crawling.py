from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from dataclasses import dataclass, field
from typing import Optional, List
import time
import re
import os
import random

# geckodriver 자동 설치 (Docker 환경 고려하여 함수로 분리)
try:
    import geckodriver_autoinstaller
    GECKODRIVER_AUTOINSTALLER_AVAILABLE = True
except ImportError:
    GECKODRIVER_AUTOINSTALLER_AVAILABLE = False


@dataclass
class CarInfo:
    """차량 정보를 담는 데이터 클래스"""
    # 기본 차량 정보
    vehicle_number: Optional[str] = None
    year_month: Optional[str] = None
    mileage: Optional[str] = None
    displacement: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    car_type: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    seating_capacity: Optional[str] = None
    seizure_mortgage: Optional[str] = None
    price: Optional[str] = None

    # 판매자 정보
    company_name: Optional[str] = None  # 업체명
    seller_name: Optional[str] = None   # 판매자명
    seller_contact: Optional[str] = None
    seller_address: Optional[str] = None  # 판매자 주소

    # 성능점검 정보
    inspection_record: Optional[str] = None

    # 모니터링/업로드용 추가 필드
    inspection_chassis_no: Optional[str] = None  # 구글 시트 AA열 VIN (덮어쓰기용)
    options: List = field(default_factory=list)    # 옵션 리스트 (OptionItem 객체)

    def print_info(self) -> None:
        """차량 정보를 포맷팅하여 출력"""
        print("\n" + "=" * 60)
        print("차량 정보".center(60))
        print("=" * 60)

        print(f"\n[ 가격 정보 ]")
        print(f"  가격: {self.price or 'N/A'}")

        print(f"\n[ 차량 기본 정보 ]")
        print(f"  차량번호: {self.vehicle_number or 'N/A'}")
        print(f"  연식: {self.year_month or 'N/A'}")
        print(f"  주행거리: {self.mileage or 'N/A'}")
        print(f"  차종: {self.car_type or 'N/A'}")

        print(f"\n[ 차량 상세 정보 ]")
        print(f"  배기량: {self.displacement or 'N/A'}")
        print(f"  연료: {self.fuel_type or 'N/A'}")
        print(f"  변속기: {self.transmission or 'N/A'}")
        print(f"  색상: {self.color or 'N/A'}")
        print(f"  인승: {self.seating_capacity or 'N/A'}")

        print(f"\n[ 기타 정보 ]")
        print(f"  지역: {self.location or 'N/A'}")
        print(f"  압류·저당: {self.seizure_mortgage or 'N/A'}")

        print(f"\n[ 판매자 정보 ]")
        print(f"  업체명: {self.company_name or 'N/A'}")
        print(f"  판매자명: {self.seller_name or 'N/A'}")
        print(f"  연락처: {self.seller_contact or 'N/A'}")
        print(f"  주소: {self.seller_address or 'N/A'}")

        print(f"\n[ 성능점검 정보 ]")
        print(f"  성능점검기록부: {self.inspection_record or 'N/A'}")

        print("=" * 60 + "\n")


@dataclass
class OptionItem:
    """차량 옵션 아이템"""
    name: str                          # 엔카 표기명 (한국어)
    mapped_name: Optional[str] = None  # 비포워드 매핑명 (영어)


# 엔카 옵션 → 비포워드 표시명 매핑
# 매핑 있는 것: 비포워드 라벨로 변환
# 매핑 없는 것: 엔카 이름 그대로 사용 (코드에서 fallback 처리)
OPTION_MAP = {
    # ── 엑셀 매핑 기준 ──────────────────────────────────────────
    '선루프': '선루프',
    '에어백': '에어백',
    '360도 어라운드 뷰': '360도 카메라',
    '스마트키': 'Push Start',
    '스마트 키': 'Push Start',
    '가죽시트': '가죽시트',
    '알루미늄 휠': '알로이 휠',
    '파워 도어록': '중앙잠금장치',
    '에어백(사이드)': '사이드 에어백',
    '차체자세 제어장치(ESC)': 'ESC',
    '내비게이션': '네비게이션',
    '네비게이션': '네비게이션',
    'CD 플레이어': 'CD Player',
    '전동시트': '파워 시트',
    '전동시트(운전석,동승석)': '파워 시트',
    '전동시트(운전석)': '파워 시트',
    '파워 스티어링 휠': '파워핸들',
    '파워 윈도우': '파워 윈도우',
    '브레이크 잠김 방지(ABS)': 'ABS',
    '후방 카메라': '백 카메라',
    '후방카메라': '백 카메라',
    '자동 에어컨': '에어컨',
    # ── 추가 별칭 ────────────────────────────────────────────────
    '파워시트': '파워 시트',
    '반가죽시트': '가죽시트',
    '어라운드뷰': '360도 카메라',
    '360도카메라': '360도 카메라',
}


class EncarSeleniumCrawler:
    """Selenium + Firefox를 사용한 엔카 크롤러"""

    # 타임아웃 상수
    DEFAULT_WAIT_TIMEOUT = 10   # 기본 대기 시간 (초) - Firefox는 충분한 여유
    PAGE_LOAD_TIMEOUT = 30      # 페이지 로드 최대 시간 (초)

    # XPath 상수 정의
    XPATHS = {
        'car_type': '//*[@id="wrap"]/div/div[1]/div[1]/div[4]/div[1]/h3',  # 전체 차종명 (상위 요소)
        'info_button': '//*[@id="wrap"]/div/div[1]/div[1]/div[4]/div[1]/div/button',
        'price': '//*[@id="wrap"]/div/div[1]/div[1]/div[5]/div/div[1]/div[1]/p',
        'vehicle_info_base': '//*[@id="bottom_sheet"]/div[2]/div[2]/div/ul/li[{}]/span',
        'contact_button': '//*[@id="wrap"]/div/div[1]/div[1]/div[5]/div/div[1]/div[4]/button',
        'seller_phone_button': '//*[@id="bottom_sheet"]/div[2]/div[2]/div/div[2]/button[2]',
        # 승용차 XPath (기본)
        'seller_contact': '//*[@id="bottom_sheet"]/div[2]/div[2]/div/div[1]/p[2]',
        'seller_name': '//*[@id="bottom_sheet"]/div[2]/div[2]/div/div[1]/p[1]',
        # 화물차 XPath (fallback)
        'seller_contact_truck': '//*[@id="bottom_sheet"]//p[2]',
        'seller_name_truck': '//*[@id="bottom_sheet"]//p[1]',
        'inspection_record': '//*[@id="bodydiv"]/div[2]/div/div[2]/table/tbody/tr[4]/td[2]',
    }

    def __init__(self, headless: bool = False):
        self.driver = None
        self.headless = headless

    @staticmethod
    def _clean_price(price_text: str) -> str:
        """가격 정제: '550만원' -> '550'"""
        if not price_text:
            return ""
        # 숫자만 추출 (쉼표 포함)
        numbers = re.findall(r'[\d,]+', price_text)
        if numbers:
            # 쉼표 제거하고 첫 번째 숫자 반환
            return numbers[0].replace(',', '')
        return ""

    @staticmethod
    def _clean_year(year_text: str) -> str:
        """연식 정제: '12년 12월 (13년형)' -> '2012'"""
        if not year_text:
            return ""
        # 첫 번째 숫자 추출 (연도)
        match = re.search(r'(\d{2})년', year_text)
        if match:
            year = int(match.group(1))
            # 2000년대로 변환 (12 -> 2012)
            if year < 50:
                return str(2000 + year)
            else:
                return str(1900 + year)
        return ""

    @staticmethod
    def _clean_displacement(displacement_text: str) -> str:
        """배기량 정제: '1,591cc' -> '1591'"""
        if not displacement_text:
            return ""
        # 숫자와 쉼표만 추출
        numbers = re.findall(r'[\d,]+', displacement_text)
        if numbers:
            # 쉼표 제거
            return numbers[0].replace(',', '')
        return ""

    @staticmethod
    def _clean_mileage(mileage_text: str) -> str:
        """주행거리 정제: '123,456km' -> '123456'"""
        if not mileage_text:
            return ""
        # 숫자와 쉼표만 추출
        numbers = re.findall(r'[\d,]+', mileage_text)
        if numbers:
            # 쉼표 제거
            return numbers[0].replace(',', '')
        return ""

    def setup_driver(self) -> None:
        """Firefox 드라이버 설정 및 초기화"""
        firefox_options = self._create_firefox_options()

        # geckodriver 자동 설치 시도 (로컬 환경에서만)
        if GECKODRIVER_AUTOINSTALLER_AVAILABLE:
            try:
                geckodriver_autoinstaller.install()
                print("geckodriver 자동 설치 완료")
            except Exception as e:
                print(f"[경고] geckodriver 자동 설치 실패 (무시하고 계속): {e}")

        # geckodriver 경로 찾기
        geckodriver_path = self._find_geckodriver()

        if geckodriver_path:
            print(f"geckodriver 경로: {geckodriver_path}")
            service = Service(geckodriver_path)
            self.driver = webdriver.Firefox(service=service, options=firefox_options)
        else:
            # PATH에서 자동으로 찾기 (Docker 환경 등)
            print("geckodriver를 PATH에서 찾습니다...")
            self.driver = webdriver.Firefox(options=firefox_options)

        # 페이지 로드 타임아웃 설정
        self.driver.set_page_load_timeout(self.PAGE_LOAD_TIMEOUT)

        # JavaScript를 통한 추가 봇 탐지 회피
        self._inject_anti_detection_js()

        print("Firefox 드라이버가 초기화되었습니다.")

    def _find_geckodriver(self) -> Optional[str]:
        """geckodriver 경로 찾기"""
        # 1. 현재 디렉토리
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Windows와 Linux 모두 지원
        for filename in ['geckodriver.exe', 'geckodriver']:
            geckodriver_path = os.path.join(current_dir, filename)
            if os.path.exists(geckodriver_path):
                return geckodriver_path

        # 2. 일반적인 다운로드 위치 (Windows)
        common_paths = [
            os.path.join(os.path.expanduser('~'), 'Downloads', 'geckodriver.exe'),
            'C:\\geckodriver\\geckodriver.exe',
            'geckodriver.exe',
        ]

        # 3. Linux 일반 경로
        if os.name != 'nt':  # Linux/Mac
            common_paths.extend([
                '/usr/local/bin/geckodriver',
                '/usr/bin/geckodriver',
                'geckodriver',
            ])

        for path in common_paths:
            if os.path.exists(path):
                return path

        # 찾지 못함 - PATH에서 찾도록 None 반환
        return None

    def _create_firefox_options(self) -> Options:
        """Firefox 옵션 생성"""
        firefox_options = Options()

        # 페이지 로드 전략 설정 (headless에서는 완전히 로드될 때까지 대기)
        if self.headless:
            firefox_options.page_load_strategy = 'normal'  # headless에서는 완전 로드
        else:
            firefox_options.page_load_strategy = 'eager'  # 일반 모드에서는 eager

        if self.headless:
            firefox_options.add_argument('--headless')

        # 기본 옵션
        firefox_options.add_argument('--width=1920')
        firefox_options.add_argument('--height=1080')

        # Firefox 프로필 설정
        firefox_options.set_preference('permissions.default.image', 2)  # 이미지 비활성화
        firefox_options.set_preference('dom.ipc.plugins.enabled.libflashplayer.so', False)
        firefox_options.set_preference('dom.webnotifications.enabled', False)  # 알림 비활성화
        firefox_options.set_preference('media.autoplay.default', 5)  # 자동재생 차단
        firefox_options.set_preference('privacy.trackingprotection.enabled', False)  # 추적 방지 비활성화 (크롤링 안정성)

        # WebDriver 탐지 회피 (Firefox는 기본적으로 Chrome보다 탐지가 어려움)
        firefox_options.set_preference('dom.webdriver.enabled', False)
        firefox_options.set_preference('useAutomationExtension', False)

        # 추가 봇 탐지 회피 설정
        firefox_options.set_preference('media.peerconnection.enabled', False)  # WebRTC 비활성화
        firefox_options.set_preference('geo.enabled', False)  # 위치 정보 비활성화
        firefox_options.set_preference('permissions.default.desktop-notification', 2)  # 데스크톱 알림 차단

        # 자동화 감지 방지
        firefox_options.set_preference('marionette.enabled', True)
        firefox_options.set_preference('marionette.logging', 'Fatal')  # 로그 최소화

        # User-Agent 설정 (최신 Firefox)
        firefox_options.set_preference('general.useragent.override',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0'
        )

        # 성능 최적화
        firefox_options.set_preference('browser.cache.disk.enable', False)
        firefox_options.set_preference('browser.cache.memory.enable', False)
        firefox_options.set_preference('browser.cache.offline.enable', False)
        firefox_options.set_preference('network.http.use-cache', False)

        # Fingerprinting 방지
        firefox_options.set_preference('privacy.resistFingerprinting', False)  # 역설적으로 False (True면 오히려 의심)
        firefox_options.set_preference('webgl.disabled', False)  # WebGL 활성화 (일반 브라우저처럼)

        # 추가 안정성 설정
        firefox_options.set_preference('browser.tabs.remote.autostart', True)
        firefox_options.set_preference('browser.tabs.remote.autostart.2', True)
        firefox_options.set_preference('dom.push.enabled', False)  # Push 알림 비활성화

        # 언어 설정 (한국)
        firefox_options.set_preference('intl.accept_languages', 'ko-KR, ko, en-US, en')

        return firefox_options

    def _inject_anti_detection_js(self) -> None:
        """JavaScript를 통한 봇 탐지 회피 스크립트 주입"""
        anti_detection_script = """
        // navigator.webdriver 제거
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Plugins 배열 추가 (실제 브라우저처럼)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });

        // Languages 설정
        Object.defineProperty(navigator, 'languages', {
            get: () => ['ko-KR', 'ko', 'en-US', 'en']
        });

        // Platform 정보
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });

        // Hardware concurrency
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });

        // Device memory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });

        // Connection 정보
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });

        // Permissions API 오버라이드
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // Chrome 객체 추가 (일부 사이트에서 확인)
        window.chrome = {
            runtime: {}
        };

        // Screen 정보 일관성 유지
        Object.defineProperty(screen, 'availWidth', {
            get: () => window.innerWidth
        });
        Object.defineProperty(screen, 'availHeight', {
            get: () => window.innerHeight
        });
        """

        try:
            self.driver.execute_script(anti_detection_script)
        except Exception as e:
            print(f"[경고] JavaScript 주입 실패: {e}")

    @staticmethod
    def _random_delay(min_seconds: float = 0.3, max_seconds: float = 0.8) -> None:
        """랜덤 딜레이 - 사람처럼 보이게"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    def _simulate_human_behavior(self) -> None:
        """사람처럼 행동하기 - 스크롤, 마우스 이동 등"""
        try:
            # 랜덤 스크롤 (사람처럼)
            scroll_amount = random.randint(100, 400)
            self.driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
            self._random_delay(0.2, 0.5)

            # 다시 위로 조금 스크롤 (자연스러운 행동)
            scroll_back = random.randint(50, 150)
            self.driver.execute_script(f"window.scrollBy(0, -{scroll_back});")
            self._random_delay(0.1, 0.3)
        except:
            pass  # 스크롤 실패해도 계속 진행

    def _get_element_text(self, xpath: str, wait: WebDriverWait, description: str = "") -> str:
        """XPath로 요소의 텍스트를 안전하게 가져오기 (재시도 포함)"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
                text = element.text.strip()
                return text
            except StaleElementReferenceException:
                if attempt < max_retries - 1:
                    time.sleep(0.5)  # 잠시 대기 후 재시도
                    continue
                else:
                    print(f"[경고] {description} 요소가 stale 상태입니다 (재시도 {max_retries}회 실패).")
                    return ""
            except (TimeoutException, NoSuchElementException) as e:
                print(f"[경고] {description} 요소를 찾을 수 없습니다.")
                return ""
        return ""

    def _click_element(self, xpath: str, wait: WebDriverWait, description: str = "") -> bool:
        """XPath로 요소를 안전하게 클릭 - 자연스러운 클릭 시뮬레이션"""
        try:
            element = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))

            # 랜덤 딜레이 추가 (사람처럼)
            self._random_delay(0.2, 0.5)

            # 마우스를 요소로 이동 후 클릭 (자연스러운 동작)
            try:
                actions = ActionChains(self.driver)
                actions.move_to_element(element).pause(random.uniform(0.1, 0.3)).click().perform()
            except:
                # ActionChains 실패 시 일반 클릭
                element.click()

            return True
        except (TimeoutException, NoSuchElementException) as e:
            print(f"[경고] {description} 클릭 실패: {e}")
            return False

    def _extract_basic_info(self, wait: WebDriverWait) -> dict:
        """기본 차량 정보 추출"""
        print("\n[ 기본 차량 정보 추출 중... ]")

        # 차종 정보는 버튼 클릭 전에 추출 (전체 텍스트)
        car_type_raw = self._get_element_text(self.XPATHS['car_type'], wait, "차종")
        # 줄바꿈 제거 및 공백 정리
        car_type = ' '.join(car_type_raw.split())

        # 상세정보 버튼 클릭
        if not self._click_element(self.XPATHS['info_button'], wait, "상세정보 버튼"):
            return {}

        # 가격 정보 (원본)
        price_raw = self._get_element_text(self.XPATHS['price'], wait, "가격")

        # JavaScript로 모든 차량 정보를 한 번에 추출 (10번의 개별 조회 → 1번으로 단축)
        vehicle_data = self.driver.execute_script("""
            const xpath = '//*[@id="bottom_sheet"]/div[2]/div[2]/div/ul/li';
            const items = [];
            for (let i = 1; i <= 11; i++) {
                try {
                    const result = document.evaluate(
                        xpath + '[' + i + ']/span',
                        document,
                        null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                        null
                    );
                    items.push(result.singleNodeValue ? result.singleNodeValue.textContent.trim() : '');
                } catch (e) {
                    items.push('');
                }
            }
            return items;
        """)

        # 추출된 데이터를 정제하여 매핑
        vehicle_info = {
            'vehicle_number': vehicle_data[0] if len(vehicle_data) > 0 else "",
            'year_month': self._clean_year(vehicle_data[1]) if len(vehicle_data) > 1 else "",
            'mileage': self._clean_mileage(vehicle_data[2]) if len(vehicle_data) > 2 else "",
            'displacement': self._clean_displacement(vehicle_data[3]) if len(vehicle_data) > 3 else "",
            'fuel_type': vehicle_data[4] if len(vehicle_data) > 4 else "",
            'transmission': vehicle_data[5] if len(vehicle_data) > 5 else "",
            'car_type': car_type,
            'color': vehicle_data[7] if len(vehicle_data) > 7 else "",
            'location': vehicle_data[8] if len(vehicle_data) > 8 else "",
            'seating_capacity': vehicle_data[9] if len(vehicle_data) > 9 else "",
            'seizure_mortgage': vehicle_data[10] if len(vehicle_data) > 10 else "",
            'price': self._clean_price(price_raw),
        }

        print("[OK] 기본 차량 정보 추출 완료")
        print(f"  가격: {price_raw} -> {vehicle_info['price']}")
        print(f"  연식: {vehicle_data[1] if len(vehicle_data) > 1 else ''} -> {vehicle_info['year_month']}")
        print(f"  배기량: {vehicle_data[3] if len(vehicle_data) > 3 else ''} -> {vehicle_info['displacement']}")
        print(f"  주행거리: {vehicle_data[2] if len(vehicle_data) > 2 else ''} -> {vehicle_info['mileage']}")
        print(f"  차종: {car_type}")
        return vehicle_info

    def _parse_seller_info(self, full_name: str) -> tuple[str, str]:
        """판매자 전체 이름을 업체명과 판매자명으로 분리

        Args:
            full_name: "123 모터스 박성욱" 형태의 전체 이름

        Returns:
            (업체명, 판매자명) 튜플
        """
        if not full_name:
            return "", ""

        # 공백으로 분리
        parts = full_name.strip().split()

        if len(parts) == 0:
            return "", ""
        elif len(parts) == 1:
            # 하나만 있으면 판매자명으로 처리
            return "", parts[0]
        else:
            # 마지막 부분을 판매자명, 나머지를 업체명으로
            seller_name = parts[-1]
            company_name = " ".join(parts[:-1])
            return company_name, seller_name

    def _extract_seller_info(self, wait: WebDriverWait) -> dict:
        """판매자 정보 추출 (승용차/화물차 fallback 지원)"""
        print("\n[ 판매자 정보 추출 중... ]")

        # 페이지 새로고침 전에 주소 추출 (bottom_sheet 열기 전에)
        seller_address = self._extract_seller_address()

        # 페이지 새로고침 (안정적)
        current_url = self.driver.current_url
        self.driver.get(current_url)
        self._random_delay(0.3, 0.6)

        # 연락처 보기 버튼 클릭 (여러 선택자 시도)
        contact_clicked = self._click_contact_button_flexible(wait)
        if not contact_clicked:
            print("[경고] 연락처 보기 버튼을 찾을 수 없습니다.")
            return {'seller_address': seller_address}

        self._random_delay(0.3, 0.7)

        # 전화번호 보기 버튼 클릭 (여러 선택자 시도)
        phone_clicked = self._click_phone_button_flexible(wait)
        if not phone_clicked:
            print("[경고] 전화번호 보기 버튼을 찾을 수 없습니다.")
            return {'seller_address': seller_address}

        self._random_delay(0.3, 0.7)

        # 판매자 정보 추출 (승용차 XPath 시도)
        full_seller_name = self._get_element_text(self.XPATHS['seller_name'], wait, "판매자명")
        seller_contact = self._get_element_text(self.XPATHS['seller_contact'], wait, "연락처")

        # 실패 시 화물차 구조로 재시도
        if not full_seller_name or not seller_contact:
            print("  승용차 XPath 실패, 화물차 구조로 재시도...")
            company_name, seller_name, seller_contact = self._extract_truck_seller_info()
        else:
            # 판매자명 파싱 (업체명과 판매자명 분리)
            company_name, seller_name = self._parse_seller_info(full_seller_name)

        print("[OK] 판매자 정보 추출 완료")
        return {
            'company_name': company_name,
            'seller_name': seller_name,
            'seller_contact': seller_contact,
            'seller_address': seller_address,
        }

    def _extract_truck_seller_info(self) -> tuple:
        """화물차 판매자 정보 추출 (JavaScript 기반)

        Returns:
            (업체명, 판매자명, 연락처) 튜플
        """
        try:
            result = self.driver.execute_script("""
                const bottomSheet = document.getElementById('bottom_sheet');
                if (!bottomSheet) return ['', '', ''];

                let company = '';
                let seller = '';
                let contact = '';

                // 1. 판매자명과 업체명 추출
                // <p class="LayerPhoneInquiry_desc_seller__*">업체명 <strong>판매자명</strong></p>
                const descSeller = bottomSheet.querySelector('[class*="LayerPhoneInquiry_desc_seller"], [class*="Inquiry_desc_seller"]');
                if (descSeller) {
                    const strongTag = descSeller.querySelector('strong');
                    if (strongTag) {
                        seller = strongTag.textContent.trim();
                        // p 태그 전체 텍스트에서 strong 텍스트를 제거하면 업체명
                        company = descSeller.textContent.replace(seller, '').trim();
                    } else {
                        // strong 태그가 없으면 전체를 판매자명으로
                        seller = descSeller.textContent.trim();
                    }
                }

                // 2. 전화번호 추출
                // <p class="LayerPhoneInquiry_phone_number__*">050-6234-9844</p>
                const phoneNumber = bottomSheet.querySelector('[class*="LayerPhoneInquiry_phone_number"], [class*="Inquiry_phone_number"]');
                if (phoneNumber) {
                    contact = phoneNumber.textContent.trim();
                }

                // 3. fallback: 간단한 XPath로 시도
                if (!seller || !contact) {
                    const paragraphs = bottomSheet.querySelectorAll('p');
                    for (const p of paragraphs) {
                        const text = p.textContent.trim();
                        // 전화번호 패턴
                        if (/0[0-9]{2,3}-[0-9]{3,4}-[0-9]{4}/.test(text)) {
                            contact = text;
                        }
                    }
                }

                return [company, seller, contact];
            """)

            company_name = result[0] if result and len(result) > 0 else ""
            seller_name = result[1] if result and len(result) > 1 else ""
            seller_contact = result[2] if result and len(result) > 2 else ""

            if company_name:
                print(f"  업체명: {company_name}")
            if seller_name:
                print(f"  판매자명: {seller_name}")
            if seller_contact:
                print(f"  연락처: {seller_contact}")

            return company_name, seller_name, seller_contact

        except Exception as e:
            print(f"[경고] 화물차 판매자 정보 추출 실패: {e}")
            return "", "", ""

    def _click_contact_button_flexible(self, wait: WebDriverWait) -> bool:
        """연락처 보기 버튼 클릭 (여러 텍스트 시도)"""
        selectors = [
            (By.XPATH, self.XPATHS['contact_button']),  # 기존 XPath
            (By.XPATH, "//button[contains(text(), '연락처')]"),
            (By.XPATH, "//button[contains(text(), '판매자문의')]"),
            (By.XPATH, "//button[contains(text(), '문의')]"),
        ]

        for by, selector in selectors:
            try:
                element = wait.until(EC.element_to_be_clickable((by, selector)))
                element.click()
                print(f"  연락처 버튼 클릭 성공")
                return True
            except (TimeoutException, NoSuchElementException):
                continue

        return False

    def _click_phone_button_flexible(self, wait: WebDriverWait) -> bool:
        """전화번호 보기 버튼 클릭 (여러 텍스트 시도)"""
        selectors = [
            (By.XPATH, self.XPATHS['seller_phone_button']),  # 기존 XPath
            (By.XPATH, "//button[contains(text(), '전화')]"),
            (By.XPATH, "//button[contains(text(), '전화 문의')]"),
            (By.XPATH, "//*[@id='bottom_sheet']//button[contains(text(), '전화')]"),
        ]

        for by, selector in selectors:
            try:
                element = wait.until(EC.element_to_be_clickable((by, selector)))
                element.click()
                print(f"  전화번호 버튼 클릭 성공")
                return True
            except (TimeoutException, NoSuchElementException):
                continue

        return False

    def _extract_seller_address(self) -> str:
        """페이지 본문에서 판매자 주소 추출"""
        try:
            address = self.driver.execute_script("""
                // 모든 li 태그에서 주소 패턴 찾기
                const allLi = document.querySelectorAll('li');

                for (const li of allLi) {
                    const text = li.textContent.trim();
                    // 주소 패턴: 시/도로 시작하는 텍스트
                    if (/^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)/.test(text)) {
                        return text;
                    }
                }

                return '';
            """)

            if address:
                print(f"  주소: {address}")
            return address

        except Exception as e:
            print(f"[경고] 주소 추출 실패: {e}")
            return ""

    def _extract_inspection_info(self, car_id: str, wait: WebDriverWait) -> dict:
        """성능점검 정보 추출"""
        print("\n[ 성능점검 정보 추출 중... ]")

        try:
            # 성능점검 페이지 URL 생성 및 이동
            inspection_url = self._build_inspection_url(car_id)
            print(f"성능점검 페이지로 이동: {inspection_url}")
            self.driver.get(inspection_url)

            # 성능점검기록부 정보 추출
            inspection_record = self._get_element_text(
                self.XPATHS['inspection_record'], wait, "성능점검기록부"
            )

            # 요소를 찾지 못했거나 값이 비어있는 경우
            if not inspection_record:
                inspection_record = "페이지없음"
                print("[경고] 성능점검 페이지를 찾을 수 없습니다.")
            else:
                print("[OK] 성능점검 정보 추출 완료")
                print(f"  성능점검기록부: {inspection_record}")

            return {
                'inspection_record': inspection_record,
            }

        except Exception as e:
            # 페이지 로드 실패 또는 기타 오류 발생 시
            print(f"[경고] 성능점검 정보 추출 실패: {e}")
            return {
                'inspection_record': "페이지없음",
            }

    def _build_inspection_url(self, car_id: str) -> str:
        """성능점검 페이지 URL 생성"""
        base_url = "https://www.encar.com/md/sl/mdsl_regcar.do"
        return f"{base_url}?method=inspectionViewNew&carid={car_id}"

    def _extract_car_id(self, url: str) -> Optional[str]:
        """URL에서 차량 ID 추출

        지원하는 URL 형식:
        - fem.encar.com/cars/detail/40869929 (경로에 ID 포함)
        - encar.com?carid=40869929 (쿼리 파라미터)
        """
        try:
            # 1. fem.encar.com 형식: /detail/숫자
            match = re.search(r'/detail/(\d+)', url)
            if match:
                car_id = match.group(1)
                print(f"차량 ID: {car_id}")
                return car_id

            # 2. 기존 형식: carid=숫자
            if "carid=" in url:
                car_id = url.split("carid=")[1].split("&")[0]
                print(f"차량 ID: {car_id}")
                return car_id

            print("[경고] 차량 ID를 찾을 수 없습니다.")
            return None

        except (IndexError, AttributeError):
            print("[경고] 차량 ID 추출 실패")
            return None

    def get_car_info(self, url: str, include_options: bool = False) -> Optional[CarInfo]:
        """모든 차량 정보 추출 (차량 정보 + 판매자 정보 + 성능점검 정보)"""
        if not self.driver:
            self.setup_driver()

        try:
            self._print_crawling_header(url)

            # URL에서 차량 ID 추출
            car_id = self._extract_car_id(url)

            # 페이지 로드
            self.driver.get(url)

            # 페이지 로드 후 사람처럼 행동 (봇 탐지 회피)
            self._random_delay(0.5, 1.2)
            self._simulate_human_behavior()

            wait = WebDriverWait(self.driver, self.DEFAULT_WAIT_TIMEOUT)

            # 1. 기본 차량 정보 추출
            basic_info = self._extract_basic_info(wait)
            if not basic_info:
                print("[경고] 기본 차량 정보 추출 실패")
                return None

            # 2. 판매자 정보 추출
            seller_info = self._extract_seller_info(wait)

            # 3. 옵션 추출 - 성능점검 전에 실행 (성능점검은 페이지 이동 발생)
            options = self._extract_options() if include_options else []

            # 4. 성능점검 정보 추출 (페이지 이동 발생)
            inspection_info = self._extract_inspection_info_if_available(car_id, wait)

            # 5. 모든 정보 통합
            all_info = {**basic_info, **seller_info, **inspection_info}
            car_info = CarInfo(**all_info)
            car_info.options = options

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
        print(f"URL: {url}\n")

    def _extract_options(self) -> List[OptionItem]:
        """엔카 차량 옵션 목록 추출 (JavaScript 기반)"""
        try:
            option_names = self.driver.execute_script("""
                const results = new Set();

                // 전략 1: [class*="option"] 요소 중 opacity가 높은 것 (활성 옵션)
                const optEls = document.querySelectorAll(
                    '[class*="option"] li, [class*="Option"] li, ' +
                    '[class*="spec"] li, [class*="Spec"] li'
                );
                for (const el of optEls) {
                    const style = window.getComputedStyle(el);
                    const opacity = parseFloat(style.opacity || '1');
                    const text = (el.innerText || '').trim();
                    if (opacity >= 0.85 && text.length >= 2 && text.length <= 30
                            && !text.includes('\\n')) {
                        results.add(text);
                    }
                }

                // 전략 2: active/on 클래스가 붙은 li 요소
                const activeLi = document.querySelectorAll(
                    'li[class*="active"], li[class*="--on"], li[class*="checked"]'
                );
                for (const el of activeLi) {
                    const text = (el.innerText || '').trim();
                    if (text.length >= 2 && text.length <= 30 && !text.includes('\\n')) {
                        results.add(text);
                    }
                }

                return [...results];
            """)

            options = []
            if option_names:
                for name in option_names:
                    name = name.strip()
                    if not name:
                        continue
                    mapped = OPTION_MAP.get(name)
                    # 부분 일치로도 매핑 시도
                    if not mapped:
                        for k, v in OPTION_MAP.items():
                            if k in name or name in k:
                                mapped = v
                                break
                    # 매핑 없으면 엔카 이름 그대로 사용
                    if not mapped:
                        mapped = name
                    options.append(OptionItem(name=name, mapped_name=mapped))

            if options:
                print(f"  [옵션] {len(options)}개 추출: {[o.name for o in options[:5]]}")
            return options

        except Exception as e:
            print(f"  [경고] 옵션 추출 실패: {e}")
            return []

    def _extract_inspection_info_if_available(
        self, car_id: Optional[str], wait: WebDriverWait
    ) -> dict:
        """차량 ID가 있을 경우에만 성능점검 정보 추출"""
        if not car_id:
            print("[경고] 차량 ID를 찾을 수 없어 성능점검 정보를 추출하지 못했습니다.")
            return {}

        return self._extract_inspection_info(car_id, wait)

    def close(self) -> None:
        """드라이버 종료"""
        if self.driver:
            self.driver.quit()
            print("\n[OK] 드라이버가 종료되었습니다.")


def main():
    """메인 실행 함수"""
    start_time = time.time()

    print(f"\n{'='*60}")
    print("크롤링 시작 (Firefox)".center(60))
    print(f"{'='*60}\n")

    url = "https://fem.encar.com/cars/detail/41422919?pageid=fc_carsearch&listAdvType=normal&carid=41422919&view_type=normal&adv_attribute=&wtClick_forList=019&advClickPosition=imp_normal_p1_g12&tempht_arg=JHUL13GYQ809_11"
    crawler = EncarSeleniumCrawler(headless=True)  # 프로덕션용 headless 모드

    try:
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
