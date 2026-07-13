"""End-to-end HTTP test of the whole 'request prayer from the elders' journey.

Mounts only the church router on a fresh app (no legacy vault routes needed) and
drives it with a separate TestClient per person, so each carries its own login
cookie — the way three real people in a church would use it.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import church_api, db


@pytest.fixture(scope="module")
def app():
    db.init_db()
    a = FastAPI()
    a.include_router(church_api.router)
    return a


def _client(app):
    return TestClient(app)


def test_full_journey_over_http(app):
    founder = _client(app)
    elder = _client(app)
    member = _client(app)

    # 1. Founder self-serves a church and is logged in as admin
    r = founder.post("/api/churches", json={
        "church_name": "Grace Presbyterian", "name": "Pastor Bob",
        "email": "bob@grace.org", "password": "secret123"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert founder.get("/api/account/me").json()["role"] == "admin"

    # Founder verifies the church (email link)
    verify = r.json()["verify_token"]
    assert founder.post("/api/churches/verify", json={"token": verify}).json()["ok"]

    # 2. Founder invites an elder and a member; each accepts and is logged in
    tok_e = founder.post("/api/invites", json={
        "email": "eli@grace.org", "church_role": "elder"}).json()["token"]
    assert elder.post("/api/invites/accept", json={
        "token": tok_e, "name": "Elder Eli", "password": "elderpass"}).json()["role"] == "elder"

    tok_m = founder.post("/api/invites", json={
        "email": "mary@grace.org", "church_role": "member"}).json()["token"]
    assert member.post("/api/invites/accept", json={
        "token": tok_m, "name": "Mary", "password": "memberpass"}).json()["role"] == "member"

    # 3. Member sends a request to the elders
    pid = member.post("/api/requests", json={
        "title": "Job interview", "body": "Pray for John's interview Thursday",
        "subject_name": "John"}).json()["id"]

    # 4. It shows in the elder queue; a plain member is forbidden from that view
    q = elder.get("/api/elders/queue").json()
    assert [p["id"] for p in q] == [pid] and q[0]["subject_name"] == "John"
    assert member.get("/api/elders/queue").status_code == 403

    # 5. Elder claims it -> becomes owner, queue clears, appears in "my flock"
    assert elder.post(f"/api/shared/{pid}/claim").json()["ok"]
    assert elder.get("/api/elders/queue").json() == []
    flock = elder.get("/api/elders/flock").json()
    assert [p["id"] for p in flock] == [pid]

    # 6. Member (a subscriber) adds an update; a non-following outsider can't
    assert member.post(f"/api/shared/{pid}/updates",
                       json={"text": "Interview moved to Friday"}).json()["ok"]

    # 7. Elder marks it answered
    assert elder.post(f"/api/shared/{pid}/status",
                      json={"answered": True, "text": "He got the job!"}).json()["ok"]

    # 8. Timeline reads correctly for the member
    tl = member.get(f"/api/shared/{pid}/timeline").json()
    assert [u["kind"] for u in tl] == ["created", "update", "update", "answered"]
    assert "He got the job!" in tl[-1]["text"]

    # 9. Pastoral notes are elder-only and never in the member timeline
    assert elder.post(f"/api/shared/{pid}/notes",
                      json={"text": "Called Tuesday, following up"}).json()["id"]
    assert len(elder.get(f"/api/shared/{pid}/notes").json()) == 1
    assert member.get(f"/api/shared/{pid}/notes").status_code == 403
    tl_text = " ".join(u["text"] for u in member.get(f"/api/shared/{pid}/timeline").json())
    assert "Called Tuesday" not in tl_text

    # 10. Answered prayer reflected in the elder's flock
    assert elder.get("/api/elders/flock").json()[0]["status"] == "answered"


def test_unauthenticated_is_rejected(app):
    anon = _client(app)
    assert anon.get("/api/account/me").status_code == 401
    assert anon.get("/api/elders/queue").status_code == 401
    assert anon.post("/api/requests", json={"title": "x"}).status_code == 401


def test_login_after_signup(app):
    c = _client(app)
    c.post("/api/churches", json={
        "church_name": "Hope Chapel", "name": "Ann", "email": "ann@hope.org",
        "password": "hopepass"})
    fresh = _client(app)
    assert fresh.post("/api/account/login", json={
        "email": "ann@hope.org", "password": "hopepass"}).json()["role"] == "admin"
    assert fresh.post("/api/account/login", json={
        "email": "ann@hope.org", "password": "wrong"}).status_code == 401
