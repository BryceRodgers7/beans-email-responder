"""Tests for app.parser, exercised against the real "The Mental Gain"
contact-form notification format (see examples/2011-2013.txt)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parser import ParseError, parse

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# Inline fixtures mirroring the real format (label marker on its own line,
# value on the following line; "Textarea" is the free-text message).
FULL = """\
From: The Mental Gain <noreply@thementalgain.com>
Subject: New Form Entry #2099 for contact me
To: <info@thementalgain.com>

You have a new website form submission:

   1. *Name*
   Jane Sample
   2. *Email*
   jane.sample@gmail.com
   3. *Phone*
   (555) 010-0100
   4. *Textarea*

   My daughter plays volleyball and gets in her head before games.
   Looking for more info about your services. Thanks!
"""

MISSING_PHONE = """\
You have a new website form submission:

   1. *Name*
   Sam Sample
   2. *Email*
   sam.sample@gmail.com
   3. *Phone*
   4. *Textarea*

   Quick question about your services.
"""

NO_EMAIL = """\
You have a new website form submission:

   1. *Name*
   No Email Person
   2. *Phone*
   (555) 010-0101
   3. *Textarea*

   I forgot to include my email.
"""

JUNK = "Just some random text with no form fields at all."


def test_parses_all_fields():
    result = parse(FULL)
    assert result.name == "Jane Sample"
    assert result.email == "jane.sample@gmail.com"
    assert result.phone == "(555) 010-0100"
    assert result.missing_fields == []


def test_client_email_not_business_sender():
    # The From/To headers carry the business's own addresses; the parsed email
    # must be the client's *Email* field, never noreply@/info@.
    result = parse(FULL)
    assert "thementalgain.com" not in result.email


def test_message_is_multiline_and_dedented():
    result = parse(FULL)
    assert result.message is not None
    assert result.message.startswith("My daughter plays volleyball")
    assert "Thanks!" in result.message
    # Leading indentation from the email body is stripped.
    assert not result.message.startswith(" ")


def test_missing_optional_field_is_flagged_not_invented():
    result = parse(MISSING_PHONE)
    assert result.email == "sam.sample@gmail.com"
    assert result.phone is None
    assert "phone" in result.missing_fields


def test_missing_email_raises():
    with pytest.raises(ParseError):
        parse(NO_EMAIL)


def test_junk_body_raises():
    with pytest.raises(ParseError):
        parse(JUNK)


def test_empty_body_raises():
    with pytest.raises(ParseError):
        parse("   ")


def test_real_example_files():
    """Validate any local real samples structurally.

    The real `examples/*.txt` are gitignored (they contain client PII), so this
    asserts only structural properties — no real names/emails are embedded in
    source. Skips when no samples are present (e.g. a fresh checkout).
    """
    files = sorted(EXAMPLES.glob("*.txt"))
    if not files:
        pytest.skip("no real samples present (gitignored)")
    for path in files:
        result = parse(path.read_text(encoding="utf-8"))
        assert "@" in result.email  # a client email was extracted
        assert "thementalgain.com" not in result.email  # not the business sender
        assert result.name  # name present
        assert result.message  # textarea captured
