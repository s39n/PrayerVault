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

from app import notes, ollama_client  # noqa: E402
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
