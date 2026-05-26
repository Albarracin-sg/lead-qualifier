"""Google Sheets client for logging leads.

Append-only log. Every message gets its own row with a conversation_id
linking messages from the same thread. Tokens Total column uses formula.
"""

import logging

import gspread
from google.oauth2.service_account import Credentials

from models.lead import LeadResult

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_HEADERS = [
    "Fecha",
    "Datos Recibidos",
    "Decision",
    "Motivo",
    "Campos Faltantes",
    "Preguntas",
    "Conversacion ID",
    "Tokens Input",
    "Tokens Output",
    "Tokens Total",
]

_DATA_COLS = len(_HEADERS)  # 10
_COL_INPUT = "H"
_COL_OUTPUT = "I"
_COL_TOTAL = "J"


class SheetLogError(Exception):
    """Raised when logging to Google Sheets fails."""


class SheetLogger:
    """Append-only lead logger with formatting and formula."""

    def __init__(self, creds_json: dict, sheet_name: str, sheet_id: str = "") -> None:
        self._creds = Credentials.from_service_account_info(creds_json, scopes=_SCOPES)
        self._client = gspread.authorize(self._creds)
        self._worksheet = self._resolve(sheet_name, sheet_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _resolve(self, name: str, key: str):
        try:
            if key:
                spreadsheet = self._client.open_by_key(key)
                logger.info("Sheet opened by key: %s", key)
            else:
                spreadsheet = self._client.open(name)

            ws = spreadsheet.sheet1
            self._apply_formatting(ws)
            return ws
        except gspread.SpreadsheetNotFound:
            logger.warning("Sheet not found, creating: %s", name)
            spreadsheet = self._client.create(name)
            ws = spreadsheet.sheet1
            ws.append_row(_HEADERS)
            self._apply_formatting(ws)
            return ws

    def _apply_formatting(self, ws) -> None:
        try:
            last_col = chr(ord("A") + _DATA_COLS - 1)
            ws.format(
                f"A1:{last_col}1",
                {
                    "textFormat": {"bold": True},
                    "backgroundColorStyle": {
                        "rgbColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
                    },
                },
            )
            ws.format("B:B", {"wrapStrategy": "WRAP"})
            ws.format("D:D", {"wrapStrategy": "WRAP"})
        except Exception as exc:
            logger.warning("Formatting failed (non-critical): %s", exc)

    def _real_row_count(self) -> int:
        return len(self._worksheet.get_all_values())

    def _set_total_formula(self, row: int) -> None:
        """Set J{row} = H{row} + I{row} as a live formula."""
        try:
            self._worksheet.update(
                f"{_COL_TOTAL}{row}",
                [[f"={_COL_INPUT}{row}+{_COL_OUTPUT}{row}"]],
                value_input_option="USER_ENTERED",
            )
        except Exception as exc:
            logger.warning("Formula set failed (row %d): %s", row, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append(self, result: LeadResult) -> int:
        """Append a row and return the 1-indexed row number."""
        try:
            row_data = result.to_sheet_row()  # 9 values (A-I)
            self._worksheet.append_row(
                row_data,
                value_input_option="USER_ENTERED",
            )
            row = self._real_row_count()
            self._set_total_formula(row)
            logger.info(
                "Row %d: %s | conv=%s | in=%d out=%d",
                row,
                result.action,
                result.conversation_id,
                result.prompt_tokens,
                result.completion_tokens,
            )
            return row
        except Exception as exc:
            raise SheetLogError(f"Failed to append: {exc}") from exc
