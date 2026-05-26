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
import os
import signal
import sys
import threading

from telegram.ext import Application, MessageHandler, filters

from bot.handler import handle_message
from config import load_config
from sheets.client import SheetLogger

logger = logging.getLogger(__name__)

# If polling doesn't establish within this many seconds, assume there's
# another instance holding the connection.  The process exits so Render
# can restart fresh (old instance will be gone by then).
_POLLING_GRACE_PERIOD_S = int(os.environ.get("POLLING_GRACE_PERIOD", "120"))

# Shared timer reference for the watchdog.
_watchdog_timer: threading.Timer | None = None


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _disarm_watchdog() -> None:
    """Disarm the watchdog timer."""
    global _watchdog_timer
    if _watchdog_timer is not None:
        _watchdog_timer.cancel()
        _watchdog_timer = None
        logger.info("Watchdog disarmed — polling connected.")
    elif hasattr(signal, "SIGALRM"):
        signal.alarm(0)
        logger.info("Watchdog disarmed — polling connected.")


def _alarm_handler(_signum, _frame) -> None:
    logger.error(
        "Polling failed within %ds (conflict?). Exiting for Render restart.",
        _POLLING_GRACE_PERIOD_S,
    )
    sys.exit(1)


def _watchdog_die() -> None:
    logger.error(
        "Polling failed within %ds. Exiting for Render restart.",
        _POLLING_GRACE_PERIOD_S,
    )
    os._exit(1)


def _arm_watchdog() -> None:
    """Arm the watchdog — fires if ``getUpdates`` never succeeds."""
    global _watchdog_timer
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(_POLLING_GRACE_PERIOD_S)
        _watchdog_timer = None
        logger.info(
            "Watchdog armed: SIGALRM in %ds.",
            _POLLING_GRACE_PERIOD_S,
        )
    else:
        _watchdog_timer = threading.Timer(_POLLING_GRACE_PERIOD_S, _watchdog_die)
        _watchdog_timer.daemon = True
        _watchdog_timer.start()
        logger.info("Watchdog armed: timer in %ds.", _POLLING_GRACE_PERIOD_S)


def _patch_get_updates(bot) -> None:
    """Monkey-patch ``get_updates`` to disarm watchdog on first success.

    PTB 21.x's ``ApplicationBuilder`` ignores the ``request`` parameter,
    so wrapping ``HTTPXRequest`` has no effect.  Instead we patch the
    actual method that gets called during polling.
    """
    original = bot.get_updates

    async def patched(*args, **kwargs):
        result = await original(*args, **kwargs)
        _disarm_watchdog()
        return result

    bot.get_updates = patched


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

    # Patch get_updates BEFORE starting polling
    _patch_get_updates(app.bot)

    # Arm watchdog — disarmed by _patch_get_updates on first success
    _arm_watchdog()

    # Python 3.14+ needs explicit event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    logger.info("Starting polling…")
    try:
        app.run_polling(allowed_updates=["messages"])
    finally:
        _disarm_watchdog()
        loop.close()


if __name__ == "__main__":
    main()
