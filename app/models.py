"""Small data structures shared across the app."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InquiryFields:
    """Structured result of parsing an inquiry email body.

    Mirrors the real "The Mental Gain" contact form, which collects a "Parent
    Name" (the guardian we reply to), a "Player Name" (the young athlete the
    inquiry is about), Email, Phone and a free-text message (the form's
    "Textarea" field).

    ``email`` is required (a draft cannot be addressed without it). All other
    fields are optional; absent ones are listed in ``missing_fields``, which is
    passed to the drafter so it writes around the gap instead of inventing
    values. A partial submission still produces a draft.
    """

    email: str
    name: str | None = None
    child_name: str | None = None
    phone: str | None = None
    message: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    # How the fields were extracted: "parser" (deterministic) or "llm" (fallback).
    extraction_method: str = "parser"

    def as_prompt_dict(self) -> dict[str, str]:
        """Render fields for prompt interpolation, with friendly blanks."""
        return {
            "name": self.name or "(not provided)",
            "child_name": self.child_name or "(not provided)",
            "email": self.email,
            "phone": self.phone or "(not provided)",
            "message": self.message or "(not provided)",
            "missing_fields": ", ".join(self.missing_fields) or "(none)",
        }
