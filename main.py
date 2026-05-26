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

from telegram.ext import Application, MessageHandler, filters

from bot.handler import handle_message
from config import load_config
from sheets.client import SheetLogger

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


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

    app.bot_data["config"] = config
    app.bot_data["sheet"] = sheet

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Python 3.14+ doesn't auto-create event loops. PTB's run_polling
    # calls get_event_loop() internally, so we create one explicitly.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        app.run_polling(allowed_updates=["messages"])
    finally:
        loop.close()


if __name__ == "__main__":
    main()
