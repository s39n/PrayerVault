"""Web push (VAPID) channel + per-user subscription storage.

A browser subscribes via the Push API and hands us a subscription object
(endpoint + keys), which we store on the user's ``NotificationPref`` row. Delivery
goes out through ``pywebpush`` signed with our VAPID keys. Disabled and inert until
``VAPID_PUBLIC_KEY`` / ``VAPID_PRIVATE_KEY`` are set (see scripts/gen_vapid.py).

Kept separate from ``notifications.py`` so the push plumbing (and its optional
``pywebpush`` dependency) is isolated; ``notifications`` just calls ``available``
and ``send``.
"""
from __future__ import annotations

import json
import logging

from . import config, db, models

log = logging.getLogger("prayervault.webpush")


class PushGone(RuntimeError):
    """The subscription is dead (404/410) and should be dropped."""


def available() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def public_key() -> str:
    return config.VAPID_PUBLIC_KEY


def _send_raw(subscription: dict, payload: dict) -> None:
    from py_vapid import Vapid01
    from pywebpush import webpush

    vapid = Vapid01.from_raw(config.VAPID_PRIVATE_KEY.encode())
    webpush(
        subscription_info=subscription,
        data=json.dumps(payload),
        vapid_private_key=vapid,
        vapid_claims={"sub": config.VAPID_SUBJECT},
    )


# Indirection so tests can capture pushes without a real endpoint.
send_raw = _send_raw


def send(subscription: dict, title: str, body: str) -> None:
    """Deliver one push. Raises ``PushGone`` if the subscription is dead."""
    payload = {"title": title, "body": body, "url": f"{config.PUBLIC_URL}/church"}
    try:
        send_raw(subscription, payload)
    except PushGone:
        raise
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone(str(e))
        raise


# --- subscription storage ------------------------------------------------

def save_subscription(user_id: str, subscription: dict) -> None:
    with db.session_scope() as s:
        p = s.get(models.NotificationPref, user_id)
        if p is None:
            p = models.NotificationPref(user_id=user_id)
        p.webpush_subscription = subscription
        p.webpush_enabled = True
        s.add(p)


def clear_subscription(user_id: str) -> None:
    with db.session_scope() as s:
        p = s.get(models.NotificationPref, user_id)
        if p is not None:
            p.webpush_subscription = None
            p.webpush_enabled = False
            s.add(p)
