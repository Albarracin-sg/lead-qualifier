"""Application configuration from environment variables."""

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Config:
    """Immutable config loaded once at startup."""

    # --- Telegram ---
    telegram_token: str

    # --- Hugging Face (Chat Completions API) ---
    hf_api_key: str
    hf_model: str = field(default="deepseek-ai/DeepSeek-V3.2:novita")
    hf_api_url: str = field(
        default="https://router.huggingface.co/v1/chat/completions"
    )

    # --- Google Sheets ---
    google_creds_json: dict = field(default_factory=dict)
    sheet_name: str = field(default="Lead Qualification Log")
    sheet_id: str = field(default="")

    # --- Runtime ---
    hf_timeout: int = field(default=30)
    hf_retries: int = field(default=2)

    # --- Logging ---
    log_level: str = field(default="INFO")


_MISSING = "__MISSING__"


def load_config() -> Config:
    """Read env vars, validate, return a ``Config``."""

    telegram_token = os.getenv("TELEGRAM_TOKEN", _MISSING)
    hf_api_key = os.getenv("HUGGINGFACE_API_KEY", _MISSING)
    hf_model = os.getenv("HUGGINGFACE_MODEL", _MISSING)
    hf_api_url = os.getenv("HUGGINGFACE_API_URL", _MISSING)
    sheet_name = os.getenv("SHEET_NAME", _MISSING)
    raw_creds = os.getenv("GOOGLE_CREDS_JSON", _MISSING)
    sheet_id = os.getenv("SHEET_ID", "")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    errors: list[str] = []

    if telegram_token is _MISSING:
        errors.append("TELEGRAM_TOKEN")
    if hf_api_key is _MISSING:
        errors.append("HUGGINGFACE_API_KEY")
    if hf_model is _MISSING:
        hf_model = "deepseek-ai/DeepSeek-V3.2:novita"
    if hf_api_url is _MISSING:
        hf_api_url = "https://router.huggingface.co/v1/chat/completions"
    if sheet_name is _MISSING:
        sheet_name = "Lead Qualification Log"

    creds_dict: dict = {}
    if raw_creds is _MISSING:
        errors.append("GOOGLE_CREDS_JSON")
    else:
        try:
            creds_dict = json.loads(raw_creds)
        except json.JSONDecodeError:
            errors.append("GOOGLE_CREDS_JSON (invalid JSON)")

    if errors:
        print("ERROR: Missing or invalid config vars:")
        for e in errors:
            print(f"  - {e}")
        print("Check your .env file or environment.")
        raise SystemExit(1)

    return Config(
        telegram_token=telegram_token,  # type: ignore[arg-type]
        hf_api_key=hf_api_key,  # type: ignore[arg-type]
        hf_model=hf_model,  # type: ignore[arg-type]
        hf_api_url=hf_api_url,
        sheet_name=sheet_name,  # type: ignore[arg-type]
        sheet_id=sheet_id,
        google_creds_json=creds_dict,
        log_level=log_level,
    )
