"""
이미지 다운로드 모듈
- DriveImageDownloader : 구글 드라이브 공유 폴더 → EXTERIOR 이미지
- MangocarImageDownloader : 망고월드카 검수 페이지 → 이미지
- fix_exif_rotation() : EXIF Orientation 기반 회전 보정
"""
import os
import re
import time
import shutil
import zipfile

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 현재 스크립트 기준 다운로드 폴더
DOWNLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloaded_images")


def fix_exif_rotation(image_path: str) -> None:
    """EXIF Orientation 태그에 따라 이미지를 올바른 방향으로 회전 후 저장.
    Pillow가 없으면 조용히 건너뜀."""
    try:
        from PIL import Image, ExifTags
        img = Image.open(image_path)
        exif = img._getexif() if hasattr(img, '_getexif') else None
        if not exif:
            return
        orientation_tag = next(
            (k for k, v in ExifTags.TAGS.items() if v == 'Orientation'), None
        )
        if orientation_tag is None:
            return
        orientation = exif.get(orientation_tag)
        rotated = None
        if orientation == 3:
            rotated = img.rotate(180, expand=True)
        elif orientation == 6:
            rotated = img.rotate(270, expand=True)
        elif orientation == 8:
            rotated = img.rotate(90, expand=True)
        if rotated:
            rotated.save(image_path)
            print(f"    [회전보정] {os.path.basename(image_path)} (orientation={orientation})")
    except ImportError:
        pass
    except Exception as e:
        print(f"    [경고] EXIF 회전 보정 실패 ({os.path.basename(image_path)}): {e}")


class DriveImageDownloader:
    """구글 드라이브 공유 폴더에서 EXTERIOR 이미지를 다운로드"""

    def __init__(self, download_folder: str = DOWNLOAD_FOLDER):
        self.download_folder = os.path.abspath(download_folder)
        self.driver = None

    # ── 드라이버 ────────────────────────────────────────────────────
    def setup_driver(self) -> None:
        os.makedirs(self.download_folder, exist_ok=True)
        # 이전 실패로 남은 .crdownload / downloads.htm 잔여 파일 정리
        for fn in os.listdir(self.download_folder):
            if fn.endswith('.crdownload') or fn.endswith('.tmp') or (
                    'downloads' in fn.lower() and '.htm' in fn.lower()):
                try:
                    os.remove(os.path.join(self.download_folder, fn))
                except Exception:
                    pass

        chrome_options = Options()
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": self.download_folder,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
        })
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        )
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        })
        # headless Chrome 다운로드 허용 (없으면 .crdownload 상태로 멈춤)
        self.driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': self.download_folder,
        })
        print(f"  [OK] 이미지 다운로드 드라이버 초기화 (download → {self.download_folder})")

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None

    # ── 메인: 드라이브에서 이미지 다운로드 ─────────────────────────
    def download_images(self, drive_link: str, row_num: int) -> list[str]:
        """구글 드라이브 공유 폴더 → EXTERIOR 폴더 진입 → 전체 선택 → 다운로드 → ZIP 해제

        Returns:
            다운로드된 이미지 파일 절대 경로 리스트
        """
        if not drive_link:
            return []

        try:
            print(f"  [드라이브 접속] {drive_link[:80]}")
            self.driver.get(drive_link)
            time.sleep(1.5)

            # EXTERIOR 폴더 찾기 & 진입
            self._enter_exterior_folder()

            # row별 다운로드 폴더 (이전 다운로드 잔여 파일 정리)
            row_path = os.path.join(self.download_folder, f"row_{row_num}")
            if os.path.exists(row_path):
                shutil.rmtree(row_path, ignore_errors=True)
                print(f"  [INFO] 기존 row_{row_num} 폴더 정리 완료")
            os.makedirs(row_path, exist_ok=True)

            # 파일 선택 & 다운로드
            return self._select_and_download(row_num, row_path)

        except Exception as e:
            print(f"  [오류] 드라이브 이미지 다운로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    # ── EXTERIOR 폴더 진입 ─────────────────────────────────────────
    def _enter_exterior_folder(self) -> None:
        exterior_link = None
        for method, xpath in [
            ("data-tooltip", "//*[contains(@data-tooltip, 'EXTERIOR')]"),
            ("aria-label",   "//*[contains(@aria-label, 'EXTERIOR')]"),
            ("text",         "//*[contains(text(), 'EXTERIOR')]"),
        ]:
            try:
                elems = self.driver.find_elements(By.XPATH, xpath)
                if elems:
                    exterior_link = elems[0]
                    break
            except Exception:
                pass

        if exterior_link:
            print("  [OK] EXTERIOR 폴더 발견, 더블클릭...")
            ActionChains(self.driver).double_click(exterior_link).perform()
            time.sleep(2)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='listitem']"))
                )
                print("  [OK] EXTERIOR 파일 목록 로딩 완료")
            except Exception:
                print("  [경고] 파일 목록 로딩 대기 타임아웃")
        else:
            print("  [INFO] EXTERIOR 폴더 없음 - 현재 폴더 이미지 다운로드")

    # ── 파일 선택 → 다운로드 → ZIP 해제 ───────────────────────────
    def _select_and_download(self, row_num: int, row_path: str) -> list[str]:
        file_items = self.driver.find_elements(By.XPATH, "//div[@role='listitem']")
        if not file_items:
            file_items = self.driver.find_elements(By.XPATH, "//div[@data-id]")
        if not file_items:
            print("  [경고] 파일 목록을 찾을 수 없습니다")
            return []

        print(f"  [OK] {len(file_items)}개 파일 발견")

        # ── 전체 선택 ──
        self._select_all_files(file_items)

        # ── 다운로드 전 스냅샷 (crdownload/tmp 포함 - 잔여 파일 오감지 방지) ──
        pre_files = set()
        if os.path.exists(self.download_folder):
            pre_files = set(os.listdir(self.download_folder))

        # ── 다운로드 버튼 클릭 ──
        if not self._click_download():
            return []

        # ── 다운로드 완료 대기 ──
        print("  [대기] 다운로드 완료 대기 (최대 300초)...")
        self._wait_for_download(timeout=300, pre_files=pre_files)

        # ── Google Drive 바이러스 경고 페이지 처리 (탭에서 열린 경우) ──
        self._bypass_drive_warning(pre_files)

        # ── 다운로드 폴더 내용 디버그 ──
        if os.path.exists(self.download_folder):
            all_files = os.listdir(self.download_folder)
            new_files = [f for f in all_files if f not in pre_files and not f.startswith('row_')]
            print(f"  [DEBUG] 다운로드 폴더 신규 파일: {new_files}")

        # ── ZIP 해제 / 이미지 수집 ──
        return self._collect_images(row_num, row_path, pre_files)

    def _select_all_files(self, file_items) -> None:
        """Ctrl+A → Shift+클릭 → Ctrl+클릭 순서로 전체 선택 시도"""
        # 방법 1: Ctrl+A
        try:
            file_items[0].click()
            time.sleep(0.3)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.5)
            print("  [OK] 전체 선택 (Ctrl+A)")
            return
        except Exception:
            pass

        # 방법 2: Shift+클릭
        try:
            file_items[0].click()
            time.sleep(0.3)
            ActionChains(self.driver).key_down(Keys.SHIFT).click(file_items[-1]).key_up(Keys.SHIFT).perform()
            time.sleep(0.5)
            print("  [OK] 전체 선택 (Shift+클릭)")
            return
        except Exception:
            pass

        # 방법 3: Ctrl+클릭
        try:
            for i, item in enumerate(file_items):
                if i == 0:
                    item.click()
                else:
                    ActionChains(self.driver).key_down(Keys.CONTROL).click(item).key_up(Keys.CONTROL).perform()
                time.sleep(0.1)
            print(f"  [OK] 전체 선택 (Ctrl+클릭 {len(file_items)}개)")
        except Exception as e:
            print(f"  [오류] 파일 선택 실패: {e}")

    def _bypass_drive_warning(self, pre_files: set) -> None:
        """Google Drive 바이러스 경고 탭이 열린 경우 'Download anyway' 클릭 후 재대기"""
        try:
            url = self.driver.current_url
        except Exception:
            return

        # 경고 페이지 URL 패턴 확인
        is_warning = any(p in url for p in [
            'uc?export=download', 'uc?id=', 'download?id=',
            'drive.usercontent.google.com',
        ])

        if not is_warning:
            # 새 탭 확인
            for handle in self.driver.window_handles:
                try:
                    self.driver.switch_to.window(handle)
                    tab_url = self.driver.current_url
                    if any(p in tab_url for p in ['uc?export=download', 'uc?id=', 'download?id=', 'drive.usercontent']):
                        is_warning = True
                        break
                except Exception:
                    pass

        if not is_warning:
            return

        print(f"  [INFO] Google Drive 경고 페이지 감지: {self.driver.current_url[:80]}")

        # "Download anyway" 버튼 클릭
        DOWNLOAD_ANYWAY_XPATHS = [
            "//*[@id='uc-download-link']",
            "//a[contains(@href,'confirm=')]",
            "//form[@id='uc-virusscan-form']//a",
            "//a[contains(text(),'Download anyway')]",
            "//a[contains(text(),'ダウンロード')]",
            "//button[contains(text(),'Download')]",
        ]
        clicked = False
        for xpath in DOWNLOAD_ANYWAY_XPATHS:
            try:
                btn = self.driver.find_element(By.XPATH, xpath)
                href = btn.get_attribute('href') or ''
                if href:
                    self.driver.get(href)
                else:
                    btn.click()
                print(f"  [OK] Download anyway 클릭 완료")
                clicked = True
                break
            except Exception:
                pass

        if clicked:
            print("  [대기] 실제 파일 다운로드 대기 (최대 300초)...")
            self._wait_for_download(timeout=300, pre_files=pre_files)
        else:
            print("  [경고] Download anyway 버튼을 찾지 못함")

    def _click_download(self) -> bool:
        """다운로드 버튼 클릭 (4가지 방법)"""
        # 방법 1: 툴바 다운로드 버튼
        try:
            btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH,
                    "//button[@aria-label='다운로드'] | //button[@aria-label='Download']"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.2)
            try:
                btn.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", btn)
            print("  [OK] 다운로드 시작 (툴바 버튼)")
            return True
        except Exception:
            pass

        # 방법 2: 더보기 메뉴
        try:
            more = self.driver.find_element(By.XPATH,
                "//button[@aria-label='더보기'] | //button[@aria-label='More actions']")
            more.click()
            time.sleep(0.5)
            dl = self.driver.find_element(By.XPATH,
                "//*[contains(text(),'다운로드') or contains(text(),'Download')]")
            dl.click()
            print("  [OK] 다운로드 시작 (더보기 메뉴)")
            return True
        except Exception:
            pass

        # 방법 3: 우클릭 메뉴
        try:
            items = self.driver.find_elements(By.XPATH, "//div[@role='listitem']") or \
                    self.driver.find_elements(By.XPATH, "//div[@data-id]")
            if items:
                ActionChains(self.driver).context_click(items[0]).perform()
                time.sleep(1)
                dl = self.driver.find_element(By.XPATH,
                    "//*[contains(text(),'다운로드') or contains(text(),'Download')]")
                dl.click()
                print("  [OK] 다운로드 시작 (우클릭 메뉴)")
                return True
        except Exception:
            pass

        # 방법 4: 단축키
        try:
            self.driver.find_element(By.TAG_NAME, "body").send_keys('p')
            print("  [OK] 다운로드 시작 (단축키 P)")
            return True
        except Exception:
            pass

        print("  [오류] 모든 다운로드 방법 실패")
        return False

    def _wait_for_download(self, timeout: int = 90, pre_files: set = None) -> None:
        """다운로드 완료 대기
        1) 먼저 새 파일이 나타날 때까지 대기 (다운로드 시작 감지)
        2) .crdownload/.tmp 파일이 사라질 때까지 대기 (다운로드 완료)
        """
        if pre_files is None:
            pre_files = set()

        end_time = time.time() + timeout

        # Phase 1: 새 파일이 나타날 때까지 대기 (구글 드라이브 ZIP 준비 시간)
        print("    Phase 1: 다운로드 시작 대기...")
        while time.time() < end_time:
            current = set(os.listdir(self.download_folder)) if os.path.exists(self.download_folder) else set()
            new_files = current - pre_files - {f for f in current if f.startswith('row_')}
            if new_files:
                print(f"    Phase 1 완료: 새 파일 감지 {list(new_files)[:3]}")
                break
            time.sleep(1.5)
        else:
            print("  [경고] 다운로드 시작 감지 못함 (타임아웃)")
            return

        # Phase 2: .crdownload 가 완전히 없어질 때까지 대기
        # downloads.htm → 실제 ZIP 순서로 내려오므로
        # crdownload 가 없어진 후에도 최대 35초 더 관찰해서 새 crdownload 가 시작되면 계속 대기
        print("    Phase 2: 다운로드 완료 대기...")
        no_crdownload_since = None
        while time.time() < end_time:
            folder_files = os.listdir(self.download_folder) if os.path.exists(self.download_folder) else []
            downloading = [f for f in folder_files if f.endswith('.crdownload') or f.endswith('.tmp')]

            if not downloading:
                if no_crdownload_since is None:
                    no_crdownload_since = time.time()
                    print("    Phase 2: crdownload 없음, 35초 관찰 중...")
                elif time.time() - no_crdownload_since >= 35:
                    print("    Phase 2 완료: 다운로드 완료")
                    return
            else:
                if no_crdownload_since is not None:
                    print("    Phase 2: 새 다운로드 감지, 계속 대기...")
                no_crdownload_since = None  # 새 crdownload → 타이머 리셋

            time.sleep(1.5)
        print("  [경고] 다운로드 완료 대기 타임아웃")

    def _handle_downloads_htm(self, pre_files: set) -> None:
        """downloads.htm 감지 시 그 안의 실제 다운로드 링크로 재시도"""
        if not os.path.exists(self.download_folder):
            return
        for fn in os.listdir(self.download_folder):
            if fn in pre_files or not fn.lower().startswith('downloads'):
                continue
            fp = os.path.join(self.download_folder, fn)
            if not fn.lower().endswith('.htm') and not fn.lower().endswith('.html'):
                continue
            print(f"  [INFO] Google Drive 바이러스 경고 페이지 감지: {fn} → 실제 링크 추출 시도")
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read()
                # 실제 다운로드 링크 추출 (form action 또는 href)
                import re as _re
                # form action
                m = _re.search(r'action=["\']([^"\']+download[^"\']*)["\']', html, _re.IGNORECASE)
                if not m:
                    m = _re.search(r'href=["\']([^"\']*export=download[^"\']*)["\']', html, _re.IGNORECASE)
                if m:
                    url = m.group(1).replace('&amp;', '&')
                    print(f"  [INFO] 실제 다운로드 URL: {url[:80]}")
                    self.driver.get(url)
                    time.sleep(5)
                os.remove(fp)
            except Exception as e:
                print(f"  [경고] downloads.htm 처리 실패: {e}")

    def _collect_images(self, row_num: int, row_path: str, pre_files: set) -> list[str]:
        """다운로드 폴더에서 새로 생긴 파일(ZIP/이미지) 수집"""
        img_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
        downloaded_files = []

        # downloads.htm 감지 → 실제 다운로드 재시도
        self._handle_downloads_htm(pre_files)
        # 재시도 후 crdownload 완료 대기
        if any(f.endswith('.crdownload') for f in os.listdir(self.download_folder) if f not in pre_files):
            print("  [INFO] 재다운로드 대기 중...")
            self._wait_for_download(timeout=300, pre_files=pre_files)

        # 새 ZIP 찾기 (확장자 없는 파일도 ZIP으로 시도 - '미확인' 파일 대응)
        zip_file_path = None
        if os.path.exists(self.download_folder):
            zip_candidates = []
            for fn in os.listdir(self.download_folder):
                if fn in pre_files or fn.startswith('row_'):
                    continue
                fp = os.path.join(self.download_folder, fn)
                fn_lower = fn.lower()
                if fn_lower.endswith('.zip'):
                    zip_candidates.append((os.path.getmtime(fp), fp, fn))
                elif not any(fn_lower.endswith(f'.{e}') for e in {'jpg','jpeg','png','gif','bmp','webp','crdownload','tmp'}):
                    # 확장자 없거나 미식별 파일 → ZIP으로 시도
                    zip_candidates.append((os.path.getmtime(fp), fp, fn))
            zip_candidates.sort(reverse=True)
            if zip_candidates:
                _, zip_file_path, found = zip_candidates[0]
                print(f"  [OK] ZIP 후보 발견: {found}")

        # ZIP 해제
        if zip_file_path:
            try:
                zip_dest = os.path.join(row_path, os.path.basename(zip_file_path))
                shutil.move(zip_file_path, zip_dest)
                with zipfile.ZipFile(zip_dest, 'r') as zf:
                    zf.extractall(row_path)
                for root, _, files in os.walk(row_path):
                    for fn in files:
                        if any(fn.lower().endswith(f'.{e}') for e in img_exts):
                            fp = os.path.join(root, fn)
                            downloaded_files.append(fp)
                            print(f"    [OK] {fn}")
                os.remove(zip_dest)
            except Exception as e:
                print(f"  [오류] ZIP 처리 실패: {e}")
        else:
            # 개별 이미지
            print("  [INFO] ZIP 없음, 개별 이미지 확인...")
            if os.path.exists(self.download_folder):
                for fn in os.listdir(self.download_folder):
                    if any(fn.lower().endswith(f'.{e}') for e in img_exts) and fn not in pre_files:
                        src = os.path.join(self.download_folder, fn)
                        dst = os.path.join(row_path, fn)
                        try:
                            shutil.move(src, dst)
                            downloaded_files.append(dst)
                            print(f"    [OK] {fn}")
                        except Exception:
                            pass

        # EXIF 회전 보정
        for fp in downloaded_files:
            fix_exif_rotation(fp)

        print(f"  [완료] 총 {len(downloaded_files)}개 이미지 다운로드")
        return downloaded_files


# ── 망고월드카 다운로더 ──────────────────────────────────────────────────────

class MangocarImageDownloader:
    """망고월드카 검수 페이지에서 이미지를 다운로드.
    각 row 마다 row_{row_num}/ 폴더를 깨끗이 비우고 사용해 교차 오염 방지."""

    def __init__(self, download_folder: str = DOWNLOAD_FOLDER):
        self.download_folder = os.path.abspath(download_folder)
        self.driver = None

    def setup_driver(self) -> None:
        os.makedirs(self.download_folder, exist_ok=True)
        # 잔여 임시 파일 + 이전 실행 망고 zip 정리 (pre_files 오염 방지)
        for fn in os.listdir(self.download_folder):
            fp = os.path.join(self.download_folder, fn)
            if not os.path.isfile(fp):
                continue
            fn_lower = fn.lower()
            # crdownload/tmp 정리
            if fn_lower.endswith('.crdownload') or fn_lower.endswith('.tmp'):
                try:
                    os.remove(fp)
                except Exception:
                    pass
            # 이전 실행 망고 zip 정리 (EXTERIOR- 로 시작하지 않는 zip)
            elif fn_lower.endswith('.zip') and not fn.startswith('EXTERIOR'):
                try:
                    os.remove(fp)
                    print(f"  [INFO] 잔여 망고 zip 정리: {fn}")
                except Exception:
                    pass
            # htm/html 잔여 파일 정리
            elif '.htm' in fn_lower or '.html' in fn_lower:
                try:
                    os.remove(fp)
                except Exception:
                    pass

        chrome_options = Options()
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": self.download_folder,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
        })
        # headless 제거: 망고카 다운로드 버튼이 headless 모드에서 downloads.htm 으로 차단됨
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        )
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        })
        self.driver.execute_cdp_cmd('Page.setDownloadBehavior', {
            'behavior': 'allow',
            'downloadPath': self.download_folder,
        })
        print(f"  [OK] 망고카 다운로드 드라이버 초기화 (download → {self.download_folder})")

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None

    MANGO_EMAIL    = "admin@mangoworldcar.com"
    MANGO_PASSWORD = "mango8802!"
    MANGO_LOGIN_URL = "https://mangoworldcar.com/ko/sign-in"

    def _login_mango(self) -> bool:
        """망고월드카 공개 사이트 로그인"""
        try:
            self.driver.get(self.MANGO_LOGIN_URL)
            time.sleep(2)
            # 이미 로그인된 경우
            if 'sign-in' not in self.driver.current_url:
                print("  [OK] 망고카 이미 로그인 상태")
                return True
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC2
            wait = WebDriverWait(self.driver, 10)
            email_field = wait.until(EC2.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[type="email"], input[name="email"]')
            ))
            email_field.clear()
            email_field.send_keys(self.MANGO_EMAIL)
            pw_field = self.driver.find_element(
                By.CSS_SELECTOR, 'input[type="password"], input[name="password"]'
            )
            pw_field.clear()
            pw_field.send_keys(self.MANGO_PASSWORD)
            pw_field.submit()
            time.sleep(2)
            if 'sign-in' in self.driver.current_url:
                print("  [경고] 망고카 로그인 실패")
                return False
            print("  [OK] 망고카 로그인 성공")
            return True
        except Exception as e:
            print(f"  [경고] 망고카 로그인 오류: {e}")
            return False

    def download_images(self, url: str, row_num: int) -> list[str]:
        """망고월드카 검수 페이지 → 이미지 다운로드 → row_{row_num}/ 저장.

        Returns:
            다운로드된 이미지 파일 절대 경로 리스트
        """
        if not url or not self.driver:
            return []

        # row 폴더 격리 (기존 파일 완전 삭제 후 재생성)
        row_path = os.path.join(self.download_folder, f"row_{row_num}")
        if os.path.exists(row_path):
            shutil.rmtree(row_path, ignore_errors=True)
            print(f"  [INFO] 기존 row_{row_num} 폴더 정리")
        os.makedirs(row_path, exist_ok=True)

        # 로그인 (최초 1회)
        self._login_mango()

        try:
            clean_url = url.replace('?readonly=true', '').replace('&readonly=true', '')
            print(f"  [망고카 접속] {clean_url[:80]}")
            self.driver.get(clean_url)
            time.sleep(3)

            # 다운로드 전 스냅샷
            pre_files = set(os.listdir(self.download_folder)) if os.path.exists(self.download_folder) else set()

            # 다운로드 버튼 클릭 (버튼 먼저, SVG는 fallback)
            download_xpaths = [
                '/html/body/main/div/div/section/div[1]/div[1]/div/section[1]/div/button[1]',
                '/html/body/main/div/div/section/div[1]/div[1]/div/section[1]/div/button[1]/div/svg',
                '//*[contains(@id,"radix-")]/div[2]/div/div/div/article[4]/section/div/div/div',
                '//article[4]/section/div/div/div',
                '//article[4]//button[contains(text(),"다운로드") or contains(text(),"Download")]',
            ]
            download_btn = None
            for xpath in download_xpaths:
                try:
                    download_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    break
                except Exception:
                    continue

            if download_btn is None:
                print("  [경고] 망고카 다운로드 버튼을 찾을 수 없음")
                return []

            self.driver.execute_script("arguments[0].click();", download_btn)
            print("  [INFO] 망고카 다운로드 버튼 클릭")
            time.sleep(2)

            # 확인 버튼 클릭 (다이얼로그가 뜬 경우만, 없으면 바로 다운로드 진행)
            confirm_xpaths = [
                '//*[contains(@id,"radix-")]/div[2]/button[1]',
                '//*[@role="dialog"]//button[1]',
                '//*[@role="alertdialog"]//button[1]',
                '//button[contains(text(),"확인") or contains(text(),"OK") or contains(text(),"다운로드") or contains(text(),"Download") or contains(text(),"네") or contains(text(),"Yes")]',
                '//div[contains(@class,"modal") or contains(@class,"dialog") or contains(@class,"popup")]//button[1]',
            ]
            confirm_btn = None
            for xpath in confirm_xpaths:
                try:
                    confirm_btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    break
                except Exception:
                    continue

            if confirm_btn is not None:
                try:
                    confirm_btn.click()
                    print("  [INFO] 확인 버튼 클릭, 다운로드 시작")
                except Exception:
                    self.driver.execute_script("arguments[0].click();", confirm_btn)
                    print("  [INFO] 확인 버튼 JS 클릭, 다운로드 시작")
            else:
                print("  [INFO] 확인 버튼 없음 — 다운로드 직접 트리거된 것으로 가정")

            # 다운로드 완료 대기 (최대 120초)
            self._wait_for_download(timeout=120, pre_files=pre_files)

            # 파일 수집 및 row 폴더로 이동
            return self._collect_images(row_num, row_path, pre_files)

        except Exception as e:
            print(f"  [오류] 망고카 이미지 다운로드 실패: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _wait_for_download(self, timeout: int = 120, pre_files: set = None) -> None:
        if pre_files is None:
            pre_files = set()
        end_time = time.time() + timeout

        print("    Phase 1: 다운로드 시작 대기...")
        while time.time() < end_time:
            current = set(os.listdir(self.download_folder)) if os.path.exists(self.download_folder) else set()
            new_files = current - pre_files - {f for f in current if f.startswith('row_')}
            if new_files:
                print(f"    Phase 1 완료: 새 파일 감지 {list(new_files)[:3]}")
                break
            time.sleep(1.5)
        else:
            print("  [경고] 다운로드 시작 감지 못함 (타임아웃)")
            return

        print("    Phase 2: 다운로드 완료 대기...")
        no_crdownload_since = None
        while time.time() < end_time:
            folder_files = os.listdir(self.download_folder) if os.path.exists(self.download_folder) else []
            downloading = [f for f in folder_files if f.endswith('.crdownload') or f.endswith('.tmp')]
            if not downloading:
                if no_crdownload_since is None:
                    no_crdownload_since = time.time()
                elif time.time() - no_crdownload_since >= 10:
                    print("    Phase 2 완료")
                    return
            else:
                no_crdownload_since = None
            time.sleep(1.5)

    def _handle_downloads_htm(self, pre_files: set) -> bool:
        """downloads.htm 감지 시 그 안의 실제 다운로드 링크로 재시도.

        Returns:
            True if an htm file was found and processed (caller should wait for download).
        """
        if not os.path.exists(self.download_folder):
            return False
        import re as _re
        handled = False
        for fn in list(os.listdir(self.download_folder)):
            if fn in pre_files:
                continue
            fn_lower = fn.lower()
            # 'downloads.htm', 'downloads.htm (1)', 'downloads.html' 등 모두 감지
            if not ('.htm' in fn_lower or '.html' in fn_lower):
                continue
            if fn_lower.endswith('.crdownload') or fn_lower.endswith('.tmp'):
                continue
            fp = os.path.join(self.download_folder, fn)
            print(f"  [INFO] downloads.htm 감지 → 실제 링크 추출 시도: {fn}")
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                    html = f.read()
                # 다운로드 URL 후보 추출 (href/action/src 중 파일 링크)
                patterns = [
                    r'href=["\']([^"\']+\.zip[^"\']*)["\']',
                    r'href=["\']([^"\']+\.jpg[^"\']*)["\']',
                    r'action=["\']([^"\']+download[^"\']*)["\']',
                    r'href=["\']([^"\']*download[^"\']*)["\']',
                    r'(?:window\.location|location\.href)\s*=\s*["\']([^"\']+)["\']',
                    # 임의 URL (http/https로 시작하는 href)
                    r'href=["\'](\bhttps?://[^"\']+)["\']',
                    r'src=["\'](\bhttps?://[^"\']+)["\']',
                ]
                found_url = None
                for pat in patterns:
                    m = _re.search(pat, html, _re.IGNORECASE)
                    if m:
                        found_url = m.group(1).replace('&amp;', '&')
                        break
                handled = True
                if found_url:
                    os.remove(fp)
                    print(f"  [INFO] 재다운로드 URL: {found_url[:80]}")
                    self.driver.get(found_url)
                    # 새 crdownload 파일이 나타날 때까지 대기 (최대 15초)
                    for _ in range(15):
                        time.sleep(1)
                        if any(
                            f.endswith('.crdownload') and f not in pre_files
                            for f in os.listdir(self.download_folder)
                        ):
                            print("  [INFO] 재다운로드 crdownload 감지")
                            break
                else:
                    # URL 추출 실패 → 파일을 브라우저로 직접 열어 JS 리다이렉트 시도
                    print(f"  [경고] downloads.htm URL 추출 실패, 브라우저로 직접 오픈 시도")
                    print(f"  [DEBUG] HTML 일부: {html[:400]}")
                    file_url = 'file:///' + fp.replace('\\', '/')
                    self.driver.get(file_url)
                    time.sleep(3)
                    os.remove(fp)
            except Exception as e:
                print(f"  [경고] downloads.htm 처리 실패: {e}")
        return handled

    def _collect_images(self, row_num: int, row_path: str, pre_files: set) -> list[str]:
        img_exts = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}
        image_files = []

        if not os.path.exists(self.download_folder):
            return []

        # downloads.htm 감지 → 실제 다운로드 재시도
        htm_handled = self._handle_downloads_htm(pre_files)
        # htm 처리 후 항상 다운로드 완료 대기 (crdownload 여부와 무관)
        if htm_handled:
            print("  [INFO] downloads.htm 처리 후 재다운로드 대기 중...")
            self._wait_for_download(timeout=120, pre_files=pre_files)

        for fn in os.listdir(self.download_folder):
            if fn in pre_files or fn.startswith('row_') or fn.endswith('.crdownload'):
                continue
            fp = os.path.join(self.download_folder, fn)
            if not os.path.isfile(fp):
                continue

            if fn.lower().endswith('.zip'):
                try:
                    dest = os.path.join(row_path, fn)
                    shutil.move(fp, dest)
                    with zipfile.ZipFile(dest, 'r') as zf:
                        zf.extractall(row_path)
                    os.remove(dest)
                    print(f"  [OK] ZIP 압축 해제: {fn}")
                except Exception as e:
                    print(f"  [오류] ZIP 처리 실패: {e}")
            elif any(fn.lower().endswith(f'.{e}') for e in img_exts):
                dest = os.path.join(row_path, fn)
                shutil.move(fp, dest)

        # row_path 내 모든 이미지 수집
        for root, _, files in os.walk(row_path):
            for fname in files:
                if any(fname.lower().endswith(f'.{e}') for e in img_exts):
                    image_files.append(os.path.join(root, fname))

        # 자연 정렬
        def _natural_key(path):
            parts = re.split(r'(\d+)', os.path.basename(path))
            return [int(p) if p.isdigit() else p.lower() for p in parts]
        image_files.sort(key=_natural_key)

        # EXIF 회전 보정
        for fp in image_files:
            fix_exif_rotation(fp)

        print(f"  [완료] 총 {len(image_files)}개 이미지 다운로드 (망고카)")
        return image_files
