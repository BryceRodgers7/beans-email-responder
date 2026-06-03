# Gmail setup: labels + the filter that feeds the app

Do this **in the Gmail account the bot will operate in** (the one that receives
the website contact-form notifications). It's a one-time, ~5-minute setup in the
Gmail web UI. You'll need to be signed into that account.

## What the app expects

The app never scans the inbox. It only looks at messages carrying one specific
label, **`Website Inquiries/New`**, drafts a reply, then moves each message to
another label. The four labels (note the `/` — they're nested under a parent
"Website Inquiries"):

| Label | Role |
| ----- | ---- |
| `Website Inquiries/New` | **Input.** A Gmail filter puts new inquiries here; the app picks them up. |
| `Website Inquiries/AI Draft Created` | Where the app moves an inquiry after drafting a reply. |
| `Website Inquiries/Error` | Where the app moves an inquiry it couldn't parse/draft. |
| `Website Inquiries/AI Assisted Drafts` | Tag the app puts on the draft it creates. |

> **Note:** the app auto-creates any of these four labels that don't exist (on
> its first run). So strictly you only *need* to create `Website Inquiries/New`
> manually — and even that gets created for you in Step 2 below while making the
> filter. Creating them by hand just lets you see/organize them sooner.

---

## Step 1 — (optional) Create the labels by hand

Skip this if you'd rather let Step 2 / the app create them.

1. Gmail → left sidebar → scroll down → **+ Create new label** (or Settings ⚙ →
   **See all settings** → **Labels** → **Create new label**).
2. Create a label named exactly **`Website Inquiries`**.
3. Create **`New`** and, in the dialog, check **"Nest label under"** →
   `Website Inquiries`. Repeat for **`AI Draft Created`**, **`Error`**, and
   **`AI Assisted Drafts`**.

The names must match exactly (capitalization and spaces included), because they
must match `config/settings.toml`.

## Step 2 — Create the filter that labels incoming inquiries

This is the piece that actually feeds the app. The contact-form notifications
arrive **From** `noreply@thementalgain.com` with a **Subject** like
`New Form Entry #2011 for contact me`.

1. Gmail → Settings ⚙ → **See all settings** → **Filters and Blocked Addresses**
   → **Create a new filter**.
2. Fill in the match criteria. Use the sender (most reliable):
   - **From:** `noreply@thementalgain.com`
   - *(optional, to be stricter)* **Subject:** `New Form Entry`
3. Click **Create filter**.
4. On the next screen, check:
   - ☑ **Apply the label:** choose `Website Inquiries/New`
     (or **New label…** to create it right here if you skipped Step 1).
   - ☐ *(optional)* **Skip the Inbox (Archive it)** — keeps the business inbox
     tidy; the app doesn't care either way.
   - ☑ *(recommended for the first run)* **Also apply filter to matching
     conversations** — this back-labels inquiries already sitting in the mailbox
     so the app processes the existing backlog, not just future mail.
5. Click **Create filter**.

## Step 3 — Verify

- Send a test submission through the website contact form (or wait for a real
  one). Within a moment it should appear under **`Website Inquiries/New`** in the
  left sidebar.
- If you ran "Also apply to matching conversations," check that past inquiries
  are now under `Website Inquiries/New`.
- Once the GitHub Action runs (see `SETUP_FOR_SISTER.md`), each message under
  `New` should move to `AI Draft Created`, a draft reply should appear in Gmail's
  **Drafts** with subject `[AI Draft] Re: your inquiry`, and that draft is tagged
  `Website Inquiries/AI Assisted Drafts`.

---

## Troubleshooting

- **App logs `Found 0 inquiry message(s)`** → nothing is under `Website
  Inquiries/New`. The filter isn't matching, or the label name doesn't match
  `config/settings.toml` exactly. Re-check the From address and label spelling.
- **The notification address is different** in her setup → replace
  `noreply@thementalgain.com` in Step 2 with whatever the real contact-form
  notifications come **From**. Open one such email → "Show original" / the From
  header to confirm. The subject pattern can change too; matching on **From** is
  the safest single criterion.
- **Drafts go to the wrong recipient** → the app reads the client's address from
  the form's `*Email*` field inside the body, not the email's From/To headers, so
  the notification format must contain that field (it does for this form).
