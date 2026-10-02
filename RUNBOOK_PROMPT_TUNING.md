# Runbook: testing the drafter & tuning the wording

For **Sabrina**, on your own computer, with the code already set up and pointed at
the Mental Gain inbox.

This is the loop for reading what the AI writes, changing how it writes, and
running it again on the same test emails until you like the result.

> ### The golden rule
> **This app never sends email.** It only creates **drafts** in Gmail, which sit
> there until you open, edit, and send them yourself. Nothing in this runbook can
> email a client.

---

## Cheat sheet

| I want to… | Command |
| --- | --- |
| Check nothing is broken | `python -m pytest -q` |
| Check my settings/keys are found | `python -m app.run --dry-run` |
| **Draft replies for everything under `New`** | `python -m app.run` |
| **Re-draft the same test emails after a tweak** | `python -m app.run --reset-drafted` |
| Re-try inquiries that **failed** | `python -m app.run --retry-errors` |
| Preview offline, without touching Gmail | `python -m tools.local_test` |

Run these in a terminal **in the project folder** (the one containing the `app`
folder and `requirements.txt`).

### The four labels

| Label | Meaning |
| --- | --- |
| `Website Inquiries/New` | Waiting to be drafted. **The app only reads this one.** |
| `Website Inquiries/AI Draft Created` | Done — a draft was made for it |
| `Website Inquiries/Error` | Something went wrong; no draft |
| `Website Inquiries/AI Assisted Drafts` | On the **drafts themselves**, so you can find them |

---

## 1. One-time install

```powershell
pip install -r requirements.txt
pip install pytest
```

`pytest` is only needed for the self-check in step 2; it isn't part of the app.

Then confirm the app can find everything:

```powershell
python -m app.run --dry-run
```

This calls **nothing** — no Gmail, no OpenAI. It just reports what it found:

```
Dry run: configuration loaded successfully.
Model = gpt-4o-mini | temperature = 0.4
Labels: new='Website Inquiries/New' ... max_batch=25
Secrets present -> OPENAI_API_KEY=True GMAIL_CLIENT_ID=False GMAIL_REFRESH_TOKEN=False
Template body present=True | 2 attachment(s): ...
```

⚠️ **`GMAIL_CLIENT_ID=False` is normal on your machine and not a problem.** Those
three `GMAIL_*` lines are only used by the automated cloud version. On your
computer the app uses the `token.json` file instead. What matters here is
`OPENAI_API_KEY=True` and that `token.json` exists in the project folder.

## 2. Self-check

```powershell
python -m pytest -q
```

Expect `60 passed`. If you see failures, stop and send Bryce the output — don't
keep going, since something is genuinely broken.

---

# 3. The tuning loop ⭐

Your test emails are already in the inbox. One round is: **run → read → tweak →
reset → run again.**

## 3a. Run it

Make sure your test emails carry the `Website Inquiries/New` label, then:

```OPEN powershell APPLICATION 
type  cd C:\git\beans-email-responder\
then type:  python -m app.run     then push enter
```

You'll see one block per inquiry and a summary line:

```
=== Found 5 inquiry message(s) under 'Website Inquiries/New' ===
[1/5] Inquiry: 'Contact me #2047 for contact me'
[1/5]   -> drafted reply to someone@gmail.com
...
=== Run complete: drafted=5 errored=0 ===
```

At most **25** per run (a safety cap). If you have more, just run it again.

## 3b. Read the drafts

In Gmail, click the **`Website Inquiries/AI Assisted Drafts`** label — or search:

```
label:"Website Inquiries/AI Assisted Drafts"
```

If that label looks empty, check the plain **Drafts** folder; labeling a draft is
a nice-to-have step that can occasionally fail without stopping the run.

Read the **first paragraph** of each. That's the only part the AI wrote —
everything after it (your services block, booking link, options, consent info,
signature, and the two PDFs) is fixed boilerplate that's identical on every draft
and doesn't change when you tune the prompt.

Ask yourself: does it sound like me? Is it accurate? Does it acknowledge the
right thing? Does it overclaim?

## 3c. Tweak the wording

Edit one of the files in **section 4** below, save it. No restart needed — the
next run reads the file fresh.

Change **one thing at a time**. If you rewrite three rules at once and the output
gets worse, you won't know which one did it.

## 3d. Delete the previous round's drafts

**Every run creates a brand-new draft — it never updates the old one.** And each
round's draft has the same subject as the last (`<Player Name> Mental
Performance`), so after three rounds you'd have three identical-looking drafts
per test email and no way to tell which is current.

So select the drafts you just read and delete them (the 🗑 icon). Then the
`AI Assisted Drafts` label always shows exactly the round you last ran.

Do this **before** step 3e, which creates the next round.

## 3e. Reset and run again — one command

```powershell
python -m app.run --reset-drafted
```

`--reset-drafted` moves your already-drafted test emails from
`AI Draft Created` back to `New` and then does a normal pass — so it re-drafts the
same test cases with your updated wording. No Gmail label-dragging needed.

You'll see the reset happen first, then the run:

```
Re-queued 5 inquiry message(s): 'Website Inquiries/AI Draft Created' -> 'Website Inquiries/New' (existing drafts left in place)
=== Found 5 inquiry message(s) under 'Website Inquiries/New' ===
...
=== Run complete: drafted=5 errored=0 ===
```

Then go back to 3b and read the new drafts. Repeat until you're happy. Each round
costs one small OpenAI call per test email — fractions of a cent. Your real spend
is at <https://platform.openai.com/usage>.

### Things to know about `--reset-drafted`

- **It resets every inquiry under `AI Draft Created`, not just today's test
  cases.** That's fine now, while that label holds only test emails. But once
  real inquiries have been answered and are sitting under it, this flag would
  re-draft those too. **Once you go live, stop using it** and re-apply the `New`
  label by hand to just the messages you want (see below).
- It's limited to **25** inquiries per invocation (the same cap as a normal run),
  newest first — so a mistaken run can't stampede through your whole history.
- It does **not** delete the old drafts, which is why 3d comes first.
- **`--retry-errors` is a different thing.** That one only rescues inquiries under
  the **`Error`** label — it does nothing for test emails that drafted
  successfully. Use `--reset-drafted` for those.

### Doing the reset by hand instead

If you ever want to re-draft only *some* messages (or you're live and avoiding the
flag), do it in Gmail:

1. Search `label:"Website Inquiries/AI Draft Created"` (or click that label).
2. Select just the messages you want.
3. Click the **label icon** (🏷) in the toolbar → tick **`Website Inquiries/New`**
   → **Apply**.
4. Run `python -m app.run` (no flag).

You do **not** have to remove the `AI Draft Created` label — the app clears it on
the next pass. Removing it is just tidiness.

> ### One trap when comparing rounds
> The model is set to `temperature = 0.4`, which means **the same prompt produces
> slightly different wording every time.** So if round 2 reads differently from
> round 1, that isn't proof your edit did anything — some of it is just natural
> variation.
>
> To compare fairly while tuning, open `config/settings.toml` and change the
> `temperature` line in the `[openai]` section from `0.4` to `0`:
>
> ```toml
> [openai]
> model = "gpt-4o-mini"
> temperature = 0
> ```
>
> Now the same inquiry + same prompt gives the same answer every time, so any
> difference you see is genuinely your edit. **Set it back to `0.4` when you're
> done** — a little variety keeps real replies from sounding copy-pasted.

---

## 4. Which file do I edit?

Three files, three different jobs. **Editing these does not require any code
knowledge** — they're plain writing.

| File | What it controls | Edit it when… |
| --- | --- | --- |
| `config/prompt_template.md` | **How** the AI writes the opening paragraph — tone, the required first/last sentences, what it must never say | The paragraph's *style* is off |
| `config/business_profile.md` | **What** the AI is allowed to know as fact about TMG | It says something inaccurate, or you want it to know a new fact |
| `config/template_body.txt` **and** `.html` | The fixed block after the paragraph — services, $90 sessions, booking link, options A/B, consent | Prices, links, or program details change |

Two cautions:

- `template_body.txt` and `template_body.html` must be **edited together** and say
  the same thing. `.txt` is the plain-text version, `.html` is the formatted one
  most people will see. If they drift apart, different recipients see different
  information.
- The AI treats **everything** in `business_profile.md` as fact, including
  examples. If you write "e.g. a free 20-minute call," it will offer clients a
  free 20-minute call. Only put true things in that file.

## 5. Blank form fields

Already handled — no code change needed, and worth knowing so the output doesn't
surprise you:

- **No email address** → no draft. The app can't address a reply, so it labels the
  inquiry `Website Inquiries/Error` and moves on. This is the only field that
  stops a draft.
- **Any other field blank** → a draft is still written. The AI is told which
  fields are missing and instructed to write around the gap without guessing and
  without mentioning that anything was blank.
- **A blank or meaningless message** ("test", "n/a") → the AI skips the specific
  acknowledgment rather than inventing a concern, and writes a short, warm note
  inviting them to share more. That behavior lives under `## Missing fields` in
  `config/prompt_template.md` if you want to reword it.

## 6. Optional: preview offline, without touching Gmail

Useful when you want to try a bold rewrite without creating real drafts or
resetting labels. It reads saved copies of inquiries from the `examples` folder
instead of your inbox.

To save an inquiry there: open it in Gmail → **⋮** menu → **Show original** →
**Download Original** → move the `.eml` file into `examples` and name it after the
inquiry number, e.g. `2051.eml`. These files stay only on your computer.

```powershell
python -m tools.local_test --no-llm            # free: what the app READ from each inquiry
python -m tools.local_test                     # what the AI WROTE
python -m tools.local_test --one 2047.eml      # just one
python -m tools.local_test --model gpt-4o      # try a smarter, pricier model
```

Results land in the `out` folder: `<number>.parsed.json` (what was extracted) and
`<number>.draft.txt` (the opening paragraph). Nothing is created in Gmail and no
labels move, so there's no reset step.

To trial a whole alternate prompt without disturbing your working one, copy
`config/prompt_template.md` to `config/prompt_experiment.md`, edit the copy, then:

```powershell
python -m tools.local_test --prompt config/prompt_experiment.md
```

In `<number>.parsed.json`, `"extraction_method": "parser"` is the normal free
path. `"llm"` means the email looked unfamiliar and the AI had to interpret it —
occasional is fine, but if *everything* says `llm`, the website form changed and
Bryce should look.

## 7. The log

Every processed inquiry appends one line to `logs/process_log.tsv` — timestamp,
drafted-or-errored, whether the parser or the AI read it, subject, email address,
and any error. Open it in Excel if a draft ever goes missing and you want to know
what happened. It keeps growing across runs, so during tuning the same test email
will appear once per round — that's expected.

## 8. If something goes wrong

| Symptom | What it means |
| --- | --- |
| `Found 0 inquiry message(s)` | Nothing is labeled `New`. Re-run with `--reset-drafted` (step 3e). |
| Ran again, but no new drafts appeared | Same thing — you ran plain `python -m app.run` after a round, so there was nothing under `New`. |
| Several near-identical drafts per inquiry | Leftovers from earlier rounds — step 3d. |
| An inquiry landed under `Error` | Check `logs/process_log.tsv` for the reason. Usually no usable email address in the form. |
| `Could not load Gmail credentials` | `token.json` is missing or expired → `python -m app.auth_bootstrap` |
| `OPENAI_API_KEY is not set` | The key isn't in `.env`. `local_test --no-llm` still works without it. |
| Draft mentions something untrue | It came from `business_profile.md` or `template_body.*`. Fix the file, not the AI. |
| Draft claims "I see this a lot" for an unrelated concern | That reassurance is meant to be limited to confidence / bouncing back from mistakes. Tighten the rule in `prompt_template.md`. |
| Output changed but I didn't edit anything | Normal at `temperature = 0.4` — see the trap box in step 3e. |
| A wall of red text ending in `FileNotFoundError` | A file path you typed is wrong — usually after `--prompt` or `--one`. Check the spelling. |
| `pytest` reports failures | Stop; send Bryce the output. |

The only command that writes to Gmail is `python -m app.run`, and even that only
ever creates drafts — so when in doubt, re-run and read the output.
