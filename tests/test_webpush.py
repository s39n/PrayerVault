"""Web push channel: subscription storage, channel selection, delivery."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import (config, db, models, notifications, orgs,
                 prayer_service as ps, webpush)

SUB = {"endpoint": "https://push.example/abc",
       "keys": {"p256dh": "BPtest", "auth": "atest"}}


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


@pytest.fixture
def vapid(monkeypatch):
    """Pretend VAPID is configured and capture pushes instead of sending them."""
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "BPUBLICKEY")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "PRIVATEKEY")
    pushes = []
    monkeypatch.setattr(webpush, "send_raw", lambda sub, payload: pushes.append((sub, payload)))
    return pushes


def _add_user(org_id, role, email):
    with db.session_scope() as s:
        u = models.User(org_id=org_id, email=email, display_name=email.split("@")[0])
        s.add(u); s.flush()
        s.add(models.Membership(org_id=org_id, user_id=u.id, role=role)); s.flush()
        return u.id


def _church(base):
    r = orgs.create_church(f"{base} Church", f"admin@{base}.org", auto_active=True)
    org = r["org_id"]
    return {"org": org, "admin": r["user_id"],
            "elder": _add_user(org, "elder", f"elder@{base}.org"),
            "member": _add_user(org, "member", f"member@{base}.org")}


def test_available_reflects_config(monkeypatch):
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "")
    assert webpush.available() is False
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "x")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "y")
    assert webpush.available() is True


def test_subscription_enables_the_webpush_channel(vapid):
    c = _church("pine")
    webpush.save_subscription(c["member"], SUB)
    with db.session_scope() as s:
        prefs = s.get(models.NotificationPref, c["member"])
        assert prefs.webpush_enabled and prefs.webpush_subscription == SUB
        assert "webpush" in notifications._channels_for(prefs)


def test_event_delivers_a_push_to_a_subscribed_follower(vapid):
    c = _church("oak")
    webpush.save_subscription(c["member"], SUB)
    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])  # notifies the member (a subscriber)
    res = notifications.dispatch_pending()
    assert res["sent"] >= 1
    assert vapid and vapid[0][0] == SUB  # the captured push went to the member's sub


def test_dead_subscription_is_dropped(vapid, monkeypatch):
    c = _church("elm2")
    webpush.save_subscription(c["member"], SUB)

    def gone(sub, payload):
        raise webpush.PushGone("410")
    monkeypatch.setattr(webpush, "send_raw", gone)

    pid = ps.create_elder_request(c["org"], c["member"], "Need", "body")
    ps.claim(c["org"], pid, c["elder"])
    notifications.dispatch_pending()
    # The dead subscription was cleared so we won't keep retrying it
    with db.session_scope() as s:
        prefs = s.get(models.NotificationPref, c["member"])
        assert prefs.webpush_subscription is None and prefs.webpush_enabled is False


def test_push_endpoints():
    app = FastAPI()
    from app import church_api
    app.include_router(church_api.router)
    cl = TestClient(app)
    cl.post("/api/churches", json={"church_name": "Cedar Ridge", "name": "Cy",
                                   "email": "cy@cedarridge.org", "password": "secret123"})
    key = cl.get("/api/push/key").json()
    assert "enabled" in key and "key" in key
    assert cl.post("/api/push/subscribe", json={"subscription": SUB}).json()["ok"]
    assert cl.post("/api/push/unsubscribe").json()["ok"]
