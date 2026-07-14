"""HTTP surface for the multi-church prayer-sharing layer.

A self-contained ``APIRouter`` so it can be mounted on the main app with one line
(``app.include_router(church_api.router)``) and tested in isolation. Sessions here
are separate from the legacy admin cookie: an account cookie carries the DB
``user_id``, and ``require_account`` resolves it to ``{user_id, org_id, role, ...}``.

Route prefixes (``/api/churches``, ``/api/account``, ``/api/requests``,
``/api/elders``, ``/api/shared``) are chosen not to collide with the legacy
single-user ``/api/prayers`` routes in ``main.py``.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import (APIRouter, BackgroundTasks, Depends, HTTPException, Request,
                     Response)
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from . import accounts, config, notifications, orgs, prayer_service as ps
from .accounts import AccountError
from .orgs import OrgError
from .prayer_service import PermissionDenied, PrayerError

router = APIRouter()
STATIC = Path(__file__).parent / "static"
log = logging.getLogger("prayervault.api")


def _safe_invite_email(to: str, church_name: str, inviter: str, accept_url: str) -> None:
    """Best-effort: an SMTP problem must never fail the invite itself."""
    try:
        notifications.email_invitation(to, church_name, inviter, accept_url)
    except Exception as e:
        log.warning("invitation email to %s failed: %s", to, e)

_session = URLSafeTimedSerializer(config.SESSION_SECRET, salt="prayervault-account")
COOKIE = "account"
MAX_AGE = config.SESSION_MAX_AGE


def _set_session(resp: Response, user_id: str) -> None:
    resp.set_cookie(COOKIE, _session.dumps({"uid": user_id}), max_age=MAX_AGE,
                    httponly=True, secure=config.COOKIE_SECURE, samesite="strict",
                    path="/")


def require_account(request: Request) -> dict:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        data = _session.loads(token, max_age=MAX_AGE)
    except BadSignature:
        raise HTTPException(401, "Session invalid or expired")
    acct = accounts.get_account(data.get("uid", ""))
    if acct is None or acct.get("role") is None:
        raise HTTPException(401, "Account not found")
    return acct


def _handle(fn):
    """Run a service call, translating domain errors into HTTP status codes."""
    try:
        return fn()
    except PermissionDenied as e:
        raise HTTPException(403, str(e))
    except (PrayerError, OrgError, AccountError) as e:
        raise HTTPException(400, str(e))


# --- bodies --------------------------------------------------------------

class ChurchSignup(BaseModel):
    church_name: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=120)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)


class TokenBody(BaseModel):
    token: str


class Login(BaseModel):
    email: str
    password: str


class InviteBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    church_role: str = Field(default="member")


class AcceptBody(BaseModel):
    token: str
    name: str = Field(default="", max_length=120)
    password: str = Field(min_length=6, max_length=200)


class NewRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=20000)
    subject_name: str = Field(default="", max_length=120)


class TextBody(BaseModel):
    text: str = Field(default="", max_length=20000)


class StatusBody(BaseModel):
    answered: bool
    text: str = Field(default="", max_length=20000)


class AssignBody(BaseModel):
    to_user_id: str


class MuteBody(BaseModel):
    muted: bool = True


class PrefsBody(BaseModel):
    email_enabled: bool | None = None
    digest_weekly: bool | None = None
    digest_day: int | None = Field(default=None, ge=0, le=6)


# --- churches & accounts -------------------------------------------------

@router.post("/api/churches")
async def create_church(body: ChurchSignup, response: Response):
    r = _handle(lambda: accounts.signup_church(
        body.church_name, body.name, body.email, body.password))
    _set_session(response, r["user_id"])
    return {"org_id": r["org_id"], "slug": r["slug"], "status": r["status"],
            "role": r["role"], "verify_token": r["verify_token"]}


@router.post("/api/churches/verify")
async def verify_church(body: TokenBody):
    org_id = _handle(lambda: orgs.verify_church(body.token))
    return {"ok": True, "org_id": org_id}


@router.post("/api/account/login")
async def account_login(body: Login, response: Response):
    acct = accounts.login(body.email, body.password)
    if acct is None:
        raise HTTPException(401, "Invalid email or password")
    _set_session(response, acct["user_id"])
    return {"ok": True, "role": acct["role"]}


@router.post("/api/account/logout")
async def account_logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/account/me")
async def account_me(acct: dict = Depends(require_account)):
    return acct


@router.get("/api/account/prefs")
async def get_prefs(acct: dict = Depends(require_account)):
    return accounts.get_prefs(acct["user_id"])


@router.post("/api/account/prefs")
async def set_prefs(body: PrefsBody, acct: dict = Depends(require_account)):
    return _handle(lambda: accounts.set_prefs(
        acct["user_id"], email_enabled=body.email_enabled,
        digest_weekly=body.digest_weekly, digest_day=body.digest_day))


@router.post("/api/invites")
async def create_invite(body: InviteBody, bg: BackgroundTasks,
                        acct: dict = Depends(require_account)):
    r = _handle(lambda: accounts.create_invitation(
        acct["org_id"], acct["user_id"], body.email, body.church_role))
    accept_url = f"{config.PUBLIC_URL}/church?invite={r['token']}"
    inviter = acct.get("name") or acct.get("email")
    bg.add_task(_safe_invite_email, r["email"], r.get("church_name", ""), inviter, accept_url)
    return {**r, "accept_url": accept_url}


@router.post("/api/invites/accept")
async def accept_invite(body: AcceptBody, response: Response):
    r = _handle(lambda: accounts.accept_invitation(body.token, body.name, body.password))
    _set_session(response, r["user_id"])
    return {"ok": True, "role": r["role"]}


# --- requests to the elders ---------------------------------------------

@router.post("/api/requests")
async def new_request(body: NewRequest, bg: BackgroundTasks,
                      acct: dict = Depends(require_account)):
    pid = _handle(lambda: ps.create_elder_request(
        acct["org_id"], acct["user_id"], body.title, body.body, body.subject_name))
    bg.add_task(notifications.dispatch_pending)
    return {"id": pid}


@router.get("/api/elders/queue")
async def elder_queue(acct: dict = Depends(require_account)):
    return _handle(lambda: ps.elder_queue(acct["org_id"], acct["user_id"]))


@router.get("/api/elders/flock")
async def elder_flock(acct: dict = Depends(require_account)):
    return _handle(lambda: ps.my_flock(acct["org_id"], acct["user_id"]))


@router.get("/api/elders/follow-up")
async def elder_follow_up(acct: dict = Depends(require_account)):
    return _handle(lambda: ps.follow_up_list(acct["org_id"], acct["user_id"]))


@router.get("/api/mine")
async def my_prayers(acct: dict = Depends(require_account)):
    return _handle(lambda: ps.subscribed_prayers(acct["org_id"], acct["user_id"]))


@router.get("/api/shared/{pid}")
async def get_shared(pid: str, acct: dict = Depends(require_account)):
    return _handle(lambda: ps.get_prayer(acct["org_id"], acct["user_id"], pid))


# --- a single shared prayer ---------------------------------------------

@router.post("/api/shared/{pid}/claim")
async def claim(pid: str, bg: BackgroundTasks, acct: dict = Depends(require_account)):
    _handle(lambda: ps.claim(acct["org_id"], pid, acct["user_id"]))
    bg.add_task(notifications.dispatch_pending)
    return {"ok": True}


@router.post("/api/shared/{pid}/assign")
async def assign(pid: str, body: AssignBody, acct: dict = Depends(require_account)):
    _handle(lambda: ps.assign(acct["org_id"], pid, acct["user_id"], body.to_user_id))
    return {"ok": True}


@router.post("/api/shared/{pid}/updates")
async def add_update(pid: str, body: TextBody, bg: BackgroundTasks,
                     acct: dict = Depends(require_account)):
    _handle(lambda: ps.add_update(acct["org_id"], pid, acct["user_id"], body.text))
    bg.add_task(notifications.dispatch_pending)
    return {"ok": True}


@router.post("/api/shared/{pid}/status")
async def set_status(pid: str, body: StatusBody, bg: BackgroundTasks,
                     acct: dict = Depends(require_account)):
    _handle(lambda: ps.set_status(acct["org_id"], pid, acct["user_id"],
                                  body.answered, body.text))
    bg.add_task(notifications.dispatch_pending)
    return {"ok": True}


@router.get("/api/shared/{pid}/timeline")
async def timeline(pid: str, acct: dict = Depends(require_account)):
    return _handle(lambda: ps.timeline(acct["org_id"], pid, acct["user_id"]))


@router.post("/api/shared/{pid}/follow")
async def follow(pid: str, acct: dict = Depends(require_account)):
    _handle(lambda: ps.follow(acct["org_id"], pid, acct["user_id"]))
    return {"ok": True}


@router.post("/api/shared/{pid}/mute")
async def mute(pid: str, body: MuteBody, acct: dict = Depends(require_account)):
    _handle(lambda: ps.set_muted(acct["org_id"], pid, acct["user_id"], body.muted))
    return {"ok": True}


@router.get("/api/shared/{pid}/notes")
async def get_notes(pid: str, acct: dict = Depends(require_account)):
    return _handle(lambda: ps.pastoral_notes(acct["org_id"], pid, acct["user_id"]))


@router.post("/api/shared/{pid}/notes")
async def add_note(pid: str, body: TextBody, acct: dict = Depends(require_account)):
    nid = _handle(lambda: ps.add_pastoral_note(
        acct["org_id"], pid, acct["user_id"], body.text))
    return {"id": nid}


# --- frontend (dependency-free; JS lives in church.js to satisfy the CSP) ---

@router.get("/church")
async def church_page():
    return FileResponse(STATIC / "church.html", headers={"Cache-Control": "no-cache"})


@router.get("/church.js")
async def church_js():
    return FileResponse(STATIC / "church.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})
