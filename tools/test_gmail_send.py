"""
Temporary test script — verify Gmail API email sending end-to-end.
Delete this file once confirmed working.
"""

import os, sys, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText

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
    sys.exit("ERROR: missing env vars: " + ", ".join(missing))

print("=" * 55)
print("Gmail API send test")
print("=" * 55)
print("  From:          ", SENDER)
print("  To:            ", TO)
print("  Client ID:     ", CLIENT_ID[:20] + "...")
print("  Refresh token: ", REFRESH_TOKEN[:10] + "...")
print()

# Stage 1 — import + build service
print("Stage 1 - building OAuth2 credentials...")
try:
    from google.oauth2.credentials  import Credentials
    from googleapiclient.discovery  import build
    from googleapiclient.errors     import HttpError
    from google.auth.exceptions     import RefreshError
except ImportError as e:
    sys.exit("ImportError: " + str(e) +
             "\nInstall: pip install google-auth google-auth-oauthlib "
             "google-auth-httplib2 google-api-python-client")

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
    print("  PASS - service built")
except RefreshError as e:
    sys.exit("  FAIL - token refresh error (token revoked?): " + str(e))
except Exception as e:
    sys.exit("  FAIL - " + type(e).__name__ + ": " + str(e))

# Stage 2 - compose
print("\nStage 2 - composing message...")
msg = MIMEMultipart("alternative")
msg["Subject"] = "[TEST] Gmail API verification - NBA Playoff Predictor"
msg["From"]    = "NBA Playoff Predictor <" + SENDER + ">"
msg["To"]      = TO
msg.attach(MIMEText(
    "<h2>Gmail API test passed!</h2>"
    "<p>OAuth2 Gmail integration is working correctly.</p>",
    "html", "utf-8"
))
raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
print("  PASS - message encoded (" + str(len(raw_b64)) + " bytes base64)")

# Stage 3 - send
print("\nStage 3 - sending via Gmail API...")
try:
    result = (
        service.users()
               .messages()
               .send(userId="me", body={"raw": raw_b64})
               .execute()
    )
    print("  PASS - message id: " + str(result.get("id")))
    print()
    print("=" * 55)
    print("SUCCESS - check " + TO + " for the test email.")
    print("=" * 55)
except HttpError as e:
    status = e.resp.status
    print("  FAIL - Gmail API HTTP " + str(status) + ": " + str(e.error_details))
    if status == 429:
        print("  --> Quota exceeded, wait and retry.")
    elif status in (401, 403):
        print("  --> Auth/scope error.")
        print("      1. Enable Gmail API in Google Cloud Console")
        print("      2. Ensure oauth scope includes gmail.send")
        print("      3. Re-run generate_gmail_token.py if token is stale")
    sys.exit(1)
except Exception as e:
    print("  FAIL - " + type(e).__name__ + ": " + str(e))
    sys.exit(1)
