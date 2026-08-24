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
