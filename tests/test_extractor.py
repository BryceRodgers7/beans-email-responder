"""Tests for app.extractor: the parse->LLM fallback orchestration and the
LLM extraction path (with a fake OpenAI client — no network)."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from app.config import load_settings
from app.extractor import extract_fields, extract_with_llm
from app.models import InquiryFields
from app.parser import ParseError

# A body the deterministic parser cannot read (no <li><b>Label</b>, no markers).
UNPARSEABLE = "Hi, someone filled out the form. Name Jane, reach her at jane@x.com."

# The real HTML layout the deterministic parser DOES read.
HTML_FULL = """\
<ol>
<li><b>Email</b><br />jane.sample@gmail.com</li>
<li><b>Name</b><br />Jane Sample</li>
</ol>
"""


class FakeOpenAI:
    """Minimal stand-in matching client.chat.completions.create(...).choices[0].message.content."""

    def __init__(self, content: str):
        self._content = content
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def settings():
    return load_settings(require_secrets=False)


@pytest.fixture
def settings_with_key(settings):
    return dataclasses.replace(settings, openai_api_key="sk-test")


def test_llm_extraction_builds_and_validates_fields(settings):
    client = FakeOpenAI(
        '{"name": "Jane", "email": "jane@gmail.com", "phone": "555-0100", "message": "hi there"}'
    )
    result = extract_with_llm("anything", settings, client=client)
    assert result.email == "jane@gmail.com"
    assert result.name == "Jane"
    assert result.message == "hi there"
    assert client.calls == 1


def test_llm_extraction_rejects_business_email(settings):
    client = FakeOpenAI('{"name": "X", "email": "info@thementalgain.com"}')
    with pytest.raises(ParseError):
        extract_with_llm("anything", settings, client=client)


def test_llm_extraction_rejects_missing_email(settings):
    client = FakeOpenAI('{"name": "X", "email": null, "phone": "555"}')
    with pytest.raises(ParseError):
        extract_with_llm("anything", settings, client=client)


def test_extract_fields_uses_parser_first_no_llm(settings):
    # Deterministic parse succeeds, so the (exploding) LLM must never be called.
    def boom_llm(body, s):
        raise AssertionError("LLM should not be called when the parser succeeds")

    result = extract_fields(HTML_FULL, settings, llm=boom_llm)
    assert result.email == "jane.sample@gmail.com"


def test_extract_fields_falls_back_to_llm_when_parser_fails(settings_with_key):
    called = {}

    def fake_llm(body, s):
        called["body"] = body
        return InquiryFields(email="recovered@x.com")

    result = extract_fields(UNPARSEABLE, settings_with_key, llm=fake_llm)
    assert called["body"] == UNPARSEABLE
    assert result.email == "recovered@x.com"


def test_extract_fields_no_api_key_reraises_without_llm(settings):
    # No OPENAI_API_KEY -> no LLM fallback available -> deterministic error
    # surfaces. Force the key off so the test doesn't depend on the ambient env.
    keyless = dataclasses.replace(settings, openai_api_key=None)
    with pytest.raises(ParseError):
        extract_fields(UNPARSEABLE, keyless)
