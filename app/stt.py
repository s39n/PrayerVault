"""Speech-to-text via a local Whisper ASR container (openai-whisper-asr-webservice)."""
import httpx

from . import config


async def transcribe(data: bytes, filename: str, content_type: str) -> str:
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f"{config.WHISPER_URL}/asr",
            params={"task": "transcribe", "output": "json"},
            files={"audio_file": (filename or "audio.webm", data,
                                  content_type or "audio/webm")},
        )
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
