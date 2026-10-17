"""Application settings, loaded from environment variables (see .env.example).

Secrets are never hard-coded. The app fails closed: if authentication is not
configured, every API request is rejected, production refuses to start in demo
mode, and a hosted demo (APP_ENV=demo) refuses to start without an access
password.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "demo" = hosted, password-protected demo on synthetic data only (see docs/DEPLOY_DEMO.md)
    app_env: Literal["development", "test", "demo", "production"] = "development"
    database_url: str = Field(default="postgresql+psycopg://cac:cac_local_dev@localhost:5432/cac_dev")

    # "entra" (production), "demo" (explicit demo mode only) or "" (unset -> fail closed)
    auth_mode: Literal["entra", "demo", ""] = ""

    # Microsoft Entra ID (scaffolded; see docs/INTEGRATION_CHECKLIST.md)
    entra_tenant_id: str = ""
    entra_api_client_id: str = ""  # audience of access tokens issued for this API
    entra_spa_client_id: str = ""  # exposed to the frontend via /api/meta
    entra_api_scope: str = ""  # e.g. api://<api-client-id>/access_as_user

    # Optional server-side AI adapter: "none" (deterministic templates only) or "anthropic"
    ai_provider: Literal["none", "anthropic"] = "none"
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: float = 20.0

    # Imports with data_classification=live are refused unless explicitly allowed (after approval).
    allow_live_import: bool = False
    # Folder watched by the scheduler for new import packages (one sub-folder per package).
    import_inbox: str = ""
    scheduler_interval_minutes: int = 60

    # Serve the built frontend from the API process (single deployable)
    frontend_dist: str = "../frontend/dist"

    cors_origins: str = ""  # comma-separated; empty means same-origin only

    # Shared-password gate in front of the whole app (UI, API, docs). Required when APP_ENV=demo.
    # Set it in the hosting platform's secret settings, never in Git.
    demo_access_user: str = "demo"
    demo_access_password: str = ""
    # Hosted demo: regenerate the synthetic data once it is this old, so it never goes stale.
    demo_reseed_after_hours: float = 24.0

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosting platforms hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    def startup_problems(self) -> list[str]:
        """Configuration errors that must stop the process from starting."""
        problems: list[str] = []
        if self.app_env == "production":
            if self.auth_mode != "entra":
                problems.append("Production requires AUTH_MODE=entra (demo mode and unset auth are refused).")
            if self.auth_mode == "entra" and not (self.entra_tenant_id and self.entra_api_client_id):
                problems.append("AUTH_MODE=entra requires ENTRA_TENANT_ID and ENTRA_API_CLIENT_ID.")
            if "cac_local_dev" in self.database_url:
                problems.append("Production must not use the local development database credentials.")
        if self.app_env == "demo":
            if len(self.demo_access_password) < 16:
                problems.append("APP_ENV=demo requires DEMO_ACCESS_PASSWORD (at least 16 characters); the hosted demo is never left open.")
            if self.auth_mode != "demo":
                problems.append("APP_ENV=demo requires AUTH_MODE=demo.")
            if self.ai_provider != "none":
                problems.append("APP_ENV=demo requires AI_PROVIDER=none (no external services in the hosted demo).")
            if self.allow_live_import or self.import_inbox:
                problems.append("APP_ENV=demo uses generated synthetic data only: unset ALLOW_LIVE_IMPORT and IMPORT_INBOX.")
            if "cac_local_dev" in self.database_url:
                problems.append("APP_ENV=demo must not use the local development database credentials.")
        if self.demo_access_password and self.auth_mode == "entra":
            problems.append("DEMO_ACCESS_PASSWORD is for demo deployments only; do not combine it with AUTH_MODE=entra.")
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY (or set AI_PROVIDER=none).")
        return problems

    @property
    def demo_mode(self) -> bool:
        return self.auth_mode == "demo" and self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
