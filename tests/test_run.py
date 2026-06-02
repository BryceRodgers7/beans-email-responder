"""Tests for the run.run_once orchestration loop, using a fake Gmail client."""
from __future__ import annotations

import pytest

from app.config import load_settings
from app.run import build_draft_subject, run_once

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
    return load_settings(require_secrets=False)


class FakeGmailClient:
    def __init__(self, messages: dict[str, str]):
        # messages: {msg_id: body}
        self.messages = messages
        self.drafts: list[tuple[str, str, str, str]] = []  # (to, subject, body, draft_id)
        self.draft_labels: list[tuple[str, str]] = []
        self.moves: list[tuple[str, list[str], list[str]]] = []
        self._counter = 0

    def ensure_labels(self, names):
        return {name: f"id::{name}" for name in names}

    def list_message_ids(self, label_id, max_results):
        return list(self.messages.keys())

    def get_text_and_subject(self, msg_id):
        return self.messages[msg_id], "New Form Entry"

    def create_draft(self, to, subject, body):
        self._counter += 1
        draft_id = f"draft{self._counter}"
        self.drafts.append((to, subject, body, draft_id))
        return draft_id

    def apply_label(self, msg_id, label_id):
        self.draft_labels.append((msg_id, label_id))

    def move(self, msg_id, add_label_ids, remove_label_ids):
        self.moves.append((msg_id, add_label_ids, remove_label_ids))


def test_subject_built_from_settings(settings):
    assert build_draft_subject(settings) == "[AI Draft] Re: your inquiry"


def test_valid_inquiry_drafts_to_client_and_moves_to_done(settings):
    client = FakeGmailClient({"m1": VALID_BODY})
    drafted, errored = run_once(client, settings, generate=lambda f, s: "Drafted body")

    assert (drafted, errored) == (1, 0)
    # Draft addressed to the client email from the form body, not the sender.
    to, subject, body, draft_id = client.drafts[0]
    assert to == "jane.sample@gmail.com"
    assert subject == "[AI Draft] Re: your inquiry"
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
