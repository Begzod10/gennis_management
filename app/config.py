import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    MOBILE_CLIENT_ID: str = os.getenv("MOBILE_CLIENT_ID", "")
    # Additional OAuth client IDs that can issue Google ID tokens against this
    # backend (mobile apps each get their own). Comma-separated. Web client is
    # always trusted via GOOGLE_CLIENT_ID above.
    GOOGLE_ALLOWED_CLIENT_IDS: str = os.getenv("GOOGLE_ALLOWED_CLIENT_IDS", "")
    # Apple Sign In — Apple bundle IDs / Service IDs accepted as `aud` claims.
    # For the native iOS app this is the app bundle ID (e.g. uz.gennis.todo).
    # Comma-separated when adding a web/Android Service ID later.
    APPLE_ALLOWED_CLIENT_IDS: str = os.getenv("APPLE_ALLOWED_CLIENT_IDS", "")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    # Optional HTTP/SOCKS5 proxy for Telegram API calls (needed when api.telegram.org
    # is blocked by the hosting provider). Example: "socks5://user:pass@host:1080"
    # or "http://host:3128". Leave empty to connect directly.
    TELEGRAM_PROXY: str = os.getenv("TELEGRAM_PROXY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_WHISPER_MODEL: str = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")
    OPENAI_REALTIME_URL: str = os.getenv("OPENAI_REALTIME_URL", "wss://api.openai.com/v1/realtime")
    OPENAI_REALTIME_MODEL: str = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")


settings = Settings()
