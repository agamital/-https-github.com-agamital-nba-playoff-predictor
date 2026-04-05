"""
Temporary test script — verify Gmail API email sending end-to-end.

Usage (set your real values):
    set GMAIL_CLIENT_ID=1009196888634-9lo42d19vbrt2lo9q86npq4ul1fvcd19.apps.googleusercontent.com
    set GMAIL_CLIENT_SECRET=your_secret
    set GMAIL_REFRESH_TOKEN=your_refresh_token
    set GMAIL_TO=agamital@gmail.com
    python tools/test_gmail_send.py

Delete this file once confirmed working.
"""

import os, sys, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText

# ── Read credentials from environment ──────────────────────────────────────
CLIENT_ID     = os.environ.get("GMAIL_CLIENT_ID",
                "1009196888634-9lo42d19vbrt2lo9q86npq4ul1fvcd19.apps.googleusercontent.com")
CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")
SENDER        = os.environ.get("GMAIL_SENDER", "nbaplayoffpredictor2000@gmail.com")
TO            = os.environ.get("GMAIL_TO", "agamital@gmail.com")

missing = [k for k, v in [
    ("GMAIL_CLIENT_SECRET", CLIENT_SECRET),
    ("GMAIL_REFRESH_TOKEN",  REFRESH_TOKEN),
] if not v]

if missing:
    sys.exit(f"ERROR: missing env vars: {', '.join(missing)}\n"
             f"Set them before running this script.")

print("=" * 55)
print("Gmail API send test")
print("=" * 55)
print(f"  From:           {SENDER}")
print(f"  To:             {TO}")
print(f"  Client ID:      {CLIENT_ID[:20]}...")
print(f"  Refresh token:  {REFRESH_TOKEN[:10]}...")
print()

# ── Stage 1: build credentials ─────────────────────────────────────────────
print("Stage 1 — building OAuth2 credentials...")
try:
    from google.oauth2.credentials  import Credentials
    from googleapiclient.discovery  import build
    from googleapiclient.errors     import HttpError
    from google.auth.exceptions     import RefreshError
except ImportError as e:
    sys.exit(
        f"ImportError: {e}\n"
        f"Install deps:  pip install google-auth google-auth-oauthlib "
        f"google-auth-httplib2 google-api-python-client"
    )

try:
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    service = build("gmail", "v1", credentials=creds)
    print("  ✓ service built\n")
except RefreshError as e:
    sys.exit(f"  ✗ Token refresh failed — token may be revoked.\n    Detail: {e}")
except Exception as e:
    sys.exit(f"  ✗ Failed to build service: {type(e).__name__}: {e}")

# ── Stage 2: compose message ────────────────────────────────────────────────
print("Stage 2 — composing message...")
msg = MIMEMultipart("alternative")
msg["Subject"] = "[TEST] Gmail API verification — NBA Playoff Predictor"
msg["From"]    = f"NBA Playoff Predictor <{SENDER}>"
msg["To"]      = TO
msg.attach(MIMEText(
    "<h2>&#127936; Gmail API test passed!</h2>"
    "<p>If you see this, the OAuth2 Gmail integration is working correctly on Railway.</p>",
    "html", "utf-8"
))
raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
print("  ✓ message encoded\n")

# ── Stage 3: send ───────────────────────────────────────────────────────────
print("Stage 3 — sending via Gmail API...")
try:
    result = (
        service.users()
               .messages()
               .send(userId="me", body={"raw": raw_b64})
               .execute()
    )
    print(f"  ✓ SENT — Gmail message id: {result.get('id')}\n")
    print("=" * 55)
    print(f"SUCCESS — check {TO} for the test email.")
    print("=" * 55)
except HttpError as e:
    status = e.resp.status
    print(f"  ✗ Gmail API error HTTP {status}: {e.error_details}")
    if status == 429:
        print("    → Quota exceeded. Wait a few minutes and retry.")
    elif status in (401, 403):
        print("    → Auth/scope error. Verify:")
        print("      1. Gmail API is enabled in Google Cloud Console")
        print("      2. OAuth consent screen has 'gmail.send' scope")
        print("      3. Refresh token was generated with the correct account")
    sys.exit(1)
except Exception as e:
    print(f"  ✗ Unexpected error: {type(e).__name__}: {e}")
    sys.exit(1)
