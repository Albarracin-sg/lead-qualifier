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
_POLLING_GRACE_PERIOD_S = int(os.environ.get("POLLING_GRACE_PERIOD", "60"))

# Shared timer reference for the watchdog.  Set before polling starts,
# cleared from the first successful getUpdates response.
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
        _watchdog_timer = None  # signal-based, no Timer object
        logger.info(
            "Watchdog armed: SIGALRM in %ds if polling not connected.",
            _POLLING_GRACE_PERIOD_S,
        )
    else:
        _watchdog_timer = threading.Timer(_POLLING_GRACE_PERIOD_S, _watchdog_die)
        _watchdog_timer.daemon = True
        _watchdog_timer.start()
        logger.info(
            "Watchdog armed: timer in %ds if polling not connected.",
            _POLLING_GRACE_PERIOD_S,
        )


class _WatchdogRequest:
    """Wraps PTB's default request to disarm watchdog on first success."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._disarmed = False

    async def post(self, url: str, *args, **kwargs):
        result = await self._inner.post(url, *args, **kwargs)
        if not self._disarmed and "getUpdates" in url:
            self._disarmed = True
            _disarm_watchdog()
        return result

    def __getattr__(self, name):
        return getattr(self._inner, name)


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
    from telegram.request import HTTPXRequest

    # Custom request that disarms the watchdog on first successful getUpdates
    inner = HTTPXRequest(
        connection_pool_size=1,
        read_timeout=30.0,
        write_timeout=30.0,
    )
    watchdog_req = _WatchdogRequest(inner)

    app = Application.builder().token(config.telegram_token).request(watchdog_req).build()

    app.bot_data["config"] = config
    app.bot_data["sheet"] = sheet

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Arm watchdog — will be disarmed by _WatchdogRequest on first getUpdates
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
