"""Read/write prayers as Obsidian-flavored Markdown notes in the vault."""
import datetime
import re
from pathlib import Path

import yaml

from . import config

SECTION_ORDER = ["Prayer", "Scripture", "Reflection", "How to Pray", "Updates"]
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-',]*$")


def vault_dir() -> Path:
    d = Path(config.VAULT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(title: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 \-']", "", title).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:80] or "Prayer"


def _safe_path(note_id: str) -> Path:
    if not ID_RE.match(note_id):
        raise ValueError("Invalid note id")
    p = (vault_dir() / f"{note_id}.md").resolve()
    if p.parent != vault_dir().resolve():
        raise ValueError("Invalid note id")
    return p


def parse_note(text: str) -> tuple[dict, dict[str, str]]:
    """Return (frontmatter, {section: body})."""
    fm: dict = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm = yaml.safe_load(text[4:end]) or {}
            body = text[end + 5:]
    sections: dict[str, str] = {}
    current = None
    lines: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            if current:
                sections[current] = "\n".join(lines).strip()
            current = m.group(1).strip()
            lines = []
        elif current:
            lines.append(line)
    if current:
        sections[current] = "\n".join(lines).strip()
    return fm, sections


def render_note(fm: dict, sections: dict[str, str]) -> str:
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    parts = [f"---\n{fm_text}\n---\n"]
    for name in SECTION_ORDER:
        if name in sections and sections[name].strip():
            parts.append(f"## {name}\n\n{sections[name].strip()}\n")
    for name, val in sections.items():
        if name not in SECTION_ORDER and val.strip():
            parts.append(f"## {name}\n\n{val.strip()}\n")
    return "\n".join(parts)


def create_note(kind: str, title: str, text: str, requested_by: str = "") -> str:
    today = datetime.date.today().isoformat()
    slug = slugify(title)
    note_id = f"{today} {slug}"
    path = _safe_path(note_id)
    n = 2
    while path.exists():
        note_id = f"{today} {slug} {n}"
        path = _safe_path(note_id)
        n += 1
    fm = {
        "title": slug,
        "date": today,
        "type": kind,
        "status": "ongoing",
        "ai": "pending",
        "tags": ["prayer", f"prayer/{'request' if kind == 'request' else 'personal'}"],
    }
    if requested_by:
        fm["requested-by"] = requested_by
    sections = {
        "Prayer": text.strip(),
        "Updates": f"- {today} — Created",
    }
    path.write_text(render_note(fm, sections), encoding="utf-8")
    return note_id


def read_note(note_id: str) -> dict:
    path = _safe_path(note_id)
    if not path.exists():
        raise FileNotFoundError(note_id)
    fm, sections = parse_note(path.read_text(encoding="utf-8"))
    return {"id": note_id, "frontmatter": fm, "sections": sections}


def write_note(note_id: str, fm: dict, sections: dict[str, str]) -> None:
    _safe_path(note_id).write_text(render_note(fm, sections), encoding="utf-8")


def list_notes() -> list[dict]:
    out = []
    for p in sorted(vault_dir().glob("*.md"), reverse=True):
        try:
            fm, sections = parse_note(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "prayer" not in (fm.get("tags") or []):
            continue
        out.append({
            "id": p.stem,
            "title": fm.get("title", p.stem),
            "date": str(fm.get("date", "")),
            "type": fm.get("type", "prayer"),
            "status": fm.get("status", "ongoing"),
            "ai": fm.get("ai", "done"),
            "requested_by": fm.get("requested-by", ""),
            "preview": (sections.get("Prayer", "")[:160]),
        })
    return out


def add_update(note_id: str, text: str) -> None:
    note = read_note(note_id)
    today = datetime.date.today().isoformat()
    updates = note["sections"].get("Updates", "")
    note["sections"]["Updates"] = (updates + f"\n- {today} — {text.strip()}").strip()
    write_note(note_id, note["frontmatter"], note["sections"])


def set_status(note_id: str, status: str, note_text: str = "") -> None:
    note = read_note(note_id)
    note["frontmatter"]["status"] = status
    today = datetime.date.today().isoformat()
    if status == "answered":
        note["frontmatter"]["answered-date"] = today
        msg = "**Answered!**" + (f" {note_text.strip()}" if note_text.strip() else "")
    else:
        note["frontmatter"].pop("answered-date", None)
        msg = "Reopened" + (f" — {note_text.strip()}" if note_text.strip() else "")
    updates = note["sections"].get("Updates", "")
    note["sections"]["Updates"] = (updates + f"\n- {today} — {msg}").strip()
    write_note(note_id, note["frontmatter"], note["sections"])


def apply_ai_result(note_id: str, result: dict | None, error: str = "") -> None:
    note = read_note(note_id)
    fm, sections = note["frontmatter"], note["sections"]
    if error or not result:
        fm["ai"] = "error"
        write_note(note_id, fm, sections)
        return
    fm["ai"] = "done"
    sections["Scripture"] = result.get("scripture_md", "")
    sections["Reflection"] = result.get("reflection", "")
    sections["How to Pray"] = result.get("prompts_md", "")
    write_note(note_id, fm, sections)
