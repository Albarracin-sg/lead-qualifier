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
_POLLING_GRACE_PERIOD_S = int(os.environ.get("POLLING_GRACE_PERIOD", "45"))


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _start_watchdog() -> threading.Timer:
    """Start a timer that force-exits the process if polling never connects.

    PTB's ``network_retry_loop`` handles ``Conflict`` (409) internally and
    never propagates it to ``run_polling``.  When two Render instances race
    for the same bot token, the new one must wait for the old one to die —
    but without health-check being able to succeed, the old one is never
    killed.

    This watchdog acts as a circuit-breaker: if the application doesn't
    reach the polling loop after *grace_period* seconds, we exit hard so
    Render restarts us in a clean state.
    """
    signal_enabled = hasattr(signal, "SIGALRM")

    if signal_enabled:
        # Use SIGALRM on Unix — interrupts the main thread directly.
        def _alarm_handler(_signum, _frame) -> None:
            logger.error(
                "Polling failed to establish within %ds (another instance?). "
                "Exiting so Render can restart.",
                _POLLING_GRACE_PERIOD_S,
            )
            sys.exit(1)

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(_POLLING_GRACE_PERIOD_S)
        logger.info(
            "Watchdog armed: SIGALRM in %ds if polling not connected.",
            _POLLING_GRACE_PERIOD_S,
        )
        return None  # no timer needed — signal handles it
    else:
        # Fallback — Timer thread on Windows (no SIGALRM).
        def _die() -> None:
            logger.error(
                "Polling failed to establish within %ds. Exiting.",
                _POLLING_GRACE_PERIOD_S,
            )
            os._exit(1)

        timer = threading.Timer(_POLLING_GRACE_PERIOD_S, _die)
        timer.daemon = True
        timer.start()
        logger.info(
            "Watchdog armed: timer in %ds if polling not connected.",
            _POLLING_GRACE_PERIOD_S,
        )
        return timer


def _disarm_watchdog(timer: threading.Timer | None) -> None:
    """Disarm the watchdog — called once polling has connected."""
    if timer is not None:
        timer.cancel()
        logger.info("Watchdog disarmed — polling connected.")
    elif hasattr(signal, "SIGALRM"):
        signal.alarm(0)
        logger.info("Watchdog disarmed — polling connected.")


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

    # Arm watchdog BEFORE starting polling
    timer = _start_watchdog()

    # Python 3.14+ needs explicit event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    logger.info("Starting polling (watchdog armed for %ds)…", _POLLING_GRACE_PERIOD_S)
    try:
        app.run_polling(allowed_updates=["messages"])
    finally:
        _disarm_watchdog(timer)
        loop.close()


if __name__ == "__main__":
    main()
