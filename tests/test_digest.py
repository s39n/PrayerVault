"""Weekly digest builder/sender + notification preferences."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import accounts, db, models, notifications, orgs, prayer_service as ps


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
            "member": _add_user(org, "member", f"member@{base}.org")}


def test_digest_summarizes_recent_activity():
    c = _church("aspen")
    pid = ps.create_elder_request(c["org"], c["member"], "Surgery", "pray")
    ps.claim(c["org"], pid, c["elder"])
    ps.add_update(c["org"], pid, c["elder"], "Surgery went well")
    ps.set_status(c["org"], pid, c["elder"], answered=True, text="Full recovery")

    # The member follows this prayer -> digest mentions the answered prayer
    digest = notifications.build_weekly_digest(c["member"])
    assert digest is not None
    subject, body = digest
    assert "Surgery" in body and "answered" in body.lower()


def test_digest_is_none_when_nothing_happened():
    c = _church("birch")
    # member follows nothing -> no digest
    assert notifications.build_weekly_digest(c["member"]) is None


def test_send_weekly_digests_respects_day_and_prefs(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "send_email",
                        lambda to, subject, body: sent.append(to))
    c = _church("cypress")
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    ps.add_update(c["org"], pid, c["elder"], "moving along")
    # Member opts into a Wednesday(2) digest
    accounts.set_prefs(c["member"], digest_weekly=True, digest_day=2)

    # Wrong day -> nobody emailed
    assert notifications.send_weekly_digests(3)["sent"] == 0
    # Right day -> the member is emailed
    res = notifications.send_weekly_digests(2)
    assert res["sent"] >= 1 and f"member@cypress.org" in sent


def test_prefs_endpoints_roundtrip():
    app = FastAPI()
    from app import church_api
    app.include_router(church_api.router)
    c = TestClient(app)
    c.post("/api/churches", json={"church_name": "Dogwood Chapel", "name": "Deb",
                                  "email": "deb@dogwood.org", "password": "secret123"})
    assert c.get("/api/account/prefs").json()["email_enabled"] is True
    r = c.post("/api/account/prefs", json={"digest_weekly": True, "digest_day": 5,
                                           "email_enabled": False})
    body = r.json()
    assert body["digest_weekly"] is True and body["digest_day"] == 5
    assert body["email_enabled"] is False
    # persisted
    assert c.get("/api/account/prefs").json()["digest_day"] == 5
