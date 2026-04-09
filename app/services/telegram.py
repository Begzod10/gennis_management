import httpx
from app.config import settings

_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram(chat_id: int, text: str) -> bool:
    """Send a Telegram message. Returns False silently on any failure."""
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    url = _SEND_URL.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            return resp.status_code == 200
    except Exception:
        return False


# ── Message templates (Uzbek) ─────────────────────────────────────────────────

def tpl_assigned(title: str, deadline, creator_name: str) -> str:
    return (
        f"📋 <b>Yangi topshiriq berildi!</b>\n\n"
        f"<b>{title}</b>\n"
        f"📅 Muddat: {deadline}\n"
        f"👤 Tayinlovchi: {creator_name}"
    )

def tpl_you_are_reviewer(title: str, deadline, creator_name: str) -> str:
    return (
        f"👁 <b>Yangi topshiriqda tekshiruvchi etib tayinlandingiz</b>\n\n"
        f"<b>{title}</b>\n"
        f"📅 Muddat: {deadline}\n"
        f"👤 Yaratuvchi: {creator_name}"
    )

def tpl_completed(title: str, executor_name: str, finish_date) -> str:
    return (
        f"✅ <b>Topshiriq bajarildi!</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 Ijrochi: {executor_name}\n"
        f"📅 Tugatilgan sana: {finish_date}"
    )

def tpl_status_changed(title: str, new_status: str) -> str:
    STATUS_UZ = {
        "not_started": "Boshlanmagan",
        "in_progress": "Jarayonda",
        "blocked": "Bloklangan",
        "completed": "Bajarildi",
        "approved": "Tasdiqlandi",
        "declined": "Rad etildi",
        "recheck": "Qayta tekshiruv",
    }
    status_label = STATUS_UZ.get(new_status, new_status)
    return (
        f"🔄 <b>Topshiriq holati o'zgardi</b>\n\n"
        f"<b>{title}</b>\n"
        f"Yangi holat: <b>{status_label}</b>"
    )

def tpl_approved(title: str, approver_name: str) -> str:
    return (
        f"✅ <b>Topshiriq tasdiqlandi!</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 Tasdiqlagan: {approver_name}"
    )

def tpl_declined(title: str, approver_name: str) -> str:
    return (
        f"❌ <b>Topshiriq rad etildi</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 Rad etgan: {approver_name}"
    )

def tpl_redirected_new(title: str, redirected_by: str) -> str:
    return (
        f"📋 <b>Topshiriq sizga yo'naltirildi</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 Yo'naltirgan: {redirected_by}"
    )

def tpl_redirected_creator(title: str, old_executor: str, new_executor: str) -> str:
    return (
        f"🔀 <b>Topshiriq ijrochisi o'zgartirildi</b>\n\n"
        f"<b>{title}</b>\n"
        f"{old_executor} → <b>{new_executor}</b>"
    )

def tpl_deleted(title: str) -> str:
    return f"🗑 <b>Topshiriq bekor qilindi</b>\n\n<b>{title}</b>"

def tpl_updated(title: str, changed_by: str) -> str:
    return (
        f"✏️ <b>Topshiriq yangilandi</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 O'zgartirgan: {changed_by}"
    )

def tpl_comment_added(title: str, sender_name: str, text: str) -> str:
    preview = text[:100] + "..." if len(text) > 100 else text
    return (
        f"💬 <b>Yangi izoh</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 {sender_name}: {preview}"
    )

def tpl_subtask_added(title: str, subtask_title: str, sender_name: str) -> str:
    return (
        f"☑️ <b>Yangi kichik vazifa qo'shildi</b>\n\n"
        f"<b>{title}</b>\n"
        f"📌 {subtask_title}\n"
        f"👤 {sender_name}"
    )

def tpl_attachment_added(title: str, sender_name: str) -> str:
    return (
        f"📎 <b>Yangi fayl biriktirildi</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 {sender_name}"
    )

def tpl_proof_added(title: str, sender_name: str, comment: str) -> str:
    body = f"\n💬 {comment}" if comment else ""
    return (
        f"📸 <b>Bajarish isboti yuklandi</b>\n\n"
        f"<b>{title}</b>\n"
        f"👤 {sender_name}{body}"
    )
