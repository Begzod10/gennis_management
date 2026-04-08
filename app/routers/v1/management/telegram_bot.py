import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, Header, Request
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


@router.post("/generate-link-code")
def generate_link_code(
    current_user: User = Depends(get_current_user),
):
    """Generate a one-time code the user sends to the bot as /start <code>."""
    code = secrets.token_urlsafe(6)[:8]
    _redis.setex(f"tg_link:{code}", _LINK_TTL, str(current_user.id))
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "")
    deep_link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    return {
        "code": code,
        "expires_in": _LINK_TTL,
        "deep_link": deep_link,
        "instruction": f"Telegram botga /start {code} yuboring",
    }


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
    db: Session = Depends(get_db),
):
    """Telegram calls this when the bot receives a message."""
    if x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    body = await request.json()
    message = body.get("message", {})
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


@router.get("/status")
def telegram_status(current_user: User = Depends(get_current_user)):
    """Check whether the current user has linked their Telegram account."""
    return {"linked": current_user.telegram_id is not None, "telegram_id": current_user.telegram_id}


@router.delete("/unlink")
def unlink_telegram(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == current_user.id).first()
    user.telegram_id = None
    db.commit()
    return {"detail": "Telegram hisobi uzildi"}
