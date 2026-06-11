# Example inquiries

These `*.txt` files are saved copies of real "The Mental Gain" contact-form
notification emails. They are the inputs for:

- `tests/test_parser.py` (validates the parser against the real format), and
- the local prompt-iteration harness `python -m tools.local_test` (Phase 4).

## Format

The live notification Gmail delivers is **HTML**: a preamble line then an
ordered list where each field is an `<li>` with a bold label and the value
following. The form emits **two Name rows** — the first is the parent/guardian,
the second is the child/athlete:

```
<li><b>Name</b><br />Pat Parent</li>
<li><b>Name</b><br />Kim Kiddo</li>
<li><b>Email</b><br /><a href="mailto:pat@x.com">pat@x.com</a></li>
<li><b>Phone</b><br />(555) 010-0100</li>
<li><b>Textarea</b><p>free-text message</p></li>
```

The parser also still handles an older plain-text/forwarded layout where each
field is a numbered, asterisk-wrapped marker on its own line with the value on
the following line(s):

```
   1. *Name*
   <parent name>
   2. *Name*
   <child name>
   3. *Email*
   <value>
   4. *Phone*
   <value>
   5. *Textarea*

   <free-text message>
```

In both layouts the parser ignores everything before the first field (headers +
preamble), splits the two Name fields into parent (`name`) and child
(`child_name`) by order, and reads the client email from the `Email` field only.

## ⚠️ PII / privacy

The sample files contain **real names, emails, and phone numbers**, so both
`examples/*.txt` and `examples/*.eml` are **gitignored** (see `.gitignore`).
Only this README is tracked. The files live locally for development but are
never committed.

This means a fresh checkout has no samples here. That's fine:
- the parser tests that read these files **skip** when they're absent, and
- `python -m tools.local_test` simply processes whatever samples you add locally.

To add samples: save a real notification as a `*.eml` here, or paste its body
into a new `*.txt` (optionally redacted). It stays local unless you force-add it.
