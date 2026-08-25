"""People & Families — a light registry so prayers can be filed under a person or
family in the personal journal.

No database: one small ``families.json`` per user, stored next to that user's
prayer notes (``<vault>/.prayervault/families.json``). A prayer note is linked to a
family by a ``family: <id>`` line in its YAML frontmatter (see notes.py). Deleting a
family only removes the registry entry — the prayer notes themselves are never
touched (they just become unfiled).
"""
import datetime
import json
import re
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


def _path(root: Path | str) -> Path:
    return Path(root) / ".prayervault" / "families.json"


def _load(root: Path | str) -> dict:
    p = _path(root)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data.get("families"), list):
                return data
        except Exception:
            pass
    return {"families": []}


def _save(root: Path | str, data: dict) -> None:
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60]


def list_families(root: Path | str) -> list[dict]:
    return _load(root).get("families", [])


def get_family(family_id: str, root: Path | str) -> dict | None:
    for f in list_families(root):
        if f.get("id") == family_id:
            return f
    return None


def create_family(name: str, root: Path | str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("A name is required")
    data = _load(root)
    base = _slug(name) or "family"
    existing = {f["id"] for f in data["families"]}
    fid, n = base, 2
    while fid in existing:
        fid = f"{base}-{n}"
        n += 1
    fam = {"id": fid, "name": name[:120], "created": datetime.date.today().isoformat()}
    data.setdefault("families", []).append(fam)
    _save(root, data)
    return fam


def rename_family(family_id: str, name: str, root: Path | str) -> dict | None:
    data = _load(root)
    for f in data.get("families", []):
        if f["id"] == family_id:
            f["name"] = (name or f["name"]).strip()[:120]
            _save(root, data)
            return f
    return None


def delete_family(family_id: str, root: Path | str) -> bool:
    data = _load(root)
    fams = data.get("families", [])
    kept = [f for f in fams if f.get("id") != family_id]
    if len(kept) == len(fams):
        return False
    data["families"] = kept
    _save(root, data)
    return True
