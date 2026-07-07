"""Telegram voice message → AI mission creation pipeline.

Flow:
  1. Download .ogg voice file from Telegram
  2. Transcribe via OpenAI Whisper
  3. GPT picks executor from live list + extracts mission fields
  4. Create mission in DB, return result dict
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Mission, User
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_assigned
from app.services.realtime_session import (
    _executor_dict,
    _NON_EXECUTOR_ROLES,
    _check_voice_assignment,
    _effective_role,
    _OWNER_ROLES,
    _ROLE_CAN_ASSIGN,
    _PROJECT_SCOPED_ROLES,
)

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"

_EXTRACT_SYSTEM = (
    "Extract mission details from a voice transcription and pick the best executor. "
    "Return ONLY valid JSON:\n"
    '{"title":"short action title","description":"detail or null",'
    '"executor_id":<int from list or null>,"deadline_days":<int default 3>,'
    '"category":"academic|admin|student|report|meeting|marketing|maintenance|finance"}\n'
    "Rules:\n"
    "- title: write in the SAME language as the transcription (Uzbek if Uzbek, Russian if Russian). Keep it short (3-6 words).\n"
    "- match executor by name first, then skill, then job, then role.\n"
    'Deadline hints: "3 kun"=3, "bir hafta"=7, "2 days"=2, "ertaga"=1.'
)

_VALID_CATEGORIES = {
    "academic", "admin", "student", "report",
    "meeting", "marketing", "maintenance", "finance",
}


async def _download_voice(file_id: str) -> tuple[bytes, str]:
    token = settings.TELEGRAM_BOT_TOKEN
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            f"{_TELEGRAM_API}/bot{token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        filename = file_path.rsplit("/", 1)[-1]
        r2 = await client.get(f"{_TELEGRAM_API}/file/bot{token}/{file_path}")
        r2.raise_for_status()
        return r2.content, filename


async def _transcribe(audio: bytes, filename: str) -> str:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            files={
                "file": (filename, audio, "audio/ogg"),
                "model": (None, settings.OPENAI_WHISPER_MODEL),
                "response_format": (None, "json"),
                "prompt": (None,
                    "Gennis, Turon, sayt, dizayn, o'zgartirish, tog'irlash, tuzatish, tekshirish, "
                    "topshiriq, vazifa, loyiha, yangilash, tayyorlash, yuborish, ko'rib chiqish, "
                    "hisobot, taqdimot, muddati, hafta, kun, oy, ertaga, "
                    "Shahzod, Sardor, Jasur, Begzod, Aziza, Nilufar, Jahongir, Alisher, Sherzod"),
            },
        )
        r.raise_for_status()
        return r.json()["text"]


async def _extract(transcript: str, executors: list) -> dict:
    base = settings.OPENAI_BASE_URL.rstrip("/")
    payload = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Transcription: {transcript}\n\n"
                    f"Executors:\n{json.dumps(executors, ensure_ascii=False)}"
                ),
            },
        ],
    }
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        r = await client.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])


async def prepare_telegram_voice(file_id: str, creator_id: int, db: Session) -> dict:
    """Download → transcribe → extract. Returns pending dict WITHOUT creating mission."""
    if not settings.OPENAI_API_KEY:
        return {"ok": False, "error": "OPENAI_API_KEY sozlanmagan"}

    try:
        audio, filename = await _download_voice(file_id)
        transcript = await _transcribe(audio, filename)
    except Exception as exc:
        logger.error("Voice download/transcribe error: %s", exc)
        return {"ok": False, "error": "Ovozni matnga o'girib bo'lmadi"}

    logger.info("Telegram voice transcript (creator=%s): %s", creator_id, transcript)

    creator = db.query(User).filter(User.id == creator_id, User.deleted == False).first()
    base = db.query(User).filter(User.deleted == False, User.is_active == True).order_by(User.name)

    if creator and creator.role not in _OWNER_ROLES:
        creator_role = _effective_role(creator)
        if creator_role in _PROJECT_SCOPED_ROLES:
            users = [creator]
        else:
            allowed_roles = _ROLE_CAN_ASSIGN.get(creator_role, set()) | {creator.role}
            users = base.filter(User.role.in_(allowed_roles)).all()
    else:
        users = base.filter(~User.role.in_(_NON_EXECUTOR_ROLES)).all()

    executors = [_executor_dict(u, db) for u in users]

    try:
        extracted = await _extract(transcript, executors)
    except Exception as exc:
        logger.error("GPT extraction error: %s", exc)
        return {"ok": False, "error": "Vazifani tushunib bo'lmadi", "transcript": transcript}

    title = (extracted.get("title") or "").strip()
    executor_id = extracted.get("executor_id")

    if not title:
        return {"ok": False, "error": "Vazifa nomi topilmadi", "transcript": transcript}
    if not executor_id:
        return {"ok": False, "error": "Ijrochi aniqlanmadi", "transcript": transcript, "title": title}

    executor = db.query(User).filter(User.id == executor_id, User.deleted == False).first()
    if not executor:
        return {"ok": False, "error": f"Ijrochi topilmadi (id={executor_id})", "transcript": transcript}

    if creator:
        err = _check_voice_assignment(creator, executor)
        if err:
            return {"ok": False, "error": err, "transcript": transcript}

    deadline_days = max(1, int(extracted.get("deadline_days") or 3))
    category = str(extracted.get("category", "admin")).lower()
    if category not in _VALID_CATEGORIES:
        category = "admin"
    executor_name = f"{executor.name} {executor.surname or ''}".strip()

    return {
        "ok": True,
        "pending": True,
        "title": title,
        "description": extracted.get("description") or None,
        "executor_id": executor_id,
        "executor_name": executor_name,
        "creator_id": creator_id,
        "deadline_days": deadline_days,
        "deadline_explicit": deadline_days != 3,
        "category": category,
        "transcript": transcript,
    }


def create_mission_from_pending(pending: dict, deadline_days: int, db: Session) -> dict:
    """Create mission from a pending dict (returned by prepare_telegram_voice)."""
    deadline = date.today() + timedelta(days=deadline_days)
    creator_id = pending["creator_id"]
    executor_id = pending["executor_id"]

    mission = Mission(
        title=pending["title"],
        description=pending.get("description"),
        category=pending["category"],
        executor_id=executor_id,
        creator_id=creator_id,
        deadline=deadline,
        status="not_started",
        kpi_weight=10,
        penalty_per_day=2,
        early_bonus_per_day=1,
        max_bonus=3,
        max_penalty=10,
        channel="telegram",
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    executor_name = pending["executor_name"]
    logger.info("Telegram voice mission created: id=%s title=%s executor=%s", mission.id, pending["title"], executor_name)

    creator = db.query(User).filter(User.id == creator_id, User.deleted == False).first()
    executor = db.query(User).filter(User.id == executor_id, User.deleted == False).first()
    if executor and executor.telegram_id:
        creator_name = f"{creator.name} {creator.surname or ''}".strip() if creator else "AI Assistant"
        send_telegram_notification.delay(
            executor.telegram_id,
            tpl_assigned(executor_name, pending["title"], deadline, creator_name),
        )

    return {
        "ok": True,
        "mission_id": mission.id,
        "title": pending["title"],
        "executor": executor_name,
        "deadline": deadline.isoformat(),
        "category": pending["category"],
    }
