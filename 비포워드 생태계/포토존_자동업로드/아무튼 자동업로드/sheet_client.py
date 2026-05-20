"""Read pending listings and write back AC/AE via the Google Sheets API.

Uses a service account JSON key (config.SERVICE_ACCOUNT_JSON) to authenticate.
The spreadsheet must be shared with the service account email:
  sales-input-01@adjustmentdata.iam.gserviceaccount.com  (Editor권한)

Reading  : gspread worksheet.get_all_values() — reliable, no browser needed.
Writing  : gspread worksheet.update_cell(row, col, value) — atomic API call.

The SheetWriter class keeps a thin browser-compatible interface so
upload_mangocar.py doesn't need changes (open() / update_row_after_upload()).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _open_worksheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        str(config.SERVICE_ACCOUNT_JSON), scopes=_SCOPES
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.SHEET_ID)
    return sh.worksheet(config.SHEET_NAME)


# ---------------------------------------------------------------- models --


@dataclass
class ListingRow:
    sheet_row: int                    # 1-based row number on the sheet
    raw: list[str]                    # full row as strings (column index = config.COL)
    options: dict[str, bool] = field(default_factory=dict)
    addons: dict[str, bool] = field(default_factory=dict)

    def get(self, col_name: str) -> str:
        idx = config.COL[col_name]
        return self.raw[idx] if idx < len(self.raw) else ""

    @property
    def email(self) -> str:
        return parse_account(self.get("계정정보"))[0]

    @property
    def password(self) -> str:
        return parse_account(self.get("계정정보"))[1]

    @property
    def identifier(self) -> str:
        return self.get("A1").strip()

    @property
    def ad_price_raw(self) -> str:
        return self.get("광고가").strip()

    @property
    def ad_price_number(self) -> str:
        """Strip $ and , from N열 광고가 → digits-only string. '' if blank."""
        return "".join(c for c in self.ad_price_raw if c.isdigit())

    @property
    def drive_url(self) -> str:
        return self.get("구글드라이브").strip()


def parse_account(o_cell: str) -> tuple[str, str]:
    """Split O열 (`이메일\\n비밀번호`) into (email, password)."""
    if not o_cell:
        return "", ""
    cleaned = o_cell.strip().strip('"').strip("'")
    parts = [p.strip() for p in cleaned.splitlines() if p.strip()]
    if len(parts) < 2:
        return (parts[0] if parts else ""), ""
    return parts[0], parts[1]


def _to_bool(cell: str) -> bool:
    return str(cell).strip().upper() == "TRUE"


# ----------------------------------------------------------------- read --


def _parse_rows(all_values: list[list[str]]) -> list[ListingRow]:
    """Convert raw gspread row lists into ListingRow objects.

    gspread's get_all_values() returns a list of lists where shorter rows are
    NOT padded, so we pad each row to at least max(COL.values())+1 entries.
    Row indices from gspread are 1-based; header rows are config.HEADER_ROWS.
    """
    max_col = max(config.COL.values()) + 1
    listings: list[ListingRow] = []
    for sheet_row_idx, raw_short in enumerate(all_values[config.HEADER_ROWS:],
                                               start=config.HEADER_ROWS + 1):
        raw = list(raw_short) + [""] * max(0, max_col - len(raw_short))
        if not any(c.strip() for c in raw):
            continue
        listing = ListingRow(sheet_row=sheet_row_idx, raw=raw)
        listing.options = {k: _to_bool(listing.get(k)) for k in config.OPTION_KEYS}
        listing.addons  = {k: _to_bool(listing.get(k)) for k in config.ADDON_KEYS}
        listings.append(listing)
    return listings


async def read_pending_rows(browser=None) -> list[ListingRow]:
    """Return ListingRow objects where AC (업로드 일자) is empty.

    `browser` is accepted for backward compatibility but ignored — data is now
    fetched directly via the Sheets API.
    """
    import asyncio
    ws = await asyncio.to_thread(_open_worksheet)
    all_values = await asyncio.to_thread(ws.get_all_values)
    logger.info("시트 행 읽기: 전체 %d행", len(all_values))
    all_rows = _parse_rows(all_values)
    pending = [
        r for r in all_rows
        if not r.get("업로드 일자").strip()
        and r.get("판매여부").strip() != "타 경로 판매"
    ]
    logger.info("pending 행 (AC 비어있음, 타경로판매 제외): %d건", len(pending))
    return pending


# --------------------------------------------------------------- write --


def today_kst_str() -> str:
    """Match the sheet's existing date format e.g. '2026. 4. 20'."""
    today = date.today()
    return f"{today.year}. {today.month}. {today.day}"


class SheetWriter:
    """Write back AC/AE via the Sheets API.

    Keeps a nodriver-Tab-compatible interface (open / update_row_after_upload)
    so the caller (upload_mangocar.py) doesn't need changes.  The `tab`
    argument to __init__ is ignored — API writes don't need a browser.
    """

    def __init__(self, tab=None) -> None:
        self._ws: Optional[gspread.Worksheet] = None

    async def open(self) -> None:
        import asyncio
        self._ws = await asyncio.to_thread(_open_worksheet)
        logger.info("SheetWriter: Sheets API 연결 완료 (시트: %s)", config.SHEET_NAME)

    def _col_letter_to_index(self, letter: str) -> int:
        """Convert column letter(s) like 'AC' → 1-based column index (29)."""
        letter = letter.upper()
        result = 0
        for ch in letter:
            result = result * 26 + (ord(ch) - ord('A') + 1)
        return result

    async def update_cell(self, cell_ref: str, value: str) -> None:
        """Write `value` to `cell_ref` (e.g. 'AC95') via the Sheets API."""
        import asyncio, re
        m = re.match(r"^([A-Za-z]+)(\d+)$", cell_ref)
        if not m:
            raise ValueError(f"Invalid cell ref: {cell_ref}")
        col_idx = self._col_letter_to_index(m.group(1))
        row_idx = int(m.group(2))
        await asyncio.to_thread(self._ws.update_cell, row_idx, col_idx, value)
        logger.info("셀 업데이트: %s = %r", cell_ref, value)

    async def update_row_after_upload(self, sheet_row: int, today_str: str, url: str) -> None:
        await self.update_cell(f"{config.COL_LETTER_UPLOAD_DATE}{sheet_row}", today_str)
        await self.update_cell(f"{config.COL_LETTER_LINK}{sheet_row}", url)

    async def update_beforward_link(self, sheet_row: int, value: str) -> None:
        await self.update_cell(f"{config.COL_LETTER_BEFORWARD_LINK}{sheet_row}", value)

    async def update_upload_result(self, sheet_row: int, value: str) -> None:
        """AK열 — 업로드 결과 ('업로드 성공' 또는 상세 실패 사유)."""
        await self.update_cell(f"{config.COL_LETTER_UPLOAD_RESULT}{sheet_row}", value)

    async def update_beforward_result(self, sheet_row: int, value: str) -> None:
        """AL열 — 비포워드 업로드 로그."""
        await self.update_cell(f"{config.COL_LETTER_BEFORWARD_RESULT}{sheet_row}", value)
