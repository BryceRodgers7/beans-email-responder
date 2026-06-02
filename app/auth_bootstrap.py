"""One-time OAuth setup: `python -m app.auth_bootstrap`.

Opens a browser for consent, writes token.json for local runs, and prints the
three values to copy into GitHub Actions secrets for the scheduled job.

Prerequisite: download the OAuth *Desktop app* client as credentials.json into
the project root (see DESIGN.md section 4).
"""
from __future__ import annotations

from .gmail_client import CREDENTIALS_PATH, SCOPES, TOKEN_PATH


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS_PATH.exists():
        print(f"Missing {CREDENTIALS_PATH}. Download the OAuth Desktop-app client first.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nSaved {TOKEN_PATH} (used for local runs).\n")

    print("Add these as GitHub Actions repository secrets for the scheduled run:")
    print(f"  GMAIL_CLIENT_ID     = {creds.client_id}")
    print(f"  GMAIL_CLIENT_SECRET = {creds.client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN = {creds.refresh_token}")
    if not creds.refresh_token:
        print(
            "\n⚠️  No refresh_token returned. Revoke prior access at "
            "https://myaccount.google.com/permissions and re-run, or ensure the "
            "consent prompt was shown (a refresh token is only issued on first consent)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
