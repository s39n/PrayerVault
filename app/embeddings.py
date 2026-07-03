"""Semantic search + related prayers via Ollama embeddings (nomic-embed-text)."""
import hashlib
import json
import math
from pathlib import Path

import httpx

from . import config, notes

INDEX_FILE = ".embeddings.json"   # dotfile: invisible in Obsidian, syncs with the vault
RELATED_THRESHOLD = 0.55
RELATED_MAX = 3


def _index_path() -> Path:
    return notes.vault_dir() / INDEX_FILE


def _load() -> dict:
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(index: dict) -> None:
    _index_path().write_text(json.dumps(index), encoding="utf-8")


def _note_text(note: dict) -> str:
    fm = note["frontmatter"]
    return f"{fm.get('title', '')}\n{note['sections'].get('Prayer', '')}"


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def _embed(text: str, is_query: bool = False) -> list[float]:
    # nomic-embed-text is trained with task prefixes; using them improves results
    prefix = "search_query: " if is_query else "search_document: "
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{config.OLLAMA_URL}/api/embeddings",
                              json={"model": config.EMBED_MODEL, "prompt": prefix + text})
        r.raise_for_status()
        return r.json()["embedding"]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def ensure_index() -> dict:
    """Embed new/changed prayers, drop deleted ones. Returns {id: {hash, vec}}."""
    index = _load()
    seen = set()
    changed = False
    for meta in notes.list_notes():
        nid = meta["id"]
        seen.add(nid)
        note = notes.read_note(nid)
        text = _note_text(note)
        h = _hash(text)
        if index.get(nid, {}).get("hash") != h:
            index[nid] = {"hash": h, "vec": await _embed(text)}
            changed = True
    for nid in list(index):
        if nid not in seen:
            del index[nid]
            changed = True
    if changed:
        _save(index)
    return index


async def search(query: str, limit: int = 10) -> list[dict]:
    index = await ensure_index()
    qv = await _embed(query, is_query=True)
    scored = sorted(((_cos(qv, e["vec"]), nid) for nid, e in index.items()), reverse=True)
    metas = {m["id"]: m for m in notes.list_notes()}
    return [{**metas[nid], "score": round(s, 3)}
            for s, nid in scored[:limit] if nid in metas]


async def add_related_section(note_id: str) -> None:
    """Write a Related section with wikilinks to the most similar prayers."""
    index = await ensure_index()
    if note_id not in index:
        return
    vec = index[note_id]["vec"]
    scored = sorted(((_cos(vec, e["vec"]), nid) for nid, e in index.items()
                     if nid != note_id), reverse=True)
    metas = {m["id"]: m for m in notes.list_notes()}
    links = []
    for s, nid in scored[:RELATED_MAX]:
        if s < RELATED_THRESHOLD or nid not in metas:
            continue
        links.append(f"- [[{nid}|{metas[nid]['title']}]]")
    if not links:
        return
    note = notes.read_note(note_id)
    note["sections"]["Related"] = "\n".join(links)
    notes.write_note(note_id, note["frontmatter"], note["sections"])
