"""Runtime settings (morning prompt config). Single JSON file, no database."""
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
    }
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
    return {"morning": morning}


def _clamp(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def save(data: dict) -> dict:
    cur = load()["morning"]
    incoming = data.get("morning") or {}
    m = {**cur, **incoming}
    m["enabled"] = bool(m.get("enabled"))
    m["delivery"] = m.get("delivery") if m.get("delivery") in ("ntfy", "none") else "none"
    m["ntfy_topic"] = str(m.get("ntfy_topic", "")).strip()[:100]
    m["hour"] = _clamp(m.get("hour"), 0, 23, 8)
    m["minute"] = _clamp(m.get("minute"), 0, 59, 0)
    out = {"morning": m}
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
