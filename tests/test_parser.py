"""Tests for app.parser, exercised against the real "The Mental Gain"
contact-form notification format (see examples/2047.eml)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parser import ParseError, parse

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# The REAL notification Gmail delivers: text/html, each field an <li> with a
# bold label. Mirrors examples/2047.eml — the form labels its two name fields
# distinctly ("Parent Name" / "Player Name") and the free-text box "Textarea".
HTML_FULL = """\
<p>You have a new website form submission: </p>
<ol>
<li><b>Parent Name</b><br />Pat Parent</li>
<li><b>Player Name</b><br />Kim Kiddo</li>
<li><b>Email</b><br /><a href="mailto:pat.parent@gmail.com">pat.parent@gmail.com</a></li>
<li><b>Phone</b><br />(555) 010-0100</li>
<li><b>Textarea</b>
<p>My daughter plays volleyball and gets in her head before games.</p>
<p>Looking for more info about your services. Thanks!</p>
<p></li>
</ol>
<p>---<br /> This message was sent from <a href="https://thementalgain.com">thementalgain.com</a>.</p>
"""

# Some forms emit an extra empty label row; the first NON-empty value must win.
HTML_EMPTY_DUPLICATE_ROW = """\
<ol>
<li><b>Parent Name</b><br />Pat Parent</li>
<li><b>Parent Name</b></li>
<li><b>Email</b><br />pat.parent@gmail.com</li>
</ol>
"""

HTML_MISSING_PHONE = """\
<ol>
<li><b>Parent Name</b><br />Sam Sample</li>
<li><b>Player Name</b><br />Sid Sample</li>
<li><b>Email</b><br />sam.sample@gmail.com</li>
<li><b>Textarea</b><p>Quick question about your services.</p></li>
</ol>
"""

# Only the email came through. A draft is still possible (and required), with
# every other field flagged for the drafter.
HTML_EMAIL_ONLY = """\
<ol>
<li><b>Parent Name</b></li>
<li><b>Player Name</b></li>
<li><b>Email</b><br /><a href="mailto:solo@gmail.com">solo@gmail.com</a></li>
<li><b>Phone</b></li>
<li><b>Textarea</b></li>
</ol>
"""

# A bare "Name" (no Parent/Player qualifier) is accepted as the parent so a
# single-name form degrades gracefully instead of losing the name entirely.
HTML_BARE_NAME = """\
<ol>
<li><b>Name</b><br />Solo Parent</li>
<li><b>Email</b><br />solo.parent@gmail.com</li>
</ol>
"""

# The client email field somehow carries a business address — must be rejected
# so we never draft a reply addressed to the business itself.
HTML_BUSINESS_EMAIL = """\
<ol>
<li><b>Parent Name</b><br />Confused Form</li>
<li><b>Email</b><br />info@thementalgain.com</li>
</ol>
"""

# The plain-text variant: label marker on its own line, value on the following
# line(s).
MARKER_FULL = """\
From: The Mental Gain <noreply@thementalgain.com>
Subject: Contact me #2099 for contact me
To: <info@thementalgain.com>

You have a new website form submission:

   1. *Parent Name*
   Pat Parent
   2. *Player Name*
   Kim Kiddo
   3. *Email*
   pat.parent@gmail.com
   4. *Phone*
   (555) 010-0100
   5. *Textarea*

   My daughter plays volleyball and gets in her head before games.
   Looking for more info about your services. Thanks!
"""

MARKER_MISSING_PHONE = """\
You have a new website form submission:

   1. *Parent Name*
   Sam Sample
   2. *Email*
   sam.sample@gmail.com
   3. *Phone*
   4. *Textarea*

   Quick question about your services.
"""

MARKER_NO_EMAIL = """\
You have a new website form submission:

   1. *Parent Name*
   No Email Person
   2. *Phone*
   (555) 010-0101
   3. *Textarea*

   I forgot to include my email.
"""

JUNK = "Just some random text with no form fields at all."


def test_parses_real_html_notification():
    result = parse(HTML_FULL)
    assert result.name == "Pat Parent"
    assert result.child_name == "Kim Kiddo"
    assert result.email == "pat.parent@gmail.com"  # taken from the anchor text
    assert result.phone == "(555) 010-0100"
    assert result.message is not None
    assert result.message.startswith("My daughter plays volleyball")
    assert "Thanks!" in result.message
    assert result.missing_fields == []


def test_parent_and_player_are_matched_by_label_not_order():
    """Swapping the two name rows must not swap who is the parent."""
    reordered = HTML_FULL.replace(
        "<li><b>Parent Name</b><br />Pat Parent</li>\n"
        "<li><b>Player Name</b><br />Kim Kiddo</li>",
        "<li><b>Player Name</b><br />Kim Kiddo</li>\n"
        "<li><b>Parent Name</b><br />Pat Parent</li>",
    )
    result = parse(reordered)
    assert result.name == "Pat Parent"
    assert result.child_name == "Kim Kiddo"


def test_parses_marker_layout():
    result = parse(MARKER_FULL)
    assert result.name == "Pat Parent"
    assert result.child_name == "Kim Kiddo"
    assert result.email == "pat.parent@gmail.com"
    assert result.phone == "(555) 010-0100"
    assert result.missing_fields == []


def test_empty_duplicate_label_row_does_not_clobber_value():
    result = parse(HTML_EMPTY_DUPLICATE_ROW)
    assert result.name == "Pat Parent"


def test_bare_name_label_is_treated_as_the_parent():
    result = parse(HTML_BARE_NAME)
    assert result.name == "Solo Parent"
    assert result.child_name is None
    assert "child_name" in result.missing_fields


def test_html_missing_optional_field_is_flagged():
    result = parse(HTML_MISSING_PHONE)
    assert result.email == "sam.sample@gmail.com"
    assert result.phone is None
    assert "phone" in result.missing_fields
    assert "name" not in result.missing_fields


def test_missing_optional_field_is_flagged_not_invented():
    result = parse(MARKER_MISSING_PHONE)
    assert result.email == "sam.sample@gmail.com"
    assert result.phone is None
    assert "phone" in result.missing_fields


def test_email_only_submission_still_parses():
    """Email is the ONLY required field: everything else missing is draftable."""
    result = parse(HTML_EMAIL_ONLY)
    assert result.email == "solo@gmail.com"
    assert result.name is None
    assert result.child_name is None
    assert result.phone is None
    assert result.message is None
    assert result.missing_fields == ["name", "child_name", "phone", "message"]


def test_missing_fields_are_named_for_the_prompt():
    """The drafter interpolates these, so absent values must read as blanks."""
    rendered = parse(HTML_EMAIL_ONLY).as_prompt_dict()
    assert rendered["name"] == "(not provided)"
    assert rendered["child_name"] == "(not provided)"
    assert rendered["message"] == "(not provided)"
    assert rendered["email"] == "solo@gmail.com"  # never a blank
    assert "message" in rendered["missing_fields"]


def test_html_business_email_is_rejected():
    # The client email must never be one of the business's own addresses.
    with pytest.raises(ParseError):
        parse(HTML_BUSINESS_EMAIL)


def test_client_email_not_business_sender():
    # The From/To headers carry the business's own addresses; the parsed email
    # must be the client's *Email* field, never noreply@/info@.
    result = parse(MARKER_FULL)
    assert "thementalgain.com" not in result.email


def test_message_is_multiline_and_dedented():
    result = parse(MARKER_FULL)
    assert result.message is not None
    assert result.message.startswith("My daughter plays volleyball")
    assert "Thanks!" in result.message
    # Leading indentation from the email body is stripped.
    assert not result.message.startswith(" ")


def test_missing_email_raises():
    with pytest.raises(ParseError):
        parse(MARKER_NO_EMAIL)


def test_junk_body_raises():
    with pytest.raises(ParseError):
        parse(JUNK)


def test_empty_body_raises():
    with pytest.raises(ParseError):
        parse("   ")


def _eml_body(path: Path) -> str:
    """Return an .eml's body, dropping the RFC-822 headers before the blank line."""
    return path.read_text(encoding="utf-8", errors="replace").partition("\n\n")[2]


def test_real_example_files():
    """Validate any local real samples structurally.

    The real `examples/*.eml` are gitignored (they contain client PII), so this
    asserts only structural properties — no real names/emails are embedded in
    source. Skips when no samples are present (e.g. a fresh checkout).
    """
    files = sorted(EXAMPLES.glob("*.eml"))
    if not files:
        pytest.skip("no real samples present (gitignored)")
    for path in files:
        result = parse(_eml_body(path))
        assert "@" in result.email, path.name  # a client email was extracted
        assert "thementalgain.com" not in result.email, path.name  # not the business
        assert result.message, path.name  # textarea captured
