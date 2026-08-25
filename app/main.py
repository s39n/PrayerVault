import asyncio
import datetime
import logging
import zipfile
from pathlib import Path

from fastapi import (BackgroundTasks, Depends, FastAPI, File, HTTPException,
                     Request, Response, UploadFile)
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from pydantic import BaseModel, Field

from . import (auth, config, db, embeddings, families, google_auth, notes, notify,
               notifications, ollama_client, settings, stt, users)
from .church_api import router as church_router

log = logging.getLogger("prayervault")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PrayerVault", docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent / "static"

# Multi-church prayer-sharing API (accounts, churches, elder flow). Distinct route
# prefixes from the legacy single-user vault routes below.
app.include_router(church_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'"
    )
    return resp


# ---------- Auth ----------

class LoginBody(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


@app.post("/api/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    auth.check_rate_limit(ip)
    if not auth.verify_credentials(body.username, body.password):
        auth.record_failure(ip)
        raise HTTPException(401, "Invalid username or password")
    token = auth.create_session_token(body.username)
    response.set_cookie(
        "session", token, max_age=config.SESSION_MAX_AGE, httponly=True,
        secure=config.COOKIE_SECURE, samesite="strict", path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("session", path="/")
    return {"ok": True}


@app.get("/api/me")
async def me(user: str = Depends(auth.require_auth)):
    p = users.profile(user)
    return {"user": user, "name": p.get("name", ""), "email": p.get("email", ""),
            "admin": users.is_admin(user)}


def require_admin(user: str = Depends(auth.require_auth)) -> str:
    if not users.is_admin(user):
        raise HTTPException(403, "Admin only")
    return user


@app.get("/api/app-config")
async def app_config():
    """Public feature flags the login screen needs before auth."""
    return {"google_login": google_auth.enabled()}


# ---------- Google sign-in & Drive backup ----------

def _html_redirect(dest: str) -> HTMLResponse:
    # A meta refresh (not a 3xx) so the follow-up navigation counts as same-site
    # and the SameSite=Strict session cookie is sent.
    return HTMLResponse(f'<!doctype html><meta http-equiv="refresh" content="0;url={dest}">'
                        '<p style="font-family:serif">One moment…</p>')


@app.get("/api/auth/google/login")
async def google_login():
    if not google_auth.enabled():
        raise HTTPException(404, "Google sign-in is not configured")
    return RedirectResponse(google_auth.auth_url("login"))


@app.get("/api/backup/drive")
async def backup_drive(user: str = Depends(auth.require_auth)):
    if not google_auth.enabled():
        raise HTTPException(404, "Google backup is not configured")
    return RedirectResponse(google_auth.auth_url("backup", user))


@app.get("/api/auth/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    if not google_auth.enabled():
        raise HTTPException(404, "Google sign-in is not configured")
    if error or not code or not state:
        return _html_redirect("/?login=failed")
    try:
        st = google_auth.read_state(state)
    except Exception:
        return _html_redirect("/?login=failed")

    if st.get("p") == "login":
        try:
            tokens = await google_auth.exchange_code(code)
            info = await google_auth.verify_id_token(tokens["id_token"])
            users.save_profile(info["sub"], info.get("email", ""), info.get("name", ""))
        except Exception:
            log.exception("Google login failed")
            return _html_redirect("/?login=failed")
        resp = _html_redirect("/")
        resp.set_cookie(
            "session", auth.create_session_token(f"g:{info['sub']}"),
            max_age=config.SESSION_MAX_AGE, httponly=True,
            secure=config.COOKIE_SECURE, samesite="strict", path="/")
        return resp

    if st.get("p") == "backup" and st.get("u"):
        try:
            tokens = await google_auth.exchange_code(code)
            data = google_auth.zip_vault(users.vault_for(st["u"]))
            await google_auth.upload_to_drive(tokens["access_token"], data)
        except Exception:
            log.exception("Drive backup failed")
            return _html_redirect("/?backup=failed")
        return _html_redirect("/?backup=ok")

    if st.get("p") == "restore" and st.get("u"):
        try:
            tokens = await google_auth.exchange_code(code)
            backups = await google_auth.list_backups(tokens["access_token"])
            if not backups:
                return _html_redirect("/?restore=empty")
            data = await google_auth.download_drive_file(
                tokens["access_token"], backups[0]["id"])
            result = notes.import_zip(data, users.vault_for(st["u"]))
        except Exception:
            log.exception("Drive restore failed")
            return _html_redirect("/?restore=failed")
        return _html_redirect(f"/?restore=ok&imported={result['imported']}")

    return _html_redirect("/")


@app.get("/api/export.zip")
async def export_zip(user: str = Depends(auth.require_auth)):
    data = google_auth.zip_vault(users.vault_for(user))
    today = datetime.date.today().isoformat()
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="prayervault-{today}.zip"',
        "Cache-Control": "no-cache"})


@app.post("/api/import.zip")
async def import_zip(file: UploadFile = File(...), user: str = Depends(auth.require_auth)):
    data = await file.read()
    if not data:
        raise HTTPException(422, "Empty file")
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(413, "Backup too large (50 MB max)")
    try:
        return notes.import_zip(data, users.vault_for(user))
    except zipfile.BadZipFile:
        raise HTTPException(422, "That doesn't look like a valid .zip backup")


@app.get("/api/restore/drive")
async def restore_drive(user: str = Depends(auth.require_auth)):
    if not google_auth.enabled():
        raise HTTPException(404, "Google Drive restore is not configured")
    return RedirectResponse(google_auth.auth_url("restore", user))


# ---------- Prayers ----------

class NewPrayer(BaseModel):
    type: str = Field(pattern="^(prayer|request)$")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    requested_by: str = Field(default="", max_length=120)
    family: str = Field(default="", max_length=60)


class TextBody(BaseModel):
    text: str = Field(default="", max_length=5000)


async def _run_ai(note_id: str, kind: str, title: str, text: str, requested_by: str,
                  root=None):
    try:
        result = await ollama_client.generate(kind, title, text, requested_by)
        notes.apply_ai_result(note_id, result, root=root)
        log.info("AI response written for %s", note_id)
        try:
            await embeddings.add_related_section(note_id, root=root)
        except Exception:
            log.warning("Embeddings unavailable; skipped Related for %s", note_id)
    except Exception as e:
        log.exception("AI generation failed for %s", note_id)
        notes.apply_ai_result(note_id, None, error=str(e), root=root)


@app.get("/api/prayers")
async def list_prayers(user: str = Depends(auth.require_auth)):
    return notes.list_notes(users.vault_for(user))


@app.post("/api/prayers")
async def create_prayer(body: NewPrayer, bg: BackgroundTasks,
                        user: str = Depends(auth.require_auth)):
    auth.check_ai_limit(user)
    root = users.vault_for(user)
    family = body.family.strip()
    if family and not families.get_family(family, root):
        raise HTTPException(422, "Unknown family")
    note_id = notes.create_note(body.type, body.title, body.text, body.requested_by,
                                family=family, root=root)
    bg.add_task(_run_ai, note_id, body.type, body.title, body.text, body.requested_by,
                root)
    return {"id": note_id}


def _get_or_404(note_id: str, root=None) -> dict:
    try:
        return notes.read_note(note_id, root)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Not found")


@app.get("/api/prayers/{note_id}")
async def get_prayer(note_id: str, user: str = Depends(auth.require_auth)):
    return _get_or_404(note_id, users.vault_for(user))


@app.post("/api/prayers/{note_id}/answered")
async def mark_answered(note_id: str, body: TextBody,
                        user: str = Depends(auth.require_auth)):
    root = users.vault_for(user)
    _get_or_404(note_id, root)
    notes.set_status(note_id, "answered", body.text, root=root)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/reopen")
async def reopen(note_id: str, body: TextBody, user: str = Depends(auth.require_auth)):
    root = users.vault_for(user)
    _get_or_404(note_id, root)
    notes.set_status(note_id, "ongoing", body.text, root=root)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/updates")
async def add_update(note_id: str, body: TextBody,
                     user: str = Depends(auth.require_auth)):
    if not body.text.strip():
        raise HTTPException(422, "Update text required")
    root = users.vault_for(user)
    _get_or_404(note_id, root)
    notes.add_update(note_id, body.text, root=root)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/regenerate")
async def regenerate(note_id: str, bg: BackgroundTasks,
                     user: str = Depends(auth.require_auth)):
    auth.check_ai_limit(user)
    root = users.vault_for(user)
    note = _get_or_404(note_id, root)
    fm, sections = note["frontmatter"], note["sections"]
    fm["ai"] = "pending"
    notes.write_note(note_id, fm, sections, root=root)
    bg.add_task(_run_ai, note_id, fm.get("type", "prayer"), fm.get("title", note_id),
                sections.get("Prayer", ""), fm.get("requested-by", ""), root)
    return {"ok": True}


# ---------- People & Families ----------

class NewFamily(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FamilyAssign(BaseModel):
    family: str = Field(default="", max_length=60)


@app.get("/api/families")
async def list_families(user: str = Depends(auth.require_auth)):
    root = users.vault_for(user)
    counts: dict[str, dict] = {}
    for item in notes.list_notes(root):
        fid = item.get("family")
        if not fid:
            continue
        c = counts.setdefault(fid, {"ongoing": 0, "answered": 0})
        c["answered" if item["status"] == "answered" else "ongoing"] += 1
    return [{**f, **counts.get(f["id"], {"ongoing": 0, "answered": 0})}
            for f in families.list_families(root)]


@app.post("/api/families")
async def create_family(body: NewFamily, user: str = Depends(auth.require_auth)):
    try:
        return families.create_family(body.name, users.vault_for(user))
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/families/{family_id}")
async def get_family(family_id: str, user: str = Depends(auth.require_auth)):
    if not families.SLUG_RE.match(family_id):
        raise HTTPException(404, "Not found")
    root = users.vault_for(user)
    fam = families.get_family(family_id, root)
    if fam is None:
        raise HTTPException(404, "Not found")
    prayers = [i for i in notes.list_notes(root) if i.get("family") == family_id]
    return {"family": fam, "prayers": prayers}


@app.delete("/api/families/{family_id}")
async def delete_family(family_id: str, user: str = Depends(auth.require_auth)):
    if not families.SLUG_RE.match(family_id):
        raise HTTPException(404, "Not found")
    families.delete_family(family_id, users.vault_for(user))
    return {"ok": True}


@app.post("/api/prayers/{note_id}/family")
async def assign_family(note_id: str, body: FamilyAssign,
                        user: str = Depends(auth.require_auth)):
    root = users.vault_for(user)
    _get_or_404(note_id, root)
    fam = body.family.strip()
    if fam and not families.get_family(fam, root):
        raise HTTPException(422, "Unknown family")
    notes.set_family(note_id, fam, root=root)
    return {"ok": True}


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...),
                     user: str = Depends(auth.require_auth)):
    data = await audio.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Recording too large (25 MB max)")
    if not data:
        raise HTTPException(422, "Empty recording")
    try:
        text = await stt.transcribe(data, audio.filename, audio.content_type)
    except Exception as e:
        raise HTTPException(503, f"Transcription service unavailable: {e}")
    return {"text": text}


@app.get("/api/search")
async def semantic_search(q: str = "", user: str = Depends(auth.require_auth)):
    q = q.strip()
    if not q:
        return []
    try:
        return await embeddings.search(q, root=users.vault_for(user))
    except Exception as e:
        raise HTTPException(503, f"Embedding model unavailable: {e}")


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/api/ask")
async def ask_scripture(body: AskBody, user: str = Depends(auth.require_auth)):
    auth.check_ai_limit(user)
    try:
        return await ollama_client.ask(body.question)
    except Exception as e:
        raise HTTPException(503, f"Model unavailable: {e}")


@app.get("/api/health")
async def health(user: str = Depends(auth.require_auth)):
    return await ollama_client.health()


# ---------- Settings & morning prompt ----------

class SettingsBody(BaseModel):
    morning: dict = Field(default_factory=dict)
    prompts: dict = Field(default_factory=dict)


@app.get("/api/settings")
async def get_settings(user: str = Depends(require_admin)):
    s = settings.load()
    s["ntfy_server"] = config.NTFY_SERVER
    s["prompt_defaults"] = {"system": ollama_client.SYSTEM_PROMPT,
                            "answer": ollama_client.ANSWER_PROMPT}
    return s


@app.post("/api/settings")
async def update_settings(body: SettingsBody, user: str = Depends(require_admin)):
    saved = settings.save(body.model_dump())
    saved["ntfy_server"] = config.NTFY_SERVER
    return saved


@app.post("/api/notify/test")
async def notify_test(user: str = Depends(require_admin)):
    m = settings.load()["morning"]
    if m["delivery"] != "ntfy" or not m["ntfy_topic"]:
        raise HTTPException(422, "Choose ntfy delivery and set a topic first.")
    try:
        title, body = notify.compose_morning()
        await notify.send_ntfy(m.get("ntfy_server", ""), m["ntfy_topic"], title, body)
    except Exception as e:
        raise HTTPException(503, f"Push failed: {e}")
    return {"ok": True}


async def _morning_loop():
    """Fire the morning prompt once per day at the configured time."""
    last_sent = None
    while True:
        try:
            m = settings.load()["morning"]
            now = datetime.datetime.now()
            if (m["enabled"] and m["delivery"] != "none"
                    and now.hour == m["hour"] and now.minute == m["minute"]
                    and last_sent != now.date()):
                if await notify.send_morning({"morning": m}):
                    last_sent = now.date()
                    log.info("Morning prompt sent via %s", m["delivery"])
        except Exception:
            log.exception("Morning scheduler error")
        await asyncio.sleep(30)


async def _dispatch_loop():
    """Safety net: flush any queued notifications the request-time background tasks
    didn't deliver (e.g. queued while SMTP was down). Sends resume once SMTP works."""
    while True:
        try:
            notifications.dispatch_pending()
        except Exception:
            log.exception("Notification dispatch error")
        await asyncio.sleep(60)


async def _digest_loop():
    """Send weekly digests once per day at 07:00 to whoever is due that weekday."""
    last_run = None
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == 7 and last_run != now.date():
                notifications.send_weekly_digests(now.weekday())
                last_run = now.date()
        except Exception:
            log.exception("Digest scheduler error")
        await asyncio.sleep(60)


@app.on_event("startup")
async def _start_scheduler():
    # Bring the schema up to date via Alembic (falls back to create_all if Alembic
    # isn't available). Keeps a fresh NAS deploy and local dev zero-config.
    db.migrate()
    asyncio.create_task(_morning_loop())
    asyncio.create_task(_dispatch_loop())
    asyncio.create_task(_digest_loop())


# ---------- Frontend ----------

NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/app.js")
async def appjs():
    return FileResponse(STATIC / "app.js", media_type="application/javascript",
                        headers=NO_CACHE)


DAY_CACHE = {"Cache-Control": "public, max-age=86400"}

# Root-level static assets (PWA + icons + veil art). Whitelist keeps
# _safe_path-style guarantees: only these exact names are ever served.
ASSETS = {
    "manifest.webmanifest": ("application/manifest+json", NO_CACHE),
    "privacy.html": ("text/html", NO_CACHE),
    "terms.html": ("text/html", NO_CACHE),
    "sw.js": ("application/javascript", NO_CACHE),
    "favicon.ico": ("image/x-icon", DAY_CACHE),
    "icon.svg": ("image/svg+xml", DAY_CACHE),
    "veil-left.svg": ("image/svg+xml", DAY_CACHE),
    "veil-right.svg": ("image/svg+xml", DAY_CACHE),
    "icon-192.png": ("image/png", DAY_CACHE),
    "icon-512.png": ("image/png", DAY_CACHE),
    "icon-maskable-512.png": ("image/png", DAY_CACHE),
    "apple-touch-icon.png": ("image/png", DAY_CACHE),
}


@app.get("/{asset}")
async def static_asset(asset: str):
    if asset not in ASSETS:
        raise HTTPException(404, "Not found")
    media_type, headers = ASSETS[asset]
    return FileResponse(STATIC / asset, media_type=media_type, headers=headers)
