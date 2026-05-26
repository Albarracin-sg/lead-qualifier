"""Lead Qualification Bot — Entry Point.

Wires the Telegram bot, Hugging Face qualifier, and Google Sheets logger
together, then starts polling.

Usage
-----
::

    # Set up your .env file (see .env.example), then:
    python main.py
"""

import asyncio
import logging
import sys
import time

from telegram.ext import Application, MessageHandler, filters

from bot.handler import handle_message
from config import load_config
from sheets.client import SheetLogger

logger = logging.getLogger(__name__)

# How long to wait between retries when the same bot token is being
# polled by another instance (e.g. during a rolling deploy on Render).
_CONFLICT_RETRY_DELAY_S = 15
_MAX_CONFLICT_RETRIES = 10


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _run_with_conflict_retry(app: Application, config) -> None:
    """Run polling, retrying if another instance holds the lock.

    Render starts the new deployment *before* stopping the old one, so
    two processes race for the same Telegram long-poll connection.  This
    loop catches ``Conflict`` (HTTP 409), waits for the old instance to
    die, and retries.
    """
    from telegram.error import Conflict

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for attempt in range(1, _MAX_CONFLICT_RETRIES + 1):
        try:
            logger.info("Starting polling (attempt %d/%d)…", attempt, _MAX_CONFLICT_RETRIES)
            app.run_polling(allowed_updates=["messages"])
            return  # normal exit — polling never returns on its own
        except Conflict:
            msg = "Conflict: another bot instance is running. Retrying in %d s (attempt %d/%d)…"
            logger.warning(msg, _CONFLICT_RETRY_DELAY_S, attempt, _MAX_CONFLICT_RETRIES)
            # run_polling closes the old loop when it exits, so create a fresh one
            loop.close()
            time.sleep(_CONFLICT_RETRY_DELAY_S)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        finally:
            loop.close()


def main() -> None:
    """Start the bot. Blocking (polls forever)."""
    config = load_config()
    _setup_logging(config.log_level)

    logger.info("Starting Lead Qualification Bot…")
    logger.info("Model: %s", config.hf_model)

    # --- Google Sheets ---
    try:
        sheet = SheetLogger(config.google_creds_json, config.sheet_name, config.sheet_id)
        logger.info("Google Sheets connected: '%s'", config.sheet_name)
    except Exception as exc:
        logger.critical("Failed to connect Google Sheets: %s", exc)
        sys.exit(1)

    # --- Telegram Bot ---
    app = Application.builder().token(config.telegram_token).build()

    # Store shared state in bot_data
    app.bot_data["config"] = config
    app.bot_data["sheet"] = sheet

    # Register handler for text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    _run_with_conflict_retry(app, config)


if __name__ == "__main__":
    main()
