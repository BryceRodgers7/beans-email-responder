"""Entrypoint: ``python -m app.run``.

One idempotent pass: list inquiries under the "New" label, parse each, draft a
reply with OpenAI, create a Gmail draft addressed to the client's email, label
the draft, and relabel the inquiry (New -> AI Draft Created, or -> Error on
failure). Never sends mail. State lives entirely in Gmail labels.
"""
from __future__ import annotations

import argparse
import html as html_lib
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

from .config import Settings, load_settings
from .drafter import generate_draft
from .extractor import extract_fields
from .logging_setup import get_logger
from .parser import ParseError, _strip_html

log = get_logger()

ROOT = Path(__file__).resolve().parent.parent
# Permanent, append-only record of EVERY inquiry we attempt to process (one row
# each), committed by CI so it survives GitHub Actions' log retention.
PROCESS_LOG_PATH = ROOT / "logs" / "process_log.tsv"
# Manual fallback footer used only when the Gmail account signature is
# unavailable (settings scope not granted, API error, or no signature set).
SIGNATURE_PATH = ROOT / "config" / "signature.txt"
# Fixed body appended after the model's personalized opening paragraph.
TEMPLATE_TEXT_PATH = ROOT / "config" / "template_body.txt"
TEMPLATE_HTML_PATH = ROOT / "config" / "template_body.html"
# Files attached to every draft (e.g. program options + consent PDFs).
ATTACHMENTS_DIR = ROOT / "attachments"


class Template(NamedTuple):
    """The fixed boilerplate body in both forms (text part / HTML part)."""

    text: str = ""
    html: str = ""


def load_template(
    text_path: Path = TEMPLATE_TEXT_PATH, html_path: Path = TEMPLATE_HTML_PATH
) -> Template:
    """Load the fixed template body. Missing files yield empty strings."""
    text = text_path.read_text(encoding="utf-8").strip() if text_path.exists() else ""
    html = html_path.read_text(encoding="utf-8").strip() if html_path.exists() else ""
    return Template(text=text, html=html)


def load_attachments(directory: Path = ATTACHMENTS_DIR) -> list[dict]:
    """Load every file in ``directory`` as an attachment descriptor.

    Each item is ``{data, maintype, subtype, filename}``. The MIME type is
    guessed from the extension (defaulting to application/octet-stream).
    """
    items: list[dict] = []
    if not directory.exists():
        return items
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        mime, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        items.append(
            {
                "data": path.read_bytes(),
                "maintype": maintype,
                "subtype": subtype or "octet-stream",
                "filename": path.name,
            }
        )
    return items


class ProcessRecord(NamedTuple):
    """One processed inquiry: outcome + details for the permanent log."""

    msg_id: str
    subject: str
    status: str  # "drafted" or "error"
    extraction: str  # "parser", "llm", or "" if extraction never completed
    email: str  # customer email if known, else ""
    error: str  # error message if any, else ""


def _sanitize(value: str) -> str:
    """Flatten a value to a single TSV-safe cell (no tabs/newlines)."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


PROCESS_LOG_HEADER = "timestamp\tstatus\textraction\tsubject\temail\tmessage_id\terror\n"


def append_process_log(record: ProcessRecord, path: Path = PROCESS_LOG_PATH) -> None:
    """Append one processed inquiry to the permanent TSV log (one row per email:
    UTC timestamp, status, extraction method, subject, customer email, message
    id, error). Writes a header row when creating the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = "\t".join(
        [
            timestamp,
            record.status,
            record.extraction,
            _sanitize(record.subject),
            _sanitize(record.email),
            record.msg_id,
            _sanitize(record.error),
        ]
    )
    with path.open("a", encoding="utf-8") as handle:
        if write_header:
            handle.write(PROCESS_LOG_HEADER)
        handle.write(row + "\n")


def write_step_summary(records: list[ProcessRecord]) -> None:
    """When running in GitHub Actions, write a Markdown summary of every
    processed inquiry to the run's summary page (the $GITHUB_STEP_SUMMARY file)."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    drafted = sum(1 for r in records if r.status == "drafted")
    errored = sum(1 for r in records if r.status == "error")
    lines = [
        "## Email drafter run",
        "",
        f"Processed {len(records)} inquiry(ies): **{drafted} drafted, {errored} errored**.",
    ]
    llm_used = sum(1 for r in records if r.extraction == "llm")
    if llm_used:
        lines.append(f"({llm_used} needed LLM extraction — the parser couldn't read them.)")
    if records:
        lines += ["", "| Status | Extraction | Subject | Email | Error |", "| --- | --- | --- | --- | --- |"]
        for r in records:
            status = "✅ drafted" if r.status == "drafted" else "⚠️ error"
            lines.append(
                f"| {status} | {r.extraction or '—'} | {_sanitize(r.subject)} | "
                f"{_sanitize(r.email)} | {_sanitize(r.error)} |"
            )
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


class Footer(NamedTuple):
    """The draft footer in both forms: ``text`` for the plain-text part, ``html``
    for the HTML alternative (preserves the signature's links and images)."""

    text: str = ""
    html: str = ""


def load_file_footer(path: Path = SIGNATURE_PATH) -> str:
    """Load the fallback footer from config/signature.txt. Lines starting with
    ``#`` are comments; returns "" when there is no non-comment content."""
    if not path.exists():
        return ""
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines).strip()


def _signature_to_text(signature_html: str) -> str:
    """Convert an HTML Gmail signature to tidy plain text (for the text part)."""
    text = _strip_html(signature_html)
    text = re.sub(r"[ \t]+\n", "\n", text)  # drop trailing whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse runs of blank lines
    return text.strip()


def _text_to_html(text: str) -> str:
    """Escape plain text and turn newlines into <br> for the HTML body part."""
    return html_lib.escape(text).replace("\n", "<br>\n")


def resolve_footer(client, settings: Settings) -> Footer:
    """Resolve the draft footer in text + HTML forms.

    Primary source is the account's Gmail signature (needs the
    ``gmail.settings.basic`` scope), kept as HTML so links/images survive. Falls
    back to ``config/signature.txt`` when the signature is unavailable (scope not
    granted, API error, or unset).
    """
    try:
        signature_html = client.get_signature()
        if signature_html and signature_html.strip():
            return Footer(text=_signature_to_text(signature_html), html=signature_html)
        log.info("No Gmail account signature set; using config/signature.txt if present.")
    except Exception as error:  # noqa: BLE001 - missing scope / API error -> file fallback
        log.warning(
            "Could not read Gmail signature (%s). Re-run `python -m app.auth_bootstrap` to "
            "grant the settings scope, or fill config/signature.txt. Falling back to file.",
            error,
        )
    file_text = load_file_footer()
    if file_text:
        return Footer(text=file_text, html=_text_to_html(file_text))
    return Footer()


def build_draft_subject(settings: Settings) -> str:
    return f"{settings.draft_subject_prefix.strip()} {settings.draft_subject.strip()}".strip()


def run_once(
    client,
    settings: Settings,
    generate=generate_draft,
    extract=extract_fields,
    footer: Footer = Footer(),
    template: Template = Template(),
    attachments: list[dict] | None = None,
    on_processed: Callable[["ProcessRecord"], None] | None = None,
) -> tuple[int, int]:
    """Process one batch. ``client``, ``generate`` and ``extract`` are injectable
    for tests.

    Each draft is composed as: the model's personalized opening paragraph +
    the fixed ``template`` body + the ``footer`` (signature), with ``attachments``
    (PDFs) added. When an HTML form exists, the draft is sent as HTML + plain-text.

    Console output groups lines per inquiry with an ``[i/N]`` tag and identifies
    each by its (unique) subject, not the opaque Gmail id. ``on_processed`` is
    called with a :class:`ProcessRecord` for EVERY inquiry (drafted or errored).

    Per-message failures are isolated: the inquiry is moved to the Error label
    and the run continues. Returns (drafted, errored) counts.
    """
    labels = client.ensure_labels(
        [settings.label_new, settings.label_done, settings.label_error, settings.label_drafts]
    )
    new_id = labels[settings.label_new]
    done_id = labels[settings.label_done]
    error_id = labels[settings.label_error]
    drafts_id = labels[settings.label_drafts]

    msg_ids = client.list_message_ids(new_id, settings.max_batch)
    total = len(msg_ids)
    log.info("=== Found %d inquiry message(s) under %r ===", total, settings.label_new)

    drafted = errored = 0

    def record(rec: ProcessRecord) -> None:
        if on_processed is not None:
            on_processed(rec)

    def errored_out(idx, msg_id, subject, extraction, email, stage, error, severe) -> None:
        nonlocal errored
        errored += 1
        (log.error if severe else log.warning)(
            "[%d/%d]   -> ERROR (%s): %s  (moved to Error)", idx, total, stage, error
        )
        client.move(msg_id, [error_id], [new_id])
        record(ProcessRecord(msg_id, subject, "error", extraction, email, f"{stage}: {error}"))

    for idx, msg_id in enumerate(msg_ids, start=1):
        inquiry_subject = ""
        customer_email = ""
        extraction = ""
        # --- read + parse (failures are safe: route to Error) ---
        try:
            body, inquiry_subject = client.get_text_and_subject(msg_id)
            log.info("[%d/%d] Inquiry: %r", idx, total, inquiry_subject or "(no subject)")
            fields = extract(body, settings)
            customer_email = fields.email
            extraction = fields.extraction_method
            if extraction == "llm":
                log.info("[%d/%d]   (parser couldn't read it; used LLM extraction)", idx, total)
        except ParseError as error:
            errored_out(idx, msg_id, inquiry_subject, extraction, customer_email, "parse", error, severe=False)
            continue
        except Exception as error:  # noqa: BLE001
            errored_out(idx, msg_id, inquiry_subject, extraction, customer_email, "read", error, severe=True)
            continue

        # --- draft + create + relabel ---
        try:
            opening = generate(fields, settings)
            text_body = "\n\n".join(
                part for part in (opening, template.text, footer.text) if part
            )
            html_chunks: list[str] = [f"<p>{_text_to_html(opening)}</p>"]
            if template.html:
                html_chunks.append(template.html)
            if footer.html:
                html_chunks.append(footer.html)
            html_body = "\n".join(html_chunks) if (template.html or footer.html) else None

            draft_subject = build_draft_subject(settings)
            draft_msg_id = client.create_draft(
                fields.email, draft_subject, text_body, html_body, attachments or None
            )
            try:
                client.apply_label(draft_msg_id, drafts_id)
            except Exception as error:  # noqa: BLE001 - non-fatal labeling of the draft
                log.warning("[%d/%d]   -> (warning) could not label draft: %s", idx, total, error)
            client.move(msg_id, [done_id], [new_id])
            drafted += 1
            log.info("[%d/%d]   -> drafted reply to %s", idx, total, customer_email)
            record(ProcessRecord(msg_id, inquiry_subject, "drafted", extraction, customer_email, ""))
        except Exception as error:  # noqa: BLE001
            errored_out(idx, msg_id, inquiry_subject, extraction, customer_email, "draft", error, severe=True)

    log.info("=== Run complete: drafted=%d errored=%d ===", drafted, errored)
    return drafted, errored


def retry_errors(client, settings: Settings) -> int:
    """Move every inquiry under the Error label back to New, so the next pass
    re-processes it (e.g. after a parser/prompt fix). Returns the count moved.

    Gmail returns up to 500 messages per page; if you have more errored
    inquiries than that, run ``--retry-errors`` again to drain the rest.
    """
    labels = client.ensure_labels([settings.label_new, settings.label_error])
    new_id = labels[settings.label_new]
    error_id = labels[settings.label_error]

    msg_ids = client.list_message_ids(error_id, 500)
    for msg_id in msg_ids:
        client.move(msg_id, [new_id], [error_id])
    log.info(
        "Re-queued %d inquiry message(s): %r -> %r",
        len(msg_ids),
        settings.label_error,
        settings.label_new,
    )
    return len(msg_ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.run", description="Draft AI replies for website inquiries."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load config and report readiness without calling Gmail/OpenAI.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Move inquiries from the Error label back to New (to re-process after "
        "a parser/prompt fix), then run a normal pass.",
    )
    args = parser.parse_args(argv)

    settings = load_settings(require_secrets=False)

    if args.dry_run:
        log.info("Dry run: configuration loaded successfully.")
        log.info("Model = %s | temperature = %s", settings.openai_model, settings.temperature)
        log.info(
            "Labels: new=%r done=%r error=%r drafts=%r | max_batch=%d",
            settings.label_new,
            settings.label_done,
            settings.label_error,
            settings.label_drafts,
            settings.max_batch,
        )
        log.info(
            "Secrets present -> OPENAI_API_KEY=%s GMAIL_CLIENT_ID=%s GMAIL_REFRESH_TOKEN=%s",
            bool(settings.openai_api_key),
            bool(settings.gmail_client_id),
            bool(settings.gmail_refresh_token),
        )
        template = load_template()
        attachments = load_attachments()
        log.info(
            "Template body present=%s | %d attachment(s): %s",
            bool(template.text and template.html),
            len(attachments),
            ", ".join(a["filename"] for a in attachments) or "(none)",
        )
        log.info("No-op complete (dry run).")
        return 0

    if not settings.openai_api_key:
        log.error("OPENAI_API_KEY is not set; cannot generate drafts.")
        return 1

    from .gmail_client import GmailClient

    client = GmailClient.from_settings(settings)
    if args.retry_errors:
        retry_errors(client, settings)
    footer = resolve_footer(client, settings)
    template = load_template()
    attachments = load_attachments()
    log.info(
        "Template body: %d chars text / %d chars html | %d attachment(s): %s",
        len(template.text),
        len(template.html),
        len(attachments),
        ", ".join(a["filename"] for a in attachments) or "(none)",
    )

    processed: list[ProcessRecord] = []

    def record_processed(record: ProcessRecord) -> None:
        processed.append(record)
        append_process_log(record)  # permanent, append-only TSV (committed by CI)

    run_once(
        client,
        settings,
        footer=footer,
        template=template,
        attachments=attachments,
        on_processed=record_processed,
    )
    write_step_summary(processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
