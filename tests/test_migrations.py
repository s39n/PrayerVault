"""Alembic migration path: db.migrate() brings the schema up to head."""
from sqlalchemy import inspect

from app import db

ALL_TABLES = {
    "organizations", "users", "memberships", "groups", "group_members",
    "prayers", "prayer_shares", "prayer_updates", "pastoral_notes",
    "subscriptions", "notification_prefs", "notifications", "invitations",
}


def test_migrate_brings_schema_to_head():
    db.migrate()
    names = set(inspect(db.engine).get_table_names())
    # Alembic recorded the version and every table exists
    assert "alembic_version" in names
    assert ALL_TABLES.issubset(names)


def test_migrate_is_idempotent():
    db.migrate()
    db.migrate()  # running again is a harmless no-op
    assert "organizations" in set(inspect(db.engine).get_table_names())
