"""All Gmail API I/O: auth, labels, reading inquiries, creating drafts.

Auth uses the installed-app OAuth flow. Locally we read a `token.json`
(created once by `python -m app.auth_bootstrap`); in CI we build credentials
directly from the GMAIL_* environment secrets. Scope is `gmail.modify` only —
the app cannot send mail.
"""
from __future__ import annotations

import base64
import quopri
import re
from email.message import EmailMessage
from pathlib import Path

from .config import Settings
from .logging_setup import get_logger
from .parser import _strip_html

log = get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    # Read-only-in-practice: lets us read the account's send-as signature so the
    # business footer on drafts matches what the owner normally uses.
    "https://www.googleapis.com/auth/gmail.settings.basic",
]
TOKEN_URI = "https://oauth2.googleapis.com/token"

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / "token.json"
CREDENTIALS_PATH = ROOT / "credentials.json"


# --------------------------------------------------------------------------- #
# Credentials / service construction
# --------------------------------------------------------------------------- #
def load_credentials(settings: Settings):
    """Load OAuth credentials from token.json (local) or env secrets (CI)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    elif settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=settings.gmail_refresh_token,
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            token_uri=TOKEN_URI,
            scopes=SCOPES,
        )
    else:
        raise RuntimeError(
            "No Gmail credentials: run `python -m app.auth_bootstrap` to create "
            "token.json, or set GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN."
        )

    if not creds.valid:
        creds.refresh(Request())
    return creds


def build_service(creds):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O) — easy to unit test
# --------------------------------------------------------------------------- #
def _charset_from(content_type: str) -> str:
    match = re.search(r'charset="?([\w\-]+)"?', content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _decode_part_body(part: dict) -> str:
    """Decode a single MIME part's body: base64url → (quoted-printable) → text."""
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data.encode("utf-8"))

    headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    cte = headers.get("content-transfer-encoding", "").lower()
    if "quoted-printable" in cte:
        # Gmail returns the part body still transfer-encoded; decode QP soft
        # breaks and =XX escapes (e.g. the =E2=80=AF seen in these notifications).
        raw = quopri.decodestring(raw)

    charset = _charset_from(headers.get("content-type", ""))
    return raw.decode(charset, errors="replace")


def _find_part(part: dict, mime_type: str) -> dict | None:
    """Depth-first search for a MIME part of the given type with body data."""
    if part.get("mimeType") == mime_type and part.get("body", {}).get("data"):
        return part
    for sub in part.get("parts", []) or []:
        found = _find_part(sub, mime_type)
        if found is not None:
            return found
    return None


def extract_plain_text(payload: dict) -> str:
    """Extract the best plain-text body from a message payload."""
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return _decode_part_body(plain)
    html_part = _find_part(payload, "text/html")
    if html_part is not None:
        return _strip_html(_decode_part_body(html_part))
    # Single-part message: the body hangs off the payload itself.
    return _decode_part_body(payload)


def extract_subject(payload: dict) -> str:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == "subject":
            return header.get("value", "")
    return ""


def pick_signature_html(send_as_entries: list[dict]) -> str:
    """Choose the best send-as signature (HTML) from a sendAs.list response.

    Prefers the primary address; falls back to any entry that has a non-empty
    signature. Returns "" when no address has a signature set.
    """
    ordered = sorted(send_as_entries, key=lambda entry: not entry.get("isPrimary", False))
    for entry in ordered:
        signature = (entry.get("signature") or "").strip()
        if signature:
            return signature
    return ""


def build_raw_message(
    to: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[dict] | None = None,
) -> str:
    """Build a base64url-encoded RFC-822 message for drafts.create.

    When ``html_body`` is given, the message carries a ``multipart/alternative``
    (plain-text fallback + HTML, so signature links/images render). When
    ``attachments`` are given (each a dict with ``data`` bytes, ``maintype``,
    ``subtype``, ``filename``), the whole thing is wrapped in ``multipart/mixed``.
    From is left to Gmail (the authenticated account); the draft is a fresh
    message to the client, not a reply within the thread.
    """
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for attachment in attachments or []:
        message.add_attachment(
            attachment["data"],
            maintype=attachment["maintype"],
            subtype=attachment["subtype"],
            filename=attachment["filename"],
        )
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")


# --------------------------------------------------------------------------- #
# Gmail client
# --------------------------------------------------------------------------- #
class GmailClient:
    """Thin wrapper over a built Gmail API service. Inject a fake in tests."""

    def __init__(self, service):
        self.service = service

    @classmethod
    def from_settings(cls, settings: Settings) -> "GmailClient":
        return cls(build_service(load_credentials(settings)))

    def ensure_labels(self, names: list[str]) -> dict[str, str]:
        """Return {name: id}, creating any labels that don't exist yet."""
        existing = {
            label["name"]: label["id"]
            for label in self.service.users().labels().list(userId="me").execute().get("labels", [])
        }
        result: dict[str, str] = {}
        for name in names:
            if name in existing:
                result[name] = existing[name]
            else:
                created = (
                    self.service.users()
                    .labels()
                    .create(
                        userId="me",
                        body={
                            "name": name,
                            "labelListVisibility": "labelShow",
                            "messageListVisibility": "show",
                        },
                    )
                    .execute()
                )
                result[name] = created["id"]
                log.info("Created Gmail label %r", name)
        return result

    def list_message_ids(self, label_id: str, max_results: int) -> list[str]:
        resp = (
            self.service.users()
            .messages()
            .list(userId="me", labelIds=[label_id], maxResults=max_results)
            .execute()
        )
        return [m["id"] for m in resp.get("messages", [])]

    def get_signature(self) -> str:
        """Return the account's send-as HTML signature ("" if none is set).

        Requires the ``gmail.settings.basic`` scope; raises if it wasn't granted
        (the caller decides whether to treat that as "no footer").
        """
        resp = self.service.users().settings().sendAs().list(userId="me").execute()
        return pick_signature_html(resp.get("sendAs", []))

    def get_text_and_subject(self, msg_id: str) -> tuple[str, str]:
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        return extract_plain_text(payload), extract_subject(payload)

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: str | None = None,
        attachments: list[dict] | None = None,
    ) -> str:
        """Create a draft addressed to ``to``; returns the draft message id.

        ``html_body`` adds an HTML alternative part (so the signature's links and
        images render); ``attachments`` adds files (e.g. the program/consent PDFs).
        """
        raw = build_raw_message(to, subject, body, html_body, attachments)
        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
        return draft["message"]["id"]

    def apply_label(self, msg_id: str, label_id: str) -> None:
        self.service.users().messages().modify(
            userId="me", id=msg_id, body={"addLabelIds": [label_id]}
        ).execute()

    def move(self, msg_id: str, add_label_ids: list[str], remove_label_ids: list[str]) -> None:
        self.service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"addLabelIds": add_label_ids, "removeLabelIds": remove_label_ids},
        ).execute()
