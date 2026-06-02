"""Configuration loading: non-secret settings from config/settings.toml,
secrets from environment variables (or a local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for 3.10
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (avoids an extra dependency). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    # OpenAI
    openai_api_key: str | None
    openai_model: str
    temperature: float
    max_retries: int
    # Gmail OAuth secrets (optional until Phase 3)
    gmail_client_id: str | None
    gmail_client_secret: str | None
    gmail_refresh_token: str | None
    # Labels
    label_new: str
    label_done: str
    label_error: str
    label_drafts: str
    max_batch: int
    # Draft subject
    draft_subject_prefix: str
    draft_subject: str


def load_settings(require_secrets: bool = False) -> Settings:
    _load_dotenv(ROOT / ".env")
    data = tomllib.loads((ROOT / "config" / "settings.toml").read_text(encoding="utf-8"))
    openai_cfg = data.get("openai", {})
    gmail_cfg = data.get("gmail", {})
    draft_cfg = data.get("draft", {})

    settings = Settings(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_model=os.environ.get("OPENAI_MODEL", openai_cfg.get("model", "gpt-4o-mini")),
        temperature=float(openai_cfg.get("temperature", 0.4)),
        max_retries=int(openai_cfg.get("max_retries", 1)),
        gmail_client_id=os.environ.get("GMAIL_CLIENT_ID"),
        gmail_client_secret=os.environ.get("GMAIL_CLIENT_SECRET"),
        gmail_refresh_token=os.environ.get("GMAIL_REFRESH_TOKEN"),
        label_new=gmail_cfg.get("label_new", "Website Inquiries/New"),
        label_done=gmail_cfg.get("label_done", "Website Inquiries/AI Draft Created"),
        label_error=gmail_cfg.get("label_error", "Website Inquiries/Error"),
        label_drafts=gmail_cfg.get("label_drafts", "Website Inquiries/AI Assisted Drafts"),
        max_batch=int(gmail_cfg.get("max_batch", 25)),
        draft_subject_prefix=draft_cfg.get("subject_prefix", "[AI Draft]"),
        draft_subject=draft_cfg.get("subject", "Re: your inquiry"),
    )

    if require_secrets:
        required = {
            "OPENAI_API_KEY": settings.openai_api_key,
            "GMAIL_CLIENT_ID": settings.gmail_client_id,
            "GMAIL_CLIENT_SECRET": settings.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": settings.gmail_refresh_token,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required secrets: {', '.join(missing)}")

    return settings
