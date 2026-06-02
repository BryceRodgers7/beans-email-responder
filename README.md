# Beans Email Drafter

AI-assisted Gmail draft generator for website contact-form inquiries. It finds
inquiry emails under a Gmail label, drafts a warm reply with the OpenAI API,
and saves a Gmail draft **addressed to the client's email from the form body**
for you to review and send manually. It never sends email.

See **[DESIGN.md](DESIGN.md)** for the full architecture and phased plan,
**[SETUP.md](SETUP.md)** for operational setup, and **[STATUS.md](STATUS.md)**
for current state / what's next (start here when resuming).

## Status

| Phase | Scope | State |
|------|-------|-------|
| 0 | Scaffold + config + `--dry-run` | ✅ done |
| 1 | Parser + tests | ✅ done (real "The Mental Gain" format) |
| 2 | OpenAI drafting (`app/drafter.py`) | ✅ done |
| 4 | Local prompt-iteration harness (`tools/local_test.py`) | ✅ done |
| 3 | Gmail integration / MVP (`app/gmail_client.py`, `app/run.py`) | ✅ code complete (needs OAuth setup to run live) |
| 5 | GitHub Actions automation (`.github/workflows/draft.yml`) | ✅ code complete (needs repo secrets) |

All code is written and unit-tested against fakes. The remaining work is
**operational**, not code: complete the Google Cloud / OAuth setup and load the
secrets. Follow **[SETUP.md](SETUP.md)** — a step-by-step runbook (note: the
Gmail mailbox is the sister's business account, so the consent must be approved
by her).

The parser (`app/parser.py`) is now matched to the real contact-form
notification format (numbered `*Label*` marker lines with the value on the
following line; fields: Name, Email, Phone, Textarea→message), validated
against `examples/2011-2013.txt`.

## ⚠️ Open TODOs

- **Business profile / voice.** `config/business_profile.md` and
  `config/prompt_template.md` have known facts filled in but still contain
  `TODO:` items (services, sign-off, call-to-action) to complete before going live.
- **PII in `examples/`.** `examples/2011-2013.txt` are real submissions with
  names/emails/phone numbers. Decide whether to gitignore `examples/` or keep
  redacted copies before committing to a public/shared repo.

## Quick start (local)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Phase 0: verify config loads
python -m app.run --dry-run

# Phase 1: run parser tests
python -m pytest -q

# Phase 4: iterate on the prompt against example inquiries (writes to out/)
python -m tools.local_test --no-llm     # parser only, free
python -m tools.local_test              # full drafts via OpenAI
python -m tools.local_test --one 2011.txt --model gpt-4o
```

**Prompt-tuning loop:** edit `config/prompt_template.md` and
`config/business_profile.md` → run `python -m tools.local_test` → read
`out/*.draft.txt` → repeat. The same parser/drafter code runs in production, so
what you tune is what ships.

Copy `.env.example` to `.env` and fill in secrets as later phases need them
(`.env` is gitignored).

## Live run (Phase 3 — against your real Gmail)

One-time setup (details in DESIGN.md §4–5):

```powershell
pip install -r requirements.txt          # installs the Google API libraries

# 1. In Google Cloud: enable Gmail API, configure OAuth consent (scope:
#    gmail.modify), create a "Desktop app" OAuth client, download it as
#    credentials.json into the project root.
# 2. One-time consent — opens a browser, writes token.json, and prints the
#    three values to copy into GitHub Actions secrets later:
python -m app.auth_bootstrap

# 3. In Gmail: create a filter (From: noreply@thementalgain.com AND
#    Subject contains "New Form Entry") that applies the label
#    "Website Inquiries/New". (The app auto-creates the other labels.)

# 4. Run one pass against your inbox (creates drafts, never sends):
python -m app.run
```

`token.json`, `credentials.json`, and `.env` are gitignored — never commit them.

