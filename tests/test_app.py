import os
import tempfile

os.environ["SESSION_SECRET"] = "test-secret"
os.environ["AUTH_USERNAME"] = "sean"
# bcrypt hash of "testpass" generated at import time
import bcrypt  # noqa: E402

os.environ["AUTH_PASSWORD_HASH"] = bcrypt.hashpw(b"testpass", bcrypt.gensalt(4)).decode()
os.environ["VAULT_DIR"] = tempfile.mkdtemp()
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import notes, notify, ollama_client, settings  # noqa: E402, F401
from app.main import app  # noqa: E402

client = TestClient(app)

FAKE_AI = {
    "scripture": [
        {"book": "Psalm", "chapter": 46, "verse_start": 1, "verse_end": 3,
         "why": "God is our refuge in trouble."},
        {"book": "John", "chapter": 14, "verse_start": 27, "verse_end": 27,
         "why": "Christ gives peace."},
    ],
    "reflection": "As Psalm 46 reminds us, God is a very present help.",
    "prompts": ["Adore God as refuge.", "Confess anxiety.", "Give thanks for Christ's peace."],
}


def test_requires_auth():
    assert client.get("/api/prayers").status_code == 401


def test_bad_login():
    r = client.post("/api/login", json={"username": "sean", "password": "wrong"})
    assert r.status_code == 401


def test_login_and_crud(monkeypatch):
    async def fake_generate(kind, title, text, requested_by=""):
        return ollama_client._shape(FAKE_AI)

    monkeypatch.setattr(ollama_client, "generate", fake_generate)

    r = client.post("/api/login", json={"username": "sean", "password": "testpass"})
    assert r.status_code == 200

    r = client.post("/api/prayers", json={
        "type": "request", "title": "Healing for a friend",
        "text": "Please pray for my friend recovering from surgery.",
        "requested_by": "The Smiths"})
    assert r.status_code == 200
    nid = r.json()["id"]

    n = client.get(f"/api/prayers/{nid}").json()
    assert n["frontmatter"]["status"] == "ongoing"
    assert n["frontmatter"]["ai"] == "done"  # TestClient runs bg tasks synchronously
    assert "[[Psalm 46#1|Psalm 46:1-3]]" in n["sections"]["Scripture"]
    assert "[[John 14#27|John 14:27]]" in n["sections"]["Scripture"]
    assert "Psalm 46" in n["sections"]["Reflection"]
    assert n["sections"]["How to Pray"].count("- ") == 3

    # File on disk is valid Obsidian markdown
    raw = (notes.vault_dir() / f"{nid}.md").read_text()
    assert raw.startswith("---\n")
    assert "## Prayer" in raw and "## Scripture" in raw and "## Updates" in raw
    assert "prayer/request" in raw

    # Updates + answered flow
    r = client.post(f"/api/prayers/{nid}/updates", json={"text": "Surgery went well"})
    assert r.status_code == 200
    r = client.post(f"/api/prayers/{nid}/answered", json={"text": "Full recovery!"})
    assert r.status_code == 200
    n = client.get(f"/api/prayers/{nid}").json()
    assert n["frontmatter"]["status"] == "answered"
    assert "answered-date" in n["frontmatter"]
    assert "Full recovery!" in n["sections"]["Updates"]

    items = client.get("/api/prayers").json()
    assert any(i["id"] == nid and i["status"] == "answered" for i in items)


def test_path_traversal_blocked():
    client.post("/api/login", json={"username": "sean", "password": "testpass"})
    r = client.get("/api/prayers/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (404, 422)


def test_wikilink_format():
    assert ollama_client._wikilink("John", 1, 13, 13) == "[[John 1#13|John 1:13]]"
    assert ollama_client._wikilink("John", 1, 13, 16) == "[[John 1#13|John 1:13-16]]"


def test_semantic_search_and_related(monkeypatch):
    from app import embeddings

    async def fake_embed(text, is_query=False):
        # crude deterministic vectors: axis 0 = sleep-ish, axis 1 = health-ish
        t = text.lower()
        return [1.0 if "sleep" in t else 0.0, 1.0 if ("surgery" in t or "health" in t) else 0.0, 0.1]

    async def fake_generate(kind, title, text, requested_by=""):
        return ollama_client._shape(FAKE_AI)

    monkeypatch.setattr(embeddings, "_embed", fake_embed)
    monkeypatch.setattr(ollama_client, "generate", fake_generate)
    client.post("/api/login", json={"username": "sean", "password": "testpass"})

    a = client.post("/api/prayers", json={"type": "prayer", "title": "Safe Sleep",
        "text": "Praying the kids sleep peacefully tonight."}).json()["id"]
    b = client.post("/api/prayers", json={"type": "prayer", "title": "Restful Sleep for Eli",
        "text": "That Eli would sleep through the night."}).json()["id"]

    r = client.get("/api/search", params={"q": "trouble sleeping"})
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert ids[0] in (a, b) and ids[1] in (a, b)
    assert all("score" in x for x in r.json())

    # second sleep prayer should have picked up a Related link to the first
    n = client.get(f"/api/prayers/{b}").json()
    assert "Related" in n["sections"]


def test_ask_endpoint(monkeypatch):
    async def fake_ask(question):
        return {"scripture_md": "- [[Psalm 46#1|Psalm 46:1]] — refuge",
                "answer": "As Psalm 46 reminds us, God is our refuge."}
    monkeypatch.setattr(ollama_client, "ask", fake_ask)
    client.post("/api/login", json={"username": "sean", "password": "testpass"})
    r = client.post("/api/ask", json={"question": "How do I find peace?"})
    assert r.status_code == 200
    body = r.json()
    assert "Psalm 46" in body["scripture_md"]
    assert body["answer"].startswith("As Psalm 46")
    # empty question rejected by validation
    assert client.post("/api/ask", json={"question": ""}).status_code == 422


def test_settings_roundtrip():
    client.post("/api/login", json={"username": "sean", "password": "testpass"})
    assert "morning" in client.get("/api/settings").json()
    r = client.post("/api/settings", json={"morning": {
        "enabled": True, "delivery": "ntfy", "ntfy_topic": "my-secret-topic",
        "hour": 8, "minute": 30}})
    m = r.json()["morning"]
    assert m["enabled"] is True and m["delivery"] == "ntfy"
    assert m["ntfy_topic"] == "my-secret-topic" and m["hour"] == 8 and m["minute"] == 30
    m = client.post("/api/settings", json={"morning": {
        "hour": 99, "minute": -5, "delivery": "bogus"}}).json()["morning"]
    assert m["hour"] == 23 and m["minute"] == 0 and m["delivery"] == "none"


def test_notify_test_push(monkeypatch):
    sent = {}
    async def fake_send(topic, title, body):
        sent.update(topic=topic, title=title, body=body)
    monkeypatch.setattr(notify, "send_ntfy", fake_send)
    client.post("/api/login", json={"username": "sean", "password": "testpass"})
    client.post("/api/settings", json={"morning": {"delivery": "ntfy", "ntfy_topic": "topic123"}})
    r = client.post("/api/notify/test", json={})
    assert r.status_code == 200
    assert sent["topic"] == "topic123" and sent["title"] and sent["body"]
    client.post("/api/settings", json={"morning": {"delivery": "ntfy", "ntfy_topic": ""}})
    assert client.post("/api/notify/test", json={}).status_code == 422


def test_transcribe(monkeypatch):
    from app import stt

    async def fake_transcribe(data, filename, content_type):
        assert data == b"fake-audio-bytes"
        return "Lord, thank you for this day."

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    client.post("/api/login", json={"username": "sean", "password": "testpass"})
    r = client.post("/api/transcribe",
                    files={"audio": ("prayer.webm", b"fake-audio-bytes", "audio/webm")})
    assert r.status_code == 200
    assert r.json()["text"] == "Lord, thank you for this day."

    r = client.post("/api/transcribe", files={"audio": ("empty.webm", b"", "audio/webm")})
    assert r.status_code == 422
