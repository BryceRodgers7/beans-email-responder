"""Diagnostic: dump the REAL structure + decoded bodies of an inquiry email.

Read-only — it creates nothing in Gmail. It finds a matching message and writes
what the Gmail API actually returns to out/ (gitignored), so we can build a
robust parser against ground truth instead of a forwarded re-rendering.

Usage:
  python -m tools.dump_message                          # newest default match
  python -m tools.dump_message --query 'subject:"Contact me"'
  python -m tools.dump_message --id <gmailMessageId>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_settings
from app.gmail_client import GmailClient, _decode_part_body
from app.logging_setup import get_logger

log = get_logger("dump_message")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"

# Broad query so it finds the notification however the label is set up.
DEFAULT_QUERY = 'from:noreply@thementalgain.com OR subject:"Contact me"'


def _structure(part: dict, indent: int = 0, lines: list[str] | None = None) -> list[str]:
    if lines is None:
        lines = []
    headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
    lines.append(
        "{}- {} (size={}, cte={})".format(
            "  " * indent,
            part.get("mimeType"),
            part.get("body", {}).get("size"),
            headers.get("content-transfer-encoding", ""),
        )
    )
    for sub in part.get("parts") or []:
        _structure(sub, indent + 1, lines)
    return lines


def _dump_text_parts(part: dict, counter: list[int]) -> None:
    mime = part.get("mimeType", "")
    if mime.startswith("text/") and part.get("body", {}).get("data"):
        text = _decode_part_body(part)
        safe = mime.replace("/", "_")
        path = OUT / f"sample.{counter[0]}.{safe}.txt"
        path.write_text(text, encoding="utf-8")
        log.info("wrote %s (%d chars)", path.relative_to(ROOT), len(text))
        counter[0] += 1
    for sub in part.get("parts") or []:
        _dump_text_parts(sub, counter)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.dump_message")
    ap.add_argument("--query", default=DEFAULT_QUERY, help="Gmail search query.")
    ap.add_argument("--id", default=None, help="Specific Gmail message id.")
    args = ap.parse_args(argv)

    settings = load_settings(require_secrets=False)
    service = GmailClient.from_settings(settings).service
    OUT.mkdir(exist_ok=True)

    if args.id:
        msg_id = args.id
    else:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=args.query, maxResults=1)
            .execute()
        )
        msgs = resp.get("messages", [])
        if not msgs:
            log.error("No messages matched query: %s", args.query)
            return 1
        msg_id = msgs[0]["id"]

    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg.get("payload", {})

    (OUT / "sample_payload.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("wrote out/sample_payload.json")

    log.info("MIME structure of message %s:", msg_id)
    for line in _structure(payload):
        log.info("%s", line)

    _dump_text_parts(payload, [0])
    log.info("Done. Inspect the files in out/ (gitignored). Share the structure")
    log.info("above and a REDACTED sample.*.txt so we can build the real parser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
