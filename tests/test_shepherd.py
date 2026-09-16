"""Shepherding nudges: outreach logging, follow-up resets, check-in drafts."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import church_api, db, models, notifications, ollama_client, orgs
from app import prayer_service as ps
from app.prayer_service import PermissionDenied, PrayerError


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
    return {
        "org": org,
        "elder": _add_user(org, "elder", f"elder@{base}.org"),
        "member": _add_user(org, "member", f"member@{base}.org"),
    }


def _backdate_updates(org_id, prayer_id, days_ago):
    """Age every update on a prayer so follow-up logic sees it as stale."""
    with db.tenant_scope(org_id) as t:
        for u in t.all(models.PrayerUpdate, models.PrayerUpdate.prayer_id == prayer_id):
            u.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
            t.add(u)


def test_outreach_resets_followup_clock():
    c = _church("shep1")
    pid = ps.create_elder_request(c["org"], c["member"], "Surgery",
                                  "Pray for Ruth's surgery", subject_name="Ruth")
    ps.claim(c["org"], pid, c["elder"])
    _backdate_updates(c["org"], pid, 10)

    assert [p["id"] for p in ps.follow_up_list(c["org"], c["elder"], days=7)] == [pid]

    ps.log_outreach(c["org"], pid, c["elder"], channel="call", note="Left a voicemail")
    assert ps.follow_up_list(c["org"], c["elder"], days=7) == []


def test_outreach_validation_and_permissions():
    c = _church("shep2")
    pid = ps.create_elder_request(c["org"], c["member"], "Surgery", "body")
    ps.claim(c["org"], pid, c["elder"])
    with pytest.raises(PrayerError):
        ps.log_outreach(c["org"], pid, c["elder"], channel="smoke-signal")
    with pytest.raises(PermissionDenied):
        ps.log_outreach(c["org"], pid, c["member"], channel="call")
    with pytest.raises(PrayerError):
        ps.log_outreach(c["org"], "nope", c["elder"], channel="call")


def test_outreach_hidden_from_member_timeline():
    c = _church("shep3")
    pid = ps.create_elder_request(c["org"], c["member"], "Surgery", "body")
    ps.claim(c["org"], pid, c["elder"])
    ps.log_outreach(c["org"], pid, c["elder"], channel="visit", note="Brought a meal")

    member_kinds = [u["kind"] for u in ps.timeline(c["org"], pid, c["member"])]
    assert "outreach" not in member_kinds
    elder_kinds = [u["kind"] for u in ps.timeline(c["org"], pid, c["elder"])]
    assert "outreach" in elder_kinds


def test_draft_checkin_uses_member_context_only(monkeypatch):
    c = _church("shep4")
    pid = ps.create_elder_request(c["org"], c["member"], "Job interview",
                                  "Pray for John's interview Thursday", subject_name="John")
    ps.claim(c["org"], pid, c["elder"])
    ps.add_pastoral_note(c["org"], pid, c["elder"], "SECRET-NOTE: marriage trouble")

    seen = {}

    async def fake_draft(subject, title, context):
        seen["subject"] = subject
        seen["context"] = context
        return "Hi John, thinking of you…"

    monkeypatch.setattr(ollama_client, "draft_checkin", fake_draft)
    out = asyncio.run(ps.draft_checkin(c["org"], pid, c["elder"]))
    assert out == {"draft": "Hi John, thinking of you…"}
    assert seen["subject"] == "John"
    assert "SECRET-NOTE" not in seen["context"]
    assert "interview" in seen["context"].lower()

    with pytest.raises(PermissionDenied):
        asyncio.run(ps.draft_checkin(c["org"], pid, c["member"]))


def test_digest_includes_shepherding_nudge():
    c = _church("shep5")
    pid = ps.create_elder_request(c["org"], c["member"], "Surgery",
                                  "body", subject_name="Ruth")
    ps.claim(c["org"], pid, c["elder"])
    _backdate_updates(c["org"], pid, 10)
    result = notifications.build_weekly_digest(c["elder"], days=7)
    assert result is not None
    subject, body = result
    assert "need a check-in" in body
    assert "Ruth" in body
    assert "Maybe this is a good time to reach out" in body


@pytest.fixture(scope="module")
def api_app():
    db.init_db()
    a = FastAPI()
    a.include_router(church_api.router)
    return a


def test_outreach_and_draft_endpoints_over_http(api_app, monkeypatch):
    founder = TestClient(api_app)
    elder = TestClient(api_app)
    member = TestClient(api_app)

    r = founder.post("/api/churches", json={
        "church_name": "Shep HTTP", "name": "Admin",
        "email": "sheph-admin@grace.org", "password": "secret123"})
    assert r.status_code == 200, r.text
    founder.post("/api/churches/verify", json={"token": r.json()["verify_token"]})

    tok_e = founder.post("/api/invites", json={
        "email": "sheph-elder@grace.org", "church_role": "elder"}).json()["token"]
    assert elder.post("/api/invites/accept", json={
        "token": tok_e, "name": "Elder", "password": "elderpass"}).status_code == 200
    tok_m = founder.post("/api/invites", json={
        "email": "sheph-member@grace.org", "church_role": "member"}).json()["token"]
    assert member.post("/api/invites/accept", json={
        "token": tok_m, "name": "Mary", "password": "memberpass"}).status_code == 200

    pid = member.post("/api/requests", json={
        "title": "Surgery", "body": "Pray for Ruth", "subject_name": "Ruth"}).json()["id"]
    assert elder.post(f"/api/shared/{pid}/claim").status_code == 200

    # Elder logs outreach; a member may not
    assert elder.post(f"/api/shared/{pid}/outreach",
                      json={"channel": "call", "note": "Voicemail"}).json() == {"ok": True}
    assert member.post(f"/api/shared/{pid}/outreach",
                       json={"channel": "call"}).status_code == 403
    assert elder.post(f"/api/shared/{pid}/outreach",
                      json={"channel": "bogus"}).status_code == 400

    # Outreach is invisible in the member's timeline
    kinds = [u["kind"] for u in member.get(f"/api/shared/{pid}/timeline").json()]
    assert "outreach" not in kinds

    # Draft check-in (Ollama stubbed); members forbidden
    async def fake_draft(subject, title, context):
        return "Hi Ruth, praying for you."

    monkeypatch.setattr(ollama_client, "draft_checkin", fake_draft)
    r = elder.post(f"/api/shared/{pid}/draft-checkin")
    assert r.status_code == 200, r.text
    assert r.json() == {"draft": "Hi Ruth, praying for you."}
    assert member.post(f"/api/shared/{pid}/draft-checkin").status_code == 403
