"""Shepherding in the personal vault: outreach log, gone-quiet follow-up, drafts."""
import datetime
import os
import tempfile

os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("AUTH_USERNAME", "sean")
import bcrypt  # noqa: E402

os.environ.setdefault("AUTH_PASSWORD_HASH",
                      bcrypt.hashpw(b"testpass", bcrypt.gensalt(4)).decode())
os.environ.setdefault("VAULT_DIR", tempfile.mkdtemp())
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import notes, ollama_client, users  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

def _login():
    client.cookies.clear()
    assert client.post("/api/login",
                       json={"username": "sean", "password": "testpass"}).status_code == 200


def _backdate(note_id, days, root=None):
    """Age a prayer so the gone-quiet logic treats it as stale."""
    n = notes.read_note(note_id, root)
    old = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    n["sections"]["Updates"] = f"- {old} — Created"
    notes.write_note(note_id, n["frontmatter"], n["sections"], root)


# --- notes-level unit tests ---------------------------------------------

def test_outreach_and_followup_reset():
    root = tempfile.mkdtemp()
    pid = notes.create_note("request", "Surgery", "Pray for Ruth's surgery",
                            requested_by="Ruth", root=root)
    assert notes.follow_up_list(root, days=14) == []            # fresh, not overdue
    _backdate(pid, 30, root)
    assert [f["id"] for f in notes.follow_up_list(root, days=14)] == [pid]
    notes.log_outreach(pid, channel="call", note="Left a voicemail", root=root)
    assert notes.follow_up_list(root, days=14) == []            # contact reset the clock
    updates = notes.read_note(pid, root)["sections"]["Updates"]
    assert "Called Ruth" in updates and "voicemail" in updates


def test_outreach_validation_and_missing():
    root = tempfile.mkdtemp()
    pid = notes.create_note("prayer", "Mine", "text", root=root)
    with pytest.raises(ValueError):
        notes.log_outreach(pid, channel="smoke-signal", root=root)
    with pytest.raises(FileNotFoundError):
        notes.log_outreach("2020-01-01 nope", channel="call", root=root)


def test_followup_excludes_answered_and_uses_latest_update():
    root = tempfile.mkdtemp()
    pid = notes.create_note("request", "Job", "Pray", requested_by="John", root=root)
    _backdate(pid, 30, root)
    # A recent ordinary update also clears it from the list
    notes.add_update(pid, "Talked at church", root=root)
    assert notes.follow_up_list(root, days=14) == []
    # Answered prayers never nag, even when long quiet
    _backdate(pid, 30, root)
    notes.set_status(pid, "answered", "Got the job!", root=root)
    assert notes.follow_up_list(root, days=14) == []


# --- HTTP endpoint tests -------------------------------------------------

def test_followup_and_outreach_endpoints(monkeypatch):
    async def fake_generate(*a, **k):
        return None
    monkeypatch.setattr(ollama_client, "generate", fake_generate)
    _login()
    root = users.vault_for("sean")
    pid = client.post("/api/prayers", json={
        "type": "request", "title": "Endpoint Surgery",
        "text": "Pray for Ruth", "requested_by": "Ruth"}).json()["id"]

    assert pid not in [f["id"] for f in client.get("/api/follow-up").json()]
    _backdate(pid, 30, root)
    row = next(f for f in client.get("/api/follow-up").json() if f["id"] == pid)
    assert row["for"] == "Ruth" and row["days_since"] >= 30

    assert client.post(f"/api/prayers/{pid}/outreach",
                       json={"channel": "call", "note": "Voicemail"}).json() == {"ok": True}
    assert pid not in [f["id"] for f in client.get("/api/follow-up").json()]
    assert client.post(f"/api/prayers/{pid}/outreach",
                       json={"channel": "bogus"}).status_code == 422
    assert client.post("/api/prayers/does-not-exist/outreach",
                       json={"channel": "call"}).status_code == 404


def test_draft_checkin_endpoint(monkeypatch):
    async def fake_generate(*a, **k):
        return None
    seen = {}

    async def fake_draft(subject, title, context):
        seen.update(subject=subject, title=title, context=context)
        return "Hi Ruth, thinking of you and praying this week."

    monkeypatch.setattr(ollama_client, "generate", fake_generate)
    monkeypatch.setattr(ollama_client, "draft_checkin", fake_draft)
    _login()
    pid = client.post("/api/prayers", json={
        "type": "request", "title": "Interview",
        "text": "Pray for Ruth's interview Thursday",
        "requested_by": "Ruth"}).json()["id"]

    r = client.post(f"/api/prayers/{pid}/draft-checkin")
    assert r.status_code == 200, r.text
    assert r.json() == {"draft": "Hi Ruth, thinking of you and praying this week."}
    assert seen["subject"] == "Ruth"                 # drafts to the person, not the title
    assert "interview" in seen["context"].lower()    # grounded in member-visible context

    assert client.post("/api/prayers/does-not-exist/draft-checkin").status_code == 404
