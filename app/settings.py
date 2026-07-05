"""Runtime settings (morning prompt config + AI prompt overrides). Single JSON file, no database."""
import json
from pathlib import Path

from . import config

DEFAULTS = {
    "morning": {
        "enabled": False,
        "delivery": "ntfy",   # "ntfy" | "none"
        "ntfy_topic": "",
        "hour": 8,
        "minute": 0,
    },
    "prompts": {
        "system": "",   # blank = use ollama_client.SYSTEM_PROMPT
        "answer": "",   # blank = use ollama_client.ANSWER_PROMPT
    },
}


def _path() -> Path:
    if config.SETTINGS_FILE:
        return Path(config.SETTINGS_FILE)
    return Path(config.VAULT_DIR) / ".prayervault" / "settings.json"


def load() -> dict:
    p = _path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    morning = {**DEFAULTS["morning"], **(data.get("morning") or {})}
    prompts = {**DEFAULTS["prompts"], **(data.get("prompts") or {})}
    return {"morning": morning, "prompts": prompts}


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def save(data: dict) -> dict:
    cur = load()
    m = {**cur["morning"], **(data.get("morning") or {})}
    m["enabled"] = bool(m.get("enabled"))
    m["delivery"] = m.get("delivery") if m.get("delivery") in ("ntfy", "none") else "none"
    m["ntfy_topic"] = str(m.get("ntfy_topic", "")).strip()[:100]
    m["hour"] = _clamp(m.get("hour"), 0, 23, 8)
    m["minute"] = _clamp(m.get("minute"), 0, 59, 0)
    p = {**cur["prompts"], **(data.get("prompts") or {})}
    p["system"] = str(p.get("system", ""))[:12000]
    p["answer"] = str(p.get("answer", ""))[:12000]
    out = {"morning": m, "prompts": p}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
