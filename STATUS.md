# Project Status & Handoff

**Last updated:** 2026-07-29 (code last changed 2026-06-11, commit `08669da`).
Point Claude at this file to resume.

This is the "where are we / what's next" living doc. For the full design see
[DESIGN.md](DESIGN.md); for operational setup steps see [SETUP.md](SETUP.md) and
[SETUP_GMAIL_LABELS_AND_FILTER.md](SETUP_GMAIL_LABELS_AND_FILTER.md).

---

## 1. One-line summary

A small Python app that reads website contact-form inquiry emails from a Gmail
label, drafts a warm reply with OpenAI addressed to the **client's email from
the form body**, saves it as a Gmail **draft** (never sends), and relabels the
inquiry. State lives entirely in Gmail labels. Targets "The Mental Gain" (a
sports-psychology business — the mailbox owner is the developer's sister).

## 2. Current state — code

- **Phases 0–5 are code-complete; 57 tests passing, 1 skipped**
  (`python -m pytest -q`). The skip is the real-sample parser test, which needs a
  local `examples/` file (gitignored — real client PII).
- All AI/Gmail calls are isolated behind modules and unit-tested against fakes,
  so no network is needed to run the suite.
- The parser and body-extraction blockers that stalled the first real run are
  both **resolved** (see §4).

### Architecture (modules)
```
app/
  run.py            Orchestration: run_once() = list New → extract → draft →
                    create draft → label draft → relabel inquiry (New→Done,
                    or →Error on failure). Per-message failures are isolated.
                    Console output groups lines per inquiry ([i/N] + subject,
                    not Gmail id). EVERY processed inquiry (drafted or errored) is
                    appended as one row to the permanent logs/process_log.tsv
                    (timestamp, status, extraction[parser|llm], subject, email,
                    message_id, error; committed by CI) + a $GITHUB_STEP_SUMMARY
                    table. Flags: `--dry-run`, `--retry-errors` (Error -> New),
                    `--reset-drafted` (AI Draft Created -> New, capped at
                    max_batch — the prompt-tuning reset; see the runbook).
  config.py         Loads config/settings.toml + secrets from env/.env → Settings.
  gmail_client.py   All Gmail I/O: OAuth creds (token.json local / env in CI),
                    ensure_labels, list_by_label, get body (base64url +
                    quoted-printable decode), create_draft, modify labels.
                    Pure helpers: extract_plain_text, extract_best_body,
                    extract_subject, build_raw_message.
                    `get_text_and_subject` uses extract_best_body: text/plain
                    when present, else RAW html (the parser does its own HTML
                    handling — do NOT pre-strip, see §4.1).
  extractor.py      `extract_fields()` = deterministic parse → LLM JSON fallback
                    (only when an API key is present) → deterministic email
                    re-validation. This is what run.py calls, not parser directly.
  parser.py         body text → InquiryFields. Parses the real HTML
                    `<li><b>Label</b> value` layout first, the older
                    `N. *Label*` marker layout as fallback. Rejects a parsed
                    client email on the business's own domain.
  drafter.py        InquiryFields → the PERSONALIZED OPENING PARAGRAPH only,
                    via OpenAI. System prompt = prompt_template.md +
                    business_profile.md; inquiry passed as a separate user
                    message (untrusted data). run.py then appends the FIXED
                    template body (config/template_body.txt/.html) + the Gmail
                    signature, and attaches every file in attachments/ (PDFs).
                    Drafts are multipart/mixed[alternative[text,html], pdfs].
  models.py         InquiryFields (email, name, child_name, phone, message,
                    missing_fields). `name` = parent/guardian, `child_name` =
                    the athlete (see §3, form format).
  auth_bootstrap.py One-time OAuth consent → writes token.json, prints GMAIL_*.
  logging_setup.py  stdout logger (per-logger handler; never logs bodies/secrets).

tools/
  local_test.py     Offline prompt-iteration harness: examples/*.txt → out/
                    (.parsed.json + .draft.txt). Flags: --no-llm, --one,
                    --prompt, --profile, --model. No Gmail.
  dump_message.py   Diagnostic (read-only): dumps a real inquiry's MIME
                    structure + decoded bodies to out/. Already used once to
                    identify the live HTML format; keep for the next surprise.

config/
  settings.toml        model (gpt-4o-mini), labels, max_batch = 25, draft subject.
  business_profile.md  Facts for the opening paragraph, incl. "What athletes come
                       to us for" (the focus-area gate — see §3). 2 TODOs left.
  prompt_template.md   System prompt: model writes ONLY the opening paragraph.
  template_body.txt    FIXED body (services/link/options/consent), plain text.
  template_body.html   FIXED body, HTML (rendered part of the draft).
  signature.txt        Fallback footer (normally the Gmail signature is used).
attachments/           PDFs attached to every draft (program options + consent).
.github/workflows/
  draft.yml            Scheduled run (cron 13/17/21 UTC) + workflow_dispatch.
                       Committed and pushed — see §3 for the open question.
```

### Gmail label workflow
`Website Inquiries/New` → (app) → `…/AI Draft Created`, or `…/Error` on failure.
Draft also gets the `…/AI Assisted Drafts` label (a draft can't leave Gmail's
Drafts system folder, so the label is how you spot AI drafts). Subject prefix is
configurable in `config/settings.toml` and currently empty. The footer is the
account's **Gmail signature** (read via `gmail.settings.basic`), appended to each
draft body; `config/signature.txt` is a fallback.

### Inquiry form format
The notification is `text/html` (no transfer-encoding), an `<ol>` of
`<li><b>Label</b><br />value</li>` rows in a fixed order, subject
`Contact me #NNNN for contact me`, from `noreply@thementalgain.com`.

- **New (2026-07-25 onward) — the only format we support.** The form was fixed to
  emit distinct labels: **`Parent Name`** and **`Player Name`**, so the parser
  matches names by label. Sample: `examples/2047.eml`.
- **Old (through 2026-07)** — two rows both labeled `Name`, parent first. No
  longer supported as such (decision 2026-07-29: only new mail matters). A bare
  `Name` is still accepted as the parent, so old mail degrades to parent-only
  instead of losing both names. Sample: `examples/2029.eml`.

Verified 2026-07-29 by diffing the two samples: the name labels are the *only*
change. Field order, the `Textarea` message label, the `mailto:` anchor on Email,
the footer, and every header are identical — so the Gmail filter and
`extract_best_body` are unaffected.

## 3. Current state — operational setup (on the sister's account/computer)

Done:
- Google Cloud project created in the sister's account; **Gmail API enabled**.
- OAuth consent screen configured. Scopes: **`gmail.modify`** +
  **`gmail.settings.basic`** (the latter reads the Gmail signature for the
  footer). `token.json` was re-consented with both scopes.
- **Published to Production (unverified).** The "requires verification" banner is
  expected for this restricted scope and is intentionally ignored — no review
  submitted (full verification needs a paid CASA assessment, unnecessary for
  single-user personal use). Production status = the refresh token does NOT
  expire every 7 days. Consent shows an "unverified app" warning that you click
  through (Advanced → Go to … (unsafe) → Allow).
- **Desktop OAuth client** created; `credentials.json` downloaded to project root.
- `python -m app.auth_bootstrap` run successfully → **`token.json` exists** on the
  sister's machine; the three `GMAIL_*` values live in it as client_id /
  client_secret / refresh_token.
- **Gmail labels + filter created** (filter: From `noreply@thementalgain.com`
  AND subject contains `Contact me` → apply `Website Inquiries/New`). Steps are
  written up in `SETUP_GMAIL_LABELS_AND_FILTER.md`.
- **OpenAI API key is on the sister's machine** (`.env` → `OPENAI_API_KEY`).
- **First real end-to-end run happened 2026-06-03**: 4 inquiries drafted, 21
  errored, remainder untouched. The 25-item ceiling is `max_batch`, not a bug —
  re-running drains the backlog. All 21 errors were the pre-fix parser failing
  on the live HTML notification; the fix landed the same day but **those 21 have
  not been retried yet** (§5, step 1).

Not done / open:
- **GitHub Actions secrets: NOT set, and the scheduled workflow has been failing
  3× a day since June** (confirmed by the user 2026-07-29). `draft.yml` is
  committed and pushed with a live `schedule:` trigger, so every cron firing
  (13/17/21 UTC) runs `python -m app.run` with no credentials and dies. Fix by
  either adding the secrets or commenting out the `schedule:` block — see §5
  step 3. (GitHub auto-disables scheduled workflows after 60 days of repo
  inactivity, so this may stop on its own around mid-August, but don't rely on
  that.)
- When the secrets ARE added: `GMAIL_REFRESH_TOKEN` must come from the **NEW
  two-scope consent**, not the original `gmail.modify`-only token.

## 4. Current limitations / known issues

1. **✅ RESOLVED (2026-06-03) — parser reads the real HTML format, and the body
   reaches it intact.** Two bugs, one after the other:
   - `parser.py` only understood the `N. *Label*` marker layout; the live
     notification is HTML (`<li><b>Label</b>`, no asterisks). `dump_message`
     confirmed it. The parser now does HTML first, markers as fallback.
   - Subtler: `gmail_client.extract_plain_text` **stripped the HTML before the
     parser saw it**, so the `<li>` path could never match and every html-only
     ORIGINAL fell through to the slow/paid LLM extraction; only `Fwd:` mails
     (which carry a text/plain part) parsed. Fixed with `extract_best_body()`.
     **Don't reintroduce pre-stripping.**
2. **`business_profile.md` has 2 TODOs left** — the one-or-two-sentence practice
   description (§"Who we are") and the preferred call-to-action (§"Typical next
   step"). The substantive content (focus areas, voice, prohibitions) is filled
   in. Note: placeholder "e.g." text in this file WILL be repeated by the model
   as fact — keep any placeholder non-specific.
3. **✅ RESOLVED (2026-07-29) — parser reads `Parent Name` / `Player Name`.**
   `FIELD_LABELS` now maps them to `name` / `child_name` as distinct labels, so
   names are matched **by label, not by position**, and the old positional
   `_assign_names` split is gone. Old two-`Name` emails are no longer supported
   as such (decision: only new mail matters going forward) — a bare `Name` is
   still accepted as the parent, so they degrade to parent-only rather than
   losing both names. Verified against `examples/2047.eml` (all fields, nothing
   missing) and `2029.eml` (parent only, `child_name` flagged missing).
4. **The 2026-06-11 prompt retune is unverified against real drafts** — the
   focus-area gating of the "she works with many athletes on this" reassurance
   needs eyes on live output, not just tests.
5. **`examples/` is gitignored** (real client PII), so fresh checkouts have no
   samples; the local harness and the real-sample parser test skip gracefully.
   Local samples as of 2026-07-29: `2029.eml` (old two-`Name` format),
   `2047.eml` (new `Parent Name`/`Player Name` format).
   Minor gap: `tests/test_parser.py::test_real_example_files` globs `*.txt`, but
   the real samples are `.eml` **with headers** — so it skips even when samples
   exist. Worth pointing it at `*.eml` and splitting the body off the headers.
6. **`logs/process_log.tsv` in this repo is header-only.** Local runs write it on
   the machine they ran on; only CI commits it back. Don't read the committed log
   as "no runs have happened".

## 5. What to tackle next

**Step 1 — Drain the error backlog** (on the machine with `token.json`):
```powershell
python -m app.run --retry-errors   # moves Error → New and reprocesses
python -m app.run                  # again if >25 remain (max_batch)
```
Then **read the resulting drafts in Gmail.** This is the first real test of both
the HTML parser fix and the parent/player name handling.

**Step 2 — Iterate on wording** with the real drafts in hand:
- `config/prompt_template.md` (opening paragraph) — check the focus-area gate
  behaves: "happy to help" always, "sees a lot of this" only for
  confidence / bouncing-back-from-mistakes concerns.
- `config/template_body.txt` + `.html` (the fixed body) — keep the two in sync.
- Fill the 2 remaining `business_profile.md` TODOs.
- Fast loop without Gmail: drop `.eml` downloads in `examples/` and run
  `python -m tools.local_test`. **Sabrina drives this herself** — the
  step-by-step is `RUNBOOK_PROMPT_TUNING.md` (written for a non-developer:
  install, the free `--no-llm` read check, the tuning loop, which config file
  owns what, how to export an inquiry from Gmail, troubleshooting).

**Step 3 — Stop the failing cron** (§3). It has been failing 3× a day since June.
Either add the three `GMAIL_*` secrets (from the **two-scope** consent) +
`OPENAI_API_KEY`, or comment out the `schedule:` block in
`.github/workflows/draft.yml` (keeping `workflow_dispatch`) until you actually
want scheduled runs. The second is the smaller move while the prompt is still
being tuned.

## 6. How to resume

1. Read this file. Skim `app/extractor.py`, `app/parser.py`, `app/run.py`.
2. Quick checks: `python -m pytest -q` (expect 60 passed — the real-sample test
   now runs against `examples/*.eml`) and `python -m app.run --dry-run`.
3. Start at §5 step 1. No code changes are outstanding — the remaining work is
   operational (drain the backlog, read real drafts) and editorial
   (prompt/template wording). Don't rebuild the working parts (Gmail plumbing,
   parser, drafter, labels, template, tests).
