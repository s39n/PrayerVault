"""Invitation emails + deferred delivery when SMTP isn't configured yet."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db, models, notifications, orgs, prayer_service as ps


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


@pytest.fixture
def app():
    a = FastAPI()
    from app import church_api
    a.include_router(church_api.router)
    return a


def test_creating_an_invite_emails_the_link(app, monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "send_email",
                        lambda to, subject, body: sent.append({"to": to, "body": body}))
    c = TestClient(app)
    c.post("/api/churches", json={"church_name": "Willow Creek", "name": "Pastor Sam",
                                  "email": "sam@willow.org", "password": "secret123"})
    r = c.post("/api/invites", json={"email": "newperson@willow.org", "church_role": "member"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["accept_url"].endswith(token)  # link carries the invite token
    # The background task delivered an email to the invitee containing that link
    assert len(sent) == 1
    assert sent[0]["to"] == "newperson@willow.org"
    assert token in sent[0]["body"] and "Willow Creek" in sent[0]["body"]


def test_unconfigured_smtp_defers_instead_of_failing():
    # No monkeypatch: the real sender runs and, with no SMTP_HOST, raises
    # SmtpNotConfigured -> the row stays queued for a later retry.
    r = orgs.create_church("Maple Grove", "admin@maple.org", auto_active=True)
    org = r["org_id"]
    with db.session_scope() as s:
        u = models.User(org_id=org, email="mem@maple.org", display_name="Mem")
        s.add(u); s.flush()
        s.add(models.Membership(org_id=org, user_id=u.id, role="member"))
        s.flush()
        member_id = u.id
    pid = ps.create_elder_request(org, member_id, "A need", "body")  # queues elder notice

    res = notifications.dispatch_pending()
    assert res["deferred"] >= 1
    # The queued notification for this church is still queued (not failed)
    with db.session_scope() as s:
        from sqlmodel import select
        rows = s.exec(select(models.Notification).where(models.Notification.org_id == org)).all()
        assert rows and all(n.status == "queued" for n in rows)
