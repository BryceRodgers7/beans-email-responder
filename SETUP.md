# Setup Runbook

A practical checklist to take this from "code complete" to "running on a
schedule." Because the mailbox belongs to **your sister's business**, some
steps must be done with **her** Google account. Those are marked 👩 (sister)
vs 🧑 (you / developer).

> The OAuth consent grants access to whichever Google account approves it. The
> resulting refresh token is what the scheduled job uses, so it must be **her
> account's** token.

---

## 0. Decide who holds what

| Item | Whose | Notes |
|---|---|---|
| Gmail mailbox | 👩 sister | The inbox we read inquiries from and create drafts in. |
| Google Cloud project + OAuth client | 🧑 or 👩 | Either works; the **consent** must be done as the sister. Simplest: create the project in her Google account. |
| OpenAI API key | 🧑 or 👩 | Any key with billing. Used to generate drafts. |
| GitHub repo + secrets | 🧑 you | Where the schedule runs. |

---

## 1. Gmail labels + filter  👩 (or 🧑 with access)

In the sister's Gmail:

1. Create the filter that routes inquiries:
   - Settings → Filters and Blocked Addresses → **Create a new filter**.
   - **From:** `noreply@thementalgain.com`
   - **Has the words:** `subject:("Contact me")`
   - Create filter → **Apply the label** → create/choose `Website Inquiries/New`
     → (optionally **Skip the Inbox**) → also tick **Also apply to matching
     conversations** to backfill existing inquiries.
2. The other labels (`AI Draft Created`, `Error`, `AI Assisted Drafts`) are
   auto-created by the app on first run, so you don't need to make them by hand.

> Verify the filter works: submit a test inquiry through the website and confirm
> the notification lands under `Website Inquiries/New`.

---

## 2. Google Cloud project + OAuth client  🧑/👩

In <https://console.cloud.google.com> (recommended: signed in as the sister):

1. Create/select a project.
2. **APIs & Services → Library → Gmail API → Enable.**
3. **OAuth consent screen:**
   - User type **External**.
   - App name, support email, developer email (any valid values).
   - **Scopes:** add `https://www.googleapis.com/auth/gmail.modify` and
     `https://www.googleapis.com/auth/gmail.settings.basic` (the latter lets the
     app read the account signature to use as the draft footer).
   - **Test users:** add the **sister's Gmail address**.
   - **Publish to Production** (the "Publishing status" → Publish App button).
     This avoids the 7-day refresh-token expiry that applies in "Testing" mode.
     With only the `gmail.modify` *sensitive* scope and a single user, Google
     does **not** require full app verification for personal use.
4. **Credentials → Create Credentials → OAuth client ID → Application type
   "Desktop app"** → Create → **Download JSON**.
5. Save that file as `credentials.json` in the project root (it is gitignored).

---

## 3. One-time consent → token  👩 must approve

On a machine with the repo and `credentials.json`:

```powershell
pip install -r requirements.txt
python -m app.auth_bootstrap
```

- A browser opens. **Sign in as the sister** and approve access.
  (If you're doing this on her behalf, do it while signed into her Google
  account; or screen-share and have her click approve.)
- On success it writes `token.json` (for local runs) and prints:

  ```
  GMAIL_CLIENT_ID     = ...
  GMAIL_CLIENT_SECRET = ...
  GMAIL_REFRESH_TOKEN = ...
  ```

- If `GMAIL_REFRESH_TOKEN` is blank, revoke prior access at
  <https://myaccount.google.com/permissions> and re-run (a refresh token is only
  issued on first consent).

---

## 4. First real run (local, manual)  🧑

```powershell
# Ensure OPENAI_API_KEY is set (in .env or the environment).
python -m app.run --dry-run     # sanity: config + which secrets are present
python -m app.run               # one real pass: creates drafts, never sends
```

Check the sister's Gmail: drafts appear under **Drafts** (subject
`Re: your inquiry`, tagged `Website Inquiries/AI Assisted Drafts`) and the
inquiry moved from `Website Inquiries/New` to `Website Inquiries/AI Draft
Created`. Review/edit/send each draft manually.

> **Footer:** drafts use the account's **Gmail signature** as the footer (Gmail
> doesn't apply signatures to API-created drafts, so the app reads it via the
> `gmail.settings.basic` scope and appends it). `config/signature.txt` is only a
> fallback for when the signature can't be read. **If you added the settings
> scope after first consenting, re-run `python -m app.auth_bootstrap`** so
> `token.json` (and the `GMAIL_*` secrets) include the new scope — otherwise the
> footer silently falls back to the file.

> This is the moment the real Gmail API is exercised end-to-end for the first
> time. Do this before relying on the schedule.

**Draining a backlog:** each run processes at most `max_batch` (25) inquiries
from `New`. If `New` has more, just run `python -m app.run` again until it
reports `Found 0`.

**Iterating on draft quality:** after editing `config/business_profile.md` or
`config/prompt_template.md`, regenerate drafts for inquiries that previously
failed or that you want to redo:

```powershell
python -m app.run --retry-errors   # moves Error-label inquiries back to New, then runs
```

This is the tune-the-prompt loop: tweak the profile/prompt → `--retry-errors` →
review the new drafts in Gmail → repeat. (To redo inquiries that already drafted
successfully, move them from `AI Draft Created` back to `New` in Gmail first.)

---

## 5. GitHub Actions (scheduled)  🧑

1. Push this repo to GitHub (private recommended — see PII note below).
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**,
   add all four:
   - `OPENAI_API_KEY`
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN`
3. Repo → **Actions → Draft inquiry replies → Run workflow** (manual trigger) to
   test. Confirm a draft appears.
4. The cron in `.github/workflows/draft.yml` then runs it ~3×/day. Adjust the
   `cron:` line to change frequency/timezone (it's UTC).

---

## Notes / gotchas

- **PII:** `examples/2011-2013.txt` contain real submitter names/emails/phones,
  and a real `token.json`/`credentials.json` must never be committed (they're
  gitignored). Keep the GitHub repo **private**. Consider redacting `examples/`.
- **Token rotation:** if the schedule starts failing with auth errors, the
  refresh token was revoked/expired — re-run step 3 and update the
  `GMAIL_REFRESH_TOKEN` secret.
- **No-send guarantee:** the app only requests `gmail.modify` (read + label +
  create draft). It has no send permission, so it cannot email anyone.
- **Business voice:** fill in the `TODO:` items in `config/business_profile.md`
  (services, sign-off, call-to-action) for higher-quality drafts. Iterate with
  `python -m tools.local_test` before/after going live.
