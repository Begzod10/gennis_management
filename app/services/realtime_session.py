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

from app.models import Mission, Tag, User, Job, UserSkill
from app.tasks import send_telegram_notification
from app.services.telegram import tpl_assigned

logger = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Gennis tizimining ovozli vazifa yordamchisi. O'zbek tilida gapir (rus yoki ingliz eshitilsa — o'sha tilda).

JARAYON:
1. Vazifani eshit.
2. list_executors chaqir — har bir xodim: ism, lavozim (job), ko'nikmalar (skills).
3. Vazifaga ENG MOS odamni tanla: skills → job → role tartibida solishtir.
4. Bitta gap bilan tasdiqlat: "X ga Y ni 3 kunga topshiraymi?"
5. Ha desa — create_mission chaqir.
6. ID bilan tasdiqlа.

QOIDALAR:
- Ism aytilsa: search_executor_by_name ishlat.
- Muddат aytilmasa: 3 kun.
- Kategoriya: maintenance(ta'mir), finance(moliya), academic(o'qitish), admin(boshqa).
- O'zing tanla — savol berma."""


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "name": "list_executors",
        "description": "Get all active staff with id, name, role, job title, and skills. Call this first to pick the best executor based on skills match.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "search_executor_by_name",
        "description": "Find a user by name. Use when manager names a specific person.",
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
        "description": "Create and assign a work mission.",
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
            "type": "realtime",
            "instructions": SYSTEM_PROMPT,
            "tools": TOOLS,
            "tool_choice": "auto",
        },
    }


def build_uzbek_primer() -> dict:
    """Inject an opening assistant message in Uzbek to lock the response language."""
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": (
                        "Assalomu alaykum! Men Gennis boshqaruv tizimining ovozli yordamchisiman. "
                        "Vazifa yaratish uchun menga ayting: kim bajaradi, nima qilish kerak va qachon?"
                    ),
                }
            ],
        },
    }


# ── Function call handlers ────────────────────────────────────────────────────

# Skills every role gets by default — not useful for AI matching between individuals
_GENERIC_SKILLS_EN = {
    "Communication", "Teamwork", "Time management", "Organization",
    "Document management", "Scheduling", "Data entry",
}


def _executor_dict(u: User, db: Session) -> dict:
    job_name = None
    if u.job_id:
        job = db.query(Job).filter(Job.id == u.job_id).first()
        job_name = job.name if job else None
    skill_rows = db.query(UserSkill).filter(UserSkill.user_id == u.id).all()
    # Only include non-generic skills so the AI gets signal, not noise
    specific = [
        f"{s.skill_uz}/{s.skill_en}"
        for s in skill_rows
        if s.skill_en not in _GENERIC_SKILLS_EN
    ]
    entry = {
        "id": u.id,
        "name": f"{u.name} {u.surname}".strip(),
        "role": u.role,
    }
    if job_name:
        entry["job"] = job_name
    if specific:
        entry["skills"] = ", ".join(specific)
    return entry


# Roles that assign missions rather than execute them — exclude from executor list
_NON_EXECUTOR_ROLES = {"owner", "director", "manager"}


def handle_list_executors(args: dict, db: Session, creator_id: int) -> str:
    users = (
        db.query(User)
        .filter(
            User.deleted == False,
            User.is_active == True,
            ~User.role.in_(_NON_EXECUTOR_ROLES),
        )
        .order_by(User.name)
        .all()
    )
    return json.dumps({"executors": [_executor_dict(u, db) for u in users]}, ensure_ascii=False)


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
    return json.dumps({"executors": [_executor_dict(u, db) for u in users]}, ensure_ascii=False)


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

    creator = db.query(User).filter(User.id == _creator_id).first()
    creator_name = f"{creator.name} {creator.surname}".strip() if creator else "AI Assistant"
    if executor.telegram_id:
        send_telegram_notification.delay(
            executor.telegram_id,
            tpl_assigned(executor_name, title, deadline, creator_name),
        )

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
