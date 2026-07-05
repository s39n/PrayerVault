import asyncio
import datetime
import logging
from pathlib import Path

from fastapi import (BackgroundTasks, Depends, FastAPI, File, HTTPException,
                     Request, Response, UploadFile)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import auth, config, embeddings, notes, notify, ollama_client, settings, stt

log = logging.getLogger("prayervault")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PrayerVault", docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent / "static"


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
    return {"user": user}


# ---------- Prayers ----------

class NewPrayer(BaseModel):
    type: str = Field(pattern="^(prayer|request)$")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    requested_by: str = Field(default="", max_length=120)


class TextBody(BaseModel):
    text: str = Field(default="", max_length=5000)


async def _run_ai(note_id: str, kind: str, title: str, text: str, requested_by: str):
    try:
        result = await ollama_client.generate(kind, title, text, requested_by)
        notes.apply_ai_result(note_id, result)
        log.info("AI response written for %s", note_id)
        try:
            await embeddings.add_related_section(note_id)
        except Exception:
            log.warning("Embeddings unavailable; skipped Related for %s", note_id)
    except Exception as e:
        log.exception("AI generation failed for %s", note_id)
        notes.apply_ai_result(note_id, None, error=str(e))


@app.get("/api/prayers")
async def list_prayers(user: str = Depends(auth.require_auth)):
    return notes.list_notes()


@app.post("/api/prayers")
async def create_prayer(body: NewPrayer, bg: BackgroundTasks,
                        user: str = Depends(auth.require_auth)):
    note_id = notes.create_note(body.type, body.title, body.text, body.requested_by)
    bg.add_task(_run_ai, note_id, body.type, body.title, body.text, body.requested_by)
    return {"id": note_id}


def _get_or_404(note_id: str) -> dict:
    try:
        return notes.read_note(note_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Not found")


@app.get("/api/prayers/{note_id}")
async def get_prayer(note_id: str, user: str = Depends(auth.require_auth)):
    return _get_or_404(note_id)


@app.post("/api/prayers/{note_id}/answered")
async def mark_answered(note_id: str, body: TextBody,
                        user: str = Depends(auth.require_auth)):
    _get_or_404(note_id)
    notes.set_status(note_id, "answered", body.text)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/reopen")
async def reopen(note_id: str, body: TextBody, user: str = Depends(auth.require_auth)):
    _get_or_404(note_id)
    notes.set_status(note_id, "ongoing", body.text)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/updates")
async def add_update(note_id: str, body: TextBody,
                     user: str = Depends(auth.require_auth)):
    if not body.text.strip():
        raise HTTPException(422, "Update text required")
    _get_or_404(note_id)
    notes.add_update(note_id, body.text)
    return {"ok": True}


@app.post("/api/prayers/{note_id}/regenerate")
async def regenerate(note_id: str, bg: BackgroundTasks,
                     user: str = Depends(auth.require_auth)):
    note = _get_or_404(note_id)
    fm, sections = note["frontmatter"], note["sections"]
    fm["ai"] = "pending"
    notes.write_note(note_id, fm, sections)
    bg.add_task(_run_ai, note_id, fm.get("type", "prayer"), fm.get("title", note_id),
                sections.get("Prayer", ""), fm.get("requested-by", ""))
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
        return await embeddings.search(q)
    except Exception as e:
        raise HTTPException(503, f"Embedding model unavailable: {e}")


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@app.post("/api/ask")
async def ask_scripture(body: AskBody, user: str = Depends(auth.require_auth)):
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


@app.get("/api/settings")
async def get_settings(user: str = Depends(auth.require_auth)):
    s = settings.load()
    s["ntfy_server"] = config.NTFY_SERVER
    return s


@app.post("/api/settings")
async def update_settings(body: SettingsBody, user: str = Depends(auth.require_auth)):
    saved = settings.save(body.model_dump())
    saved["ntfy_server"] = config.NTFY_SERVER
    return saved


@app.post("/api/notify/test")
async def notify_test(user: str = Depends(auth.require_auth)):
    m = settings.load()["morning"]
    if m["delivery"] != "ntfy" or not m["ntfy_topic"]:
        raise HTTPException(422, "Choose ntfy delivery and set a topic first.")
    try:
        title, body = notify.compose_morning()
        await notify.send_ntfy(m["ntfy_topic"], title, body)
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


@app.on_event("startup")
async def _start_scheduler():
    asyncio.create_task(_morning_loop())


# ---------- Frontend ----------

NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/app.js")
async def appjs():
    return FileResponse(STATIC / "app.js", media_type="application/javascript",
                        headers=NO_CACHE)
