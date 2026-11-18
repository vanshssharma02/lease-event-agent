"""Configuration module for lease-event-agent."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter API credentials
    OPENROUTER_API_KEY: str = ""

    # Primary LLM Model configuration
    # Note: The slug should be verified on OpenRouter (https://openrouter.ai/models)
    LLM_MODEL: str = "google/gemma-4-26b-a4b-it:free"

    # Fallback model for resilience if primary model encounters rate limits or errors
    LLM_FALLBACK_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Operating mode: "live" (calls OpenRouter) or "mock" (deterministic synthetic generator)
    LLM_MODE: str = "mock"

    # Scheduler settings
    SCHEDULER_TZ: str = "UTC"
    SCHEDULER_HOUR: int = 6

    # SMTP Notification settings (optional, defaults to local DB/log if unset)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None

    # API / UI settings
    API_URL: str = "http://localhost:8000"

    # Project directories
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = BASE_DIR / "data" / "lease_register.db"
    CHROMA_PERSIST_DIR: Path = BASE_DIR / "chroma_db"
    NOTIFICATIONS_LOG_PATH: Path = BASE_DIR / "data" / "notifications.log"


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
