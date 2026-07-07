"""Per-user storage.

The admin (password login) keeps the Obsidian vault at VAULT_DIR, exactly as
before. Google users are identified as "g:<sub>" (Google's stable account id)
and each gets their own folder under USERS_DIR — their prayers never touch the
admin's vault.
"""
import json
import re
from pathlib import Path

from . import config

_SUB_RE = re.compile(r"^[0-9]{1,64}$")


def is_admin(user: str) -> bool:
    return not user.startswith("g:")


def _users_dir() -> Path:
    d = Path(config.USERS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(user: str) -> str:
    sub = user[2:]
    if not _SUB_RE.match(sub):
        raise ValueError("Invalid user id")
    return sub


def vault_for(user: str) -> Path:
    """Directory this user's prayer notes live in."""
    if is_admin(user):
        d = Path(config.VAULT_DIR)
    else:
        d = _users_dir() / _sub(user) / "prayers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_profile(sub: str, email: str, name: str) -> None:
    if not _SUB_RE.match(sub):
        raise ValueError("Invalid user id")
    d = _users_dir() / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.json").write_text(
        json.dumps({"email": email, "name": name}), encoding="utf-8")


def profile(user: str) -> dict:
    if is_admin(user):
        return {"email": "", "name": user}
    try:
        p = _users_dir() / _sub(user) / "profile.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"email": "", "name": "Friend"}
