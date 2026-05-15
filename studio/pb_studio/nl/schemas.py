from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RouterModeEnum(str, Enum):
    business_action = "business_action"
    learning = "learning"
    clarify = "clarify"
    casual = "casual"
    refusal = "refusal"
    error = "error"


class IntentEnum(str, Enum):
    studio_digest = "studio_digest"
    project_digest = "project_digest"
    open_risks_or_sla = "open_risks_or_sla"
    list_chats = "list_chats"
    list_projects = "list_projects"
    kb_search = "kb_search"
    kb_ask = "kb_ask"
    diagnostics_status = "diagnostics_status"
    help_capabilities = "help_capabilities"
    learning_request = "learning_request"
    casual_or_assistant = "casual_or_assistant"
    unclear = "unclear"
    confirmation_reply = "confirmation_reply"


class NLRouterRequest(BaseModel):
    """Input to NL router (control group only)."""

    text: str = Field(min_length=1, max_length=12000)
    normalized_text: str = ""
    trigger_type: str = "mention"
    sender_telegram_user_id: int | None = None


class NLRouterDecision(BaseModel):
    """Strict JSON-shaped router output (validated)."""

    mode: RouterModeEnum
    intent: IntentEnum | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    parameters: dict[str, Any] = Field(default_factory=dict)
    needs_confirmation: bool = False
    clarify_question: str | None = None
    learning_type: str | None = None
    suggested_text: str | None = None

    @field_validator("parameters", mode="before")
    @classmethod
    def _params_dict(cls, v: Any) -> dict[str, Any]:
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {}


class LearningDecision(BaseModel):
    """Nested classification for learning_request."""

    learning_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_text: str | None = None
    scope_type: str | None = None  # global | project | chat | client
    scope_hint: str | None = None
    needs_confirmation: bool = True
    clarify_question: str | None = None
