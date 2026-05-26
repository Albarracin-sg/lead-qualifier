"""Telegram message handler — acts as a friendly secretary.

Every message gets logged as its own row with a conversation_id
linking messages from the same thread (append-only log).
"""

import logging
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from models.lead import LeadResult
from qualifier.client import QualifierError, qualify_lead
from sheets.client import SheetLogger, SheetLogError

logger = logging.getLogger(__name__)

_MAX_HISTORY = 4

_REPLIES = {
    "qualified": (
        "Gracias por contactarnos! Con la info que me pasaste, veo que podrian encajar "
        "muy bien con lo que estamos buscando. Vamos a derivar tu consulta a nuestro "
        "equipo para que se comuniquen con ustedes."
    ),
    "disqualified": (
        "Gracias por tu interes! Lamentablemente en este momento no estamos trabajando "
        "con empresas de ese perfil. Te deseo mucho exito con tu proyecto!"
    ),
}


def _build_reply(result: LeadResult) -> str:
    if result.action == "needs_info":
        if result.questions:
            return (
                "Gracias por escribirnos! Para poder evaluar bien su proyecto, "
                "necesitaria saber algunos datos mas:\n\n"
                + "\n".join(f"  - {q}" for q in result.questions[:2])
                + "\n\nCuando me los pasen, lo reviso al toque!"
            )
        return (
            "Gracias por escribirnos! Me ayudarias con un poco mas de informacion "
            "para poder evaluar su proyecto?"
        )
    return _REPLIES.get(result.action, _REPLIES["disqualified"])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    raw_input: str = update.message.text.strip()
    if not raw_input:
        await update.message.reply_text("Hola! Contame sobre tu proyecto y lo evaluo.")
        return

    chat_id: int = update.effective_chat.id if update.effective_chat else 0
    config: Config = context.bot_data["config"]
    sheet: SheetLogger = context.bot_data["sheet"]

    # Conversation context
    contexts: dict = context.bot_data.setdefault("contexts", {})
    ctx = contexts.get(chat_id)

    # Generate or reuse conversation ID
    conv_id: str = ctx["conv_id"] if ctx else str(uuid.uuid4())[:8]

    processing_msg = await update.message.reply_text("Dame un segundito que reviso la info...")

    try:
        history = []
        if ctx:
            history = ctx["history"][-_MAX_HISTORY:]

        result = qualify_lead(raw_input, config, history=history or None)
        result.conversation_id = conv_id

        logger.info(
            "Chat %d conv=%s: action=%s",
            chat_id, conv_id, result.action,
        )

        reply = _build_reply(result)
        await processing_msg.edit_text(reply)

        # Append row (always new row, conv_id groups the thread)
        try:
            sheet.append(result)
            # Save context for next turn
            ctx_entry = {
                "conv_id": conv_id,
                "history": (ctx["history"] if ctx else []) + [(raw_input, reply)],
            }
            contexts[chat_id] = ctx_entry
        except SheetLogError as exc:
            logger.warning("Sheet log failed: %s", exc)
            await update.message.reply_text(
                "Quedo todo registrado igual, pero hubo un problema con el log."
            )

    except QualifierError as exc:
        logger.error("Qualifier error: %s", exc)
        await processing_msg.edit_text(
            "Hubo un error procesando la info. Proba de nuevo en un ratito!"
        )
    except Exception:
        logger.exception("Unexpected error")
        await processing_msg.edit_text(
            "Paso algo inesperado, proba de nuevo en un rato!"
        )
