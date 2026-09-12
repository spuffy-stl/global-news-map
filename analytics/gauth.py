"""Mint Google OAuth access tokens from this VM's service account key.

Uses the gcloud credentials.db service-account key for
muse-agent@muse-spuffy.iam.gserviceaccount.com. No keys to manage.
"""
import json
import sqlite3

from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

ACCOUNT = "muse-agent@muse-spuffy.iam.gserviceaccount.com"
CRED_DB = "/home/hatch/.config/gcloud/credentials.db"


def get_token(scopes):
    """Return a fresh access token string for the given scopes."""
    db = sqlite3.connect(CRED_DB)
    row = db.execute(
        "SELECT value FROM credentials WHERE account_id = ?", (ACCOUNT,)
    ).fetchone()
    if not row:
        raise RuntimeError("no gcloud credential for " + ACCOUNT)
    info = json.loads(row[0])
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    creds.refresh(Request())
    return creds.token
