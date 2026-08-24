"""Call the local Ollama model and shape its output for the vault note."""
import json
import re

import httpx

from . import config, settings


class OllamaError(RuntimeError):
    """A problem talking to Ollama (unreachable, model missing, or bad output)."""

SYSTEM_PROMPT = """You are a pastoral assistant grounded in Reformed (Presbyterian) theology,
consistent with the Westminster Standards. You will be given a personal prayer or a prayer
request. Respond ONLY with a JSON object with these keys:

"scripture": an array of 2-4 objects, each with:
  "book" (e.g. "Psalm", "John", "1 Peter" — full book name, singular "Psalm"),
  "chapter" (integer),
  "verse_start" (integer),
  "verse_end" (integer, same as verse_start for a single verse),
  "why" (one sentence: how this passage speaks to the request)

"reflection": 2-3 short paragraphs of biblical encouragement addressed to the person praying.
Warm and pastoral, God-centered, honest about suffering, anchored in the character and
promises of God in Christ. Reference the passages you chose by name (e.g. "As Psalm 46
reminds us..."). No markdown headers.

"prompts": an array of 3-5 short suggestions for how to pray through this, loosely following
adoration, confession, thanksgiving, supplication. Each a single sentence.

Choose real passages and quote references accurately. Do not invent verse numbers."""

ANSWER_PROMPT = """You are a pastoral teacher grounded in Reformed (Presbyterian) theology,
consistent with the Westminster Standards. You will be given a question. Respond ONLY with a
JSON object with these keys:

"scripture": an array of 2-4 objects, each with:
  "book" (full book name, singular "Psalm", e.g. "Psalm", "John", "1 Peter"),
  "chapter" (integer),
  "verse_start" (integer),
  "verse_end" (integer, same as verse_start for a single verse),
  "why" (one sentence: how this passage speaks to the question)

"answer": 2-3 short paragraphs answering the question from Scripture. Warm and pastoral,
God-centered, honest, anchored in the character and promises of God in Christ. Reference the
passages you chose by name (e.g. "As Romans 8 reminds us..."). Point to Christ and the gospel.
If the question is outside what Scripture directly addresses, say so humbly rather than
speculating. No markdown headers.

Choose real passages and quote references accurately. Do not invent verse numbers."""


def _prompt(name: str, default: str) -> str:
    """Return the user's custom prompt from settings, or the built-in default if blank."""
    try:
        custom = settings.load()["prompts"].get(name, "").strip()
    except Exception:
        custom = ""
    return custom or default


def _wikilink(book: str, chapter: int, v1: int, v2: int) -> str:
    ref = f"{book} {chapter}:{v1}" + (f"-{v2}" if v2 and v2 != v1 else "")
    return f"[[{book} {chapter}#{v1}|{ref}]]"


def _shape(raw: dict) -> dict:
    scripture_lines = []
    for s in raw.get("scripture", []):
        try:
            book = str(s["book"]).strip()
            ch = int(s["chapter"])
            v1 = int(s["verse_start"])
            v2 = int(s.get("verse_end") or v1)
            why = str(s.get("why", "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not book or ch < 1 or v1 < 1:
            continue
        line = f"- {_wikilink(book, ch, v1, v2)}"
        if why:
            line += f" — {why}"
        scripture_lines.append(line)
    prompts = [f"- {str(p).strip()}" for p in raw.get("prompts", []) if str(p).strip()]
    return {
        "scripture_md": "\n".join(scripture_lines),
        "reflection": str(raw.get("reflection", "")).strip(),
        "prompts_md": "\n".join(prompts),
    }


async def _chat(messages: list[dict]) -> str:
    """POST to Ollama's /api/chat and return the reply content, with clear errors."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.6},
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
        try:
            r = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
        except httpx.TimeoutException as e:
            raise OllamaError(
                f"Ollama model '{config.OLLAMA_MODEL}' didn't respond within "
                f"{config.OLLAMA_TIMEOUT}s. It may be too large/slow for the host — try a "
                f"smaller, non-'thinking' model (e.g. qwen2.5:7b), or raise OLLAMA_TIMEOUT."
            ) from e
        if r.status_code == 404:
            raise OllamaError(
                f"Model '{config.OLLAMA_MODEL}' was not found on the Ollama server at "
                f"{config.OLLAMA_URL}. Pull it with `ollama pull {config.OLLAMA_MODEL}`, "
                f"or set OLLAMA_MODEL to a model that server already has."
            )
        r.raise_for_status()
        return r.json()["message"]["content"]


def _parse_json(content: str) -> dict:
    """Extract a JSON object from the reply, tolerating code fences and reasoning
    models that prepend a <think>...</think> block before the JSON."""
    content = content.strip()
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    content = re.sub(r"^```(json)?|```$", "", content, flags=re.MULTILINE).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)  # first {...} object
        if match:
            return json.loads(match.group(0))
        raise OllamaError(
            "The model did not return valid JSON. Try a different OLLAMA_MODEL "
            "(a non-'thinking' model such as qwen2.5 is most reliable here)."
        )


async def generate(kind: str, title: str, text: str, requested_by: str = "") -> dict:
    who = f" (requested by {requested_by})" if requested_by else ""
    label = "prayer request" if kind == "request" else "personal prayer"
    user_msg = f"This is a {label}{who}, titled \"{title}\":\n\n{text}"
    content = await _chat([
        {"role": "system", "content": _prompt("system", SYSTEM_PROMPT)},
        {"role": "user", "content": user_msg},
    ])
    return _shape(_parse_json(content))


async def ask(question: str) -> dict:
    """Answer a free-form question with Scripture references + a Reformed reflection."""
    content = await _chat([
        {"role": "system", "content": _prompt("answer", ANSWER_PROMPT)},
        {"role": "user", "content": question.strip()},
    ])
    raw = _parse_json(content)
    return {"scripture_md": _shape(raw)["scripture_md"], "answer": str(raw.get("answer", "")).strip()}


async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{config.OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
        return {"ollama": "ok", "model": config.OLLAMA_MODEL,
                "model_available": any(m.startswith(config.OLLAMA_MODEL.split(":")[0]) for m in models)}
    except Exception as e:
        return {"ollama": "unreachable", "model": config.OLLAMA_MODEL, "error": str(e)}
