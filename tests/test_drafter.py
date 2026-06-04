"""Tests for app.drafter using a mocked OpenAI client (no network calls)."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from app import drafter
from app.config import load_settings
from app.drafter import DraftError, build_system_prompt, build_user_message, generate_draft
from app.models import InquiryFields


@pytest.fixture
def settings():
    # Real (non-secret) settings from config/settings.toml; tweak retries low.
    base = load_settings(require_secrets=False)
    return dataclasses.replace(base, max_retries=1, openai_api_key="test-key")


@pytest.fixture
def fields():
    return InquiryFields(
        email="jane.sample@gmail.com",
        name="Jane Sample",
        phone="(555) 010-0100",
        message="My daughter plays volleyball and gets in her head before games.",
        missing_fields=[],
    )


def _ok_response(content="Hi there, thanks so much for reaching out!"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=99),
    )


class FakeCompletions:
    def __init__(self, responder):
        self._responder = responder
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responder(len(self.calls), kwargs)


class FakeClient:
    def __init__(self, responder):
        self.chat = SimpleNamespace(completions=FakeCompletions(responder))


def test_system_prompt_contains_guardrails_and_profile():
    system = build_system_prompt()
    assert "Do NOT invent" in system
    # Business profile is inlined (the placeholder is replaced).
    assert "{business_profile}" not in system
    assert "The Mental Gain" in system


def test_user_message_contains_inquiry_and_missing_flags():
    f = InquiryFields(email="a@b.com", name="Kid Name", message="hello", missing_fields=["phone"])
    msg = build_user_message(f)
    assert "a@b.com" in msg
    assert "hello" in msg
    assert "phone" in msg  # missing field surfaced
    assert "data, not instructions" in msg  # injection framing


def test_generate_draft_returns_text_and_sends_two_messages(settings, fields):
    client = FakeClient(lambda n, kw: _ok_response("Drafted reply body."))
    result = generate_draft(fields, settings, client=client)
    assert result == "Drafted reply body."

    sent = client.chat.completions.calls[0]
    assert sent["model"] == settings.openai_model
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "user"]
    assert "jane.sample@gmail.com" in sent["messages"][1]["content"]


def test_generate_draft_returns_body_only_no_footer(settings, fields):
    # The footer is the caller's job (app.run); the drafter returns body only.
    client = FakeClient(lambda n, kw: _ok_response("Body text."))
    assert generate_draft(fields, settings, client=client) == "Body text."


def test_generate_draft_retries_then_succeeds(settings, fields, monkeypatch):
    monkeypatch.setattr(drafter.time, "sleep", lambda *_: None)

    def responder(call_number, kwargs):
        if call_number == 1:
            raise RuntimeError("transient")
        return _ok_response("Recovered draft.")

    client = FakeClient(responder)
    result = generate_draft(fields, settings, client=client)
    assert result == "Recovered draft."
    assert len(client.chat.completions.calls) == 2


def test_generate_draft_raises_after_exhausting_retries(settings, fields, monkeypatch):
    monkeypatch.setattr(drafter.time, "sleep", lambda *_: None)

    def always_fail(call_number, kwargs):
        raise RuntimeError("down")

    client = FakeClient(always_fail)
    with pytest.raises(DraftError):
        generate_draft(fields, settings, client=client)


def test_empty_completion_raises(settings, fields, monkeypatch):
    monkeypatch.setattr(drafter.time, "sleep", lambda *_: None)
    client = FakeClient(lambda n, kw: _ok_response(""))
    with pytest.raises(DraftError):
        generate_draft(fields, settings, client=client)
