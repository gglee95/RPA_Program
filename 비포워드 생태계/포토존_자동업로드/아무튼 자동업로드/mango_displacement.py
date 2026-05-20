"""망고카 listing detail 페이지에서 배기량(cc) 값을 추출한다.

사용자가 제시한 XPath:
    /html/body/main/div/div/section/div[1]/div[4]/div[4]/div[5]/span[2]/span
는 위치 기반이라 페이지 구조 변경에 약하다. 본 모듈은 그 대신 "배기량" 라벨
텍스트 다음에 오는 첫 번째 숫자를 정규식으로 찾는 라벨 기반 방식을 쓴다.
실패하면 명확하게 예외를 던진다 (글로벌 규칙: 폴백/기본값 금지).
"""
from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DISPLACEMENT_RE = re.compile(r"배기량\s*[:\-]?\s*([\d,]+)\s*(?:cc|CC|씨씨)?")


def fetch_displacement(mango_url: str) -> str:
    """망고카 listing 페이지 HTML 에서 배기량 숫자(콤마 제거)를 반환.

    Raises:
        ValueError: URL이 비어있거나, 페이지 응답에 배기량 라벨/숫자가 없음.
        requests.HTTPError: HTTP 응답 코드가 4xx/5xx.
    """
    if not mango_url:
        raise ValueError("mango_url 이 비어있어 배기량 조회 불가")

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    resp = requests.get(mango_url, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text

    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text)

    m = _DISPLACEMENT_RE.search(text)
    if not m:
        raise ValueError(
            f"페이지에서 '배기량' 값을 찾지 못함 (url={mango_url[:120]})"
        )
    value = m.group(1).replace(",", "")
    logger.info("[mango] 배기량 추출: %s cc (from %s)", value, mango_url[:80])
    return value
