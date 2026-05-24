"""Mobile-side Telegram bot linking.

Flow:
  1. Mobile client calls POST /mobile/telegram/generate-link-code → server
     stores `mobile_tg_link:<code>` in Redis (5 min TTL) with the caller's
     {system, external_id} encoded as `<system>:<id>`.
  2. Mobile client opens the deep link `t.me/<bot>?start=<code>`.
  3. Telegram bot fires the existing /telegram/webhook with the /start
     payload; the webhook resolves the code, sets `user.telegram_id` for
     management users or upserts a `MobileTelegramLink` row for
     Gennis/Turon users.

Status / unlink endpoints branch on the caller's system the same way.
"""
import json
import os
import secrets
from typing import Optional

import redis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.mobile.deps import get_mobile_identity
from app.mobile.schemas import MobileIdentity
from app.models import MobileTelegramLink, User


router = APIRouter(prefix="/mobile/telegram", tags=["Mobile - Telegram"])

_redis = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
)
_LINK_TTL = 300  # seconds


def _redis_key(code: str) -> str:
    return f"mobile_tg_link:{code}"


@router.post("/generate-link-code", summary="Generate one-time code to link Telegram")
def generate_link_code(identity: MobileIdentity = Depends(get_mobile_identity)):
    """Mint a one-time code; the mobile client passes it to the bot.

    The Redis value is `<system>:<external_id>` so the webhook can route the
    binding to the right place (management `User.telegram_id` vs the bridge
    table) without needing a second lookup.
    """
    code = secrets.token_urlsafe(6)[:8]
    _redis.setex(_redis_key(code), _LINK_TTL, f"{identity.system}:{identity.external_id}")

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


@router.get("/status", summary="Check whether the caller's Telegram is linked")
def telegram_status(
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
):
    telegram_id = _lookup_telegram_id(identity, db)
    return {"linked": telegram_id is not None, "telegram_id": telegram_id}


@router.delete("/unlink", summary="Disconnect the caller's Telegram link")
def unlink(
    identity: MobileIdentity = Depends(get_mobile_identity),
    db: Session = Depends(get_db),
):
    if identity.system == "management":
        user = db.query(User).filter(User.id == identity.external_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user.telegram_id is None:
            return {"detail": "Telegram allaqachon uzilgan"}
        user.telegram_id = None
        db.commit()
        return {"detail": "Telegram hisobi uzildi"}

    row = (
        db.query(MobileTelegramLink)
        .filter(
            MobileTelegramLink.system == identity.system,
            MobileTelegramLink.external_id == identity.external_id,
        )
        .first()
    )
    if not row:
        return {"detail": "Telegram allaqachon uzilgan"}
    db.delete(row)
    db.commit()
    return {"detail": "Telegram hisobi uzildi"}


# ── Helpers shared with the webhook ──────────────────────────────────────────

def _lookup_telegram_id(identity: MobileIdentity, db: Session) -> Optional[int]:
    if identity.system == "management":
        user = db.query(User).filter(User.id == identity.external_id).first()
        return user.telegram_id if user else None
    row = (
        db.query(MobileTelegramLink)
        .filter(
            MobileTelegramLink.system == identity.system,
            MobileTelegramLink.external_id == identity.external_id,
        )
        .first()
    )
    return row.telegram_id if row else None


def resolve_mobile_link_code(code: str) -> Optional[tuple[str, int]]:
    """Webhook helper: pop a mobile link code from Redis and return (system, external_id)."""
    value = _redis.get(_redis_key(code))
    if not value:
        return None
    try:
        system, ext = value.split(":", 1)
        return system, int(ext)
    except (ValueError, AttributeError):
        return None


def consume_mobile_link_code(code: str) -> None:
    _redis.delete(_redis_key(code))
