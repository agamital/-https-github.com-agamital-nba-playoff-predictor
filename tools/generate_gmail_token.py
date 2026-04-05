"""
One-time script to obtain a Gmail API refresh token via OAuth2.

Run this ONCE on your local machine (it opens a browser for consent):
    pip install google-auth-oauthlib
    python tools/generate_gmail_token.py

Then copy the printed GMAIL_REFRESH_TOKEN value into Railway env vars.
You never need to run this again — the token doesn't expire unless
explicitly revoked in your Google account.

Prerequisites:
  1. Google Cloud Console → APIs & Services → Enable "Gmail API"
  2. OAuth consent screen → add your Gmail as a test user
  3. Credentials → Create OAuth 2.0 Client ID (Desktop application)
  4. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET below (or as env vars)
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID     = os.getenv("GMAIL_CLIENT_ID",     "1009196888634-9lo42d19vbrt2lo9q86npq4ul1fvcd19.apps.googleusercontent.com")
CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")   # set via env var, never hardcode

if not CLIENT_SECRET:
    raise SystemExit(
        "ERROR: set GMAIL_CLIENT_SECRET env var before running this script.\n"
        "  Windows CMD:   set GMAIL_CLIENT_SECRET=your_secret && python tools/generate_gmail_token.py\n"
        "  bash/zsh:      GMAIL_CLIENT_SECRET=your_secret python tools/generate_gmail_token.py"
    )

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

client_config = {
    "installed": {
        "client_id":                CLIENT_ID,
        "client_secret":            CLIENT_SECRET,
        "auth_uri":                 "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                "https://oauth2.googleapis.com/token",
        "redirect_uris":            ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=0)

print("\n" + "=" * 60)
print("Add these to Railway → Settings → Variables:")
print("=" * 60)
print(f"GMAIL_CLIENT_ID      = {CLIENT_ID}")
print(f"GMAIL_CLIENT_SECRET  = {CLIENT_SECRET}")
print(f"GMAIL_REFRESH_TOKEN  = {creds.refresh_token}")
print(f"GMAIL_SENDER         = nbaplayoffpredictor2000@gmail.com")
print("=" * 60)
print("\nDone. You can close this terminal.")
