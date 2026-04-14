import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import redis

from app.database import get_db
from app.models import User
from app.config import settings
from app.tasks import send_telegram_notification
from app.routers.v1.auth import get_current_user

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

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_telegram_notification.delay(
                chat_id,
                "Botdan foydalanish uchun management tizimidan kod oling.",
            )
            return {"ok": True}

        code = parts[1].strip()
        user_id_str = _redis.get(f"tg_link:{code}")
        if not user_id_str:
            send_telegram_notification.delay(chat_id, "❌ Kod noto'g'ri yoki muddati o'tgan.")
            return {"ok": True}

        user = db.query(User).filter(User.id == int(user_id_str)).first()
        if not user:
            return {"ok": True}

        user.telegram_id = chat_id
        db.commit()
        _redis.delete(f"tg_link:{code}")
        send_telegram_notification.delay(
            chat_id,
            f"✅ Hurmatli {user.name}, Telegram hisobingiz muvaffaqiyatli bog'landi!",
        )

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
