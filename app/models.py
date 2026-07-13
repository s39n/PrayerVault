"""Relational schema for the multi-tenant, multi-church prayer-sharing layer.

This is the source of truth for churches, users, memberships, groups, shared
prayers, updates, subscriptions, and notifications. See
``docs/multiuser-prayer-sharing-plan.md`` for the design.

The cardinal rule (see ``db.Tenant``): every church-owned row carries ``org_id``
and is only ever reached through a tenant-scoped session, so one church can never
read another's data. ``Organization`` and platform-level ``User`` identity are the
only tables without an ``org_id`` gate — ``User`` instead *belongs to* one org.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Role / status vocabularies (kept as plain strings for SQLite simplicity) ---
CHURCH_ROLES = ("admin", "elder", "member")
GROUP_ROLES = ("leader", "member")
VISIBILITIES = ("private", "direct", "elders", "group")
PRAYER_STATUS = ("ongoing", "answered")
ORG_STATUS = ("pending_verify", "active", "suspended")


class Organization(SQLModel, table=True):
    """A church — the tenant boundary. Has no ``org_id`` (it *is* the org)."""

    __tablename__ = "organizations"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)
    status: str = Field(default="pending_verify")  # ORG_STATUS
    created_by: str | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)
    # branding, elder-request on/off, allowed email domain, follow_up_days (default 7)
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))


class User(SQLModel, table=True):
    """A person. One person = one church (a second church = a second account)."""

    __tablename__ = "users"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    email: str = Field(index=True)
    display_name: str = ""
    auth_provider: str = "google"  # google | password
    google_sub: str | None = Field(default=None, index=True, unique=True)
    password_hash: str | None = None
    onboarded: dict = Field(default_factory=dict, sa_column=Column(JSON))  # tours seen
    created_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_user_org_email"),)


class Membership(SQLModel, table=True):
    """A user's church-tier role (admin | elder | member)."""

    __tablename__ = "memberships"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")  # CHURCH_ROLES
    status: str = Field(default="active")  # active | invited
    created_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership"),)


class Group(SQLModel, table=True):
    __tablename__ = "groups"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    name: str
    slug: str = Field(index=True)
    description: str = ""
    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_group_slug"),)


class GroupMember(SQLModel, table=True):
    __tablename__ = "group_members"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    group_id: str = Field(foreign_key="groups.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="member")  # GROUP_ROLES; leaders can invite
    status: str = Field(default="active")  # active | invited | requested
    joined_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)


class Prayer(SQLModel, table=True):
    """Source-of-truth row for a shared prayer. Body stays Markdown (AI sections)."""

    __tablename__ = "prayers"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    title: str
    kind: str = "request"  # prayer | request
    owner_id: str | None = Field(default=None, foreign_key="users.id")  # null until claimed
    subject_name: str = ""  # e.g. "John" when praying for someone
    visibility: str = "private"  # VISIBILITIES
    group_id: str | None = Field(default=None, foreign_key="groups.id")
    status: str = "ongoing"  # PRAYER_STATUS
    answered_at: datetime | None = None
    body_md: str = ""  # "## Prayer" text plus AI Scripture/Reflection/How to Pray
    ai_status: str = "pending"  # pending | done | error
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PrayerShare(SQLModel, table=True):
    """For visibility=direct: the named recipients of a request."""

    __tablename__ = "prayer_shares"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    prayer_id: str = Field(foreign_key="prayers.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("prayer_id", "user_id", name="uq_prayer_share"),)


class PrayerUpdate(SQLModel, table=True):
    """Append-only timeline (the DB form of the "## Updates" section)."""

    __tablename__ = "prayer_updates"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    prayer_id: str = Field(foreign_key="prayers.id", index=True)
    author_id: str = Field(foreign_key="users.id")
    text: str
    kind: str = "update"  # update | answered | reopened | created
    created_at: datetime = Field(default_factory=_now)


class PastoralNote(SQLModel, table=True):
    """ELDER-ONLY note on a prayer — never surfaced to the member (see plan §3b)."""

    __tablename__ = "pastoral_notes"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    prayer_id: str = Field(foreign_key="prayers.id", index=True)
    author_id: str = Field(foreign_key="users.id")  # an elder
    text: str
    created_at: datetime = Field(default_factory=_now)


class Subscription(SQLModel, table=True):
    """Who follows a prayer -> who gets notified. Mute silences one thread."""

    __tablename__ = "subscriptions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    prayer_id: str = Field(foreign_key="prayers.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    muted: bool = False
    created_at: datetime = Field(default_factory=_now)

    __table_args__ = (UniqueConstraint("prayer_id", "user_id", name="uq_subscription"),)


class NotificationPref(SQLModel, table=True):
    """Per-user channel toggles. Keyed by user (which implies the org)."""

    __tablename__ = "notification_prefs"

    user_id: str = Field(foreign_key="users.id", primary_key=True)
    email_enabled: bool = True
    webpush_enabled: bool = False
    sms_enabled: bool = False
    ntfy_enabled: bool = False
    ntfy_topic: str = ""
    digest_weekly: bool = False
    digest_day: int = 0  # 0=Mon .. 6=Sun
    email_address: str = ""
    phone_e164: str = ""
    webpush_subscription: dict | None = Field(default=None, sa_column=Column(JSON))


class Notification(SQLModel, table=True):
    """Outbox / delivery log — idempotent, retryable, auditable."""

    __tablename__ = "notifications"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    prayer_id: str | None = Field(default=None, foreign_key="prayers.id")
    event_type: str = ""  # prayer.created | prayer.update | prayer.answered | ...
    channel: str = "email"  # email | webpush | sms | ntfy | digest
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "queued"  # queued | sent | failed
    error: str = ""
    created_at: datetime = Field(default_factory=_now)
    sent_at: datetime | None = None


class Invitation(SQLModel, table=True):
    """Invite link to a church and/or a group. The member-signup allow-list."""

    __tablename__ = "invitations"

    id: str = Field(default_factory=_uuid, primary_key=True)
    org_id: str = Field(foreign_key="organizations.id", index=True)
    email: str = Field(index=True)
    group_id: str | None = Field(default=None, foreign_key="groups.id")
    church_role: str = "member"  # member | elder | admin
    group_role: str | None = None  # leader | member (when group_id set)
    token: str = Field(index=True)  # signed; the thing the invitee presents
    invited_by: str = Field(foreign_key="users.id")
    accepted_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
