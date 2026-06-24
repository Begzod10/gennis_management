"""Voice-to-mission assistant.

Transcribes an audio file via the Whisper API, then uses GPT to extract
one or more mission proposals from the transcript.  The caller is responsible
for ranking executors via the existing suggest_executors() helper.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class VoiceAssistantError(RuntimeError):
    """Raised when transcription or extraction fails."""


@dataclass
class VoiceMissionProposal:
    title: str
    description: Optional[str]
    deadline_days: int          # days from today
    category: str               # one of CategoryEnum values
    executor_role_hint: str     # hint for executor ranking (job/skill keyword)
    raw_excerpt: str = ""       # relevant slice of transcript for this mission


_EXTRACTION_SYSTEM_PROMPT = (
    "You are an assistant that converts spoken instructions into structured task lists. "
    "The input is a transcribed voice message from a manager or team leader. "
    "Extract every distinct task or mission they mention. "
    "For each mission produce: "
    "  title (short, action-oriented), "
    "  description (expanded detail, may be null), "
    "  deadline_days (integer — how many days from today; default 3 if not mentioned), "
    "  category (one of: academic, admin, student, report, meeting, marketing, maintenance, finance), "
    "  executor_role_hint (a keyword describing the ideal executor's job or skill, e.g. 'developer', 'accountant', 'designer', 'teacher'), "
    "  raw_excerpt (the exact words from the transcript that relate to this mission). "
    "The transcript may be in Uzbek, Russian, or English — extract regardless of language but "
    "write title and description in the same language as the transcript. "
    "Return strict JSON only — no prose, no markdown — with this shape: "
    '{"missions": [{"title": "...", "description": "...", "deadline_days": 3, '
    '"category": "admin", "executor_role_hint": "...", "raw_excerpt": "..."}]}'
)


def transcribe_audio(audio_bytes: bytes, filename: str, language: Optional[str] = None) -> str:
    """Send audio bytes to the Whisper API and return the transcript text."""
    if not settings.OPENAI_API_KEY:
        raise VoiceAssistantError("OPENAI_API_KEY is not configured")

    # Whisper endpoint — always hit the real OpenAI base when a proxy is set,
    # because many proxies only forward /chat/completions.
    base = settings.OPENAI_BASE_URL.rstrip("/")
    url = f"{base}/audio/transcriptions"

    form: dict = {
        "model": (None, settings.OPENAI_WHISPER_MODEL),
        "response_format": (None, "json"),
        "file": (filename, audio_bytes, _mime_for(filename)),
    }
    if language:
        form["language"] = (None, language)

    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            resp = client.post(url, headers=headers, files=form)
    except httpx.HTTPError as exc:
        raise VoiceAssistantError(f"Whisper transport error: {exc}") from exc

    if resp.status_code >= 400:
        raise VoiceAssistantError(
            f"Whisper HTTP {resp.status_code}: {resp.text[:400]}"
        )

    try:
        return resp.json()["text"]
    except (KeyError, json.JSONDecodeError) as exc:
        raise VoiceAssistantError(f"Unexpected Whisper response: {exc}") from exc


def _mime_for(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "mp3": "audio/mpeg",
        "mp4": "audio/mp4",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
    }.get(ext, "application/octet-stream")


_VALID_CATEGORIES = {
    "academic", "admin", "student", "report",
    "meeting", "marketing", "maintenance", "finance",
}


def extract_missions(transcript: str) -> List[VoiceMissionProposal]:
    """Ask GPT to parse the transcript and return structured mission proposals."""
    if not settings.OPENAI_API_KEY:
        raise VoiceAssistantError("OPENAI_API_KEY is not configured")
    if not transcript.strip():
        return []

    payload = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"

    try:
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise VoiceAssistantError(f"GPT transport error: {exc}") from exc

    if resp.status_code >= 400:
        raise VoiceAssistantError(
            f"GPT HTTP {resp.status_code}: {resp.text[:400]}"
        )

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        raw = json.loads(content).get("missions", [])
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise VoiceAssistantError(f"Unparseable GPT response: {exc}") from exc

    proposals: List[VoiceMissionProposal] = []
    for item in raw:
        try:
            category = str(item.get("category", "admin")).lower()
            if category not in _VALID_CATEGORIES:
                category = "admin"
            proposals.append(
                VoiceMissionProposal(
                    title=str(item["title"]).strip(),
                    description=str(item["description"]).strip() if item.get("description") else None,
                    deadline_days=max(1, int(item.get("deadline_days", 3))),
                    category=category,
                    executor_role_hint=str(item.get("executor_role_hint", "")).strip(),
                    raw_excerpt=str(item.get("raw_excerpt", "")).strip(),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return proposals
