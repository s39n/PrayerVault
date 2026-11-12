"""Semantic search + related prayers via embeddings (Ollama, or an OpenAI-compatible
gateway such as 9router when EMBED_BASE_URL / LLM_BASE_URL is set)."""
import hashlib
import json
import math
from pathlib import Path

import httpx

from . import config, notes

INDEX_FILE = ".embeddings.json"   # dotfile: invisible in Obsidian, syncs with the vault
RELATED_THRESHOLD = 0.55
RELATED_MAX = 3
# Index entries written before the model was recorded came from this model.
LEGACY_EMBED_MODEL = "nomic-embed-text:latest"


def _index_path(root: Path | str | None = None) -> Path:
    return notes.vault_dir(root) / INDEX_FILE


def _load(root: Path | str | None = None) -> dict:
    try:
        return json.loads(_index_path(root).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(index: dict, root: Path | str | None = None) -> None:
    _index_path(root).write_text(json.dumps(index), encoding="utf-8")


def _note_text(note: dict) -> str:
    fm = note["frontmatter"]
    return f"{fm.get('title', '')}\n{note['sections'].get('Prayer', '')}"


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def _embed(text: str, is_query: bool = False) -> list[float]:
    # nomic-embed-text is trained with task prefixes; using them improves results
    prefix = "search_query: " if is_query else "search_document: "
    if not config.EMBED_MODEL.split("/")[-1].startswith("nomic"):
        prefix = ""  # task prefixes are nomic-specific
    async with httpx.AsyncClient(timeout=120) as client:
        if config.EMBED_BASE_URL:
            headers = {"Content-Type": "application/json"}
            if config.EMBED_API_KEY:
                headers["Authorization"] = f"Bearer {config.EMBED_API_KEY}"
            r = await client.post(f"{config.EMBED_BASE_URL}/embeddings", headers=headers,
                                  json={"model": config.EMBED_MODEL, "input": prefix + text})
            r.raise_for_status()
            return r.json()["data"][0]["embedding"]
        r = await client.post(f"{config.OLLAMA_URL}/api/embeddings",
                              json={"model": config.EMBED_MODEL, "prompt": prefix + text})
        r.raise_for_status()
        return r.json()["embedding"]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def ensure_index(root: Path | str | None = None) -> dict:
    """Embed new/changed prayers, drop deleted ones. Returns {id: {hash, vec}}."""
    index = _load(root)
    seen = set()
    changed = False
    for meta in notes.list_notes(root):
        nid = meta["id"]
        seen.add(nid)
        note = notes.read_note(nid, root)
        text = _note_text(note)
        h = _hash(text)
        entry = index.get(nid, {})
        # Re-embed when the text changed OR the embedding model changed — vectors
        # from different models aren't comparable (and may differ in length).
        if entry.get("hash") != h or entry.get("model", LEGACY_EMBED_MODEL) != config.EMBED_MODEL:
            index[nid] = {"hash": h, "model": config.EMBED_MODEL, "vec": await _embed(text)}
            changed = True
    for nid in list(index):
        if nid not in seen:
            del index[nid]
            changed = True
    if changed:
        _save(index, root)
    return index


async def search(query: str, limit: int = 10,
                 root: Path | str | None = None) -> list[dict]:
    index = await ensure_index(root)
    qv = await _embed(query, is_query=True)
    scored = sorted(((_cos(qv, e["vec"]), nid) for nid, e in index.items()), reverse=True)
    metas = {m["id"]: m for m in notes.list_notes(root)}
    return [{**metas[nid], "score": round(s, 3)}
            for s, nid in scored[:limit] if nid in metas]


async def add_related_section(note_id: str, root: Path | str | None = None) -> None:
    """Write a Related section with wikilinks to the most similar prayers."""
    index = await ensure_index(root)
    if note_id not in index:
        return
    vec = index[note_id]["vec"]
    scored = sorted(((_cos(vec, e["vec"]), nid) for nid, e in index.items()
                     if nid != note_id), reverse=True)
    metas = {m["id"]: m for m in notes.list_notes(root)}
    links = []
    for s, nid in scored[:RELATED_MAX]:
        if s < RELATED_THRESHOLD or nid not in metas:
            continue
        links.append(f"- [[{nid}|{metas[nid]['title']}]]")
    if not links:
        return
    note = notes.read_note(note_id, root)
    note["sections"]["Related"] = "\n".join(links)
    notes.write_note(note_id, note["frontmatter"], note["sections"], root)
