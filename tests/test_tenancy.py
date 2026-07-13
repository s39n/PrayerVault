"""Tenant isolation — the load-bearing correctness property (plan §5b).

If any of these fail, one church can see or mutate another church's prayers.
Treat this file as security-critical.
"""
import pytest

from app import db, models
from app.db import Tenant, TenantError


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.init_db()


def _make_church(name, slug):
    with db.session_scope() as s:  # platform-level creation
        org = models.Organization(name=name, slug=slug, status="active")
        s.add(org)
        s.flush()  # org exists before user FK
        user = models.User(org_id=org.id, email=f"admin@{slug}.org",
                           display_name=f"{name} Admin", auth_provider="google",
                           google_sub=f"sub-{slug}")
        s.add(user)
        s.flush()  # user exists before membership FK
        s.add(models.Membership(org_id=org.id, user_id=user.id, role="admin"))
        s.flush()
        return org.id, user.id


def _add_prayer(org_id, owner_id, title):
    with db.tenant_scope(org_id) as t:
        p = t.add(models.Prayer(title=title, kind="request", owner_id=owner_id,
                                visibility="elders", body_md="Please pray."))
        t.session.flush()
        return p.id


def test_reads_are_scoped_to_the_church():
    a_org, a_user = _make_church("Grace", "grace")
    b_org, b_user = _make_church("Trinity", "trinity")
    a_prayer = _add_prayer(a_org, a_user, "Grace prayer")
    b_prayer = _add_prayer(b_org, b_user, "Trinity prayer")

    with db.tenant_scope(a_org) as t:
        titles = {p.title for p in t.all(models.Prayer)}
        assert titles == {"Grace prayer"}
        # Church A cannot fetch Church B's prayer by id
        assert t.get(models.Prayer, b_prayer) is None
        # ...but sees its own
        assert t.get(models.Prayer, a_prayer).title == "Grace prayer"

    with db.tenant_scope(b_org) as t:
        assert {p.title for p in t.all(models.Prayer)} == {"Trinity prayer"}


def test_cross_tenant_write_is_blocked():
    a_org, a_user = _make_church("Hope", "hope")
    b_org, _ = _make_church("Zion", "zion")
    # Try to smuggle a row tagged for church B into church A's tenant
    with db.tenant_scope(a_org) as t:
        rogue = models.Prayer(org_id=b_org, title="rogue", body_md="x")
        with pytest.raises(TenantError):
            t.add(rogue)


def test_org_id_is_stamped_from_the_tenant_not_the_caller():
    a_org, a_user = _make_church("Cornerstone", "tn-cornerstone")
    with db.tenant_scope(a_org) as t:
        p = t.add(models.Prayer(title="unstamped", body_md="x"))  # no org_id given
        t.session.flush()
        assert p.org_id == a_org


def test_organization_reads_only_self():
    a_org, _ = _make_church("Emmanuel", "tn-emmanuel")
    b_org, _ = _make_church("Redeemer", "tn-redeemer")
    with db.tenant_scope(a_org) as t:
        assert t.organization().id == a_org
        assert t.get(models.Organization, b_org) is None
        assert {o.id for o in t.all(models.Organization)} == {a_org}


def test_cross_tenant_delete_is_blocked():
    a_org, a_user = _make_church("Shiloh", "shiloh")
    b_org, b_user = _make_church("Bethel", "bethel")
    b_prayer = _add_prayer(b_org, b_user, "Bethel prayer")
    with db.tenant_scope(a_org) as t:
        # Load B's prayer through B, then try to delete it via A's tenant
        b_obj = t.session.get(models.Prayer, b_prayer)  # raw fetch, bypassing scope
        with pytest.raises(TenantError):
            t.delete(b_obj)


def test_tenant_requires_org_id():
    with pytest.raises(TenantError):
        Tenant(session=None, org_id="")
