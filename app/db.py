"""Database engine + the tenant-isolation choke point.

Everything that touches church-owned data goes through :class:`Tenant`, a thin
wrapper over a SQLModel session bound to a single ``org_id``. It:

* stamps ``org_id`` on every row it inserts (and refuses a mismatched one),
* filters every read by ``org_id``,
* returns ``None`` for any object that belongs to a different church.

This is the single most important correctness property of the multi-church design
(plan §5b): a request for church A can never see or mutate church B's rows, because
the ``org_id`` comes from the server-resolved session — never from client input.
Route handlers should obtain a ``Tenant`` and never build raw cross-org queries.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from . import config, models

T = TypeVar("T", bound=SQLModel)

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, echo=False, connect_args=_connect_args)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
    """Enforce foreign keys on SQLite (off by default)."""
    if config.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def init_db() -> None:
    """Create tables if they don't exist. Alembic owns migrations in production;
    this keeps tests and first-run local dev zero-config."""
    if config.DATABASE_URL.startswith("sqlite"):
        path = config.DATABASE_URL.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A committing session context. Use for platform-level (superadmin) work."""
    with Session(engine, expire_on_commit=False) as s:
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise


class TenantError(RuntimeError):
    """Raised on an attempt to cross the tenant boundary."""


class Tenant:
    """A church-scoped view over a session. All church data access flows here."""

    def __init__(self, session: Session, org_id: str):
        if not org_id:
            raise TenantError("Tenant requires an org_id")
        self.session = session
        self.org_id = org_id

    # -- writes -----------------------------------------------------------
    def add(self, obj: T) -> T:
        """Insert, stamping org_id. Refuses an object tagged for another church."""
        if isinstance(obj, models.Organization):
            raise TenantError("Organizations are managed at the platform layer")
        if hasattr(obj, "org_id"):
            current = getattr(obj, "org_id", None)
            if not current:
                obj.org_id = self.org_id
            elif current != self.org_id:
                raise TenantError("cross-tenant write blocked")
        self.session.add(obj)
        return obj

    # -- reads ------------------------------------------------------------
    def get(self, model: type[T], id: str) -> T | None:
        """Fetch by primary key, but only if it belongs to this church."""
        obj = self.session.get(model, id)
        if obj is None:
            return None
        if not self._belongs(obj):
            return None  # invisible across the tenant boundary
        return obj

    def all(self, model: type[T], *where) -> list[T]:
        """Select rows of ``model`` for this church, with optional extra filters."""
        stmt = self._scoped_select(model)
        for clause in where:
            stmt = stmt.where(clause)
        return list(self.session.exec(stmt))

    def one_or_none(self, model: type[T], *where) -> T | None:
        rows = self.all(model, *where)
        return rows[0] if rows else None

    def organization(self) -> models.Organization | None:
        """This tenant's own church row (the only Organization it may read)."""
        return self.session.get(models.Organization, self.org_id)

    # -- lifecycle --------------------------------------------------------
    def commit(self) -> None:
        self.session.commit()

    def refresh(self, obj: T) -> T:
        self.session.refresh(obj)
        return obj

    def delete(self, obj: T) -> None:
        if not self._belongs(obj):
            raise TenantError("cross-tenant delete blocked")
        self.session.delete(obj)

    # -- internals --------------------------------------------------------
    def _scoped_select(self, model: type[T]):
        stmt = select(model)
        if hasattr(model, "org_id"):
            stmt = stmt.where(model.org_id == self.org_id)
        elif model is models.Organization:
            stmt = stmt.where(model.id == self.org_id)
        return stmt

    def _belongs(self, obj) -> bool:
        if isinstance(obj, models.Organization):
            return obj.id == self.org_id
        if hasattr(obj, "org_id"):
            return getattr(obj, "org_id", None) == self.org_id
        return True  # models without an org gate (e.g. NotificationPref by user) — caller guards


@contextmanager
def tenant_scope(org_id: str) -> Iterator[Tenant]:
    """Open a committing, church-scoped unit of work."""
    with Session(engine, expire_on_commit=False) as s:
        t = Tenant(s, org_id)
        try:
            yield t
            s.commit()
        except Exception:
            s.rollback()
            raise
