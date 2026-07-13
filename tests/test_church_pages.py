"""Frontend serving + the read endpoints the UI depends on."""
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


def _founder(app, church, email):
    c = TestClient(app)
    c.post("/api/churches", json={"church_name": church, "name": "Founder",
                                  "email": email, "password": "secret123"})
    return c


def test_frontend_is_served(app):
    c = TestClient(app)
    page = c.get("/church")
    assert page.status_code == 200
    assert "PrayerVault" in page.text and "/church.js" in page.text
    js = c.get("/church.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("application/javascript")


def test_mine_and_single_view(app):
    c = _founder(app, "Riverside Chapel", "founder@riverside.org")
    assert c.get("/api/mine").json() == []
    pid = c.post("/api/requests", json={"title": "Travel mercies", "body": "safe trip"}).json()["id"]
    mine = c.get("/api/mine").json()
    assert [p["id"] for p in mine] == [pid]
    one = c.get(f"/api/shared/{pid}").json()
    assert one["id"] == pid and one["title"] == "Travel mercies"


def test_single_view_blocked_across_churches(app):
    a = _founder(app, "Northgate Fellowship", "a@northgate.org")
    b = _founder(app, "Southgate Fellowship", "b@southgate.org")
    pid = a.post("/api/requests", json={"title": "Private need", "body": "x"}).json()["id"]
    # Founder of the other church cannot read it (invisible across tenants -> 400 not found)
    assert b.get(f"/api/shared/{pid}").status_code == 400
