import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import redis

from app.database import get_db
from app.models import MobileTelegramLink, User
from app.config import settings
from app.tasks import send_telegram_notification
from app.routers.v1.auth import get_current_user
from app.mobile.telegram import consume_mobile_link_code, resolve_mobile_link_code
from app.services.telegram_voice import prepare_telegram_voice, create_mission_from_pending

router = APIRouter(prefix="/telegram", tags=["Telegram"])

_redis = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)
_LINK_TTL = 300  # 5 minutes


@router.post(
    "/generate-link-code",
    summary="Generate one-time link code",
    responses={
        200: {
            "description": "One-time code to send to the bot",
            "content": {
                "application/json": {
                    "example": {
                        "code": "aB3xK9mZ",
                        "expires_in": 300,
                        "deep_link": "https://t.me/gennis_office_bot?start=aB3xK9mZ",
                        "instruction": "Telegram botga /start aB3xK9mZ yuboring",
                    }
                }
            },
        }
    },
)
def generate_link_code(
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time code the user sends to the bot as /start <code>."""
    code = secrets.token_urlsafe(6)[:8]
    _redis.setex(f"tg_link:{code}", _LINK_TTL, str(current_user.id))
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "")
    deep_link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    tg_link = f"tg://resolve?domain={bot_username}&start={code}" if bot_username else None
    return {
        "code": code,
        "expires_in": _LINK_TTL,
        "deep_link": deep_link,
        "tg_link": tg_link,
        "instruction": f"Telegram botga /start {code} yuboring",
    }


class TelegramWebhookBody(BaseModel):
    model_config = {"json_schema_extra": {
        "example": {
            "update_id": 123456789,
            "message": {
                "message_id": 42,
                "from": {
                    "id": 987654321,
                    "first_name": "Jasur",
                    "username": "jasur_dev",
                },
                "chat": {"id": 987654321, "type": "private"},
                "date": 1712534400,
                "text": "/start aB3xK9mZ",
            },
        }
    }}

    update_id: int = Field(..., example=123456789)
    message: dict = Field(
        default={},
        example={
            "message_id": 42,
            "from": {"id": 987654321, "first_name": "Jasur"},
            "chat": {"id": 987654321, "type": "private"},
            "date": 1712534400,
            "text": "/start aB3xK9mZ",
        },
    )


@router.post(
    "/webhook",
    summary="Telegram webhook (called by Telegram servers)",
    responses={
        200: {
            "description": "Always returns ok: true",
            "content": {"application/json": {"example": {"ok": True}}},
        },
        403: {
            "description": "Invalid webhook secret token",
            "content": {"application/json": {"example": {"detail": "Forbidden"}}},
        },
    },
)
async def telegram_webhook(
    body: TelegramWebhookBody,
    x_telegram_bot_api_secret_token: str = Header(
        None,
        example="gennis_office_bot_secret_1001",
        description="Must match TELEGRAM_WEBHOOK_SECRET env var",
    ),
    db: Session = Depends(get_db),
):
    """Telegram calls this when the bot receives a message."""
    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    message = body.message
    text = (message.get("text") or "").strip()
    chat_id = message.get("chat", {}).get("id")
    tg_first_name = message.get("from", {}).get("first_name", "")
    tg_last_name = message.get("from", {}).get("last_name", "")
    tg_full_name = f"{tg_first_name} {tg_last_name}".strip() or tg_first_name

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_telegram_notification.delay(
                chat_id,
                f"Salom, <b>{tg_full_name}</b>!\nBotdan foydalanish uchun management tizimidan kod oling.",
            )
            return {"ok": True}

        code = parts[1].strip()

        # 1. Legacy web link code (`tg_link:<code>` → bare management user id)
        user_id_str = _redis.get(f"tg_link:{code}")
        if user_id_str:
            user = db.query(User).filter(User.id == int(user_id_str)).first()
            if user:
                user.telegram_id = chat_id
                db.commit()
                _redis.delete(f"tg_link:{code}")
                full_name = f"{user.name} {user.surname}".strip() if user.surname else user.name
                send_telegram_notification.delay(
                    chat_id,
                    f"✅ Hurmatli <b>{full_name}</b>, Telegram hisobingiz muvaffaqiyatli bog'landi!",
                )
            return {"ok": True}

        # 2. Mobile link code (`mobile_tg_link:<code>` → "<system>:<id>")
        resolved = resolve_mobile_link_code(code)
        if not resolved:
            send_telegram_notification.delay(chat_id, "❌ Kod noto'g'ri yoki muddati o'tgan.")
            return {"ok": True}

        system, external_id = resolved
        full_name = tg_full_name  # fallback when we can't resolve a name

        if system == "management":
            user = db.query(User).filter(User.id == external_id).first()
            if user:
                user.telegram_id = chat_id
                db.commit()
                full_name = f"{user.name} {user.surname or ''}".strip() or full_name
        else:
            link = (
                db.query(MobileTelegramLink)
                .filter(
                    MobileTelegramLink.system == system,
                    MobileTelegramLink.external_id == external_id,
                )
                .first()
            )
            if link:
                link.telegram_id = chat_id
            else:
                db.add(MobileTelegramLink(
                    system=system,
                    external_id=external_id,
                    telegram_id=chat_id,
                ))
            db.commit()

        consume_mobile_link_code(code)
        send_telegram_notification.delay(
            chat_id,
            f"✅ Hurmatli <b>{full_name}</b>, Telegram hisobingiz muvaffaqiyatli bog'landi!",
        )

    # ── Pending deadline reply: user sends a number after voice ─────────────
    elif text and text.strip().isdigit():
        pending_key = f"tg_voice_pending:{chat_id}"
        pending_json = _redis.get(pending_key)
        if pending_json:
            import json as _json
            pending = _json.loads(pending_json)
            deadline_days = max(1, int(text.strip()))
            result = create_mission_from_pending(pending, deadline_days, db)
            _redis.delete(pending_key)
            reply = (
                f"✅ <b>Vazifa yaratildi!</b>\n\n"
                f"📋 {result['title']}\n"
                f"👤 Ijrochi: <b>{result['executor']}</b>\n"
                f"📅 Muddat: {result['deadline']}\n"
                f"🔖 Kategoriya: {result['category']}\n"
                f"🆔 ID: <code>{result['mission_id']}</code>"
            )
            send_telegram_notification.delay(chat_id, reply)
            return {"ok": True}

    # ── Voice message → AI mission creation ──────────────────────────────────
    elif message.get("voice"):
        creator = db.query(User).filter(
            User.telegram_id == chat_id,
            User.deleted == False,
            User.is_active == True,
        ).first()

        if not creator:
            send_telegram_notification.delay(
                chat_id,
                "❌ Telegram hisobingiz bog'lanmagan.\nAvval <b>Management</b> tizimida Telegram ulang.",
            )
            return {"ok": True}

        send_telegram_notification.delay(chat_id, "⏳ Ovoz xabari qayta ishlanmoqda...")

        result = await prepare_telegram_voice(message["voice"]["file_id"], creator.id, db)

        if result["ok"]:
            import json as _json
            _redis.setex(f"tg_voice_pending:{chat_id}", 120, _json.dumps(result))
            deadline_hint = result["deadline_days"]
            reply = (
                f"🎯 <b>{result['title']}</b>\n"
                f"👤 Ijrochi: <b>{result['executor_name']}</b>\n"
                f"🔖 Kategoriya: {result['category']}\n\n"
                f"📅 Muddat necha kun? (standart: <b>{deadline_hint}</b>)\n"
                f"<i>Raqam yuboring yoki {deadline_hint} uchun shu raqamni yuboring</i>"
            )
        else:
            reply = "❌ " + result.get("error", "Noma'lum xato")
            if result.get("transcript"):
                reply += f"\n\n🎤 <i>{result['transcript']}</i>"
            if result.get("title"):
                reply += f"\n📋 Sarlavha: {result['title']}"

        send_telegram_notification.delay(chat_id, reply)

    return {"ok": True}


@router.get(
    "/status",
    summary="Check Telegram link status",
    responses={
        200: {
            "description": "Whether the current user has linked their Telegram account",
            "content": {
                "application/json": {
                    "examples": {
                        "linked": {
                            "summary": "Account linked",
                            "value": {"linked": True, "telegram_id": 987654321},
                        },
                        "not_linked": {
                            "summary": "Account not linked",
                            "value": {"linked": False, "telegram_id": None},
                        },
                    }
                }
            },
        }
    },
)
def telegram_status(current_user: User = Depends(get_current_user)):
    """Check whether the current user has linked their Telegram account."""
    return {"linked": current_user.telegram_id is not None, "telegram_id": current_user.telegram_id}


@router.delete(
    "/unlink",
    summary="Unlink Telegram account",
    responses={
        200: {
            "description": "Telegram account unlinked successfully",
            "content": {
                "application/json": {
                    "example": {"detail": "Telegram hisobi uzildi"}
                }
            },
        }
    },
)
def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    user.telegram_id = None
    db.commit()
    return {"detail": "Telegram hisobi uzildi"}
