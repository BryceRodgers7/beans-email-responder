"""Parse a website-inquiry email body into structured fields.

Pure functions, no I/O. Built for the real "The Mental Gain" contact-form
notification format, where each field label sits on its own line as a numbered,
asterisk-wrapped marker and the value follows on the next line(s):

    You have a new website form submission:

       1. *Name*
       Jane Doe
       2. *Email*
       jane.doe@example.com
       3. *Phone*
       (555) 010-0100
       4. *Textarea*

       I'm looking for a sports psychologist for my daughter...

Notes:
  * Everything before the first recognized label line (email headers, the
    "You have a new website form submission:" preamble) is ignored.
  * The client email comes ONLY from the *Email* field, never from the
    notification's From/To headers (which are the business's own addresses).
  * Quoted-printable decoding of the raw Gmail part is handled upstream in the
    Gmail body-extraction layer (Phase 3), not here.
"""
from __future__ import annotations

import html
import re

from .models import InquiryFields


class ParseError(Exception):
    """Raised when an inquiry cannot be parsed safely (e.g. no client email)."""


# Canonical field name -> accepted label strings (matched case-insensitively
# against the text inside the *...* marker). The form's free-text box is
# labeled "Textarea"; we map it to our canonical "message".
FIELD_LABELS: dict[str, list[str]] = {
    "name": ["name", "full name"],
    "email": ["email", "email address", "e-mail"],
    "phone": ["phone", "phone number"],
    "message": ["textarea", "message", "comments"],
}

# A draft cannot be addressed without the client's email.
REQUIRED: list[str] = ["email"]

# Matches a label marker line like "   1. *Name*" -> captures "Name".
_LABEL_LINE_RE = re.compile(r"^\s*\d+\.\s*\*\s*([^*]+?)\s*\*\s*$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*(html|table|tr|td|div|p|br)\b", text, re.IGNORECASE))


def _strip_html(text: str) -> str:
    text = re.sub(r"<\s*/?\s*(br|tr|p|div|li)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


def parse(body: str) -> InquiryFields:
    """Parse a raw inquiry email body into :class:`InquiryFields`.

    Raises :class:`ParseError` if the body is empty, contains no recognizable
    form fields, or lacks a valid client email — so the caller can route the
    message to the Error label.
    """
    if not body or not body.strip():
        raise ParseError("Empty inquiry body")

    text = _strip_html(body) if _looks_like_html(body) else body

    label_lookup = {
        label.lower(): canonical
        for canonical, labels in FIELD_LABELS.items()
        for label in labels
    }

    values: dict[str, list[str]] = {}
    current: str | None = None  # the field whose value lines we are collecting

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = _LABEL_LINE_RE.match(line)
        if match:
            # A new label marker: switch context. Unknown labels set current to
            # None so their value lines are ignored rather than misattributed.
            current = label_lookup.get(match.group(1).strip().lower())
            if current is not None:
                values.setdefault(current, [])
            continue
        if current is not None:
            values[current].append(line)

    if not values:
        raise ParseError("No recognizable form fields found in inquiry body")

    collected: dict[str, str] = {}
    for key, parts in values.items():
        stripped = [part.strip() for part in parts]
        if key == "message":
            collected[key] = "\n".join(stripped).strip()
        else:
            collected[key] = " ".join(p for p in stripped if p).strip()

    # Validate the required client email.
    email_match = _EMAIL_RE.search(collected.get("email", ""))
    if not email_match:
        raise ParseError("No valid client email address found in inquiry body")

    # Optional fields that came back empty are flagged for human review.
    missing = [
        field_name
        for field_name in FIELD_LABELS
        if field_name not in REQUIRED and not collected.get(field_name)
    ]

    return InquiryFields(
        email=email_match.group(0),
        name=collected.get("name") or None,
        phone=collected.get("phone") or None,
        message=collected.get("message") or None,
        missing_fields=missing,
    )
