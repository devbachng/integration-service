"""
Configuration for the Integration Service.

Everything is read from environment variables so the service can be
deployed (Docker / CI) without any code change. See .env.example for
the full list of variables and their defaults.
"""
from __future__ import annotations
import os


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # --- source systems ---
    SIS_URL: str = os.getenv("SIS_URL", "http://127.0.0.1:8001").rstrip("/")
    LMS_URL: str = os.getenv("LMS_URL", "http://127.0.0.1:8002").rstrip("/")

    # --- tenant & credentials (never logged, see app/logging_utils.py) ---
    TENANT_ID: str = os.getenv("TENANT_ID", "TEAM01")
    SIS_CLIENT_ID: str = os.getenv("SIS_CLIENT_ID", "WEB-CONSOLE")
    SIS_CLIENT_SECRET: str = os.getenv("SIS_CLIENT_SECRET", "student-secret")
    LMS_CLIENT_ID: str = os.getenv("LMS_CLIENT_ID", "WEB-CONSOLE")
    LMS_CLIENT_SECRET: str = os.getenv("LMS_CLIENT_SECRET", "student-secret")

    # --- integration service own storage ---
    INTEGRATION_DB_URL: str = os.getenv(
        "INTEGRATION_DB_URL", "sqlite:////home/claude/project/integration-service/data/integration.db"
    )

    # --- operating mode ---
    # "poll" (default, robust for grading/demo) or "webhook" (also registers
    # callbacks on SIS/LMS pointing back at this service).
    INTEGRATION_MODE: str = os.getenv("INTEGRATION_MODE", "poll")
    PUBLIC_CALLBACK_BASE_URL: str = os.getenv("PUBLIC_CALLBACK_BASE_URL", "http://127.0.0.1:8000")
    POLL_INTERVAL_SECONDS: float = float(os.getenv("POLL_INTERVAL_SECONDS", "3"))
    RETRY_WORKER_INTERVAL_SECONDS: float = float(os.getenv("RETRY_WORKER_INTERVAL_SECONDS", "2"))
    RECONCILE_INTERVAL_SECONDS: float = float(os.getenv("RECONCILE_INTERVAL_SECONDS", "0"))  # 0 = only manual/startup

    # --- retry / backoff policy (NFR-02, NFR-03) ---
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "6"))
    BACKOFF_BASE_SECONDS: float = float(os.getenv("BACKOFF_BASE_SECONDS", "2"))
    BACKOFF_MAX_SECONDS: float = float(os.getenv("BACKOFF_MAX_SECONDS", "60"))

    # --- rate-limit awareness (NFR-12) ---
    HTTP_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
    RECONCILE_PACING_SECONDS: float = float(os.getenv("RECONCILE_PACING_SECONDS", "0.25"))

    # --- misc ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    AUTO_RESET_ON_START: bool = _bool("AUTO_RESET_ON_START", "false")
    AUTO_BOOTSTRAP_ON_START: bool = _bool("AUTO_BOOTSTRAP_ON_START", "true")
    ADMIN_KEY: str = os.getenv("ADMIN_KEY", "admin-secret")  # only used if AUTO_RESET_ON_START=true


settings = Settings()
