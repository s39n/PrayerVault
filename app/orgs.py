"""Church (tenant) + membership service layer.

Platform-level operations that create and resolve churches and their members.
Church creation is self-serve (plan §11): anyone may found a church and become its
admin, but the church starts ``pending_verify`` until the founder confirms their
email (the anti-abuse gate). Members, by contrast, only ever join by invitation.

These functions run *above* the tenant boundary (they create the tenant itself), so
they use ``db.session_scope`` rather than a ``Tenant``. Everything downstream that
touches an existing church's data must go through ``db.Tenant`` (see ``db.py``).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import select

from . import config, db, models

# Signed, expiring token the founder presents to activate their church.
_verify = URLSafeTimedSerializer(config.SESSION_SECRET, salt="prayervault-church-verify")
VERIFY_MAX_AGE = 60 * 60 * 24 * 3  # 3 days to confirm

DEFAULT_SETTINGS = {
    "follow_up_days": 7,      # drives the elder "needs follow-up" list (plan §3b)
    "elder_requests": True,   # allow "send to the elders" destination
    "allowed_email_domain": "",
    "branding": {},
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "church"


def _unique_slug(session, base: str) -> str:
    slug, n = base, 2
    while session.exec(
        select(models.Organization).where(models.Organization.slug == slug)
    ).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


class OrgError(RuntimeError):
    """Church-creation / membership problem surfaced to callers."""


def create_church(
    name: str,
    founder_email: str,
    founder_name: str = "",
    google_sub: str | None = None,
    password_hash: str | None = None,
    auto_active: bool = False,
) -> dict:
    """Create a church and its founding admin.

    Returns ``{org_id, user_id, slug, status, verify_token}``. The church is
    ``pending_verify`` unless ``auto_active`` (used in dev/tests). ``verify_token``
    is what the founder-confirmation email must carry.
    """
    name = (name or "").strip()
    founder_email = (founder_email or "").strip().lower()
    if not name:
        raise OrgError("Church name is required")
    if not founder_email:
        raise OrgError("Founder email is required")

    with db.session_scope() as s:
        slug = _unique_slug(s, slugify(name))
        org = models.Organization(
            name=name,
            slug=slug,
            status="active" if auto_active else "pending_verify",
            settings=dict(DEFAULT_SETTINGS),
        )
        s.add(org)
        s.flush()  # org exists before user FK

        user = models.User(
            org_id=org.id,
            email=founder_email,
            display_name=(founder_name or "").strip(),
            auth_provider="google" if google_sub else "password",
            google_sub=google_sub,
            password_hash=password_hash,
        )
        s.add(user)
        s.flush()  # user exists before membership FK

        s.add(models.Membership(org_id=org.id, user_id=user.id, role="admin"))
        org.created_by = user.id
        s.flush()

        return {
            "org_id": org.id,
            "user_id": user.id,
            "slug": org.slug,
            "status": org.status,
            "verify_token": _verify.dumps({"org": org.id}),
        }


def verify_church(token: str, max_age: int = VERIFY_MAX_AGE) -> str:
    """Activate a church from a founder-confirmation token. Returns the org_id.

    Idempotent: verifying an already-active church is a no-op that still returns
    the org_id. Raises ``OrgError`` on a bad/expired token or unknown church.
    """
    try:
        data = _verify.loads(token, max_age=max_age)
    except SignatureExpired:
        raise OrgError("Verification link has expired")
    except BadSignature:
        raise OrgError("Verification link is invalid")
    org_id = data.get("org")
    with db.session_scope() as s:
        org = s.get(models.Organization, org_id)
        if org is None:
            raise OrgError("Church not found")
        if org.status == "pending_verify":
            org.status = "active"
            s.add(org)
        return org.id


# --- lookups (platform-level; callers still gate by role where needed) ---

def user_by_google_sub(google_sub: str) -> models.User | None:
    with db.session_scope() as s:
        return s.exec(
            select(models.User).where(models.User.google_sub == google_sub)
        ).first()


def membership_role(org_id: str, user_id: str) -> str | None:
    """The user's church-tier role (admin|elder|member), or None if not a member."""
    with db.session_scope() as s:
        m = s.exec(
            select(models.Membership).where(
                models.Membership.org_id == org_id,
                models.Membership.user_id == user_id,
            )
        ).first()
        return m.role if m else None


def is_active(org_id: str) -> bool:
    with db.session_scope() as s:
        org = s.get(models.Organization, org_id)
        return bool(org and org.status == "active")


def follow_up_days(org_id: str) -> int:
    with db.session_scope() as s:
        org = s.get(models.Organization, org_id)
        settings = (org.settings if org else None) or {}
        return int(settings.get("follow_up_days", DEFAULT_SETTINGS["follow_up_days"]))
