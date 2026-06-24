"""OpenAI Realtime API session configuration and function-call handlers.

Defines the AI's system prompt, the tools it can call (list_executors,
search_executor_by_name, create_mission), and the logic that executes
those tools against the management database.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Mission, Tag, User, Job

logger = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a voice mission assistant for the Gennis management system.
You help managers, directors, and team leaders create work missions through natural conversation.

LANGUAGE RULE: The user may speak in Uzbek, Russian, or English. You MUST detect and respond in the exact same language they use. Do NOT switch languages.

YOUR WORKFLOW:
1. Listen to what work the manager describes.
2. If an executor is mentioned by name, call search_executor_by_name to find them.
3. If no executor is mentioned, call list_executors and suggest the most relevant person based on the task.
4. Confirm the details (who, what, deadline) in one short sentence before creating.
5. Call create_mission to create it.
6. Confirm success with the mission ID.

RULES:
- Be concise. No long explanations.
- Ask only ONE clarifying question at a time.
- Default deadline: 3 days from today, unless specified otherwise.
- Default category: "admin", unless the task clearly belongs to another (maintenance, finance, academic, etc.).
- If the manager mentions multiple tasks in one message, handle them one at a time.
- Never invent executor names — always look them up first.

EXAMPLES of how you speak:
- Uzbek: "Topshiriq yaratildi: Ali Karimovga 3 kunlik uy-joy ta'mirlash vazifasi (ID: 42)."
- Russian: "Задание создано: Алишер Каримов — ремонт офиса, срок 3 дня (ID: 42)."
- English: "Mission created: Ali Karimov — office repair, due in 3 days (ID: 42)."
"""


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "name": "list_executors",
        "description": (
            "List all active users available as mission executors. "
            "Returns their id, full name, role, and job title."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "search_executor_by_name",
        "description": (
            "Search for an active user by name (case-insensitive, partial match). "
            "Use this when the manager mentions someone by name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The name or partial name to search for (first or last name).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "type": "function",
        "name": "create_mission",
        "description": "Create a new work mission and assign it to an executor.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short, action-oriented mission title."},
                "description": {
                    "type": "string",
                    "description": "Detailed description of the mission. Optional.",
                },
                "executor_id": {
                    "type": "integer",
                    "description": "The user ID of the person who will execute this mission.",
                },
                "creator_id": {
                    "type": "integer",
                    "description": "The user ID of the person creating this mission (the manager speaking).",
                },
                "deadline_days": {
                    "type": "integer",
                    "description": "Number of days from today for the deadline. Default is 3.",
                    "default": 3,
                },
                "category": {
                    "type": "string",
                    "description": "Mission category.",
                    "enum": [
                        "academic", "admin", "student", "report",
                        "meeting", "marketing", "maintenance", "finance",
                    ],
                },
            },
            "required": ["title", "executor_id", "creator_id", "deadline_days", "category"],
        },
    },
]


# ── OpenAI Realtime session config ────────────────────────────────────────────

def build_session_update() -> dict:
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": SYSTEM_PROMPT,
            "voice": "alloy",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 700,
            },
            "tools": TOOLS,
            "tool_choice": "auto",
        },
    }


# ── Function call handlers ────────────────────────────────────────────────────

def handle_list_executors(args: dict, db: Session, creator_id: int) -> str:
    users = (
        db.query(User)
        .filter(User.deleted == False, User.is_active == True)
        .order_by(User.name)
        .all()
    )
    result = []
    for u in users:
        job_name = None
        if u.job_id:
            job = db.query(Job).filter(Job.id == u.job_id).first()
            job_name = job.name if job else None
        result.append({
            "id": u.id,
            "name": f"{u.name} {u.surname}".strip(),
            "role": u.role,
            "job": job_name,
        })
    return json.dumps({"executors": result}, ensure_ascii=False)


def handle_search_executor_by_name(args: dict, db: Session, creator_id: int) -> str:
    name_q = str(args.get("name", "")).strip()
    if not name_q:
        return json.dumps({"executors": [], "error": "name is required"})

    pattern = f"%{name_q}%"
    users = (
        db.query(User)
        .filter(
            User.deleted == False,
            User.is_active == True,
            (User.name.ilike(pattern) | User.surname.ilike(pattern)),
        )
        .limit(5)
        .all()
    )
    result = []
    for u in users:
        job_name = None
        if u.job_id:
            job = db.query(Job).filter(Job.id == u.job_id).first()
            job_name = job.name if job else None
        result.append({
            "id": u.id,
            "name": f"{u.name} {u.surname}".strip(),
            "role": u.role,
            "job": job_name,
        })
    return json.dumps({"executors": result}, ensure_ascii=False)


_VALID_CATEGORIES = {
    "academic", "admin", "student", "report",
    "meeting", "marketing", "maintenance", "finance",
}


def handle_create_mission(args: dict, db: Session, creator_id: int) -> str:
    title = str(args.get("title", "")).strip()
    if not title:
        return json.dumps({"error": "title is required"})

    executor_id = args.get("executor_id")
    if not executor_id:
        return json.dumps({"error": "executor_id is required"})

    _creator_id = args.get("creator_id", creator_id)

    executor = db.query(User).filter(User.id == executor_id, User.deleted == False).first()
    if not executor:
        return json.dumps({"error": f"Executor with id {executor_id} not found"})

    deadline_days = max(1, int(args.get("deadline_days", 3)))
    deadline = date.today() + timedelta(days=deadline_days)

    category = str(args.get("category", "admin")).lower()
    if category not in _VALID_CATEGORIES:
        category = "admin"

    description = args.get("description") or None

    mission = Mission(
        title=title,
        description=description,
        category=category,
        executor_id=executor_id,
        creator_id=_creator_id,
        deadline=deadline,
        status="not_started",
        kpi_weight=10,
        penalty_per_day=2,
        early_bonus_per_day=1,
        max_bonus=3,
        max_penalty=10,
        channel="line_management",
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    executor_name = f"{executor.name} {executor.surname}".strip()
    logger.info("Voice mission created: id=%s title=%s executor=%s", mission.id, title, executor_name)
    return json.dumps({
        "success": True,
        "mission_id": mission.id,
        "title": title,
        "executor": executor_name,
        "deadline": deadline.isoformat(),
        "category": category,
    }, ensure_ascii=False)


# ── Dispatch ──────────────────────────────────────────────────────────────────

_HANDLERS = {
    "list_executors": handle_list_executors,
    "search_executor_by_name": handle_search_executor_by_name,
    "create_mission": handle_create_mission,
}


def dispatch_function_call(name: str, args_str: str, db: Session, creator_id: int) -> str:
    handler = _HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown function: {name}"})
    try:
        args = json.loads(args_str) if args_str else {}
        return handler(args, db, creator_id)
    except Exception as exc:
        logger.warning("Function call '%s' failed: %s", name, exc)
        return json.dumps({"error": str(exc)})
