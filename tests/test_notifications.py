"""Event fan-out + email delivery outbox."""
import pytest

from app import db, models, notifications, orgs, prayer_service as ps


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


def _add_user(org_id, role, email):
    with db.session_scope() as s:
        u = models.User(org_id=org_id, email=email, display_name=email.split("@")[0])
        s.add(u)
        s.flush()
        s.add(models.Membership(org_id=org_id, user_id=u.id, role=role))
        s.flush()
        return u.id


def _church(base):
    r = orgs.create_church(f"{base} Church", f"admin@{base}.org", auto_active=True)
    org = r["org_id"]
    return {"org": org, "admin": r["user_id"],
            "elder": _add_user(org, "elder", f"elder@{base}.org"),
            "member": _add_user(org, "member", f"member@{base}.org"),
            "other": _add_user(org, "member", f"other@{base}.org")}


@pytest.fixture
def outbox(monkeypatch):
    """Capture outgoing email and drain any queue left by earlier tests."""
    sent = []
    monkeypatch.setattr(notifications, "send_email",
                        lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}))
    notifications.dispatch_pending()  # drain leftovers into 'sent'
    sent.clear()
    return sent


def _tos(outbox):
    return {m["to"] for m in outbox}


def test_new_request_emails_the_elders_not_the_requester(outbox):
    c = _church("bells")
    ps.create_elder_request(c["org"], c["member"], "Job interview", "body")
    res = notifications.dispatch_pending()
    assert res["sent"] >= 2
    tos = _tos(outbox)
    assert "admin@bells.org" in tos and "elder@bells.org" in tos
    assert "member@bells.org" not in tos  # the requester isn't emailed about their own


def test_claim_emails_the_requester(outbox):
    c = _church("cedar")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    notifications.dispatch_pending()  # clear the created-event mail
    outbox.clear()
    ps.claim(c["org"], pid, c["elder"])
    notifications.dispatch_pending()
    assert "member@cedar.org" in _tos(outbox)
    assert "elder@cedar.org" not in _tos(outbox)  # the actor isn't notified


def test_answered_emails_subscribers(outbox):
    c = _church("dover")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    notifications.dispatch_pending()
    outbox.clear()
    ps.set_status(c["org"], pid, c["elder"], answered=True, text="Praise God")
    notifications.dispatch_pending()
    tos = _tos(outbox)
    assert "member@dover.org" in tos and "elder@dover.org" not in tos


def test_muted_subscriber_is_not_emailed(outbox):
    c = _church("elm")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    ps.set_muted(c["org"], pid, c["member"], True)
    notifications.dispatch_pending()
    outbox.clear()
    ps.add_update(c["org"], pid, c["elder"], "an update")
    notifications.dispatch_pending()
    assert "member@elm.org" not in _tos(outbox)  # muted -> silent


def test_delivery_failure_is_recorded_not_raised(monkeypatch):
    def boom(to, subject, body):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(notifications, "send_email", boom)
    c = _church("fern")
    ps.create_elder_request(c["org"], c["member"], "Need", "body")
    res = notifications.dispatch_pending()
    assert res["failed"] >= 1 and res["sent"] == 0


def test_notify_event_never_raises_on_bad_prayer():
    # Unknown prayer id must be a no-op, not an exception.
    assert notifications.notify_event("nope", "prayer.update", "missing", "x") == 0
