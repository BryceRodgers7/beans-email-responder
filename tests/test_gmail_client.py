"""Tests for the pure helpers in app.gmail_client (no network)."""
from __future__ import annotations

import base64

from app.gmail_client import (
    build_raw_message,
    extract_best_body,
    extract_plain_text,
    extract_subject,
    pick_signature_html,
)
from app.parser import parse


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def test_extract_plain_text_single_part():
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64url("Hello world")},
    }
    assert extract_plain_text(payload) == "Hello world"


def test_extract_plain_text_prefers_plain_in_multipart():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64url("<p>HTML</p>")}},
            {"mimeType": "text/plain", "body": {"data": _b64url("PLAIN")}},
        ],
    }
    assert extract_plain_text(payload) == "PLAIN"


def test_extract_plain_text_decodes_quoted_printable():
    # Real-notification style: a narrow no-break space encoded as =E2=80=AF
    # plus a soft line break (a trailing '=' that joins two wrapped lines).
    encoded = b"10:19=E2=80=AFPM =\nnext"
    payload = {
        "mimeType": "text/plain",
        "headers": [
            {"name": "Content-Type", "value": "text/plain; charset=UTF-8"},
            {"name": "Content-Transfer-Encoding", "value": "quoted-printable"},
        ],
        "body": {"data": base64.urlsafe_b64encode(encoded).decode("utf-8")},
    }
    result = extract_plain_text(payload)
    assert "10:19" in result and "PM" in result and "next" in result
    assert " " in result  # the narrow no-break space decoded
    assert "=" not in result  # soft break + escapes resolved


def test_extract_plain_text_html_fallback_strips_tags():
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64url("<p>Hi <b>there</b></p>")},
    }
    result = extract_plain_text(payload)
    assert "Hi" in result and "there" in result
    assert "<" not in result


def test_extract_subject():
    payload = {"headers": [{"name": "Subject", "value": "New Form Entry #2011"}]}
    assert extract_subject(payload) == "New Form Entry #2011"


# The real notification is HTML-only with <li><b>Label</b> rows. extract_best_body
# must return it RAW (not stripped) so the structural parser can read it — this is
# the regression that made every original inquiry fall through to LLM extraction.
REAL_HTML = (
    "<p>You have a new website form submission: </p>\n<ol>\n"
    "<li><b>Name</b><br />Rhoda Mina</li>\n"
    '<li><b>Email</b><br /><a href="mailto:rhoda.mina@gmail.com">rhoda.mina@gmail.com</a></li>\n'
    "<li><b>Phone</b><br />(904) 994-1382</li>\n"
    "<li><b>Textarea</b>\n<p>Looking for info for my daughter.</p>\n<p></li>\n</ol>"
)


def test_extract_best_body_returns_raw_html_for_html_only():
    payload = {"mimeType": "text/html", "body": {"data": _b64url(REAL_HTML)}}
    body = extract_best_body(payload)
    assert "<li>" in body and "<b>" in body  # raw, NOT stripped


def test_extract_best_body_prefers_plain_text():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64url(REAL_HTML)}},
            {"mimeType": "text/plain", "body": {"data": _b64url("PLAIN MARKERS")}},
        ],
    }
    assert extract_best_body(payload) == "PLAIN MARKERS"


def test_real_html_notification_parses_via_extract_best_body():
    # End-to-end: the production body path feeds the parser, no LLM fallback.
    payload = {"mimeType": "text/html", "body": {"data": _b64url(REAL_HTML)}}
    fields = parse(extract_best_body(payload))
    assert fields.email == "rhoda.mina@gmail.com"
    assert fields.name == "Rhoda Mina"
    assert fields.message and "daughter" in fields.message


def test_pick_signature_prefers_primary():
    entries = [
        {"sendAsEmail": "alias@x.com", "signature": "<div>Alias sig</div>"},
        {"sendAsEmail": "me@x.com", "isPrimary": True, "signature": "<div>Primary sig</div>"},
    ]
    assert pick_signature_html(entries) == "<div>Primary sig</div>"


def test_pick_signature_falls_back_to_any_nonempty():
    entries = [
        {"sendAsEmail": "me@x.com", "isPrimary": True, "signature": ""},
        {"sendAsEmail": "alias@x.com", "signature": "<div>Alias sig</div>"},
    ]
    assert pick_signature_html(entries) == "<div>Alias sig</div>"


def test_pick_signature_empty_when_none_set():
    assert pick_signature_html([{"sendAsEmail": "me@x.com", "isPrimary": True}]) == ""


def test_build_raw_message_roundtrips():
    raw = build_raw_message("client@example.com", "[AI Draft] Re: your inquiry", "Body text")
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8")
    assert "To: client@example.com" in decoded
    assert "Subject: [AI Draft] Re: your inquiry" in decoded
    assert "Body text" in decoded
    # We never set From (Gmail fills the authenticated account).
    assert "From:" not in decoded


def test_build_raw_message_html_is_multipart_alternative():
    raw = build_raw_message(
        "client@example.com",
        "Re: your inquiry",
        "Body text",
        "<p>Body text</p><div>Sig <a href='https://x.com'>link</a></div>",
    )
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8")
    assert "multipart/alternative" in decoded
    assert "text/plain" in decoded and "text/html" in decoded
    assert "Body text" in decoded  # plain-text fallback present
    assert "https://x.com" in decoded  # signature link survives in the HTML part


def test_build_raw_message_with_attachments_is_multipart_mixed():
    raw = build_raw_message(
        "client@example.com",
        "Re: your inquiry",
        "Body text",
        "<p>Body text</p>",
        attachments=[
            {"data": b"%PDF-1.4 data", "maintype": "application", "subtype": "pdf", "filename": "doc.pdf"}
        ],
    )
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8")
    assert "multipart/mixed" in decoded
    assert "multipart/alternative" in decoded  # the body alternative is nested inside
    assert "application/pdf" in decoded
    assert 'filename="doc.pdf"' in decoded
