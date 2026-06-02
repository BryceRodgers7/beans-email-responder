"""Local prompt-iteration harness — NO Gmail, NO drafts created.

Runs the SAME parser and drafter used in production against the example
inquiry files, writing results to out/ so you can rapidly tune the prompt.

Usage:
    python -m tools.local_test                 # all examples, with OpenAI
    python -m tools.local_test --no-llm        # parser only (free)
    python -m tools.local_test --one 2011.txt  # a single example
    python -m tools.local_test --prompt config/prompt_template.md --model gpt-4o

Outputs per example <name>.txt:
    out/<name>.parsed.json   what the parser extracted (+ flagged-missing fields)
    out/<name>.draft.txt     the generated email body (unless --no-llm)
    out/<name>.error.txt     written instead if parsing/drafting failed
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from app.config import load_settings
from app.drafter import DraftError, generate_draft
from app.logging_setup import get_logger
from app.parser import ParseError, parse

log = get_logger("local_test")

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
OUT = ROOT / "out"


def _select_files(one: str | None) -> list[Path]:
    if one:
        candidate = Path(one)
        if not candidate.is_absolute():
            candidate = EXAMPLES / one
        if not candidate.exists():
            raise SystemExit(f"Example not found: {candidate}")
        return [candidate]
    return sorted(EXAMPLES.glob("*.txt"))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    log.info("wrote %s", path.relative_to(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tools.local_test",
        description="Run parser + draft generation against example inquiries. No Gmail.",
    )
    ap.add_argument("--prompt", default=None, help="Alternate prompt template path.")
    ap.add_argument("--profile", default=None, help="Alternate business profile path.")
    ap.add_argument("--model", default=None, help="Override OpenAI model.")
    ap.add_argument("--no-llm", action="store_true", help="Parser only; skip OpenAI (free).")
    ap.add_argument("--one", default=None, help="Process a single example (name or path).")
    args = ap.parse_args(argv)

    settings = load_settings(require_secrets=False)
    if args.model:
        settings = dataclasses.replace(settings, openai_model=args.model)

    draft_kwargs = {}
    if args.prompt:
        draft_kwargs["prompt_path"] = Path(args.prompt)
    if args.profile:
        draft_kwargs["profile_path"] = Path(args.profile)

    OUT.mkdir(exist_ok=True)
    files = _select_files(args.one)
    log.info("Processing %d example(s); llm=%s model=%s", len(files), not args.no_llm, settings.openai_model)

    ok = errors = 0
    for path in files:
        stem = path.stem
        body = path.read_text(encoding="utf-8")
        try:
            fields = parse(body)
        except ParseError as error:
            _write(OUT / f"{stem}.error.txt", f"ParseError: {error}\n")
            errors += 1
            continue

        _write(
            OUT / f"{stem}.parsed.json",
            json.dumps(dataclasses.asdict(fields), indent=2, ensure_ascii=False),
        )

        if args.no_llm:
            ok += 1
            continue

        try:
            draft = generate_draft(fields, settings, **draft_kwargs)
        except DraftError as error:
            _write(OUT / f"{stem}.error.txt", f"DraftError: {error}\n")
            errors += 1
            continue

        _write(OUT / f"{stem}.draft.txt", draft + "\n")
        ok += 1

    log.info("Done. ok=%d errors=%d  (see out/)", ok, errors)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
