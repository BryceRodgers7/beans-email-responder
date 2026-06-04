"""Tests for the run.run_once orchestration loop, using a fake Gmail client."""
from __future__ import annotations

import dataclasses

import pytest

from app.config import load_settings
from app.run import (
    Footer,
    ProcessRecord,
    Template,
    append_process_log,
    build_draft_subject,
    load_attachments,
    load_file_footer,
    resolve_footer,
    retry_errors,
    run_once,
)

VALID_BODY = """\
You have a new website form submission:

   1. *Name*
   Jane Sample
   2. *Email*
   jane.sample@gmail.com
   3. *Phone*
   (555) 010-0100
   4. *Textarea*

   My daughter plays volleyball. Looking for info.
"""

JUNK_BODY = "no form fields here at all"


@pytest.fixture
def settings():
    # Force the OpenAI key off so the parse->LLM fallback never makes a live call
    # for JUNK_BODY in these orchestration tests (deterministic parse only).
    base = load_settings(require_secrets=False)
    return dataclasses.replace(base, openai_api_key=None)


class FakeGmailClient:
    def __init__(self, messages: dict[str, str], signature_html: str = ""):
        # messages: {msg_id: body}
        self.messages = messages
        self.signature_html = signature_html
        self.drafts: list[tuple[str, str, str, str]] = []  # (to, subject, body, draft_id)
        self.draft_html: list[str | None] = []  # html_body per draft (None if plain)
        self.draft_attachments: list[list[dict] | None] = []  # attachments per draft
        self.draft_labels: list[tuple[str, str]] = []
        self.moves: list[tuple[str, list[str], list[str]]] = []
        self._counter = 0

    def get_signature(self):
        return self.signature_html

    def ensure_labels(self, names):
        return {name: f"id::{name}" for name in names}

    def list_message_ids(self, label_id, max_results):
        return list(self.messages.keys())

    def get_text_and_subject(self, msg_id):
        # Real inquiry subjects carry a unique form number; mirror that here.
        return self.messages[msg_id], f"New Form Entry #{msg_id}"

    def create_draft(self, to, subject, body, html_body=None, attachments=None):
        self._counter += 1
        draft_id = f"draft{self._counter}"
        self.drafts.append((to, subject, body, draft_id))
        self.draft_html.append(html_body)
        self.draft_attachments.append(attachments)
        return draft_id

    def apply_label(self, msg_id, label_id):
        self.draft_labels.append((msg_id, label_id))

    def move(self, msg_id, add_label_ids, remove_label_ids):
        self.moves.append((msg_id, add_label_ids, remove_label_ids))


def test_subject_built_from_settings(settings):
    assert build_draft_subject(settings) == "Re: your inquiry"


def test_valid_inquiry_drafts_to_client_and_moves_to_done(settings):
    client = FakeGmailClient({"m1": VALID_BODY})
    drafted, errored = run_once(client, settings, generate=lambda f, s: "Drafted body")

    assert (drafted, errored) == (1, 0)
    # Draft addressed to the client email from the form body, not the sender.
    to, subject, body, draft_id = client.drafts[0]
    assert to == "jane.sample@gmail.com"
    assert subject == "Re: your inquiry"
    assert body == "Drafted body"
    # Draft was labeled with the AI-assisted-drafts label.
    assert client.draft_labels == [(draft_id, "id::Website Inquiries/AI Assisted Drafts")]
    # Inquiry moved New -> AI Draft Created.
    assert client.moves == [
        ("m1", ["id::Website Inquiries/AI Draft Created"], ["id::Website Inquiries/New"])
    ]


def test_unparseable_inquiry_moves_to_error_without_drafting(settings):
    client = FakeGmailClient({"bad": JUNK_BODY})
    drafted, errored = run_once(client, settings, generate=lambda f, s: "should not be called")

    assert (drafted, errored) == (0, 1)
    assert client.drafts == []
    assert client.moves == [
        ("bad", ["id::Website Inquiries/Error"], ["id::Website Inquiries/New"])
    ]


def test_draft_generation_failure_moves_to_error(settings):
    client = FakeGmailClient({"m1": VALID_BODY})

    def boom(fields, settings):
        raise RuntimeError("openai down")

    drafted, errored = run_once(client, settings, generate=boom)
    assert (drafted, errored) == (0, 1)
    assert client.drafts == []
    assert client.moves[-1] == (
        "m1",
        ["id::Website Inquiries/Error"],
        ["id::Website Inquiries/New"],
    )


def test_mixed_batch_is_isolated(settings):
    client = FakeGmailClient({"good": VALID_BODY, "bad": JUNK_BODY})
    drafted, errored = run_once(client, settings, generate=lambda f, s: "ok")
    assert (drafted, errored) == (1, 1)
    assert len(client.drafts) == 1


def test_run_once_appends_footer_text_and_html(settings):
    client = FakeGmailClient({"m1": VALID_BODY})
    footer = Footer(text="Warm regards,\nCoach Sam", html="<div>Warm regards,<br>Coach Sam</div>")
    run_once(client, settings, generate=lambda f, s: "Body", footer=footer)

    _to, _subject, body, _id = client.drafts[0]
    assert body == "Body\n\nWarm regards,\nCoach Sam"  # plain-text part
    # HTML part: opening wrapped in <p>, then the verbatim signature HTML.
    assert client.draft_html[0] == "<p>Body</p>\n<div>Warm regards,<br>Coach Sam</div>"


def test_run_once_no_footer_keeps_plain_text(settings):
    client = FakeGmailClient({"m1": VALID_BODY})
    run_once(client, settings, generate=lambda f, s: "Body")  # default empty footer/template
    assert client.drafts[0][2] == "Body"
    assert client.draft_html[0] is None  # no HTML part when there's no footer/template
    assert client.draft_attachments[0] is None


def test_run_once_composes_opening_template_footer_and_attachments(settings):
    client = FakeGmailClient({"m1": VALID_BODY})
    template = Template(text="FIXED BODY", html="<p>FIXED BODY</p>")
    footer = Footer(text="Sabrina", html="<div>Sabrina</div>")
    pdfs = [{"data": b"%PDF-1", "maintype": "application", "subtype": "pdf", "filename": "a.pdf"}]

    run_once(
        client,
        settings,
        generate=lambda f, s: "Personal opening.",
        footer=footer,
        template=template,
        attachments=pdfs,
    )

    _to, _subject, body, _id = client.drafts[0]
    # Plain-text part: opening + fixed template + signature, in order.
    assert body == "Personal opening.\n\nFIXED BODY\n\nSabrina"
    # HTML part: opening wrapped, then template HTML, then signature HTML.
    assert client.draft_html[0] == "<p>Personal opening.</p>\n<p>FIXED BODY</p>\n<div>Sabrina</div>"
    # Attachments passed through.
    assert client.draft_attachments[0] == pdfs


def test_resolve_footer_uses_gmail_signature(settings):
    client = FakeGmailClient({}, signature_html="<div>Warm regards,<br>Coach Sam</div>")
    footer = resolve_footer(client, settings)
    assert footer.text == "Warm regards,\nCoach Sam"
    assert footer.html == "<div>Warm regards,<br>Coach Sam</div>"  # kept verbatim


def test_resolve_footer_falls_back_to_file_when_no_signature(settings):
    # No Gmail signature -> falls back to config/signature.txt (comments-only by
    # default -> empty Footer). Asserts the fallback path doesn't raise.
    client = FakeGmailClient({}, signature_html="")
    assert resolve_footer(client, settings) == Footer()
    assert load_file_footer() == ""  # default config file has no real lines


def test_resolve_footer_falls_back_when_scope_missing(settings):
    class RaisingClient(FakeGmailClient):
        def get_signature(self):
            raise RuntimeError("insufficient scope: gmail.settings.basic")

    client = RaisingClient({})
    # Should swallow the error and fall back to the file (empty Footer default).
    assert resolve_footer(client, settings) == Footer()


def test_run_once_records_every_inquiry_with_subject_and_outcome(settings):
    # One good (drafts) + one junk (errors). Both must be recorded, one row each.
    client = FakeGmailClient({"2011": VALID_BODY, "2099": JUNK_BODY})
    seen: list[ProcessRecord] = []
    drafted, errored = run_once(
        client, settings, generate=lambda f, s: "opening", on_processed=seen.append
    )

    assert (drafted, errored) == (1, 1)
    assert len(seen) == 2  # every processed inquiry recorded
    by_status = {r.status: r for r in seen}

    ok = by_status["drafted"]
    assert ok.subject == "New Form Entry #2011"  # subject, not the opaque id
    assert ok.email == "jane.sample@gmail.com"  # customer email captured
    assert ok.error == ""

    bad = by_status["error"]
    assert bad.subject == "New Form Entry #2099"
    assert bad.email == ""  # unknown for an unparseable inquiry
    assert "parse" in bad.error


def test_append_process_log_writes_one_row_per_email(tmp_path):
    path = tmp_path / "logs" / "process_log.tsv"
    append_process_log(
        ProcessRecord("2011", "New Form Entry #2011", "drafted", "jane@x.com", ""), path=path
    )
    append_process_log(
        ProcessRecord("2099", "New Form Entry #2099", "error", "", "parse: no email"), path=path
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "timestamp\tstatus\tsubject\temail\tmessage_id\terror"
    assert lines[1].split("\t")[1:] == ["drafted", "New Form Entry #2011", "jane@x.com", "2011", ""]
    assert lines[2].split("\t")[1:] == ["error", "New Form Entry #2099", "", "2099", "parse: no email"]
    assert len(lines) == 3  # header + one row per email


def test_load_attachments_reads_files_with_mimetypes(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    items = load_attachments(tmp_path)
    by_name = {a["filename"]: a for a in items}
    assert set(by_name) == {"doc.pdf", "note.txt"}
    assert (by_name["doc.pdf"]["maintype"], by_name["doc.pdf"]["subtype"]) == ("application", "pdf")
    assert by_name["doc.pdf"]["data"] == b"%PDF-1.4 fake"
    assert (by_name["note.txt"]["maintype"], by_name["note.txt"]["subtype"]) == ("text", "plain")


def test_load_attachments_missing_dir_is_empty(tmp_path):
    assert load_attachments(tmp_path / "nope") == []


def test_retry_errors_moves_error_back_to_new(settings):
    # Two inquiries sitting under the Error label get re-queued to New.
    client = FakeGmailClient({"e1": "x", "e2": "y"})
    moved = retry_errors(client, settings)
    assert moved == 2
    assert client.moves == [
        ("e1", ["id::Website Inquiries/New"], ["id::Website Inquiries/Error"]),
        ("e2", ["id::Website Inquiries/New"], ["id::Website Inquiries/Error"]),
    ]
