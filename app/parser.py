"""Parse a website-inquiry email body into structured fields.

Pure functions, no I/O. Handles the two layouts we've seen from the
"The Mental Gain" contact form:

1. The REAL notification Gmail delivers — **HTML**, each field an ``<li>`` whose
   label is bold and the value follows::

       <li><b>Email</b><br /><a href="mailto:jane@x.com">jane@x.com</a></li>

2. An older plain-text / forwarded re-rendering where each field label is a
   numbered, asterisk-wrapped marker on its own line, value on the next::

       1. *Name*
       Jane Doe
       2. *Email*
       jane@x.com

Both reduce to a ``{canonical_field: value}`` mapping that is then validated:
the client email is required, must be a real address, and must NOT be one of
the business's own addresses (the From/To headers carry those, never a client).

When neither layout parses, ``app/extractor.py`` falls back to an LLM. That
fallback reuses :func:`validate_and_build` here, so the recipient email is
always validated deterministically — never a model guess.
"""
from __future__ import annotations

import html
import re

from .models import InquiryFields


class ParseError(Exception):
    """Raised when an inquiry cannot be parsed safely (e.g. no client email)."""


# Canonical field name -> accepted label strings (matched case-insensitively
# against the marker text / bold label). The form's free-text box is labeled
# "Textarea"; we map it to our canonical "message".
FIELD_LABELS: dict[str, list[str]] = {
    "name": ["name", "full name"],
    "email": ["email", "email address", "e-mail"],
    "phone": ["phone", "phone number"],
    "message": ["textarea", "message", "comments"],
}

# A draft cannot be addressed without the client's email.
REQUIRED: list[str] = ["email"]

# The business's own domains. A parsed *client* email must never be one of
# these — otherwise we'd draft a reply addressed to the business itself.
BUSINESS_DOMAINS: tuple[str, ...] = ("thementalgain.com",)

# Matches a marker line like "   1. *Name*" -> captures "Name".
_LABEL_LINE_RE = re.compile(r"^\s*\d+\.\s*\*\s*([^*]+?)\s*\*\s*$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TAG_RE = re.compile(r"<[^>]+>")
# Each <li>…</li> form-field item, and the bold label inside it.
_LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_BOLD_RE = re.compile(r"<(?:b|strong)\b[^>]*>(.*?)</(?:b|strong)>", re.IGNORECASE | re.DOTALL)


def _label_lookup() -> dict[str, str]:
    return {
        label.lower(): canonical
        for canonical, labels in FIELD_LABELS.items()
        for label in labels
    }


def _looks_like_html(text: str) -> bool:
    return bool(re.search(r"<\s*(html|table|tr|td|div|p|br|ol|ul|li)\b", text, re.IGNORECASE))


def _strip_html(text: str) -> str:
    text = re.sub(r"<\s*/?\s*(br|tr|p|div|li)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


def _clean_value(canonical: str, text: str) -> str:
    """Collapse a raw value to a tidy string.

    The free-text ``message`` keeps line breaks (joined non-empty lines); all
    other fields collapse to a single space-joined line.
    """
    lines = [line.strip() for line in text.splitlines()]
    joiner = "\n" if canonical == "message" else " "
    return joiner.join(line for line in lines if line).strip()


def _parse_html_list(body: str) -> dict[str, str]:
    """Extract fields from the real ``<li><b>Label</b> value`` HTML notification."""
    lookup = _label_lookup()
    collected: dict[str, str] = {}
    for inner in _LI_RE.findall(body):
        bold = _BOLD_RE.search(inner)
        if not bold:
            continue
        label = _strip_html(bold.group(1)).strip().lower()
        canonical = lookup.get(label)
        if canonical is None:
            continue
        # The value is everything in the <li> except the bold label itself.
        value_html = inner[: bold.start()] + inner[bold.end() :]
        value = _clean_value(canonical, _strip_html(value_html))
        # First non-empty wins (some forms emit duplicate/empty label rows).
        if value and not collected.get(canonical):
            collected[canonical] = value
    return collected


def _parse_marker_format(text: str) -> dict[str, str]:
    """Extract fields from the ``N. *Label*`` marker layout (value on next lines)."""
    lookup = _label_lookup()
    values: dict[str, list[str]] = {}
    current: str | None = None  # the field whose value lines we are collecting
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = _LABEL_LINE_RE.match(line)
        if match:
            # A new marker: switch context. Unknown labels set current to None
            # so their value lines are ignored rather than misattributed.
            current = lookup.get(match.group(1).strip().lower())
            if current is not None:
                values.setdefault(current, [])
            continue
        if current is not None:
            values[current].append(line)

    collected = {key: _clean_value(key, "\n".join(parts)) for key, parts in values.items()}
    return {key: value for key, value in collected.items() if value}


def validate_and_build(
    collected: dict[str, str], *, business_domains: tuple[str, ...] = BUSINESS_DOMAINS
) -> InquiryFields:
    """Validate a ``{field: value}`` mapping and build :class:`InquiryFields`.

    Shared by the deterministic parser and the LLM fallback so the client email
    is validated identically in both paths. Raises :class:`ParseError` if no
    fields were found, the client email is missing/invalid, or it belongs to the
    business itself.
    """
    if not collected:
        raise ParseError("No recognizable form fields found in inquiry body")

    email_match = _EMAIL_RE.search(collected.get("email", "") or "")
    if not email_match:
        raise ParseError("No valid client email address found in inquiry body")
    email = email_match.group(0)

    lowered = email.lower()
    if any(lowered.endswith("@" + domain) or lowered.endswith("." + domain) for domain in business_domains):
        raise ParseError(f"Parsed email {email!r} belongs to the business, not a client")

    # Optional fields that came back empty are flagged for human review.
    missing = [
        field_name
        for field_name in FIELD_LABELS
        if field_name not in REQUIRED and not collected.get(field_name)
    ]

    return InquiryFields(
        email=email,
        name=collected.get("name") or None,
        phone=collected.get("phone") or None,
        message=collected.get("message") or None,
        missing_fields=missing,
    )


def parse(body: str, *, business_domains: tuple[str, ...] = BUSINESS_DOMAINS) -> InquiryFields:
    """Deterministically parse a raw inquiry email body into :class:`InquiryFields`.

    Tries the HTML ``<li>`` layout first, then the ``N. *Label*`` marker layout.
    Raises :class:`ParseError` if the body is empty, contains no recognizable
    form fields, or lacks a valid client email — so the caller can route the
    message to the Error label (or to the LLM fallback in app/extractor.py).
    """
    if not body or not body.strip():
        raise ParseError("Empty inquiry body")

    collected: dict[str, str] = {}
    if _looks_like_html(body):
        collected = _parse_html_list(body)
    if not collected:
        text = _strip_html(body) if _looks_like_html(body) else body
        collected = _parse_marker_format(text)

    return validate_and_build(collected, business_domains=business_domains)
