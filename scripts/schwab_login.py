"""One-time Schwab OAuth link.

Opens a browser to log into Schwab and authorize the app, then saves the
token to data/schwab_token.json. Re-run only if the token is deleted or
refresh fails (Schwab refresh tokens expire every ~7 days; schwab-py
refreshes access tokens automatically, but the 7-day re-login is manual).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DATA_DIR, TOKEN_FILE, SchwabCredentials  # noqa: E402


def main() -> None:
    creds = SchwabCredentials()
    if not creds.configured:
        sys.exit("Fill in SCHWAB_APP_KEY / SCHWAB_APP_SECRET in .env first "
                 "(copy .env.example to .env).")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    from schwab.auth import client_from_login_flow
    print("A browser window will open. Log into Schwab and click Allow.")
    print(f"Callback URL configured: {creds.callback_url}")
    client_from_login_flow(
        api_key=creds.app_key,
        app_secret=creds.app_secret,
        callback_url=creds.callback_url,
        token_path=str(TOKEN_FILE),
    )
    print(f"Token saved to {TOKEN_FILE}. You can now run: "
          ".venv/bin/python run.py --feed schwab")


if __name__ == "__main__":
    main()
