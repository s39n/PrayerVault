"""Shared-prayer flow, centered on the "request prayer from the elders" journey.

A member sends a request to their church's elders; an elder claims ownership and
shepherds it; any subscriber can add updates; the owner (or an elder/admin) marks it
answered. Elders get a queue of unclaimed requests, a "my flock" list, a follow-up
nudge list, and private pastoral notes the member never sees (plan §3b).

Everything here is tenant-scoped through ``db.Tenant`` and permission-checked against
the caller's church-tier role, so it cannot touch another church's data and cannot be
driven by someone without the right role. Notification *fan-out* is represented by
``Subscription`` rows; actually delivering messages is Phase 3.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from . import db, models

ELDER_ROLES = ("elder", "admin")


class PrayerError(RuntimeError):
    """A shared-prayer operation failed (not found, bad state, etc.)."""


class PermissionDenied(PrayerError):
    """The caller's role does not permit this action."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role(t: db.Tenant, user_id: str) -> str | None:
    m = t.one_or_none(models.Membership, models.Membership.user_id == user_id)
    return m.role if m else None


def _subscribed(t: db.Tenant, prayer_id: str, user_id: str) -> models.Subscription | None:
    return t.one_or_none(
        models.Subscription,
        models.Subscription.prayer_id == prayer_id,
        models.Subscription.user_id == user_id,
    )


def _subscribe(t: db.Tenant, prayer_id: str, user_id: str) -> None:
    if _subscribed(t, prayer_id, user_id) is None:
        t.add(models.Subscription(prayer_id=prayer_id, user_id=user_id))


def _prayer_dict(p: models.Prayer) -> dict:
    return {
        "id": p.id, "title": p.title, "kind": p.kind, "owner_id": p.owner_id,
        "subject_name": p.subject_name, "visibility": p.visibility,
        "status": p.status, "ai_status": p.ai_status, "body_md": p.body_md,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


# --- member: create a request to the elders ------------------------------

def create_elder_request(org_id: str, requester_id: str, title: str, body: str,
                         subject_name: str = "") -> str:
    """A church member sends a prayer need to the elders. Returns the prayer id."""
    title = (title or "").strip()
    if not title:
        raise PrayerError("A title is required")
    with db.tenant_scope(org_id) as t:
        if _role(t, requester_id) is None:
            raise PermissionDenied("Only church members can request prayer")
        org = t.organization()
        if org and not (org.settings or {}).get("elder_requests", True):
            raise PrayerError("This church has disabled requests to the elders")
        p = t.add(models.Prayer(
            title=title, kind="request", visibility="elders", owner_id=None,
            subject_name=(subject_name or "").strip(), status="ongoing",
            body_md=(body or "").strip(), ai_status="pending",
        ))
        t.session.flush()
        t.add(models.PrayerUpdate(prayer_id=p.id, author_id=requester_id,
                                  text="Prayer requested", kind="created"))
        _subscribe(t, p.id, requester_id)
        return p.id


# --- elder: queue + claim ------------------------------------------------

def elder_queue(org_id: str, elder_id: str) -> list[dict]:
    """Unclaimed requests waiting for an elder to pick them up."""
    with db.tenant_scope(org_id) as t:
        if _role(t, elder_id) not in ELDER_ROLES:
            raise PermissionDenied("Elders only")
        rows = t.all(
            models.Prayer,
            models.Prayer.visibility == "elders",
            models.Prayer.owner_id.is_(None),
            models.Prayer.status == "ongoing",
        )
        return [_prayer_dict(p) for p in sorted(rows, key=lambda p: p.created_at)]


def claim(org_id: str, prayer_id: str, elder_id: str) -> None:
    """An elder takes ownership of a request ("I've got this")."""
    with db.tenant_scope(org_id) as t:
        if _role(t, elder_id) not in ELDER_ROLES:
            raise PermissionDenied("Elders only")
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        if p.owner_id and p.owner_id != elder_id:
            raise PrayerError("Already claimed by another elder")
        p.owner_id = elder_id
        p.updated_at = _now()
        t.add(p)
        _subscribe(t, prayer_id, elder_id)
        t.add(models.PrayerUpdate(prayer_id=prayer_id, author_id=elder_id,
                                  text="An elder is now praying for this", kind="update"))


def assign(org_id: str, prayer_id: str, actor_id: str, to_elder_id: str) -> None:
    """Owner/elder/admin hands a prayer to another elder."""
    with db.tenant_scope(org_id) as t:
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        if _role(t, actor_id) not in ELDER_ROLES and p.owner_id != actor_id:
            raise PermissionDenied("Only the owner or an elder can reassign")
        if _role(t, to_elder_id) not in ELDER_ROLES:
            raise PrayerError("Can only assign to an elder")
        p.owner_id = to_elder_id
        p.updated_at = _now()
        t.add(p)
        _subscribe(t, prayer_id, to_elder_id)


# --- updates + status ----------------------------------------------------

def _can_write(t: db.Tenant, p: models.Prayer, user_id: str) -> bool:
    return (
        p.owner_id == user_id
        or _role(t, user_id) in ELDER_ROLES
        or _subscribed(t, p.id, user_id) is not None
    )


def add_update(org_id: str, prayer_id: str, author_id: str, text: str) -> None:
    """Append a member-visible update; any subscriber (or elder/owner) may."""
    text = (text or "").strip()
    if not text:
        raise PrayerError("Update text is required")
    with db.tenant_scope(org_id) as t:
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        if not _can_write(t, p, author_id):
            raise PermissionDenied("You are not following this prayer")
        t.add(models.PrayerUpdate(prayer_id=prayer_id, author_id=author_id,
                                  text=text, kind="update"))
        p.updated_at = _now()
        t.add(p)
        _subscribe(t, prayer_id, author_id)


def set_status(org_id: str, prayer_id: str, actor_id: str, answered: bool,
               text: str = "") -> None:
    """Mark answered or reopen. Owner, an elder, or admin only."""
    with db.tenant_scope(org_id) as t:
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        if p.owner_id != actor_id and _role(t, actor_id) not in ELDER_ROLES:
            raise PermissionDenied("Only the owner or an elder can change status")
        p.status = "answered" if answered else "ongoing"
        p.answered_at = _now() if answered else None
        p.updated_at = _now()
        t.add(p)
        note = ("Answered!" if answered else "Reopened") + (f" {text.strip()}" if text.strip() else "")
        t.add(models.PrayerUpdate(prayer_id=prayer_id, author_id=actor_id, text=note,
                                  kind="answered" if answered else "reopened"))


def timeline(org_id: str, prayer_id: str, viewer_id: str) -> list[dict]:
    """Member-visible update timeline (never includes pastoral notes)."""
    with db.tenant_scope(org_id) as t:
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        rows = t.all(models.PrayerUpdate, models.PrayerUpdate.prayer_id == prayer_id)
        rows.sort(key=lambda u: u.created_at)
        return [{"text": u.text, "kind": u.kind, "author_id": u.author_id,
                 "created_at": u.created_at} for u in rows]


# --- subscriptions -------------------------------------------------------

def follow(org_id: str, prayer_id: str, user_id: str) -> None:
    with db.tenant_scope(org_id) as t:
        if t.get(models.Prayer, prayer_id) is None:
            raise PrayerError("Prayer not found")
        _subscribe(t, prayer_id, user_id)


def set_muted(org_id: str, prayer_id: str, user_id: str, muted: bool) -> None:
    with db.tenant_scope(org_id) as t:
        sub = _subscribed(t, prayer_id, user_id)
        if sub is None:
            raise PrayerError("Not following this prayer")
        sub.muted = muted
        t.add(sub)


# --- elder dashboard: my flock + follow-up -------------------------------

def my_flock(org_id: str, elder_id: str) -> list[dict]:
    """Prayers this elder owns, newest activity first."""
    with db.tenant_scope(org_id) as t:
        if _role(t, elder_id) not in ELDER_ROLES:
            raise PermissionDenied("Elders only")
        rows = t.all(models.Prayer, models.Prayer.owner_id == elder_id)
        return [_prayer_dict(p) for p in sorted(rows, key=lambda p: p.updated_at, reverse=True)]


def follow_up_list(org_id: str, elder_id: str, days: int | None = None) -> list[dict]:
    """Ongoing prayers I own with no update in ``days`` (default from church settings)."""
    with db.tenant_scope(org_id) as t:
        if _role(t, elder_id) not in ELDER_ROLES:
            raise PermissionDenied("Elders only")
        if days is None:
            org = t.organization()
            days = int((org.settings or {}).get("follow_up_days", 7)) if org else 7
        cutoff = _now() - timedelta(days=days)
        out = []
        owned = t.all(
            models.Prayer,
            models.Prayer.owner_id == elder_id,
            models.Prayer.status == "ongoing",
        )
        for p in owned:
            ups = t.all(models.PrayerUpdate, models.PrayerUpdate.prayer_id == p.id)
            last = max((u.created_at for u in ups), default=p.created_at)
            if _aware(last) < cutoff:
                d = _prayer_dict(p)
                d["last_activity"] = last
                out.append(d)
        return sorted(out, key=lambda d: d["last_activity"])


def _aware(dt: datetime) -> datetime:
    """SQLite may hand back naive datetimes; treat them as UTC for comparison."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- elder-only pastoral notes (never shown to the member) ---------------

def add_pastoral_note(org_id: str, prayer_id: str, elder_id: str, text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise PrayerError("Note text is required")
    with db.tenant_scope(org_id) as t:
        if _role(t, elder_id) not in ELDER_ROLES:
            raise PermissionDenied("Elders only")
        if t.get(models.Prayer, prayer_id) is None:
            raise PrayerError("Prayer not found")
        n = t.add(models.PastoralNote(prayer_id=prayer_id, author_id=elder_id, text=text))
        t.session.flush()
        return n.id


def pastoral_notes(org_id: str, prayer_id: str, reader_id: str) -> list[dict]:
    """Elder/admin only — members must never reach this."""
    with db.tenant_scope(org_id) as t:
        if _role(t, reader_id) not in ELDER_ROLES:
            raise PermissionDenied("Pastoral notes are visible to elders only")
        rows = t.all(models.PastoralNote, models.PastoralNote.prayer_id == prayer_id)
        rows.sort(key=lambda n: n.created_at)
        return [{"text": n.text, "author_id": n.author_id, "created_at": n.created_at}
                for n in rows]


# --- read helpers for the UI ---------------------------------------------

def get_prayer(org_id: str, viewer_id: str, prayer_id: str) -> dict:
    """A single prayer, if the viewer is allowed to see it."""
    with db.tenant_scope(org_id) as t:
        p = t.get(models.Prayer, prayer_id)
        if p is None:
            raise PrayerError("Prayer not found")
        if not (_role(t, viewer_id) in ELDER_ROLES
                or p.owner_id == viewer_id
                or _subscribed(t, prayer_id, viewer_id) is not None):
            raise PermissionDenied("You cannot view this prayer")
        return _prayer_dict(p)


def subscribed_prayers(org_id: str, user_id: str) -> list[dict]:
    """Prayers this person follows (their own requests + anything they joined)."""
    with db.tenant_scope(org_id) as t:
        subs = t.all(models.Subscription, models.Subscription.user_id == user_id)
        out = []
        for sub in subs:
            p = t.get(models.Prayer, sub.prayer_id)
            if p is not None:
                d = _prayer_dict(p)
                d["muted"] = sub.muted
                out.append(d)
        return sorted(out, key=lambda d: d["updated_at"], reverse=True)
