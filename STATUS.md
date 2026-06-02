# Project Status & Handoff

**Last updated:** 2026-06-02. Point Claude at this file to resume.

This is the "where are we / what's next" living doc. For the full design see
[DESIGN.md](DESIGN.md); for operational setup steps see [SETUP.md](SETUP.md).

---

## 1. One-line summary

A small Python app that reads website contact-form inquiry emails from a Gmail
label, drafts a warm reply with OpenAI addressed to the **client's email from
the form body**, saves it as a Gmail **draft** (never sends), and relabels the
inquiry. State lives entirely in Gmail labels. Targets "The Mental Gain" (a
sports-psychology business — the mailbox owner is the developer's sister).

## 2. Current state — code

- **Phases 0–5 are code-complete; 25 tests passing** (`python -m pytest -q`).
- All AI/Gmail calls are isolated behind modules and unit-tested against fakes,
  so no network is needed to run the suite.

### Architecture (modules)
```
app/
  run.py            Orchestration: run_once() = list New → parse → draft →
                    create draft → label draft → relabel inquiry (New→Done,
                    or →Error on failure). Per-message failures are isolated.
                    `--dry-run` reports config without calling Gmail/OpenAI.
  config.py         Loads config/settings.toml + secrets from env/.env → Settings.
  gmail_client.py   All Gmail I/O: OAuth creds (token.json local / env in CI),
                    ensure_labels, list_by_label, get body (base64url +
                    quoted-printable decode), create_draft, modify labels.
                    Pure helpers: extract_plain_text, extract_subject,
                    build_raw_message.
  parser.py         body text → InquiryFields. ***BRITTLE — see limitations.***
  drafter.py        InquiryFields → draft body via OpenAI. System prompt =
                    prompt_template.md + business_profile.md; inquiry passed as
                    a separate user message (treated as untrusted data).
  models.py         InquiryFields (email, name, phone, message, missing_fields).
  auth_bootstrap.py One-time OAuth consent → writes token.json, prints GMAIL_*.
  logging_setup.py  stdout logger (per-logger handler; never logs bodies/secrets).

tools/
  local_test.py     Offline prompt-iteration harness: examples/*.txt → out/
                    (.parsed.json + .draft.txt). Flags: --no-llm, --one,
                    --prompt, --profile, --model. No Gmail.
  dump_message.py   NEW diagnostic (read-only): dumps a real inquiry's MIME
                    structure + decoded bodies to out/. NOT RUN YET — this is
                    the first task tomorrow.

config/
  settings.toml        model, labels, max_batch, draft subject/prefix.
  business_profile.md  ***Has TODO placeholders — biggest quality lever.***
  prompt_template.md   System prompt (voice + guardrails).
```

### Gmail label workflow
`Website Inquiries/New` → (app) → `…/AI Draft Created`, or `…/Error` on failure.
Draft also gets `…/AI Assisted Drafts` + an `[AI Draft]` subject prefix (a draft
can't leave Gmail's Drafts system folder, so the label+prefix are the workaround).

## 3. Current state — operational setup (on the sister's account/computer)

Done:
- Google Cloud project created in the sister's account; **Gmail API enabled**.
- OAuth consent screen configured, scope **`gmail.modify`** only.
- **Published to Production (unverified).** The "requires verification" banner is
  expected for this restricted scope and is intentionally ignored — no review
  submitted (full verification needs a paid CASA assessment, unnecessary for
  single-user personal use). Production status = the refresh token does NOT
  expire every 7 days. Consent shows an "unverified app" warning that you click
  through (Advanced → Go to … (unsafe) → Allow).
- **Desktop OAuth client** created; `credentials.json` downloaded to project root.
- `python -m app.auth_bootstrap` run successfully → **`token.json` exists** on the
  sister's machine; the three `GMAIL_*` values were retrieved (live in token.json
  as client_id / client_secret / refresh_token).

Not done yet (intentionally or blocked):
- **OpenAI API key** not yet on the sister's machine (user will transfer it
  safely; goes in `.env` as `OPENAI_API_KEY`).
- **Gmail filter + labels** not created yet (filter: From `noreply@thementalgain.com`
  AND subject contains `New Form Entry` → apply `Website Inquiries/New`).
- **No real `python -m app.run` end-to-end run has happened yet.**
- **GitHub Actions secrets / schedule:** deliberately deferred. User does NOT
  want scheduling yet — wants to run manually and tune the prompt first.

## 4. Current limitations / known issues

1. **🔴 BLOCKER — the parser targets the wrong email format.** The files in
   `examples/` (`1. *Name*`, `*Email*` with asterisks) turned out to be Gmail's
   *forwarded re-rendering*, not the real notification. The actual incoming
   email (as the Gmail API returns it) is **HTML** (`<li>`, `<b>`, no asterisks).
   So `parser.py` (regex for `1. *Label*` marker lines) will fail on real mail.
   This blocks both real runs and meaningful prompt testing.
2. **business_profile.md is mostly TODO placeholders** (services, sign-off/sender
   name, call-to-action). Drafts are generic until filled in. Note: placeholder
   "e.g." text in this file WILL be repeated by the model as fact — keep
   placeholders non-specific.
3. **`examples/*.txt` are gitignored** (real client PII), so fresh checkouts have
   none; the local harness and the real-sample parser test need local files /
   skip gracefully.
4. No real end-to-end verification against live Gmail yet (first real run pending
   the parser fix).

## 5. What we decided to tackle next (the plan)

**Goal: make inquiry parsing robust and format-agnostic via LLM extraction.**

Step 1 — **Capture ground truth.** Run the new diagnostic on the machine with
`token.json`:
```powershell
python -m tools.dump_message
```
It writes `out/sample.*.txt` (decoded bodies) + `out/sample_payload.json` and
prints the MIME structure. Share: the structure lines + one **redacted** body.

Step 2 — **Implement LLM-based extraction** (replaces/Wraps `parser.py`):
- Clean the body (prefer the `text/html` part → readable text).
- LLM returns fields as JSON `{name, email, phone, message, missing}` (low temp).
- **Deterministically validate the client email** (must be a valid address AND
  must NOT be a `thementalgain.com` address) before drafting; invalid → Error
  label. The recipient address must never be a model guess.
- Keep the existing draft guardrails. Regex parser becomes a free fallback or is
  retired. Update tests.

Step 3 — **Test the loop:** put the OpenAI key in `.env`, drop a couple of real
(redacted) bodies in `examples/`, iterate with `python -m tools.local_test`,
and fill in `business_profile.md`.

Step 4 — **First real run:** create the Gmail filter/label, send a test inquiry,
run `python -m app.run`, verify a draft appears and the inquiry relabels.

Step 5 (later, when happy) — Add GitHub secrets and enable the schedule.

## 6. How to resume tomorrow

1. Read this file + skim `app/parser.py`, `app/gmail_client.py`, `tools/dump_message.py`.
2. Ask the user to run `python -m tools.dump_message` and paste the MIME
   structure + a redacted body.
3. Proceed with Step 2 (LLM extraction). Don't rebuild the working parts (Gmail
   plumbing, drafter, labels, tests) — only swap the "body → fields" step.

**Quick checks:** `python -m pytest -q` (expect pass, real-sample test skipped)
and `python -m app.run --dry-run`.
