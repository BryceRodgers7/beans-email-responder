# Example inquiries

These `*.txt` files are saved copies of real "The Mental Gain" contact-form
notification emails. They are the inputs for:

- `tests/test_parser.py` (validates the parser against the real format), and
- the local prompt-iteration harness `python -m tools.local_test` (Phase 4).

## Format

Each notification has email headers, a preamble line, then numbered
asterisk-wrapped field markers with the value on the following line(s):

```
   1. *Name*
   <value>
   2. *Email*
   <value>
   3. *Phone*
   <value>
   4. *Textarea*

   <free-text message>
```

The parser ignores everything before the first marker (headers + preamble) and
reads the client email from the `*Email*` field only.

## ⚠️ PII / privacy

The sample `*.txt` files contain **real names, emails, and phone numbers**, so
`examples/*.txt` is **gitignored** (see `.gitignore`). Only this README is
tracked. The files live locally for development but are never committed.

This means a fresh checkout has no `*.txt` here. That's fine:
- the parser tests that read these files **skip** when they're absent, and
- `python -m tools.local_test` simply processes whatever `*.txt` you add locally.

To add samples: forward a real notification, paste the plain-text body into a
new `*.txt` here (optionally redacted). It stays local unless you force-add it.
