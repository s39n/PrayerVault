"""Google sign-in and Google Drive backup.

Plain server-side OAuth 2.0 with httpx — no Google SDK, no JS SDK (keeps the
frontend dependency-free and the CSP intact). The id_token is verified via
Google's tokeninfo endpoint (checks signature, expiry) plus an audience check
here. Drive backups use the drive.file scope, so the app can only ever see
files it created itself.
"""
import datetime
import io
import json
import urllib.parse
import uuid
import zipfile
from pathlib import Path

import httpx
from itsdangerous import URLSafeTimedSerializer

from . import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
STATE_MAX_AGE = 600  # seconds an OAuth round trip may take

_state = URLSafeTimedSerializer(config.SESSION_SECRET, salt="prayervault-oauth-state")


def enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def redirect_uri() -> str:
    return f"{config.PUBLIC_URL}/api/auth/google/callback"


def auth_url(purpose: str, user: str = "") -> str:
    """Build the Google consent URL. purpose: "login" | "backup"."""
    if purpose == "login":
        scope, prompt = "openid email profile", "select_account"
    else:
        scope, prompt = "https://www.googleapis.com/auth/drive.file", "consent"
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": scope,
        "state": _state.dumps({"p": purpose, "u": user}),
        "prompt": prompt,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def read_state(state: str) -> dict:
    """Decode + verify the signed state. Raises on tamper/expiry."""
    return _state.loads(state, max_age=STATE_MAX_AGE)


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
        r.raise_for_status()
        return r.json()


async def verify_id_token(id_token: str) -> dict:
    """Validate via Google's tokeninfo endpoint; returns {sub, email, name, ...}."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(TOKENINFO_URL, params={"id_token": id_token})
        r.raise_for_status()
        info = r.json()
    if info.get("aud") != config.GOOGLE_CLIENT_ID:
        raise ValueError("id_token audience mismatch")
    if not info.get("sub"):
        raise ValueError("id_token missing subject")
    return info


def zip_vault(root: Path) -> bytes:
    """Zip every prayer note in a user's folder (markdown only, no dotfiles)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.glob("*.md")):
            z.writestr(p.name, p.read_text(encoding="utf-8"))
    return buf.getvalue()


DRIVE_LIST_URL = "https://www.googleapis.com/drive/v3/files"


async def list_backups(access_token: str) -> list[dict]:
    """List the PrayerVault backup zips this app created in the user's Drive,
    newest first. Works with the drive.file scope (app-created files only)."""
    params = {
        "q": ("name contains 'PrayerVault Backup' and "
              "mimeType='application/zip' and trashed=false"),
        "orderBy": "modifiedTime desc",
        "fields": "files(id,name,modifiedTime)",
        "pageSize": 25,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(DRIVE_LIST_URL, params=params,
                             headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.json().get("files", [])


async def download_drive_file(access_token: str, file_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(f"{DRIVE_LIST_URL}/{file_id}", params={"alt": "media"},
                             headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.content


async def upload_to_drive(access_token: str, data: bytes) -> None:
    """Upload the zip as a new file in the user's own Drive (multipart/related)."""
    name = f"PrayerVault Backup {datetime.date.today().isoformat()}.zip"
    boundary = uuid.uuid4().hex
    meta = json.dumps({"name": name, "mimeType": "application/zip"})
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{meta}\r\n"
        f"--{boundary}\r\nContent-Type: application/zip\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            DRIVE_UPLOAD_URL,
            content=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            })
        r.raise_for_status()
