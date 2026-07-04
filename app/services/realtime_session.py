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

SYSTEM_PROMPT = """Sen Gennis tizimining ovozli vazifa yordamchisisan. Javoblaring OVOZDA o'qiladi:
qisqa (1-2 gap), ro'yxatsiz, belgilarsiz.
O'zbek tilida gapir; foydalanuvchi rus yoki inglizcha gapirsa — o'sha tilga o't.

JARAYON:
1. Vazifani eshit. Bir nechta vazifa aytilsa — bittalab, ketma-ket bajar.
2. Ism aytilsa — search_executor_by_name chaqir. Ism aytilmasa — list_executors chaqir.
3. ENG MOS xodimni tanla: skills > job > role. Teng bo'lsa — vazifasi kamrog'ini ol.
4. Bitta gap bilan tasdiqlat: "X ga Y ni N kunga topshiraymi?" (N — foydalanuvchi aytgan muddat).
5. "Ha" desa — create_mission chaqir. "Yo'q" desa — nimani o'zgartirishni so'ra, keyin qayta tasdiqlat.
6. Muvaffaqiyatda qisqa tasdiqla: "Bo'ldi, vazifa raqami 124, X ga topshirildi."

MUDDAT QOIDASI (MUHIM):
- Foydalanuvchi muddat aytsa — ALBATTA shu muddatni ishla. Standartga qaytma.
- "5 kun", "bir hafta", "2 kun", "uch kun", "10 kun" — barchasini to'g'ri o'qib deadline_days ga yoz.
- "bir hafta" = 7, "ikki hafta" = 14, "bir oy" = 30, "ertaga" = 1, "indinga" = 2.
- Hafta kuni aytilsa ("dushanbagacha", "jumagacha") — bugungi sanadan shu kungacha necha kun borligini hisoblab deadline_days ga yoz.
- Muddat AYTILMASA FAQAT standart 3 kun.

ISM QOIDASI (MUHIM):
- Ism aytilsa: search_executor_by_name chaqir.
- Natija executors bo'sh qaytsa lekin all_executors mavjud bo'lsa: all_executors ichidan foydalanuvchi aytgan ismga HAQIQATAN o'xshash odamni qidir. STT tez-tez qiladigan xatolar: x↔h, s↔sh, o↔o', a↔o, q↔k, j↔dj. Masalan "Shaxzod" → "Shahzod", "Jaxongir" → "Jahongir", "Aziza" → "Azizа".
- O'xshashini topsang, tasdiqlashda to'liq aniq ismini ayt: "Shahzod Sobirjonovga topshiraymi?"
- Ikkita bir xil darajada o'xshash odam bo'lsa — ikkalasini aytib, qaysi biri ekanini so'ra.
- Yaqin o'xshash ism BO'LMASA — hech kimni tanlama, "Topa olmadim, ismni qayta ayting" de.
- Hech qachon aytilgan ism o'rniga butunlay boshqa odamni tayinlama.

BOSHQA QOIDALAR:
- Kategoriya: maintenance (ta'mir), finance (moliya), academic (o'qitish), admin (qolgani). Ikkilansang — admin.
- Tool xato qaytarsa: uzr so'ra, bir marta qayta urin, bo'lmasa "keyinroq urinib ko'ring" de.
- Vazifaga aloqasi yo'q gaplarga qisqa javob berib, vazifaga qaytar."""


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
            "required": ["title", "executor_id", "deadline_days", "category"],
        },
    },
]


# ── OpenAI Realtime session config ────────────────────────────────────────────

_WEEKDAYS_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def build_session_update(creator_name: str = "") -> dict:
    from datetime import date as _date
    today = _date.today()
    weekday = _WEEKDAYS_UZ[today.weekday()]
    context = f"\n\nBugungi sana: {today.strftime('%Y-%m-%d')}, {weekday}."
    if creator_name:
        context += (
            f"\nSen bilan gaplashayotgan kishi: {creator_name}. Vazifani shu kishi yaratayapti."
            f"\nIjrochi sifatida hech qachon shu kishining o'zini tanlama — vazifani boshqa xodimga topshir."
            f"\nFaqat foydalanuvchi aniq \"o'zimga topshir\" desa — o'ziga tayinlashga ruxsat."
        )
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": SYSTEM_PROMPT + context,
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


def _stt_variants(name: str) -> list[str]:
    """Generate common STT mis-transcription variants of an Uzbek name."""
    variants = [name]
    # x ↔ h (most common: "Shaxzod" ↔ "Shahzod", "Jaxon" ↔ "Jahon")
    if "x" in name.lower():
        variants.append(name.lower().replace("x", "h"))
        variants.append(name.lower().replace("x", "kh"))
    if "h" in name.lower():
        variants.append(name.lower().replace("h", "x"))
    # sh ↔ s
    if "sh" in name.lower():
        variants.append(name.lower().replace("sh", "s"))
    # q ↔ k
    if "q" in name.lower():
        variants.append(name.lower().replace("q", "k"))
    if "k" in name.lower():
        variants.append(name.lower().replace("k", "q"))
    return list(dict.fromkeys(v for v in variants if v))  # deduplicate, preserve order


def handle_search_executor_by_name(args: dict, db: Session, creator_id: int) -> str:
    name_q = str(args.get("name", "")).strip()
    if not name_q:
        return json.dumps({"executors": [], "error": "name is required"})

    def _search(term: str):
        pattern = f"%{term}%"
        return (
            db.query(User)
            .filter(
                User.deleted == False,
                User.is_active == True,
                (User.name.ilike(pattern) | User.surname.ilike(pattern)),
            )
            .limit(5)
            .all()
        )

    # 1. Try each word in query (handles full-name queries like "Shahzodbek Omonboyev")
    for word in name_q.split():
        if len(word) < 3:
            continue
        users = _search(word)
        if users:
            return json.dumps({"executors": [_executor_dict(u, db) for u in users]}, ensure_ascii=False)

    # 2. Try STT transliteration variants of each word
    for word in name_q.split():
        if len(word) < 3:
            continue
        for variant in _stt_variants(word)[1:]:  # skip first (already tried)
            users = _search(variant)
            if users:
                return json.dumps({
                    "executors": [_executor_dict(u, db) for u in users],
                    "note": f"Matched '{variant}' (STT variant of '{word}')",
                }, ensure_ascii=False)

    # 3. Try progressively shorter prefix of first word
    first_word = name_q.split()[0] if name_q.split() else name_q
    for prefix_len in range(max(4, len(first_word) - 2), 3, -1):
        users = _search(first_word[:prefix_len])
        if users:
            return json.dumps({
                "executors": [_executor_dict(u, db) for u in users],
                "note": f"Prefix match for '{name_q}'",
            }, ensure_ascii=False)

    return json.dumps({"executors": [], "error": f"No executor found matching '{name_q}'. Ask the user to repeat the name clearly."}, ensure_ascii=False)


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
