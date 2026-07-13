"""Church (tenant) creation, verification, and membership lookups."""
import pytest

from app import db, models, orgs
from app.orgs import OrgError


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


def test_create_church_makes_founder_an_admin():
    # Distinctive name so the slug assertion holds in the shared test DB.
    r = orgs.create_church("Alpha Test Kirk", "pastor@alphakirk.org", "Pastor Bob")
    assert r["status"] == "pending_verify"
    assert r["slug"] == "alpha-test-kirk"
    assert r["verify_token"]
    # Founder is an admin member of the new church
    assert orgs.membership_role(r["org_id"], r["user_id"]) == "admin"
    # Default settings applied
    assert orgs.follow_up_days(r["org_id"]) == 7
    # Church is not usable until verified
    assert orgs.is_active(r["org_id"]) is False


def test_slugs_are_unique_across_same_named_churches():
    # A distinctive name so the assertion holds regardless of other churches
    # created in the shared test database.
    a = orgs.create_church("Zzq Slugtest Fellowship", "a@zzq.org")
    b = orgs.create_church("Zzq Slugtest Fellowship", "b@zzq.org")
    assert a["slug"] == "zzq-slugtest-fellowship"
    assert b["slug"] == "zzq-slugtest-fellowship-2"
    assert a["org_id"] != b["org_id"]


def test_verify_activates_the_church_and_is_idempotent():
    r = orgs.create_church("Hope Chapel", "founder@hope.org")
    assert orgs.is_active(r["org_id"]) is False
    org_id = orgs.verify_church(r["verify_token"])
    assert org_id == r["org_id"]
    assert orgs.is_active(r["org_id"]) is True
    # Verifying again is a harmless no-op
    assert orgs.verify_church(r["verify_token"]) == r["org_id"]


def test_verify_rejects_a_bad_token():
    with pytest.raises(OrgError):
        orgs.verify_church("not-a-real-token")


def test_auto_active_skips_verification():
    r = orgs.create_church("Zion Fellowship", "z@zion.org", auto_active=True)
    assert r["status"] == "active"
    assert orgs.is_active(r["org_id"]) is True


def test_founder_lookup_by_google_sub():
    r = orgs.create_church("Emmanuel", "e@emmanuel.org", google_sub="google-123")
    u = orgs.user_by_google_sub("google-123")
    assert u is not None and u.id == r["user_id"] and u.org_id == r["org_id"]
    assert orgs.user_by_google_sub("nobody") is None


def test_created_church_is_tenant_scoped():
    r = orgs.create_church("Redeemer", "r@redeemer.org", auto_active=True)
    other = orgs.create_church("Cornerstone", "c@corner.org", auto_active=True)
    # A tenant bound to Redeemer sees its own admin user, not Cornerstone's
    with db.tenant_scope(r["org_id"]) as t:
        users = t.all(models.User)
        assert {u.org_id for u in users} == {r["org_id"]}
        assert t.get(models.User, other["user_id"]) is None


def test_missing_name_or_email_rejected():
    with pytest.raises(OrgError):
        orgs.create_church("", "x@y.org")
    with pytest.raises(OrgError):
        orgs.create_church("No Email Church", "")
