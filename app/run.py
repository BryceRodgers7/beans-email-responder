"""Entrypoint: ``python -m app.run``.

One idempotent pass: list inquiries under the "New" label, parse each, draft a
reply with OpenAI, create a Gmail draft addressed to the client's email, label
the draft, and relabel the inquiry (New -> AI Draft Created, or -> Error on
failure). Never sends mail. State lives entirely in Gmail labels.
"""
from __future__ import annotations

import argparse

from .config import Settings, load_settings
from .drafter import generate_draft
from .logging_setup import get_logger
from .parser import ParseError, parse

log = get_logger()


def build_draft_subject(settings: Settings) -> str:
    return f"{settings.draft_subject_prefix.strip()} {settings.draft_subject.strip()}".strip()


def run_once(client, settings: Settings, generate=generate_draft) -> tuple[int, int]:
    """Process one batch. ``client`` and ``generate`` are injectable for tests.

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
    log.info("Found %d inquiry message(s) under %r", len(msg_ids), settings.label_new)

    drafted = errored = 0
    for msg_id in msg_ids:
        # --- read + parse (failures are safe: route to Error) ---
        try:
            body, _subject = client.get_text_and_subject(msg_id)
            fields = parse(body)
        except ParseError as error:
            log.warning("Parse failed for %s: %s — moving to Error", msg_id, error)
            client.move(msg_id, [error_id], [new_id])
            errored += 1
            continue
        except Exception as error:  # noqa: BLE001
            log.error("Unexpected read error for %s: %s — moving to Error", msg_id, error)
            client.move(msg_id, [error_id], [new_id])
            errored += 1
            continue

        # --- draft + create + relabel ---
        try:
            draft_body = generate(fields, settings)
            subject = build_draft_subject(settings)
            draft_msg_id = client.create_draft(fields.email, subject, draft_body)
            try:
                client.apply_label(draft_msg_id, drafts_id)
            except Exception as error:  # noqa: BLE001 - non-fatal labeling of the draft
                log.warning("Could not label draft for %s: %s", msg_id, error)
            client.move(msg_id, [done_id], [new_id])
            drafted += 1
            log.info("Drafted reply for inquiry %s (subject=%r)", msg_id, subject)
        except Exception as error:  # noqa: BLE001
            log.error("Draft generation failed for %s: %s — moving to Error", msg_id, error)
            client.move(msg_id, [error_id], [new_id])
            errored += 1

    log.info("Run complete: drafted=%d errored=%d", drafted, errored)
    return drafted, errored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.run", description="Draft AI replies for website inquiries."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load config and report readiness without calling Gmail/OpenAI.",
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
        log.info("No-op complete (dry run).")
        return 0

    if not settings.openai_api_key:
        log.error("OPENAI_API_KEY is not set; cannot generate drafts.")
        return 1

    from .gmail_client import GmailClient

    client = GmailClient.from_settings(settings)
    run_once(client, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
