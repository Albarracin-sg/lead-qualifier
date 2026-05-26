"""Lead data model shared across all layers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LeadResult:
    """Result of evaluating a single message in a conversation."""

    raw_input: str
    action: str  # "qualified" | "needs_info" | "disqualified"
    reasoning: str
    missing_fields: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    conversation_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_sheet_row(self) -> list[str]:
        action_label = {
            "qualified": "Cualificado",
            "needs_info": "Faltan datos",
            "disqualified": "No cualificado",
        }.get(self.action, self.action)

        campos = ", ".join(self.missing_fields) if self.missing_fields else "-"
        preguntas = " | ".join(self.questions) if self.questions else "-"

        return [
            self.timestamp.isoformat(),
            self.raw_input,
            action_label,
            self.reasoning,
            campos,
            preguntas,
            self.conversation_id,
            str(self.prompt_tokens),
            str(self.completion_tokens),
            # Tokens Total column J is set by formula in the sheet logger
        ]

    @classmethod
    def from_llm_response(
        cls,
        raw_input: str,
        response: Mapping[str, object],
        conversation_id: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> "LeadResult":
        action = str(response.get("accion", "disqualified"))
        if action not in ("qualified", "needs_info", "disqualified"):
            action = "disqualified"

        missing = response.get("campos_faltantes", [])
        missing = [str(f) for f in missing] if isinstance(missing, list) else []

        questions = response.get("preguntas", [])
        questions = [str(q) for q in questions] if isinstance(questions, list) else []

        return cls(
            raw_input=raw_input,
            action=action,
            reasoning=str(response.get("razonamiento", "")),
            missing_fields=missing,
            questions=questions,
            conversation_id=conversation_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
