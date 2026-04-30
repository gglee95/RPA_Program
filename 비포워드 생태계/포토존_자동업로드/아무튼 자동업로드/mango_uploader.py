"""Mango Car upload automation driven by nodriver.

Step model captured from the live site:
  STEP 01 — `/ko/car-normal-create`
    Two tabs (차대번호 = 17-char VIN, 차량번호 = Korean license plate).
    Type the identifier into the active tab's textbox, click 조회하기.
    Possible outcomes:
      - Modal "이미 등록된 차량입니다" → click 확인 → SKIP
      - STEP 02 form appears → continue
  STEP 02+ — fields are still being mapped against the live form during the
    first guided run; `fill_step02` is a deliberate scaffold that uses the
    visible labels we expect (광고가, 옵션, 특이사항, 검수, 세차) and falls
    back to logging when a selector misses so the user can refine it.

Cookies for mangoworldcar.com are explicitly cleared before each `login()`
so the previous row's seller session never leaks into the next.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import nodriver as uc
from nodriver import cdp

import config

logger = logging.getLogger(__name__)


VIN_PATTERN = re.compile(r"^[A-Z0-9]{17}$", re.IGNORECASE)
PLATE_PATTERN = re.compile(r"^\d{2,3}[가-힣]\d{4}$")


@dataclass
class LookupResult:
    ok: bool                 # True = ready to fill STEP 02
    reason: str = ""         # 'duplicate' | 'not_found' | 'unsupported_id' | 'ok'


async def _clear_mangocar_cookies(browser: uc.Browser) -> None:
    """Drop every mangoworldcar.com cookie via CDP, in two passes:
      1. `storage.clear_data_for_origin` wipes origin-scoped state.
      2. `network.get_cookies(urls=[…])` enumerates any remaining cookies
         scoped to the host and deletes them one at a time via
         `network.delete_cookies`.

    nodriver's `browser.cookies.get_all()` hangs on Google sessions so we
    deliberately avoid it and scope every CDP call to mangoworldcar.com.
    """
    # Pass 1 — origin clear (also covers localStorage / IndexedDB just in case)
    for origin in (
        "https://mangoworldcar.com",
        "https://www.mangoworldcar.com",
    ):
        try:
            await browser.connection.send(
                cdp.storage.clear_data_for_origin(
                    origin=origin,
                    storage_types="cookies,local_storage,indexeddb",
                )
            )
        except Exception:
            pass

    # Pass 2 — enumerate + delete any stragglers scoped to the host
    try:
        cookies = await asyncio.wait_for(
            browser.connection.send(
                cdp.network.get_cookies(
                    urls=[
                        "https://mangoworldcar.com",
                        "https://mangoworldcar.com/ko",
                        "https://www.mangoworldcar.com",
                    ]
                )
            ),
            timeout=5,
        )
    except Exception:
        cookies = []

    for c in cookies:
        try:
            await browser.connection.send(
                cdp.network.delete_cookies(
                    name=c.name,
                    domain=getattr(c, "domain", None),
                    path=getattr(c, "path", "/") or "/",
                )
            )
        except Exception:
            pass


class MangoUploader:
    def __init__(self, browser: uc.Browser) -> None:
        self.browser = browser
        self.tab: uc.Tab | None = None

    # --- auth -----------------------------------------------------------

    async def login(self, email: str, password: str) -> None:
        """Log in as `email`. Aggressively clears prior session first so every
        row starts with a blank mangoworldcar.com state (no leakage between
        seller accounts).
        """
        await _clear_mangocar_cookies(self.browser)
        self.tab = await self.browser.get(config.SIGN_IN_URL, new_tab=True)
        await self.tab.sleep(1.5)

        # If we're already past sign-in (stale cookies survived the clear
        # attempt), try to click logout, clear cookies, then navigate.
        current_url = await self.tab.evaluate("window.location.href")
        if isinstance(current_url, str) and "/sign-in" not in current_url:
            logger.warning("기존 세션 감지 — 로그아웃 시도 후 재시도")
            # JS로 로그아웃 버튼 클릭 시도
            await self.tab.evaluate("""
            (() => {
                for (const el of document.querySelectorAll('button,a')) {
                    const t = (el.textContent||'').trim();
                    if (t.includes('Logout') || t.includes('로그아웃')) { el.click(); return; }
                }
            })()
            """)
            await self.tab.sleep(2.0)
            await _clear_mangocar_cookies(self.browser)
            await self.tab.get(config.SIGN_IN_URL)
            await self.tab.sleep(2.0)
            current_url = await self.tab.evaluate("window.location.href")
            if isinstance(current_url, str) and "/sign-in" not in current_url:
                # 마지막 수단: 직접 sign-in URL 강제 재시도
                await _clear_mangocar_cookies(self.browser)
                await self.tab.get(config.SIGN_IN_URL)
                await self.tab.sleep(2.0)
                current_url = await self.tab.evaluate("window.location.href")
                if isinstance(current_url, str) and "/sign-in" not in current_url:
                    raise RuntimeError(
                        f"망고카 세션 클리어 실패 — 여전히 {current_url} 에 있음"
                    )

        # Wait for the sign-in form to fully appear.
        await self.tab.wait_for("input[type=password]", timeout=15)

        # Verify we're on the sign-in page (not already redirected elsewhere)
        pre_url = await self.tab.evaluate("window.location.href")
        if isinstance(pre_url, str) and "/sign-in" not in pre_url:
            logger.warning("로그인 페이지가 아님 (%s) — 재시도", pre_url)
            await _clear_mangocar_cookies(self.browser)
            await self.tab.get(config.SIGN_IN_URL)
            await self.tab.sleep(1.5)
            await self.tab.wait_for("input[type=password]", timeout=15)

        # Use JS nativeInputValueSetter so React controlled inputs accept the
        # value AND special characters (*, @, etc.) are not mangled by send_keys.
        esc_email = email.replace("\\", "\\\\").replace("'", "\\'")
        esc_pw    = password.replace("\\", "\\\\").replace("'", "\\'")
        await self.tab.evaluate(f"""
        (() => {{
            function setVal(sel, val) {{
                const el = document.querySelector(sel);
                if (!el) return false;
                el.focus();
                const proto = window.HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                setter.call(el, val);
                el.dispatchEvent(new Event('input', {{bubbles:true}}));
                el.dispatchEvent(new Event('change', {{bubbles:true}}));
                el.dispatchEvent(new Event('blur', {{bubbles:true}}));
                return true;
            }}
            setVal('input[type="email"],input[type="text"]', '{esc_email}');
            setVal('input[type="password"]', '{esc_pw}');
        }})()
        """)
        await self.tab.sleep(0.4)

        # Click the submit button and wait for the URL to change away from sign-in.
        # We do NOT rely on "My page" text because stale cookies can make that
        # text appear on the sign-in page itself (false positive).
        login_btn = await self.tab.select('button[type="submit"]')
        await login_btn.click()

        # Wait for redirect: URL must leave /sign-in within 25s
        deadline = asyncio.get_event_loop().time() + 25
        while asyncio.get_event_loop().time() < deadline:
            cur = await self.tab.evaluate("window.location.href")
            if isinstance(cur, str) and "/sign-in" not in cur:
                break
            await self.tab.sleep(0.5)
        else:
            cur_url = await self.tab.evaluate("window.location.href")
            raise RuntimeError(
                f"로그인 실패 — 25초 후에도 sign-in 페이지에 머물러 있음: {cur_url}"
            )

        # Secondary check: confirm the logged-in nav marker is visible
        try:
            await self.tab.wait_for(text="My page", timeout=8)
        except Exception:
            # "My page" may not be visible yet if still loading; that's OK
            pass

        logger.info("로그인 성공: %s", email)

    async def logout(self) -> None:
        if self.tab is None:
            return
        # Click the first button/link whose text is Logout or 로그아웃. nodriver
        # doesn't support :has-text so we walk the DOM in JS and click.
        js = """
        (() => {
            const needles = ['Logout', '로그아웃'];
            for (const el of document.querySelectorAll('button, a')) {
                const t = (el.textContent || '').trim();
                if (needles.some(n => t.includes(n))) { el.click(); return true; }
            }
            return false;
        })()
        """
        clicked = False
        try:
            result = await self.tab.evaluate(js)
            clicked = bool(result) and not isinstance(result, Exception)
        except Exception:
            clicked = False
        if clicked:
            await self.tab.sleep(1.5)
        else:
            logger.warning("Logout 버튼 못 찾음 - 쿠키 강제 삭제로 대체")
        await _clear_mangocar_cookies(self.browser)

    async def _enter_car_sell_tab(self) -> None:
        """Navigate to the car-create page via the seller's '내차 팔기' flow.

        Strategy (in order):
          1. Navigate to the site root (/ko) so the React nav is in a known
             state, then look for the '내차 팔기' link by text OR href pattern.
          2. On the seller landing page, click '매물등록'.
          3. If either step fails, fall back to the direct URL — but add an
             extra wait so the client-side state can settle.
        """
        assert self.tab is not None

        # ── Step A: Go to homepage, find the "내차 팔기" nav link ────────────
        await self.tab.get(config.BASE_URL + "/ko")
        await self.tab.sleep(3.0)   # let React hydrate the nav

        sell_tab_js = """
        (() => {
            // Try text match first
            const textNeedles = ['내차 팔기', '내차팔기', '내 차 팔기'];
            for (const el of document.querySelectorAll('a, button')) {
                const t = (el.textContent || '').trim();
                if (textNeedles.some(n => t === n || t.startsWith(n))) {
                    el.click(); return t;
                }
            }
            // Fallback: any <a> linking to car-sell
            for (const a of document.querySelectorAll('a[href]')) {
                if (a.href.includes('car-sell')) { a.click(); return a.href; }
            }
            return null;
        })()
        """
        register_btn_js = """
        (() => {
            const needles = ['매물등록', '매물 등록'];
            for (const el of document.querySelectorAll('a, button')) {
                const t = (el.textContent || '').trim();
                if (needles.some(n => t === n || t.startsWith(n))) {
                    el.click(); return t;
                }
            }
            // Fallback: any link to car-normal-create
            for (const a of document.querySelectorAll('a[href]')) {
                if (a.href.includes('car-normal-create')) { a.click(); return a.href; }
            }
            return null;
        })()
        """

        async def _retry(js: str, label: str, attempts: int = 8) -> bool:
            for i in range(attempts):
                try:
                    r = await self.tab.evaluate(js)
                except Exception:
                    r = None
                if r:
                    logger.info("%s 클릭: %r", label, r)
                    await self.tab.sleep(2.5)
                    return True
                if i == attempts - 1:
                    # Last attempt — dump visible nav links for debugging
                    try:
                        url = await self.tab.evaluate("window.location.href")
                        links = await self.tab.evaluate(
                            "JSON.stringify([...document.querySelectorAll('a[href]')].slice(0,20)"
                            ".map(a=>({text:a.textContent.trim().slice(0,30),href:a.href.slice(0,60)})))"
                        )
                        logger.warning("%s 못 찾음 — 현재 URL: %s | 링크들: %s", label, url, links)
                    except Exception:
                        pass
                await self.tab.sleep(1.0)
            return False

        # Step A: click "내차 팔기" from the homepage
        if not await _retry(sell_tab_js, "내차 팔기"):
            logger.warning("내차 팔기 링크 못 찾음 - /ko/car-sell-list 로 직접 이동")
            await self.tab.get(config.CAR_LIST_URL)
            await self.tab.sleep(3.0)

        # Step B: click "매물등록" on the landing/list page
        if not await _retry(register_btn_js, "매물등록"):
            logger.warning("매물등록 버튼 못 찾음 - /ko/car-normal-create 로 직접 이동")
            await self.tab.get(config.CAR_CREATE_URL)
            await self.tab.sleep(3.0)

    # --- STEP 01: lookup ------------------------------------------------

    async def lookup_vehicle(self, identifier: str) -> LookupResult:
        identifier = (identifier or "").strip()
        if not identifier:
            return LookupResult(False, "unsupported_id")

        assert self.tab is not None
        # The upload flow must be entered via the "내차 팔기" nav link, not by
        # directly navigating to /ko/car-normal-create. Direct URLs reliably
        # reach STEP 01 visually but can trigger a spurious "이미 등록된 차량입니다"
        # modal — likely some client-side state needs the tab-click to set up.
        await self._enter_car_sell_tab()
        await self.tab.wait_for("input", timeout=15)
        await self.tab.sleep(1.0)

        if VIN_PATTERN.match(identifier):
            tab_label = "차대번호"
        elif PLATE_PATTERN.match(identifier):
            tab_label = "차량번호"
        else:
            logger.warning("J열 값이 VIN/차량번호 형식 어디에도 안 맞음: %r", identifier)
            return LookupResult(False, "unsupported_id")

        # Click the right STEP 01 tab if it isn't the default
        if tab_label == "차량번호":
            tab_btn = await self.tab.find(tab_label, best_match=True)
            await tab_btn.click()
            await self.tab.sleep(0.5)

        # Grab the visible VIN/plate input. The page renders one text input
        # inside the active tab panel — fall back to a simple scan if the
        # primary selector misses.
        text_input = await self.tab.select("input[type=text]")
        if text_input is None:
            # Defensive: walk every input, pick the one with a 17-digit or plate placeholder
            candidates = await self.tab.select_all("input")
            text_input = next((el for el in candidates if (el.attrs.get("placeholder") or "")), None)
        if text_input is None:
            raise RuntimeError("STEP 01 입력창을 찾을 수 없습니다")
        await text_input.send_keys(identifier)
        await self.tab.sleep(0.3)
        lookup_btn = await self.tab.find("조회하기", best_match=True)
        await lookup_btn.click()

        # ── 모달 처리 루프 ───────────────────────────────────────────────────
        # 조회하기 클릭 후 나타날 수 있는 모달:
        #   A) "XXX 이 맞으신가요?" — 차량 정보 확인 → 확인 클릭 → STEP 02
        #   B) "이미 등록된 차량입니다"  — 진짜 중복 → SKIP
        #   C) "차량 정보가 없습니다" — 직접 입력 → 확인 클릭 → STEP 02
        # ※ 모달을 먼저 확인한다 — "매물 등록" 텍스트가 배경 nav에도 있어서
        #   폼 감지를 먼저 하면 모달이 떠 있어도 성공으로 오인하기 때문.
        js_modal_info = """
        (() => {
            const selectors = [
                '[role=dialog]','[role=alertdialog]',
                '.ant-modal-content','.modal-content',
                '[class*="modal"],[class*="dialog"],[class*="popup"]'
            ];
            for (const sel of selectors) {
                const els = [...document.querySelectorAll(sel)];
                for (const el of els) {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    const text = (el.innerText || '').trim();
                    if (text.length > 5) return text.slice(0, 300);
                }
            }
            return null;
        })()
        """

        js_click_confirm = """
        (() => {
            const dialogs = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')]
                .filter(el => window.getComputedStyle(el).display !== 'none');
            for (const d of dialogs) {
                const btns = d.querySelectorAll('button');
                if (btns.length >= 2) { btns[1].click(); return true; }
                if (btns.length === 1) { btns[0].click(); return true; }
            }
            return false;
        })()
        """

        duplicate_confirmed = False
        for _attempt in range(6):
            await self.tab.sleep(2)

            # ── 모달 먼저 확인 ── (배경 nav의 "매물 등록" 오탐 방지)
            try:
                modal_text = await self.tab.evaluate(js_modal_info)
            except Exception:
                modal_text = None

            logger.info("[%s] 모달 텍스트 (attempt %d): %r", identifier, _attempt, (modal_text or "")[:80])

            if modal_text and "맞으신가요" in modal_text:
                # A) 차량 확인 모달 → 확인 클릭 (nodriver CDP 클릭 우선, JS fallback)
                logger.info("[%s] 차량 확인 모달 → 확인 클릭", identifier)
                confirmed = False
                try:
                    # '확인' 텍스트 버튼을 nodriver로 직접 클릭
                    confirm_btn = await self.tab.find("확인", best_match=True, timeout=3)
                    await confirm_btn.click()
                    confirmed = True
                except Exception:
                    pass
                if not confirmed:
                    try:
                        await self.tab.evaluate(js_click_confirm)
                    except Exception:
                        pass
                await self.tab.sleep(1.0)
                continue

            if modal_text and ("직접 입력" in modal_text or "차량 정보가 없습니다" in modal_text):
                # C) 조회 불가 → 차대번호 없음 → 취소(첫 번째 버튼) 클릭 후 SKIP
                logger.warning("[%s] 차대번호 없음 모달 — 취소 클릭 후 SKIP", identifier)
                cancel_clicked = await self.tab.evaluate("""
                (() => {
                    const dialogs = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')]
                        .filter(el => window.getComputedStyle(el).display !== 'none');
                    for (const d of dialogs) {
                        const btns = d.querySelectorAll('button');
                        if (btns.length >= 1) { btns[0].click(); return true; }
                    }
                    return false;
                })()
                """)
                if not cancel_clicked:
                    try:
                        cancel_btn = await self.tab.find("취소", best_match=True, timeout=3)
                        await cancel_btn.click()
                    except Exception:
                        pass
                await self.tab.sleep(0.5)
                return LookupResult(False, "vin_not_found")

            if modal_text and "이미 등록" in modal_text:
                # B) 진짜 중복 모달
                logger.warning("[%s] 중복 모달 확인 → SKIP", identifier)
                try:
                    await self.tab.evaluate(js_click_confirm)
                except Exception:
                    pass
                duplicate_confirmed = True
                break

            if modal_text:
                # 알 수 없는 모달(면책고지 등) → 확인 클릭 후 계속
                logger.info("[%s] 기타 모달 감지 → 확인 클릭 후 계속", identifier)
                try:
                    ok = await self.tab.find("확인", best_match=True, timeout=3)
                    await ok.click()
                except Exception:
                    try:
                        await self.tab.evaluate(js_click_confirm)
                    except Exception:
                        pass
                await self.tab.sleep(1.0)
                continue

            # 모달 없음 → 현재 페이지 상태 확인
            # 아직 조회 결과를 기다리는 중(STEP 1 검색 폼)이면 계속 대기
            page_state = await self.tab.evaluate("""
            (() => {
                const hasBrand = [...document.querySelectorAll('div[class*="font-medium"],label')]
                    .some(el => (el.textContent||'').replace(/[*\\s]/g,'').includes('브랜드'));
                const hasPrice = (document.body.textContent||'').includes('광고가');
                const hasRegister = [...document.querySelectorAll('button')]
                    .some(b => ['등록하기','등록완료'].includes((b.textContent||'').trim()));
                const hasNextBtn = [...document.querySelectorAll('button')]
                    .some(b => (b.textContent||'').trim() === '다음');
                // 아직 검색 폼(차대번호 입력 화면)인지 확인
                const stillSearch = !hasBrand && !hasPrice && !hasRegister;
                if (hasBrand || (hasNextBtn && !stillSearch)) return 'vehicle_info';
                if (hasPrice || hasRegister) return 'listing_form';
                return 'search_form';
            })()
            """)
            logger.info("[%s] 페이지 상태: %s (attempt %d)", identifier, page_state, _attempt)
            if page_state == 'search_form' and _attempt < 5:
                # 아직 조회 결과 대기 중 → 계속 폴링
                continue
            # 폼에 진입했거나 더 기다려도 소용없음 → 루프 탈출
            break

        # ── 최종 등록 폼 감지 ────────────────────────────────────────────────
        # 실제 폼 헤딩은 "매물 등록" (STEP 02 텍스트 아님)
        if not duplicate_confirmed:
            for marker in ("매물 등록", "STEP 02", "광고가", "브랜드 정보"):
                try:
                    await self.tab.wait_for(text=marker, timeout=4)
                    logger.info("[%s] 등록 폼 진입 성공 (감지: %r)", identifier, marker)
                    return LookupResult(True, "ok")
                except Exception:
                    pass

        if duplicate_confirmed:
            logger.info("[%s] 이미 등록된 차량 - SKIP", identifier)
            return LookupResult(False, "duplicate")

        logger.warning("[%s] STEP 02로 진입하지 못함", identifier)
        return LookupResult(False, "not_found")

    # --- screenshots ----------------------------------------------------

    async def _screenshot(self, label: str) -> None:
        """Save a PNG screenshot to STATE_DIR/screenshots/<label>.png."""
        import base64
        from nodriver import cdp as _cdp
        try:
            shots_dir = config.STATE_DIR / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            result = await self.tab.send(_cdp.page.capture_screenshot(format_="png"))
            path = shots_dir / f"{label}.png"
            path.write_bytes(base64.b64decode(result.data))
            logger.info("[스크린샷] %s", path.name)
        except Exception as exc:
            logger.debug("스크린샷 실패 (%s): %s", label, exc)

    # --- vehicle info form (직접입력 STEP 01) ----------------------------

    async def _select_radix_by_label(self, label: str, value: str) -> bool:
        """Find Radix Select dropdown near label text, open it, click matching option."""
        if not value:
            return False
        escaped_label = label.replace("'", "\\'")
        escaped_value = value.replace("'", "\\'")
        # 레이블 div는 "* 브랜드 선택" 패턴 — *와 공백 제거 후 label 포함 여부로 판단
        opened = await self.tab.evaluate(f"""
        (() => {{
            function cleanText(el) {{
                return (el.textContent||'').replace(/\\*/g,'').trim();
            }}
            // font-medium div에서 레이블 찾기
            for (const el of document.querySelectorAll('div[class*="font-medium"],label')) {{
                const t = cleanText(el);
                if (t !== '{escaped_label}' && !t.startsWith('{escaped_label}')) continue;
                let node = el.parentElement;
                for (let i = 0; i < 6; i++) {{
                    if (!node) break;
                    const btn = node.querySelector('button[role="combobox"],button[aria-haspopup]');
                    if (btn && !btn.hasAttribute('disabled') && !btn.dataset.disabled) {{
                        btn.click(); return true;
                    }}
                    node = node.parentElement;
                }}
            }}
            return false;
        }})()
        """)
        if not opened:
            logger.warning("드롭다운 못 열음 (label=%s)", label)
            return False
        await self.tab.sleep(1.0)
        clicked = await self.tab.evaluate(f"""
        (() => {{
            const opts = [...document.querySelectorAll('[role="option"]')]
                .filter(el => window.getComputedStyle(el).display !== 'none');
            const val = '{escaped_value}';
            // 1단계: 정확 일치 또는 접두어 일치
            for (const el of opts) {{
                const t = (el.textContent||'').trim();
                if (t === val || t.startsWith(val)) {{ el.click(); return t; }}
            }}
            // 2단계: 값이 옵션에 포함되거나 옵션이 값에 포함 (부분 일치)
            for (const el of opts) {{
                const t = (el.textContent||'').trim();
                if (t.includes(val) || val.includes(t)) {{ el.click(); return 'fuzzy:'+t; }}
            }}
            // 못 찾으면 옵션 목록 반환 (디버그)
            const names = opts.map(el => (el.textContent||'').trim()).slice(0, 20);
            document.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape',bubbles:true}}));
            return JSON.stringify(names);
        }})()
        """)
        if clicked and not clicked.startswith('['):
            logger.info("드롭다운 선택: %s = %s", label, clicked)
            await self.tab.sleep(0.5)
            return True
        logger.warning("드롭다운 옵션 못 찾음: label=%s, value=%s | 옵션목록: %s", label, value, clicked)
        return False

    # 드롭다운 값 매핑 (시트 한글값 → 망고카 영어/숫자 옵션)
    _TRANSMISSION_MAP = {
        "자동": "AUTO", "오토": "AUTO", "AT": "AUTO",
        "수동": "MANUAL", "매뉴얼": "MANUAL", "MT": "MANUAL",
    }
    # 모델명 별칭 (시트 표기 → 망고카 표기)
    _MODEL_ALIASES: dict[str, str] = {
        "소나타": "쏘나타",
        "그랜져": "그랜저",
        "스포티지R": "스포티지",
        "K5": "K5",
    }
    _COLOR_MAP = {
        "화이트": "WHITE", "흰색": "WHITE", "백색": "WHITE",
        "블랙": "BLACK", "검정": "BLACK", "검정색": "BLACK", "흑색": "BLACK",
        "실버": "SILVER", "은색": "SILVER",
        "그레이": "GRAY", "회색": "GRAY",
        "펄": "PEARL", "진주": "PEARL",
        "블루": "BLUE", "파랑": "BLUE", "파란색": "BLUE",
        "레드": "RED", "빨강": "RED", "빨간색": "RED",
        "브라운": "BROWN", "갈색": "BROWN",
        "그린": "GREEN", "초록": "GREEN",
        "옐로우": "YELLOW", "노랑": "YELLOW",
        "골드": "GOLD", "금색": "GOLD",
        "오렌지": "ORANGE",
        "퍼플": "PURPLE", "보라": "PURPLE",
        "핑크": "PINK", "분홍": "PINK",
        "네이비": "NAVY", "남색": "NAVY",
        "민트": "MINT",
        "기타": "ETC",
    }

    @staticmethod
    def _map_transmission(val: str) -> str:
        return MangoUploader._TRANSMISSION_MAP.get(val, val)

    @staticmethod
    def _map_color(val: str) -> str:
        # 이미 영어 대문자면 그대로 (ASCII 체크)
        if val.isascii() and val.replace('_', '').isalpha():
            return val.upper()
        return MangoUploader._COLOR_MAP.get(val, val)

    @staticmethod
    def _map_seating(val: str) -> str:
        import re
        m = re.search(r'\d+', val)
        return m.group() if m else val

    @staticmethod
    def _map_drive(has_4wd: bool) -> str:
        return "4WD" if has_4wd else "2WD"

    async def _select_grade_if_present(self) -> None:
        """세부모델 선택 후 나타날 수 있는 '등급' 드롭다운 — 첫 번째 옵션 선택.

        시트에 등급 정보가 없으므로 드롭다운이 보이면 첫 번째 옵션을 자동 선택.
        없으면 무시.
        """
        opened = await self.tab.evaluate("""
        (() => {
            function cleanText(el) { return (el.textContent||'').replace(/[*\\s]/g,''); }
            for (const el of document.querySelectorAll('div[class*="font-medium"],label')) {
                const t = cleanText(el);
                if (t.includes('등급') || t.includes('트림') || t.includes('Grade')) {
                    let node = el.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!node) break;
                        const btn = node.querySelector('button[role="combobox"],button[aria-haspopup]');
                        if (btn && !btn.hasAttribute('disabled')) {
                            btn.click(); return true;
                        }
                        node = node.parentElement;
                    }
                }
            }
            return false;
        })()
        """)
        if not opened:
            return
        await self.tab.sleep(1.0)
        clicked = await self.tab.evaluate("""
        (() => {
            const opts = [...document.querySelectorAll('[role="option"]')]
                .filter(el => window.getComputedStyle(el).display !== 'none');
            if (opts.length > 0) { opts[0].click(); return opts[0].textContent.trim(); }
            document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
            return null;
        })()
        """)
        if clicked:
            logger.info("등급 드롭다운 첫 번째 옵션 선택: %s", clicked)
            await self.tab.sleep(0.5)

    async def _click_mileage_confirm_checkbox(self) -> None:
        """고주행 경고 시 나타나는 '(필수) 이 내용에 동의합니다' 체크박스 클릭."""
        clicked = await self.tab.evaluate("""
        (() => {
            const chks = [...document.querySelectorAll('[role="checkbox"][aria-checked="false"]')];
            let n = 0;
            for (const chk of chks) {
                // 옵션/부가서비스 체크박스가 아닌, 동의 체크박스만 클릭
                const container = chk.closest('div');
                const text = container ? (container.textContent||'') : '';
                if (text.includes('동의') || text.includes('확인') || text.includes('agree')) {
                    chk.click(); n++;
                }
            }
            return n;
        })()
        """)
        if clicked:
            logger.info("주행거리 확인 체크박스 클릭: %s개", clicked)
            await self.tab.sleep(0.5)

    async def _select_country(self, country: str) -> None:
        """차량위치 국가 선택 — '국가 선택' 버튼 직접 클릭 후 옵션 선택."""
        escaped = country.replace("'", "\\'")
        opened = await self.tab.evaluate(f"""
        (() => {{
            // '국가 선택' placeholder가 있는 버튼 클릭
            for (const btn of document.querySelectorAll('button[aria-haspopup]')) {{
                const t = (btn.textContent||'').trim();
                if (t.includes('국가 선택') || t.includes('대한민국')) {{
                    btn.click(); return true;
                }}
            }}
            return false;
        }})()
        """)
        if not opened:
            logger.warning("차량위치 버튼 못 찾음")
            return
        await self.tab.sleep(1.0)
        clicked = await self.tab.evaluate(f"""
        (() => {{
            for (const el of document.querySelectorAll('[role="option"]')) {{
                if (window.getComputedStyle(el).display === 'none') continue;
                const t = (el.textContent||'').trim();
                if (t.includes('{escaped}')) {{ el.click(); return t; }}
            }}
            document.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape',bubbles:true}}));
            return null;
        }})()
        """)
        logger.info("차량위치 선택: %r", clicked)
        if clicked:
            await self.tab.sleep(0.5)

    async def _pick_registration_date(self, year_str: str) -> None:
        """최초 등록일 — 연식 Jan 1 설정 시도. 실패해도 무시.
        목표 연도에 도달하지 못하면 날짜를 클릭하지 않고 캘린더를 닫는다.
        """
        if not year_str or not year_str.isdigit():
            return
        target_year = int(year_str)
        date_set = False
        try:
            opened = await self.tab.evaluate("""
            (() => {
                // 1순위: aria-haspopup="dialog" 버튼 중 날짜 관련 텍스트
                for (const btn of document.querySelectorAll('button[aria-haspopup="dialog"]')) {
                    const t = (btn.textContent||'').trim();
                    if (t.includes('날짜') || t.includes('선택')) { btn.click(); return 'by-aria'; }
                }
                // 2순위: "최초 등록일" 레이블 근처 버튼
                for (const lbl of document.querySelectorAll('div[class*="font-medium"],label,span')) {
                    const t = (lbl.textContent||'').replace(/[*\\s]/g,'');
                    if (!t.includes('최초등록일') && !t.includes('등록일')) continue;
                    let node = lbl.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!node) break;
                        const btn = node.querySelector('button');
                        if (btn) { btn.click(); return 'near-label'; }
                        node = node.parentElement;
                    }
                }
                // 3순위: 날짜 텍스트 버튼
                for (const btn of document.querySelectorAll('button')) {
                    const t = (btn.textContent||'').trim();
                    if (t.includes('날짜를 선택') || t.includes('날짜 선택')) {
                        btn.click(); return 'by-text';
                    }
                }
                return false;
            })()
            """)
            if not opened:
                return
            await self.tab.sleep(1.0)

            import re as _re, json as _json
            _MONTH_EN = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            for _ in range(300):
                info = await self.tab.evaluate("""
                (() => {
                    const d = document.querySelector('[role="dialog"]');
                    if (!d) return null;
                    const h = d.querySelector('[role="heading"],caption,h2,h3,div[class*="caption"]');
                    const fullText = (d.innerText||'').slice(0,80);
                    const btns = [...d.querySelectorAll('button')].map(b=>b.textContent.trim()).filter(t=>t);
                    return JSON.stringify({h: h?(h.textContent||'').trim():fullText, btns: btns.slice(0,5)});
                })()
                """)
                if not info:
                    break
                data = _json.loads(info)
                heading = data.get("h", "")
                m_y = _re.search(r'(\d{4})', heading)
                m_mo_ko = _re.search(r'(\d{1,2})월', heading)
                m_mo_en = _re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)', heading.lower())
                cur_year = int(m_y.group(1)) if m_y else 0
                if m_mo_ko:
                    cur_month = int(m_mo_ko.group(1))
                elif m_mo_en:
                    cur_month = _MONTH_EN[m_mo_en.group(1)]
                else:
                    cur_month = 1
                if cur_year == target_year and cur_month == 1:
                    await self.tab.evaluate("""
                    (() => {
                        const d = document.querySelector('[role="dialog"]');
                        if (!d) return;
                        for (const btn of d.querySelectorAll('button')) {
                            const lbl = (btn.getAttribute('aria-label') || '').trim();
                            if (/^1[일,\s]|^1$/.test(lbl)) { btn.click(); return; }
                        }
                        for (const btn of d.querySelectorAll('button')) {
                            if (btn.textContent.trim() === '1') { btn.click(); return; }
                        }
                    })()
                    """)
                    await self.tab.sleep(0.8)
                    still_open = await self.tab.evaluate(
                        "!!document.querySelector('[role=\"dialog\"]')"
                    )
                    if still_open:
                        await self.tab.evaluate(
                            "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
                        )
                        await self.tab.sleep(0.3)
                    logger.info("날짜 설정: %s-01-01", target_year)
                    date_set = True
                    break
                if cur_year > target_year or (cur_year == target_year and cur_month > 1):
                    await self.tab.evaluate("""
                    (() => {
                        const d = document.querySelector('[role="dialog"]');
                        if (!d) return;
                        for (const btn of d.querySelectorAll('button')) {
                            const lbl = (btn.getAttribute('aria-label')||'').toLowerCase();
                            if (lbl.includes('prev') || lbl.includes('이전')) { btn.click(); return; }
                        }
                        const btns = d.querySelectorAll('button');
                        if (btns[0]) btns[0].click();
                    })()
                    """)
                    await self.tab.sleep(0.2)
                else:
                    break

            # 목표 연도에 도달하지 못했으면 캘린더를 Escape로 닫아 날짜 미입력 상태 유지
            if not date_set:
                logger.warning("날짜 피커: %s년으로 이동 실패 — 날짜 미입력 상태로 캘린더 닫기", target_year)
                await self.tab.evaluate(
                    "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))"
                )
                await self.tab.sleep(0.3)

        except Exception as e:
            logger.warning("날짜 피커 실패 (무시): %s", e)
            await self.tab.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        await self.tab.sleep(0.3)

    async def _select_model_by_xpath(self, value: str) -> bool:
        """모델명 버튼을 XPath로 직접 클릭 후 옵션 선택.
        XPath: //*[@id="car-create-form"]/section[1]/section/div[3]/button
        """
        if not value:
            return False
        escaped_value = value.replace("'", "\\'")
        opened = await self.tab.evaluate(f"""
        (() => {{
            const xp = '//*[@id="car-create-form"]/section[1]/section/div[3]/button';
            const res = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            const btn = res.singleNodeValue;
            if (btn && !btn.disabled && !btn.dataset.disabled) {{ btn.click(); return true; }}
            return false;
        }})()
        """)
        if not opened:
            logger.warning("모델명 XPath 버튼 못 찾음 — label fallback")
            return await self._select_radix_by_label("모델명", value)
        await self.tab.sleep(1.0)
        clicked = await self.tab.evaluate(f"""
        (() => {{
            const opts = [...document.querySelectorAll('[role="option"]')]
                .filter(el => window.getComputedStyle(el).display !== 'none');
            const val = '{escaped_value}';
            for (const el of opts) {{
                const t = (el.textContent||'').trim();
                if (t === val || t.startsWith(val)) {{ el.click(); return t; }}
            }}
            for (const el of opts) {{
                const t = (el.textContent||'').trim();
                if (t.includes(val) || val.includes(t)) {{ el.click(); return 'fuzzy:'+t; }}
            }}
            const names = opts.map(el => (el.textContent||'').trim()).slice(0, 20);
            document.dispatchEvent(new KeyboardEvent('keydown', {{key:'Escape',bubbles:true}}));
            return JSON.stringify(names);
        }})()
        """)
        if clicked and not str(clicked).startswith('['):
            logger.info("모델명(XPath) 선택: %s", clicked)
            await self.tab.sleep(0.5)
            return True
        logger.warning("모델명 옵션 못 찾음: value=%s | 옵션목록: %s", value, clicked)
        return False

    async def _fill_vehicle_info(self, listing) -> None:
        """기본정보 입력 폼(직접입력 모드) 채우기 후 다음 클릭."""
        assert self.tab is not None
        await self.tab.sleep(1.0)

        # 차대번호
        vin = listing.identifier
        if vin:
            await self._try_fill_by_label("차대번호", vin)

        # 연식 — 성공 여부를 추적해서 실패 시 날짜 피커 스킵
        연식 = listing.get("연식").strip()
        연식_ok = False
        if 연식:
            연식_ok = await self._select_radix_by_label("연식", 연식)
            if not 연식_ok:
                logger.warning("연식 드롭다운 실패 (%s) — 최초등록일 입력 스킵", 연식)

        # 브랜드 → 모델명 (캐스케이딩)
        브랜드 = listing.get("브랜드").strip()
        if 브랜드:
            await self._select_radix_by_label("브랜드 선택", 브랜드)
            await self.tab.sleep(1.5)

        # E열(차종) → 모델명: XPath로 버튼 직접 클릭
        차종 = listing.get("차종").strip()
        if 차종:
            차종_mapped = self._MODEL_ALIASES.get(차종, 차종)
            await self._select_model_by_xpath(차종_mapped)
            await self.tab.sleep(3.0)  # 세부모델/변속기 드롭다운 로딩 대기

        # 세부모델(F열)은 사용하지 않음 — 모델명(E열)만으로 매칭

        # 변속기 (자동→AUTO, 수동→MANUAL; 없으면 AUTO 기본값)
        미션 = listing.get("미션").strip()
        미션_mapped = self._map_transmission(미션) if 미션 else "AUTO"
        ok = await self._select_radix_by_label("변속기", 미션_mapped)
        if not ok:
            await self.tab.sleep(2.0)
            await self._select_radix_by_label("변속기", 미션_mapped)
        await self.tab.sleep(1.0)  # 연료 드롭다운 로딩 대기

        # 연료 (변속기 선택 후 DOM 갱신이 있을 수 있어 재시도)
        유종 = listing.get("유종").strip()
        if 유종:
            ok = await self._select_radix_by_label("연료", 유종)
            if not ok:
                await self.tab.sleep(1.0)
                await self._select_radix_by_label("연료", 유종)

        # 색상 (화이트→WHITE 등)
        색상 = listing.get("차량색상").strip()
        if 색상:
            await self._select_radix_by_label("색상", self._map_color(색상))

        # 승차인원 (5인승→5 등)
        인승 = listing.get("인승").strip()
        if 인승:
            await self._select_radix_by_label("승차인원", self._map_seating(인승))

        # 구동방식: 4WD 옵션 체크면 4WD, 아니면 2WD
        drive = self._map_drive(bool(listing.options.get("4WD")))
        await self._select_radix_by_label("구동방식", drive)

        # 차량 위치 → 무조건 대한민국 (버튼 직접 클릭 방식)
        await self._select_country("대한민국")

        # 배기량 (직접입력 모드 전용 필수 필드 — 시트에 없으므로 기본값)
        # VIN 조회 성공 시에는 이 필드가 폼에 없어서 자동 skip됨
        await self._try_fill_by_label("배기량", "2000")

        # 최초 등록일 → 연식 드롭다운이 성공했을 때만 입력 (실패 시 기본값 2026 방지)
        if 연식_ok:
            await self._pick_registration_date(연식)

        # 주행거리 텍스트 (콤마 제거: "550,000" → "550000")
        주행거리 = re.sub(r"[,\s]", "", listing.get("실주행거리").strip())
        if 주행거리:
            await self._try_fill_by_label("주행거리", 주행거리)
            await self.tab.sleep(0.5)
            # 고주행 경고 체크박스(필수 동의)가 나타났으면 클릭
            await self._click_mileage_confirm_checkbox()

        # 판매자 수금가(차량 광고가) — 기본정보 섹션에 포함된 필수 가격 필드
        price = listing.ad_price_number
        if price:
            ok = await self._try_fill_by_label("판매자 수금가", price)
            if not ok:
                await self._try_fill_by_label("광고가", price)

        await self.tab.sleep(0.5)
        await self._screenshot("before_next_click")

        # 다음 버튼 클릭
        clicked = await self.tab.evaluate("""
        (() => {
            for (const btn of document.querySelectorAll('button')) {
                const t = (btn.textContent||'').trim();
                if (t === '다음') { btn.click(); return true; }
            }
            return false;
        })()
        """)
        logger.info("기본정보 입력 완료, 다음 클릭: %s", clicked)
        await self.tab.sleep(4.0)

        # 다음 클릭 후 validation 에러 확인
        errs = await self.tab.evaluate("""
        JSON.stringify([...document.querySelectorAll('[class*="error"],[class*="invalid"],[class*="destructive"],[role="alert"]')]
            .map(el => (el.textContent||'').trim().slice(0, 80))
            .filter(t => t && t.length > 3).slice(0, 8))
        """)
        if errs and errs != "[]":
            # 어느 필드가 실패했는지 레이블과 함께 로깅
            field_errors = await self.tab.evaluate("""
            JSON.stringify(
                [...document.querySelectorAll('[class*="error"],[class*="invalid"],[class*="destructive"],[role="alert"]')]
                .filter(el => (el.textContent||'').trim().length > 3)
                .map(el => {
                    const t = (el.textContent||'').trim().slice(0,60);
                    let label = '';
                    let node = el.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!node) break;
                        const lbl = node.querySelector('div[class*="font-medium"],label,legend');
                        if (lbl) { label = (lbl.textContent||'').replace(/\\*/g,'').trim().slice(0,30); break; }
                        node = node.parentElement;
                    }
                    return label + ' → ' + t;
                })
                .slice(0, 10)
            )
            """)
            await self._screenshot("step1_validation_errors")
            raise RuntimeError(
                f"기본정보 입력 오류 — 업로드 중단: {field_errors}"
            )
        else:
            await self._screenshot("after_next_click")

    # --- STEP 02+: fill listing details --------------------------------

    async def fill_step02(self, listing) -> None:
        assert self.tab is not None
        await self.tab.sleep(1.0)

        # 직접입력 모드 감지: 다음 버튼 + 브랜드 관련 레이블이 있으면 기본정보 입력 폼
        on_vehicle_info = await self.tab.evaluate("""
        (() => {
            const hasNext = [...document.querySelectorAll('button')]
                .some(b => b.textContent.trim() === '다음');
            const hasBrand = [...document.querySelectorAll('div[class*="font-medium"],label')]
                .some(el => (el.textContent||'').replace(/\*/g,'').trim().includes('브랜드'));
            return hasNext && hasBrand;
        })()
        """)

        if on_vehicle_info:
            logger.info("직접입력 기본정보 폼 감지 → 차량 정보 입력 후 다음 클릭")
            await self._fill_vehicle_info(listing)
            await self.tab.sleep(2.0)

        # ── 광고가 (price) ──────────────────────────────────────────────────
        price = listing.ad_price_number
        if price:
            await self._try_fill_by_label("광고가", price)

        # ── 주행거리 ─────────────────────────────────────────────────────────
        mileage = re.sub(r"[,\s]", "", listing.get("실주행거리").strip())
        if mileage:
            await self._try_fill_by_label("주행거리", mileage)
            await self._try_fill_by_label("실주행거리", mileage)

        # ── 옵션 체크박스 ────────────────────────────────────────────────────
        for key, checked in listing.options.items():
            if checked:
                await self._try_check_by_label(key)

        # ── 부가서비스 (검수/세차) ────────────────────────────────────────────
        for key, checked in listing.addons.items():
            if checked:
                await self._try_check_by_label(key)

        # ── 특이사항 ─────────────────────────────────────────────────────────
        notes = listing.get("특이사항")
        if notes:
            await self._try_fill_by_label("특이사항", notes)

    async def _try_fill_by_label(self, label: str, value: str) -> bool:
        """레이블 텍스트 기준으로 가장 가까운 input/textarea를 찾아 값 입력.

        React controlled input은 단순 .value 대입이 무시되므로
        HTMLInputElement.prototype.value의 native setter를 사용.
        """
        escaped_label = label.replace("'", "\\'")
        escaped_value = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        try:
            result = await self.tab.evaluate(f"""
            (() => {{
                function findInput(labelText) {{
                    const candidates = [
                        ...document.querySelectorAll('label'),
                        ...document.querySelectorAll('div[class*="font-medium"]'),
                        ...document.querySelectorAll('span[class*="font-medium"]'),
                        ...document.querySelectorAll('p,span,div'),
                    ];
                    for (const el of candidates) {{
                        const t = (el.textContent||'').replace(/[*\\s]/g,'');
                        const cleaned = labelText.replace(/[*\\s]/g,'');
                        if (!t.includes(cleaned)) continue;
                        // 해당 엘리먼트 기준 위로 6단계까지 input 탐색
                        let node = el.parentElement;
                        for (let i = 0; i < 8; i++) {{
                            if (!node) break;
                            const inp = node.querySelector('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]),textarea');
                            if (inp) return inp;
                            node = node.parentElement;
                        }}
                    }}
                    return null;
                }}
                const input = findInput('{escaped_label}');
                if (!input) return 'not_found';
                input.focus();
                // React controlled input을 위한 native setter 사용
                const proto = input.tagName === 'TEXTAREA'
                    ? window.HTMLTextAreaElement.prototype
                    : window.HTMLInputElement.prototype;
                const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                nativeSetter.call(input, '{escaped_value}');
                input.dispatchEvent(new Event('input', {{bubbles:true}}));
                input.dispatchEvent(new Event('change', {{bubbles:true}}));
                // blur 이벤트 — React Hook Form이 touched 상태로 전환하며 유효성 재검사
                input.dispatchEvent(new Event('blur', {{bubbles:true}}));
                return 'ok:' + (input.name||input.id||'?') + ':' + input.value.slice(0,30);
            }})()
            """)
            if result == 'not_found':
                logger.warning("필드 셀렉터 못 찾음: %s", label)
                return False
            else:
                logger.info("필드 입력: %s = %s → %s", label, value, result)
                return True
        except Exception as e:
            logger.warning("필드 입력 실패: %s (%s)", label, e)
            return False

    async def _try_check_by_label(self, label: str) -> None:
        try:
            el = await self.tab.find(label, best_match=True, timeout=3)
            await el.click()
            logger.info("옵션 체크: %s", label)
        except Exception:
            logger.warning("옵션 라벨 못 찾음: %s", label)

    # --- photos ---------------------------------------------------------

    async def upload_photos(self, category_files: dict[str, list[Path]]) -> None:
        """Upload photos in PHOTO_CATEGORIES order.

        Strategy: try the first <input type=file> we see with all files
        concatenated in order; if that fails, the per-category fallback in
        the next iteration of this method (added after first guided run)
        will pick the right input per category.
        """
        assert self.tab is not None
        ordered = [
            str(p)
            for canonical, _aliases in config.PHOTO_CATEGORIES
            for p in category_files.get(canonical, [])
        ]
        if not ordered:
            logger.info("업로드할 사진이 없음")
            return
        try:
            file_input = await self.tab.select("input[type=file]")
            # nodriver Element supports send_file via CDP DOM.setFileInputFiles
            await file_input.send_file(*ordered)
            logger.info("단일 input에 %d장 업로드", len(ordered))
        except AttributeError:
            # Older nodriver: fall back to CDP directly
            await self._set_input_files_via_cdp(ordered)
        except Exception as exc:
            logger.warning("사진 업로드 실패 (%s) - 첫 실행에서 셀렉터 보강 필요", exc)

    async def _set_input_files_via_cdp(self, paths: list[str]) -> None:
        assert self.tab is not None
        # Find the file input nodeId
        doc = await self.tab.send(cdp.dom.get_document())
        node_id = await self.tab.send(
            cdp.dom.query_selector(node_id=doc.node_id, selector="input[type=file]")
        )
        await self.tab.send(cdp.dom.set_file_input_files(files=paths, node_id=node_id))
        logger.info("CDP set_file_input_files: %d개", len(paths))

    # --- submit ---------------------------------------------------------

    _JS_CLICK_ACTION = """
    (() => {
        const NAV_SKIP = ['offers', '(KST)', 'Logout', 'My page', '조회하기', 'Search'];
        function isNav(btn) {
            const t = (btn.textContent||'').trim();
            return NAV_SKIP.some(s => t.includes(s)) || btn.type === 'reset';
        }
        // 텍스트 우선순위: 등록하기 > 등록완료 > 다음 > 매물등록
        const labels = ['등록하기', '등록완료', '다음', '매물등록'];
        for (const label of labels) {
            for (const btn of document.querySelectorAll('button')) {
                if (isNav(btn)) continue;
                const t = (btn.textContent||'').trim().replace(/\\s+/g,'');
                if (t === label || t.startsWith(label)) {
                    btn.click(); return 'label:' + t;
                }
            }
        }
        return null;
    })()
    """

    async def submit(
        self,
        category_files: "dict[str, list[Path]] | None" = None,
        listing=None,
    ) -> str:
        """Navigate through remaining form steps and submit.

        Handles multi-step: options page → photo upload page → 등록하기.
        category_files and listing are optional; if provided, photos are uploaded
        and 특이사항 is filled on the photo step.
        """
        assert self.tab is not None
        # 페이지 HTML 덤프 (구조 파악용)
        try:
            html = await self.tab.evaluate("document.body.innerHTML")
            dump_path = config.STATE_DIR / "before_submit.html"
            dump_path.write_text(str(html), encoding="utf-8")
            logger.info("HTML 덤프: %s", dump_path)
        except Exception as e:
            logger.warning("HTML 덤프 실패: %s", e)

        photo_uploaded = False  # 사진 업로드 한 번만 시도
        notes_filled = False    # 특이사항 한 번만 시도

        last_clicked = None
        consecutive_same_errors = 0
        last_errors: str = ""
        success_modal_seen = False  # "매물등록에 성공했습니다" 모달 감지 플래그
        for attempt in range(25):
            await self.tab.sleep(2)
            url = await self.tab.evaluate("window.location.href")
            if isinstance(url, str) and "MGC_" in url:
                logger.info("submit 완료, URL: %s", url)
                return url

            # car-sell-list로 이동 = 등록 성공 후 목록으로 리다이렉트
            # 페이지 내 가장 최근 MGC_ 링크를 추출해서 반환
            if isinstance(url, str) and "car-sell-list" in url:
                mgc_url = await self.tab.evaluate("""
                (() => {
                    for (const a of document.querySelectorAll('a[href]')) {
                        if (a.href.includes('MGC_')) return a.href;
                    }
                    return null;
                })()
                """)
                if mgc_url:
                    logger.info("submit 완료 (sell-list 리다이렉트), URL: %s", mgc_url)
                    return str(mgc_url)
                logger.info("submit 완료 (sell-list 리다이렉트, MGC_ 링크 없음)")
                return url

            # 성공 모달 이후 MGC_ URL 대기 — 버튼 클릭 없이 URL만 폴링
            if success_modal_seen:
                logger.info("성공 모달 후 MGC_ URL 대기 중 (attempt %d), 현재: %s", attempt, url)
                continue

            # 모달 처리 (우선)
            modal_handled = await self.tab.evaluate("""
            (() => {
                const d = [...document.querySelectorAll('[role="dialog"],[role="alertdialog"]')]
                    .find(el => window.getComputedStyle(el).display !== 'none');
                if (!d) return null;
                const text = (d.innerText||'').trim().slice(0, 80);
                const btns = d.querySelectorAll('button');
                if (btns.length >= 2) { btns[1].click(); return 'confirm:' + text; }
                if (btns.length === 1) { btns[0].click(); return 'only:' + text; }
                return 'no-btn:' + text;
            })()
            """)
            if modal_handled:
                logger.info("submit 후 모달 처리 (attempt %d): %r", attempt, modal_handled)
                # 성공 모달이면 이후 루프에서 버튼 클릭 없이 URL 대기
                if isinstance(modal_handled, str) and "성공" in modal_handled:
                    success_modal_seen = True
                continue

            # 사진 업로드 페이지 감지 및 처리
            has_file_input = await self.tab.evaluate(
                "!!document.querySelector('input[type=\"file\"]')"
            )
            if has_file_input and not photo_uploaded:
                photo_uploaded = True
                if category_files:
                    ordered = [
                        str(p)
                        for canonical, _aliases in config.PHOTO_CATEGORIES
                        for p in category_files.get(canonical, [])
                    ]
                    if ordered:
                        try:
                            file_input = await self.tab.select("input[type=file]")
                            await file_input.send_file(*ordered)
                            logger.info("사진 업로드: %d장", len(ordered))
                            await self.tab.sleep(60.0)
                        except Exception as exc:
                            logger.warning("사진 업로드 실패: %s", exc)
                    else:
                        logger.info("사진 없음 (빈 카테고리)")
                else:
                    logger.info("사진 파일 없음 (Drive 폴더 비어있음)")

                # 특이사항 입력
                if listing and not notes_filled:
                    notes = listing.get("특이사항")
                    if notes:
                        await self._try_fill_by_label("특이사항", notes)
                        notes_filled = True

                # 사진 업로드 완료 후: 1) 일반 다음/등록 버튼 클릭
                await self.tab.sleep(1.0)
                general_clicked = await self.tab.evaluate(self._JS_CLICK_ACTION)
                if general_clicked:
                    logger.info("사진 업로드 후 일반 버튼 클릭: %r", general_clicked)
                await self.tab.sleep(2.0)

                # 2) 최종 등록 버튼 클릭 (XPath: /html/body/main/div/div/div[3]/div[2]/button)
                reg_clicked = await self.tab.evaluate("""
                (() => {
                    const xp = '/html/body/main/div/div/div[3]/div[2]/button';
                    const res = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                    const btn = res.singleNodeValue;
                    if (btn) { btn.click(); return (btn.textContent||'').trim(); }
                    return null;
                })()
                """)
                if reg_clicked:
                    logger.info("최종 등록 버튼 클릭: %r", reg_clicked)
                    await self.tab.sleep(60.0)
                else:
                    logger.warning("최종 등록 버튼 XPath 미발견")
                continue

            # validation 에러 메시지 확인
            errs = await self.tab.evaluate("""
            JSON.stringify([...document.querySelectorAll('[class*="error"],[class*="invalid"],[class*="destructive"],[role="alert"]')]
                .map(el => (el.textContent||'').trim().slice(0, 60))
                .filter(t => t && t.length > 3)
                .slice(0, 5))
            """)
            if errs and errs != "[]":
                logger.info("submit 후 validation 오류 (attempt %d): %s", attempt, errs)
                if errs == last_errors:
                    consecutive_same_errors += 1
                else:
                    consecutive_same_errors = 0
                    last_errors = errs
                if consecutive_same_errors >= 4:
                    final_url = await self.tab.evaluate("window.location.href")
                    raise RuntimeError(
                        f"submit 반복 validation 오류 (해결 불가): {errs} | URL: {final_url}"
                    )
            else:
                consecutive_same_errors = 0
                last_errors = ""

            # 다음/등록하기 버튼 클릭 (multi-step 진행)
            clicked = await self.tab.evaluate(self._JS_CLICK_ACTION)
            if clicked and clicked != last_clicked:
                logger.info("submit 단계 버튼 클릭 (attempt %d): %r", attempt, clicked)
                last_clicked = clicked

        final_url = await self.tab.evaluate("window.location.href")
        raise TimeoutError(f"submit 후 MGC_ URL 미확인 (현재: {final_url})")
