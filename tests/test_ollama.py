"""Robust parsing of Ollama replies + clear errors for a missing model."""
import asyncio

import httpx
import pytest

from app import ollama_client
from app.ollama_client import OllamaError, _parse_json


def test_parse_plain_json():
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_strips_reasoning_block():
    content = '<think>let me reason...</think>\n{"reflection": "x", "scripture": []}'
    assert _parse_json(content)["reflection"] == "x"


def test_parse_extracts_embedded_object():
    assert _parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}


def test_parse_garbage_raises_ollama_error():
    with pytest.raises(OllamaError):
        _parse_json("no json here at all")


class _Client404:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        return httpx.Response(404, request=httpx.Request("POST", url))


def test_missing_model_raises_clear_error(monkeypatch):
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _Client404)
    with pytest.raises(OllamaError) as exc:
        asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    msg = str(exc.value).lower()
    assert "not found" in msg and "ollama_model" in msg


class _ClientTimeout:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        raise httpx.ReadTimeout("timed out")


def test_slow_model_raises_clear_timeout_error(monkeypatch):
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _ClientTimeout)
    with pytest.raises(OllamaError) as exc:
        asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    assert "didn't respond" in str(exc.value).lower()


class _CaptureClient:
    last_payload = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        _CaptureClient.last_payload = json
        return httpx.Response(
            200, request=httpx.Request("POST", url),
            json={"message": {"content": '{"ok": true}', "thinking": "let me reason"}})


def test_thinking_mode_sends_think_and_reads_content(monkeypatch):
    monkeypatch.setattr(ollama_client.config, "OLLAMA_THINK", True)
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _CaptureClient)
    content = asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    assert content == '{"ok": true}'
    assert _CaptureClient.last_payload.get("think") is True


def test_think_omitted_when_disabled(monkeypatch):
    monkeypatch.setattr(ollama_client.config, "OLLAMA_THINK", False)
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _CaptureClient)
    asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    assert "think" not in _CaptureClient.last_payload


# ---- OpenAI-compatible gateway (9router) ----

class _GatewayClient:
    calls = []
    status = 200

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _GatewayClient.calls.append((url, json, headers))
        if _GatewayClient.status != 200:
            return httpx.Response(_GatewayClient.status, request=httpx.Request("POST", url))
        if url.endswith("/embeddings"):
            body = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        else:
            body = {"choices": [{"message": {"content": '{"reflection": "ok"}'}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


def _use_gateway(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://router:20128/v1")
    monkeypatch.setattr(config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(config, "LLM_MODEL", "kimchi/auto")
    monkeypatch.setattr(config, "EMBED_BASE_URL", "http://router:20128/v1")
    monkeypatch.setattr(config, "EMBED_API_KEY", "sk-test")
    monkeypatch.setattr(config, "USE_GATEWAY", True)
    _GatewayClient.calls = []
    _GatewayClient.status = 200
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", _GatewayClient)


def test_gateway_chat_uses_openai_api_with_key(monkeypatch):
    _use_gateway(monkeypatch)
    out = asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    assert out == '{"reflection": "ok"}'
    url, payload, headers = _GatewayClient.calls[0]
    assert url == "http://router:20128/v1/chat/completions"
    assert payload["model"] == "kimchi/auto"
    assert payload["response_format"] == {"type": "json_object"}
    assert headers["Authorization"] == "Bearer sk-test"


def test_gateway_bad_key_raises_clear_error(monkeypatch):
    _use_gateway(monkeypatch)
    _GatewayClient.status = 401
    with pytest.raises(OllamaError) as exc:
        asyncio.run(ollama_client._chat([{"role": "user", "content": "hi"}]))
    assert "llm_api_key" in str(exc.value).lower()


def test_gateway_embeddings(monkeypatch):
    from app import config, embeddings
    _use_gateway(monkeypatch)
    monkeypatch.setattr(config, "EMBED_MODEL", "gc/gemini-embedding-001")
    vec = asyncio.run(embeddings._embed("hello"))
    assert vec == [0.1, 0.2, 0.3]
    url, payload, _ = _GatewayClient.calls[0]
    assert url.endswith("/embeddings") and payload["input"] == "hello"  # no nomic prefix


def test_embedding_model_change_triggers_reindex(monkeypatch, tmp_path):
    from app import config, embeddings, notes
    monkeypatch.setattr(config, "EMBED_MODEL", "new-model")
    note = {"frontmatter": {"title": "t"}, "sections": {"Prayer": "p"}}
    monkeypatch.setattr(notes, "list_notes", lambda root=None: [{"id": "n1"}])
    monkeypatch.setattr(notes, "read_note", lambda nid, root=None: note)
    monkeypatch.setattr(notes, "vault_dir", lambda root=None: tmp_path)
    h = embeddings._hash(embeddings._note_text(note))
    embeddings._save({"n1": {"hash": h, "vec": [1.0]}})  # legacy entry, no model
    async def fake(text, is_query=False):
        return [9.0, 9.0]
    monkeypatch.setattr(embeddings, "_embed", fake)
    idx = asyncio.run(embeddings.ensure_index())
    assert idx["n1"]["vec"] == [9.0, 9.0] and idx["n1"]["model"] == "new-model"


def test_same_embedding_model_via_gateway_prefix_does_not_reindex(monkeypatch, tmp_path):
    from app import config, embeddings, notes
    monkeypatch.setattr(config, "EMBED_MODEL", "ollama-local/nomic-embed-text")
    note = {"frontmatter": {"title": "t"}, "sections": {"Prayer": "p"}}
    monkeypatch.setattr(notes, "list_notes", lambda root=None: [{"id": "n1"}])
    monkeypatch.setattr(notes, "read_note", lambda nid, root=None: note)
    monkeypatch.setattr(notes, "vault_dir", lambda root=None: tmp_path)
    h = embeddings._hash(embeddings._note_text(note))
    embeddings._save({"n1": {"hash": h, "vec": [1.0]}})  # legacy nomic entry
    async def boom(text, is_query=False):
        raise AssertionError("should not re-embed")
    monkeypatch.setattr(embeddings, "_embed", boom)
    assert asyncio.run(embeddings.ensure_index())["n1"]["vec"] == [1.0]
