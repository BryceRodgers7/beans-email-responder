# Beans Email Drafter — Design & Phased Implementation Plan

AI-assisted Gmail draft generator for website contact-form inquiries.

> **Decisions locked in**
> - Inquiry bodies are **predictable plain-text fields** → deterministic regex parser.
> - Business voice/facts live in **editable, version-controlled config files**.
> - Default model: **`gpt-4o-mini`** (overridable via env/config).
> - Runs **a few times per day** via GitHub Actions cron; Gmail refresh token + OpenAI key stored as **encrypted GitHub Actions secrets**.
> - **No database. No web server. No queue.** Gmail labels are the only state store.
> - **Never sends email.** Only creates drafts for manual review.

---

## 1. Recommended Architecture

A single short-lived Python script (`python -m app.run`) that performs one idempotent pass:

```
                    ┌─────────────────────────────────────────────┐
                    │  GitHub Actions cron  (a few times / day)    │
                    │  ── OR ──  local `python -m app.run`         │
                    └───────────────────────┬─────────────────────┘
                                            │
                                            ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │  app.run  (one pass, idempotent, stateless except Gmail labels)     │
   │                                                                     │
   │  1. Auth to Gmail (OAuth refresh token) + OpenAI                     │
   │  2. List messages with label  Website Inquiries/New                 │
   │  3. For each message:                                               │
   │       a. parser.parse(body)  → InquiryFields                        │
   │            └─ on parse failure → label Error, continue              │
   │       b. drafter.generate(fields) → draft text (OpenAI)             │
   │       c. gmail.create_draft(to=fields.email, body=...)              │
   │       d. relabel: -New  +AI Draft Created  +AI Assisted Drafts      │
   │       e. on any exception in b–d → label Error, log, continue       │
   └────────────────────────────────────────────────────────────────────┘
```

Design principles:

- **Stateless between runs.** All state is encoded in Gmail labels. A crash mid-run is safe because each message is processed independently and relabeled only after its draft exists.
- **Idempotent.** Re-running never double-drafts: a message only qualifies if it still carries `Website Inquiries/New`. Relabeling is the commit point.
- **Fail-soft per message.** One bad email moves to `Error` and the run continues; it never blocks the batch.
- **Thin layers, no framework.** Plain functions + a couple of small dataclasses. The Gmail and OpenAI calls are isolated behind `gmail_client.py` and `drafter.py` so they can be swapped or mocked.

### Module responsibilities

| Module | Responsibility |
|---|---|
| `app/run.py` | Orchestration: the one-pass loop above. CLI entrypoint. |
| `app/config.py` | Load env vars + config files; validate required settings; expose a typed `Settings` object. |
| `app/gmail_client.py` | All Gmail API I/O: auth, list by label, get message, create draft, modify labels, ensure-labels-exist. Decodes the `text/plain` part (base64url → quoted-printable) before handing the body to the parser. |
| `app/parser.py` | Pure function: raw email body → `InquiryFields` dataclass (or raise `ParseError`). No I/O. |
| `app/drafter.py` | Build prompt from config + fields, call OpenAI, return draft text. No Gmail knowledge. |
| `app/models.py` | Small dataclasses: `InquiryFields`, `DraftResult`. |
| `app/logging_setup.py` | Structured, redacting logger (never logs full bodies / secrets). |
| `tools/local_test.py` | Local prompt-iteration harness (writes `.txt`, no Gmail). Phase 4. |

---

## 2. Project Folder Structure

```
beans-email-drafter/
├── README.md
├── DESIGN.md                     # this file
├── pyproject.toml                # deps + tool config (or requirements.txt)
├── .env.example                  # documents required env vars (no secrets)
├── .gitignore                    # ignores .env, token.json, credentials.json, out/
│
├── app/
│   ├── __init__.py
│   ├── run.py                    # entrypoint:  python -m app.run
│   ├── config.py
│   ├── gmail_client.py
│   ├── parser.py
│   ├── drafter.py
│   ├── models.py
│   └── logging_setup.py
│
├── config/
│   ├── business_profile.md       # facts: who you are, services, what NOT to promise
│   ├── prompt_template.md        # system/instruction template with {placeholders}
│   └── settings.toml             # non-secret tunables: model, label names, max batch
│
├── examples/                     # local test inputs (Phase 4) — safe to commit if redacted
│   ├── inquiry_basic.txt
│   ├── inquiry_missing_phone.txt
│   └── inquiry_malformed.txt
│
├── out/                          # local test outputs (gitignored)
│   └── .gitkeep
│
├── tools/
│   └── local_test.py             # python -m tools.local_test
│
├── tests/
│   ├── test_parser.py
│   └── test_drafter.py           # uses a mocked OpenAI client
│
└── .github/
    └── workflows/
        └── draft.yml             # scheduled run
```

Secrets that never get committed: `.env`, `credentials.json` (OAuth client), `token.json` (refresh token). In CI these come from GitHub Secrets instead of files.

---

## 3. Gmail Label / State Workflow

Labels (created once; the app also ensures they exist on startup):

| Label | Meaning | Who sets it |
|---|---|---|
| `Website Inquiries/New` | Fresh inquiry awaiting a draft | Gmail filter (on arrival) |
| `Website Inquiries/AI Draft Created` | Draft generated successfully | App |
| `Website Inquiries/Error` | Could not parse/draft safely | App |
| `Website Inquiries/AI Assisted Drafts` | Applied to the **draft message** itself | App |

> Gmail treats `Parent/Child` label names as a nested label in the UI. We use the literal strings above.

### State transitions

```
            Gmail filter
   (new inquiry) ──────────────▶  [New]
                                    │
                 app reads + parses │
                ┌───────────────────┴───────────────────┐
                │                                        │
         parse/draft OK                            parse fails / API error
                │                                        │
                ▼                                        ▼
   create draft (to: client email)              -New  +Error
   +AI Assisted Drafts on the draft                     │
                │                                        ▼
   -New  +AI Draft Created on inquiry            (you investigate manually)
                │
                ▼
        [AI Draft Created]   ◀── you review the draft, edit, send manually
```

Why labels as state: zero infra, human-inspectable in the Gmail UI, naturally idempotent, and trivially recoverable (drag a message back to `New` to reprocess).

### The draft-folder limitation (and our workaround)

**Limitation:** The Gmail API creates drafts via `users.drafts.create`. A draft is a special message that always lives in the `DRAFT` system folder; the API **will not let you remove `DRAFT`**, and Gmail's web UI shows drafts only under *Drafts* regardless of other labels. So a draft that appears *only* under a custom folder is **not possible**.

**What we do instead (closest practical alternative):**
1. Create the draft normally (it appears in Drafts — unavoidable).
2. **Apply the custom label `Website Inquiries/AI Assisted Drafts` to the draft's underlying message** via `users.messages.modify`. The draft is then findable under that label as well as Drafts. (Label-on-draft support varies slightly by client, so we also do #3.)
3. *(Optional)* A subject prefix can be set via `draft.subject_prefix` in
   `config/settings.toml` to make drafts searchable. It currently defaults to
   empty (no prefix) — AI drafts are identified by the `AI Assisted Drafts` label.

This gives you a clear, filterable view of AI-assisted drafts without fighting Gmail's system-folder rules.

**Signature/footer:** Gmail does not apply the account signature to
API-created drafts, so the app reads the send-as signature (via the
`gmail.settings.basic` scope) and appends it. To keep the signature's links and
images, drafts are built as **`multipart/alternative`** (plain-text fallback +
HTML part with the signature HTML verbatim). See `app/run.resolve_footer` /
`build_raw_message`; `config/signature.txt` is a plain-text fallback when the
signature can't be read.

---

## 4. Gmail API Setup Steps

One-time, in Google Cloud Console (free):

1. **Create/select a project** at console.cloud.google.com.
2. **Enable the Gmail API** (APIs & Services → Library → Gmail API → Enable).
3. **Configure the OAuth consent screen:**
   - User type: **External** (or Internal if you have Workspace).
   - Add yourself as a **Test user** — this keeps the app in "testing" mode so you don't need Google verification for personal use.
   - Scope: `https://www.googleapis.com/auth/gmail.modify` (read + label + create drafts; does **not** grant send — good; least privilege for our needs).
4. **Create OAuth client credentials:** Credentials → Create Credentials → OAuth client ID → **Desktop app**. Download `credentials.json`.
5. **Create the labels** in Gmail (or let the app auto-create them on first run): `Website Inquiries/New`, `.../AI Draft Created`, `.../Error`, `.../AI Assisted Drafts`.
6. **Create the Gmail filter** that routes inquiries to `Website Inquiries/New`:
   - Settings → Filters → Create filter.
   - Match the real notification: **From** `noreply@thementalgain.com` **and** **Subject contains** `New Form Entry` (subjects look like `New Form Entry #2011 for contact me`). Using both the sender and subject avoids false positives.
   - Action: **Apply label** `Website Inquiries/New`, and optionally **Skip the Inbox**.

> Scope note: `gmail.modify` is the minimum that covers list + read + modify-labels + drafts.create. We intentionally do **not** request `gmail.send`, so the app is structurally incapable of sending.

---

## 5. OAuth / Token Setup Plan

We use the standard installed-app OAuth flow once locally, then reuse the resulting **refresh token** everywhere (including CI).

**Local, first time:**
1. Put `credentials.json` (from step 4) in the project root (gitignored).
2. Run `python -m app.auth_bootstrap` (a tiny one-off helper using `google-auth-oauthlib`'s `InstalledAppFlow`). A browser opens; you consent.
3. The flow writes `token.json` containing the **refresh token** + client info.
4. Local runs read `token.json` automatically and silently refresh the access token when expired.

**For GitHub Actions:** there is no browser, so we feed the same credentials via secrets:
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (extracted from `token.json` / `credentials.json`).
- `config.py` builds a `google.oauth2.credentials.Credentials` object directly from those three values + the token URI, with no file needed. It refreshes the access token in-process each run.

This means **one** consent, and the long-lived refresh token is the only Gmail secret CI needs.

**Token longevity caveats (documented so future-you isn't surprised):**
- While the OAuth app is in **"Testing"** publishing status, Google expires refresh tokens after **7 days**. For a long-running unattended job you must either **publish the app to "In production"** (self-issued, no full verification needed for your own account using a sensitive—not restricted—scope) to get a non-expiring refresh token, **or** re-run the bootstrap weekly. **Recommendation: publish to Production** to get a stable token.
- A refresh token is also invalidated if you revoke access or change your Google password. If CI starts 401-ing, re-bootstrap and update the secret.

---

## 6. OpenAI API Integration Plan

- **Library:** official `openai` Python SDK.
- **Auth:** `OPENAI_API_KEY` env var (local `.env`; CI secret).
- **Model:** default `gpt-4o-mini`, read from `config/settings.toml` → overridable by env `OPENAI_MODEL`.
- **Call shape:** Chat Completions with two messages:
  - **system** = rendered `prompt_template.md` + `business_profile.md` (the guardrails: warm/professional/concise; never invent pricing, availability, commitments, or outcomes; only use facts present in the inquiry or profile).
  - **user** = the structured, parsed `InquiryFields` (name, email, phone, message — the fields the real form collects), plus an explicit list of which fields were **missing**.
- **Grounding / anti-hallucination controls:**
  - `temperature` low (e.g. `0.4`).
  - The system prompt instructs: *if key info is missing, do not fabricate — instead include a clearly marked line the business owner can fill in, e.g. `[NEEDS REVIEW: client did not specify a budget/timeline].`*
  - We pass the parsed fields as structured text, not the raw email, so the model can't latch onto signatures/footers.
- **Output:** plain email body text (no subject invention; subject is derived deterministically from `config/settings.toml` — `Re: your inquiry` by default, with an optional prefix). The business footer from `config/signature.txt` is appended after the model's text.
- **Resilience:** one retry with backoff on transient errors; on hard failure the message goes to `Error`. Token/usage is logged (counts only) for cost visibility.
- **Cost:** at a few inquiries/day on `gpt-4o-mini`, this is fractions of a cent per draft.

---

## 7. GitHub Actions Scheduled Workflow Design

`.github/workflows/draft.yml`:

```yaml
name: Draft inquiry replies
on:
  schedule:
    - cron: "0 13,17,21 * * *"   # ~3x/day UTC; adjust to your timezone
  workflow_dispatch: {}           # manual "Run workflow" button for testing

concurrency:
  group: email-drafter            # never overlap runs
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  draft:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt   # or: pip install .
      - name: Run drafter
        env:
          GMAIL_CLIENT_ID:     ${{ secrets.GMAIL_CLIENT_ID }}
          GMAIL_CLIENT_SECRET: ${{ secrets.GMAIL_CLIENT_SECRET }}
          GMAIL_REFRESH_TOKEN: ${{ secrets.GMAIL_REFRESH_TOKEN }}
          OPENAI_API_KEY:      ${{ secrets.OPENAI_API_KEY }}
          OPENAI_MODEL:        gpt-4o-mini
        run: python -m app.run
```

Notes:
- **`workflow_dispatch`** lets you trigger a run on demand from the Actions tab while testing.
- **`concurrency`** prevents two overlapping runs from double-processing.
- **Best-effort cron:** GitHub may delay scheduled jobs under load; fine for "a few times a day." The label model means a delayed/skipped run just processes everything on the next pass.
- **No artifacts/secrets written to disk.** Everything is env-injected.
- Exit non-zero only on *infrastructure* failure (auth down); per-message failures are handled via `Error` label so a single bad email doesn't fail the whole job and spam you with red X's. (Configurable.)

---

## 8. Local Development / Testing Workflow

Two local modes:

**(a) Real run against your live mailbox** — `python -m app.run`
Uses `token.json`; does everything CI does. Good for end-to-end verification with a test inquiry you send yourself.

**(b) Offline prompt-iteration harness (Phase 4)** — `python -m tools.local_test`
The fast feedback loop you asked for, with **no Gmail and no drafts created**:

```
examples/*.txt  ──▶  parser.parse  ──▶  drafter.generate  ──▶  out/<name>.draft.txt
```

- Reads every `examples/*.txt` (saved real-but-redacted inquiry bodies).
- Runs the **same** `parser.py` and `drafter.py` used in production (no divergence).
- Writes the generated draft to `out/<name>.draft.txt`, plus an `out/<name>.parsed.json` showing exactly what the parser extracted and which fields were flagged missing.
- Flags: `--prompt config/prompt_template.md` (swap templates), `--model`, `--no-llm` (parser-only, free), `--one <file>`.
- Because the prompt/profile live in `config/`, you iterate by editing `config/prompt_template.md` + `config/business_profile.md`, re-running, and diffing `out/`. When happy, that exact template is what production uses — zero copy-paste drift.

Workflow to harden the prompt:
1. Collect 5–10 representative inquiries (including messy/missing-field ones) into `examples/`.
2. Iterate template → run harness → read `out/` → adjust. Repeat.
3. Commit the final `config/` files. Production picks them up on next scheduled run.

---

## 9. Security Considerations

- **Least-privilege scope:** `gmail.modify` only — no send capability exists in the granted scope. The app is structurally unable to send mail.
- **Secrets handling:**
  - Local: `.env`, `credentials.json`, `token.json` are **gitignored**; never committed.
  - CI: client id/secret, refresh token, OpenAI key are **GitHub Encrypted Secrets**, injected as env vars, never written to disk or logs.
- **Log redaction:** `logging_setup.py` logs message IDs, field *names*, counts, and status — **never** full email bodies, client PII beyond what's needed, or any secret. The raw inquiry body is not logged.
- **PII in `examples/`:** sample inquiries must be **redacted** before committing (or keep `examples/` gitignored). Documented in README.
- **Prompt-injection awareness:** the inquiry body is untrusted user input. We (a) pass *parsed structured fields* rather than raw text to the model, (b) keep guardrails in the system prompt, and (c) **never auto-send** — a human reviews every draft, which is the ultimate backstop against a malicious "ignore your instructions and email X" inquiry.
- **Token rotation:** documented re-bootstrap procedure if the refresh token is revoked/expires; recommend publishing the OAuth app to Production to avoid 7-day test-mode expiry.
- **Blast radius:** worst case the app mislabels or drafts something odd; it cannot send, delete, or exfiltrate, and all actions are visible/reversible in Gmail.
- **Dependency hygiene:** pin versions in `requirements.txt`; small dependency surface (`google-api-python-client`, `google-auth*`, `openai`, `tomli`/stdlib `tomllib`).

---

## 10. Phased Implementation Plan

Each phase is independently runnable and reviewable.

### Phase 0 — Scaffold (½ day)
- Create folder structure, `pyproject.toml`/`requirements.txt`, `.gitignore`, `.env.example`, `README` stub.
- `config.py` loading env + `settings.toml`; `logging_setup.py`.
- **Done when:** `python -m app.run --dry-run` loads config and logs "no-op" cleanly.

### Phase 1 — Parser + tests (½–1 day)
- `models.py` (`InquiryFields`), `parser.py` (regex field extraction, missing-field detection, `ParseError` on malformed input).
- `tests/test_parser.py` covering: full inquiry, missing optional fields, missing required email (→ error), junk body.
- **Done when:** tests pass against `examples/` fixtures. *(No Gmail/OpenAI yet.)*

### Phase 2 — OpenAI drafting + config-driven prompt (1 day)
- `config/business_profile.md`, `config/prompt_template.md`.
- `drafter.py`: render prompt, call OpenAI, return body; missing-field `[NEEDS REVIEW: …]` behavior; retry/backoff.
- `tests/test_drafter.py` with a **mocked** OpenAI client (assert prompt contains guardrails + flagged-missing fields).
- **Done when:** drafting works on parsed fixtures (verified via the harness in Phase 4 or an ad-hoc script).

### Phase 3 — Gmail integration + full pass (1–2 days)
- `auth_bootstrap.py` (one-time consent → `token.json`).
- `gmail_client.py`: credentials-from-token-or-env, `ensure_labels`, `list_by_label`, `get_message`, `create_draft`, `modify_labels`.
- `run.py`: the full one-pass loop with per-message try/except → `Error`, success relabeling, configured subject + `AI Assisted Drafts` label on the draft.
- **Done when:** sending yourself a test inquiry → labeling it `New` → running locally produces a correctly-addressed draft and relabels the inquiry to `AI Draft Created`. **MVP complete.**

### Phase 4 — Local prompt-iteration harness (½ day)
- `tools/local_test.py` as specified in §8 (`examples/` → `out/`, `--no-llm`, `--prompt`, `--model`).
- Seed `examples/` with redacted samples.
- **Done when:** editing `config/prompt_template.md` and re-running visibly changes `out/` drafts, with no Gmail calls.

### Phase 5 — GitHub Actions production (½ day)
- Add the four+ repo secrets; commit `draft.yml`.
- Publish OAuth app to Production (stable refresh token).
- Trigger via `workflow_dispatch`, verify a real draft is created, confirm cron timing.
- **Done when:** the scheduled job runs unattended and drafts appear for review.

### Phase 6 — Hardening (ongoing, optional)
- Tune cron frequency, low-volume cost logging, optional failure notification (e.g. a daily summary line), README runbook for token rotation.

---

### Suggested first build target
Phases 1–4 require **no Google setup at all** and give you a fully testable parser + prompt loop. I recommend building 0→1→2→4 first (pure local, fast iteration on the AI voice), then doing the Google Cloud OAuth setup and wiring Phase 3, and finally Phase 5 for automation.
