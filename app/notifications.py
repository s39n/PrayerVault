"""Notification pipeline: event -> subscribers -> per-user channels -> outbox.

When something happens to a shared prayer, ``notify_event`` fans it out into one
``notifications`` row per (recipient x enabled channel), status ``queued``. A
separate ``dispatch_pending`` worker delivers those rows and marks them
``sent``/``failed`` — so delivery is idempotent, retryable, and auditable
(plan §6). Email is the first channel; NTFY, web push, and SMS slot in behind the
same interface later.

Everything is opt-in and safe when unconfigured: with no ``SMTP_HOST`` set, email
delivery simply fails-soft and the app is unaffected. ``notify_event`` never raises
into the caller — a notification problem must never break a prayer action.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage

from sqlmodel import select

from . import config, db, models

log = logging.getLogger("prayervault.notify")

# subject template + body template per event. {actor} and {title} are filled in.
EVENTS = {
    "prayer.created": ("New prayer request", "{actor} asked for prayer: “{title}”."),
    "prayer.claimed": ("An elder is praying", "{actor} is now shepherding “{title}”."),
    "prayer.update": ("Update on a prayer", "{actor} added an update to “{title}”."),
    "prayer.answered": ("Answered prayer ✨", "“{title}” has been marked answered."),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def email_enabled() -> bool:
    return bool(config.SMTP_HOST)


# --- delivery (override ``send_email`` in tests) -------------------------

class SmtpNotConfigured(RuntimeError):
    """SMTP isn't set up yet — the message should stay queued, not fail."""


def _smtp_send(to: str, subject: str, body: str) -> None:
    if not config.SMTP_HOST:
        raise SmtpNotConfigured("SMTP is not configured")
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
        if config.SMTP_STARTTLS:
            s.starttls(context=ssl.create_default_context())
        if config.SMTP_USER:
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
        s.send_message(msg)


# Indirection so tests can capture outgoing mail without real SMTP.
send_email = _smtp_send


def email_invitation(to: str, church_name: str, inviter_name: str, accept_url: str) -> None:
    """Send an invite link. Raises on delivery failure (callers run it best-effort)."""
    church = church_name or "your church"
    subject = f"You're invited to pray with {church}"
    body = (
        f"{inviter_name} invited you to join {church}'s prayer list on PrayerVault.\n\n"
        f"Accept your invitation and set up your account:\n{accept_url}\n\n"
        f"If you weren't expecting this, you can safely ignore this email."
    )
    send_email(to, subject, body)


def _channels_for(prefs: models.NotificationPref | None) -> list[str]:
    """Which channels a user wants. Defaults to email when they have no prefs row."""
    if prefs is None:
        return ["email"]
    channels = []
    if prefs.email_enabled:
        channels.append("email")
    # Future: ntfy / webpush / sms gated on their prefs + config.
    return channels


# --- fan-out -------------------------------------------------------------

def notify_event(org_id: str, event_type: str, prayer_id: str, actor_id: str) -> int:
    """Enqueue notifications for an event. Returns how many rows were queued.

    Recipients: for ``prayer.created`` it's the church's elders (a new request
    should reach whoever can claim it); for everything else it's the prayer's
    subscribers. The actor and muted subscribers are always excluded. Never raises.
    """
    try:
        with db.session_scope() as s:
            prayer = s.get(models.Prayer, prayer_id)
            if prayer is None or prayer.org_id != org_id:
                return 0
            actor = s.get(models.User, actor_id)
            actor_name = (actor.display_name or actor.email) if actor else "Someone"

            if event_type == "prayer.created":
                elders = s.exec(
                    select(models.Membership).where(
                        models.Membership.org_id == org_id,
                        models.Membership.role.in_(("elder", "admin")),
                    )
                ).all()
                recipient_ids = {m.user_id for m in elders}
            else:
                subs = s.exec(
                    select(models.Subscription).where(
                        models.Subscription.prayer_id == prayer_id,
                        models.Subscription.muted == False,  # noqa: E712
                    )
                ).all()
                recipient_ids = {sub.user_id for sub in subs}
            recipient_ids.discard(actor_id)

            queued = 0
            for uid in recipient_ids:
                user = s.get(models.User, uid)
                if user is None or user.org_id != org_id:
                    continue
                prefs = s.get(models.NotificationPref, uid)
                for channel in _channels_for(prefs):
                    s.add(models.Notification(
                        org_id=org_id, user_id=uid, prayer_id=prayer_id,
                        event_type=event_type, channel=channel, status="queued",
                        payload={"title": prayer.title, "actor": actor_name},
                    ))
                    queued += 1
            return queued
    except Exception:
        log.exception("notify_event failed for %s/%s", event_type, prayer_id)
        return 0


# --- delivery worker -----------------------------------------------------

def dispatch_pending(limit: int = 100) -> dict:
    """Deliver queued notifications. Returns ``{sent, failed, deferred}`` counts.

    A ``deferred`` row (SMTP not configured yet) is left ``queued`` so the periodic
    dispatcher retries it once email is set up — it is never marked failed.
    """
    sent = failed = deferred = 0
    with db.session_scope() as s:
        pending = s.exec(
            select(models.Notification)
            .where(models.Notification.status == "queued")
            .limit(limit)
        ).all()
        for n in pending:
            try:
                _deliver(s, n)
                n.status = "sent"
                n.sent_at = _now()
                sent += 1
                s.add(n)
            except SmtpNotConfigured:
                deferred += 1  # leave queued; retry when SMTP is configured
            except Exception as e:  # keep going; one bad address shouldn't stall the rest
                n.status = "failed"
                n.error = str(e)[:500]
                failed += 1
                s.add(n)
                log.warning("notification %s failed: %s", n.id, e)
    return {"sent": sent, "failed": failed, "deferred": deferred}


def _deliver(s, n: models.Notification) -> None:
    subject, template = EVENTS.get(n.event_type, ("PrayerVault", "{title}"))
    payload = n.payload or {}
    body = template.format(actor=payload.get("actor", "Someone"),
                           title=payload.get("title", "a prayer"))
    body += f"\n\nOpen PrayerVault: {config.PUBLIC_URL}/church"
    if n.channel == "email":
        user = s.get(models.User, n.user_id)
        prefs = s.get(models.NotificationPref, n.user_id)
        to = (prefs.email_address if prefs and prefs.email_address else
              (user.email if user else ""))
        if not to:
            raise RuntimeError("no email address for user")
        send_email(to, subject, body)
    else:
        raise RuntimeError(f"channel {n.channel} not deliverable yet")


# --- weekly digest -------------------------------------------------------

def build_weekly_digest(user_id: str, days: int = 7) -> tuple[str, str] | None:
    """Summarize the past week for one user. None when there's nothing to say."""
    from datetime import timedelta
    cutoff = _now() - timedelta(days=days)
    with db.session_scope() as s:
        user = s.get(models.User, user_id)
        if user is None:
            return None
        subs = s.exec(
            select(models.Subscription).where(
                models.Subscription.user_id == user_id,
                models.Subscription.muted == False,  # noqa: E712
            )
        ).all()
        answered, active = [], []
        for sub in subs:
            p = s.get(models.Prayer, sub.prayer_id)
            if p is None:
                continue
            recent = [u for u in s.exec(
                select(models.PrayerUpdate).where(models.PrayerUpdate.prayer_id == p.id)
            ).all() if _aware(u.created_at) >= cutoff]
            if p.status == "answered" and p.answered_at and _aware(p.answered_at) >= cutoff:
                answered.append(p.title)
            elif recent:
                active.append((p.title, len(recent)))

        membership = s.exec(
            select(models.Membership).where(models.Membership.user_id == user_id)
        ).first()
        unclaimed = 0
        if membership and membership.role in ("elder", "admin"):
            unclaimed = len(s.exec(
                select(models.Prayer).where(
                    models.Prayer.org_id == user.org_id,
                    models.Prayer.visibility == "elders",
                    models.Prayer.owner_id.is_(None),
                    models.Prayer.status == "ongoing",
                )
            ).all())

    if not (answered or active or unclaimed):
        return None
    lines = ["Here's this week on your prayer list.\n"]
    if unclaimed:
        lines.append(f"• {unclaimed} request(s) are waiting for an elder to claim.")
    for title, n in active:
        lines.append(f"• “{title}” — {n} new update(s).")
    for title in answered:
        lines.append(f"• “{title}” was answered. Praise God!")
    lines.append(f"\nOpen PrayerVault: {config.PUBLIC_URL}/church")
    return "Your weekly prayer digest", "\n".join(lines)


def send_weekly_digests(weekday: int) -> dict:
    """Send digests to everyone opted into a digest on ``weekday`` (0=Mon..6=Sun)."""
    sent = skipped = 0
    with db.session_scope() as s:
        prefs = s.exec(
            select(models.NotificationPref).where(
                models.NotificationPref.digest_weekly == True,  # noqa: E712
                models.NotificationPref.digest_day == weekday,
            )
        ).all()
        targets = [(p.user_id, p.email_address) for p in prefs]
        users = {u.id: u for u in s.exec(select(models.User)).all()}
    for user_id, pref_email in targets:
        digest = build_weekly_digest(user_id)
        if digest is None:
            skipped += 1
            continue
        to = pref_email or (users[user_id].email if user_id in users else "")
        if not to:
            skipped += 1
            continue
        try:
            send_email(to, digest[0], digest[1])
            sent += 1
        except Exception as e:
            log.warning("digest to %s failed: %s", to, e)
    return {"sent": sent, "skipped": skipped}


def _aware(dt):
    from datetime import timezone as _tz
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)
