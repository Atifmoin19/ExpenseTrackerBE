"""App settings, read from environment variables.

Field names match CONTRACT.md's "Backend env vars" section exactly — do not
rename these without updating CONTRACT.md and Backend/.env.example together.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres (Neon)
    DATABASE_URL: str = ""

    # JWT / auth
    JWT_SECRET: str = ""
    JWT_ACCESS_TTL_MINUTES: int = 60
    JWT_REFRESH_TTL_DAYS: int = 30

    # Email OTP (EmailJS — sends via a connected Gmail account, no domain
    # verification needed; PRIVATE_KEY doubles as the server-side accessToken
    # that lets this bypass EmailJS's normal browser-origin check)
    EMAILJS_SERVICE_ID: str = ""
    EMAILJS_TEMPLATE_ID: str = ""
    EMAILJS_PUBLIC_KEY: str = ""
    EMAILJS_PRIVATE_KEY: str = ""

    # Google Identity Services
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Web Push / VAPID
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:you@example.com"

    # Neon Object Storage (S3-compatible)
    AWS_ENDPOINT_URL_S3: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = ""
    S3_BUCKET_NAME: str = ""

    ALLOWED_ORIGINS: str = "http://localhost:5173"
    ENV: str = "development"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in {"production", "prod"}

    @property
    def is_development(self) -> bool:
        return not self.is_production


settings = Settings()
