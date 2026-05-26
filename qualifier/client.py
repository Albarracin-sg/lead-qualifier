"""Hugging Face Chat Completions API client for lead qualification."""

import json
import logging
import re
from collections.abc import Mapping

import requests

from config import Config
from models.lead import LeadResult
from qualifier.prompt import build_messages

logger = logging.getLogger(__name__)


class QualifierError(Exception):
    """Raised when qualification fails."""


def _extract_json(text: str) -> Mapping[str, object]:
    match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, re.DOTALL)
    if match:
        raw = match.group(1)
    else:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if not match:
            raise QualifierError("No JSON in LLM response")
        raw = match.group(1)

    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise QualifierError(f"Expected dict, got {type(parsed).__name__}")
    return parsed


def qualify_lead(
    raw_input: str,
    config: Config,
    history: list[tuple[str, str]] | None = None,
) -> LeadResult:
    messages = build_messages(raw_input, history=history)

    headers = {
        "Authorization": f"Bearer {config.hf_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config.hf_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 512,
    }

    last_error: Exception | None = None

    for attempt in range(1, config.hf_retries + 1):
        try:
            logger.info("HF API call (attempt %d/%d)", attempt, config.hf_retries)
            resp = requests.post(
                config.hf_api_url,
                headers=headers,
                json=payload,
                timeout=config.hf_timeout,
            )
            resp.raise_for_status()
            data: dict = resp.json()

            # Token usage
            usage = data.get("usage", {})
            pt = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
            ct = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0
            logger.info("Tokens — in: %d, out: %d", pt, ct)

            choices = data.get("choices", [])
            if not choices:
                raise QualifierError("No choices in response")

            raw_text = choices[0].get("message", {}).get("content", "")
            if not raw_text:
                raise QualifierError("Empty content")

            logger.debug("LLM raw: %s", raw_text[:300])
            parsed = _extract_json(raw_text)
            return LeadResult.from_llm_response(
                raw_input,
                parsed,
                prompt_tokens=pt,
                completion_tokens=ct,
            )

        except requests.Timeout:
            logger.warning("Timeout (attempt %d)", attempt)
            last_error = QualifierError("API timed out")
        except requests.HTTPError as exc:
            logger.warning("HTTP %s (attempt %d)", exc.response.status_code, attempt)
            last_error = QualifierError(f"HTTP error: {exc}")
        except (json.JSONDecodeError, QualifierError, KeyError, IndexError) as exc:
            logger.warning("Parse error (attempt %d): %s", attempt, exc)
            last_error = QualifierError(str(exc))

    raise QualifierError(f"Failed after {config.hf_retries} attempts") from last_error
