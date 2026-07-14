"""User accounts for the multi-church layer: password auth, signup, invitations.

This is distinct from the legacy single-user ``auth.py`` (which guards Sean's own
Obsidian vault). Here every account is a row in ``users`` belonging to exactly one
church. Founders self-serve a church; everyone else joins by an invitation whose
signed token is the member-signup allow-list (plan §8, §11).

Google sign-in can slot in later as an alternative identity — the ``User`` model
already carries ``google_sub`` — but password accounts make the whole flow usable
and testable without external OAuth.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import select

from . import config, db, models, orgs

_invite = URLSafeTimedSerializer(config.SESSION_SECRET, salt="prayervault-invite")
INVITE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days to accept

# Who may invite which church role.
_INVITE_MATRIX = {"admin": {"admin", "elder", "member"}, "elder": {"member"}}


class AccountError(RuntimeError):
    """Signup / login / invitation problem surfaced to callers."""


def hash_password(pw: str) -> str:
    if not pw or len(pw) < 6:
        raise AccountError("Password must be at least 6 characters")
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()


def _check_password(pw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- signup / login ------------------------------------------------------

def signup_church(church_name: str, name: str, email: str, password: str) -> dict:
    """Self-serve: found a church and become its (password) admin.

    Returns ``{user_id, org_id, slug, status, verify_token, role}``.
    """
    r = orgs.create_church(
        church_name, email, name, password_hash=hash_password(password)
    )
    return {**r, "role": "admin"}


def login(email: str, password: str) -> dict | None:
    """Verify email + password. Returns an account dict, or None."""
    email = (email or "").strip().lower()
    with db.session_scope() as s:
        users = list(s.exec(select(models.User).where(models.User.email == email)))
    for u in users:
        if _check_password(password, u.password_hash):
            return get_account(u.id)
    return None


def get_account(user_id: str) -> dict | None:
    """Resolve a user id to the principal a request runs as."""
    with db.session_scope() as s:
        u = s.get(models.User, user_id)
        if u is None:
            return None
        m = s.exec(
            select(models.Membership).where(
                models.Membership.org_id == u.org_id,
                models.Membership.user_id == u.id,
            )
        ).first()
        return {
            "user_id": u.id,
            "org_id": u.org_id,
            "email": u.email,
            "name": u.display_name,
            "role": m.role if m else None,
        }


# --- invitations ---------------------------------------------------------

def create_invitation(org_id: str, inviter_id: str, email: str,
                      church_role: str = "member") -> dict:
    """An admin (any role) or elder (members only) invites someone. Returns token."""
    email = (email or "").strip().lower()
    if not email:
        raise AccountError("Invitee email is required")
    if church_role not in models.CHURCH_ROLES:
        raise AccountError("Unknown role")
    inviter_role = orgs.membership_role(org_id, inviter_id)
    if church_role not in _INVITE_MATRIX.get(inviter_role, set()):
        raise AccountError("You are not permitted to invite that role")
    with db.tenant_scope(org_id) as t:
        inv = t.add(models.Invitation(
            email=email, church_role=church_role, invited_by=inviter_id,
            token="",  # set after we have an id
            expires_at=_now() + timedelta(seconds=INVITE_MAX_AGE),
        ))
        t.session.flush()
        inv.token = _invite.dumps({"inv": inv.id})
        t.add(inv)
        org = t.organization()
        return {"invitation_id": inv.id, "token": inv.token, "email": email,
                "church_role": church_role,
                "church_name": org.name if org else ""}


def accept_invitation(token: str, name: str, password: str) -> dict:
    """Create the invited user's account. Returns an account dict + sets no cookie."""
    try:
        data = _invite.loads(token, max_age=INVITE_MAX_AGE)
    except SignatureExpired:
        raise AccountError("Invitation has expired")
    except BadSignature:
        raise AccountError("Invitation is invalid")
    inv_id = data.get("inv")
    pw_hash = hash_password(password)
    with db.session_scope() as s:
        inv = s.get(models.Invitation, inv_id)
        if inv is None:
            raise AccountError("Invitation not found")
        if inv.accepted_at is not None:
            raise AccountError("Invitation already used")
        user = models.User(
            org_id=inv.org_id, email=inv.email, display_name=(name or "").strip(),
            auth_provider="password", password_hash=pw_hash,
        )
        s.add(user)
        s.flush()
        s.add(models.Membership(org_id=inv.org_id, user_id=user.id, role=inv.church_role))
        inv.accepted_at = _now()
        s.add(inv)
        s.flush()
        return {"user_id": user.id, "org_id": inv.org_id, "email": inv.email,
                "name": user.display_name, "role": inv.church_role}
