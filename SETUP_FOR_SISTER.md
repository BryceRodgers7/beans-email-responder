# Setup: run the email drafter on your own GitHub account

You already have the code on your machine. This gets it into a new repo under
**your** GitHub account, with the scheduled job running on **your** secrets and
Actions minutes. Nothing secret ever gets committed — keys live in GitHub's
encrypted "Actions secrets," not in the code.

Estimated time: ~15 min (most of it is the one-time Gmail consent).

---

## 1. Create an empty repo on GitHub

1. Go to <https://github.com/new>.
2. Name it (e.g. `email-drafter`). **Private** is recommended.
3. Do **not** add a README, .gitignore, or license (keeps it empty so your
   existing code pushes cleanly).
4. Click **Create repository**. Leave the page open — you'll need the URL.

## 2. Push your local code to it

Open a terminal in the project folder (the one containing `app/` and
`requirements.txt`) and run:

```bash
git init                     # skip if it's already a git repo
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/email-drafter.git
git push -u origin main
```

> If `git remote add origin` says it already exists, run
> `git remote set-url origin https://github.com/<your-username>/email-drafter.git`
> instead.

The scheduled workflow only runs from the **`main`** branch, so make sure that's
the branch you pushed (the commands above handle that).

## 3. Generate your Gmail credentials (one time)

The bot needs permission to read inquiries and create drafts in **your** Gmail.

1. In Google Cloud Console, create/download an **OAuth "Desktop app" client** and
   save it as `credentials.json` in the project root. (See `DESIGN.md` section 4
   for the click-path.)
2. Run the bootstrap locally:

   ```bash
   pip install -r requirements.txt
   python -m app.auth_bootstrap
   ```

3. A browser opens — sign in with the Gmail account the bot should work in and
   approve access.
4. The script prints three values. **Copy them somewhere temporary** — you'll
   paste them into GitHub next:

   ```
   GMAIL_CLIENT_ID     = ...
   GMAIL_CLIENT_SECRET = ...
   GMAIL_REFRESH_TOKEN = ...
   ```

   > If it warns "No refresh_token returned," revoke the app at
   > <https://myaccount.google.com/permissions> and re-run — a refresh token is
   > only issued on the first consent.

You'll also need your **OpenAI API key** from
<https://platform.openai.com/api-keys> (this bills to your OpenAI account).

## 4. Add the 4 secrets to the repo

In your repo on GitHub: **Settings → Secrets and variables → Actions →
New repository secret**. Add each of these (name must match exactly):

| Secret name           | Value                                |
| --------------------- | ------------------------------------ |
| `OPENAI_API_KEY`      | your OpenAI key (`sk-...`)           |
| `GMAIL_CLIENT_ID`     | from step 3                          |
| `GMAIL_CLIENT_SECRET` | from step 3                          |
| `GMAIL_REFRESH_TOKEN` | from step 3                          |

After saving, the page lists 4 secrets (values stay hidden — that's expected).

## 5. Enable Actions

1. Go to the **Actions** tab.
2. If prompted, click **"I understand my workflows, go ahead and enable them."**
3. You should see the **"Draft inquiry replies"** workflow listed.

## 6. Confirm it works

1. Actions tab → **Draft inquiry replies** → **Run workflow** button (manual
   trigger) → **Run workflow**.
2. Open the run and watch the **Run drafter** step. Success looks like a log line
   such as `Run complete: drafted=N errored=N` and a green check.
3. The schedule (a few times per day) will now run automatically — no further
   action needed.

---

## Good to know

- **Free tip:** OpenAI keys only work if your OpenAI account has billing/credit.
  If the run errors on the OpenAI call, that's usually why.
- **Scheduled jobs auto-pause after 60 days of no repo activity.** GitHub emails
  you to re-enable. A tiny commit now and then keeps it alive.
- **Never commit `credentials.json`, `token.json`, or `.env`** — they're for your
  machine only. Check they're listed in `.gitignore` before pushing.
