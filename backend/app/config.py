"""Application settings, loaded from environment variables (see .env.example).

Secrets are never hard-coded. The app fails closed: if authentication is not
configured, every API request is rejected, and production refuses to start in
demo mode.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
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
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY (or set AI_PROVIDER=none).")
        return problems

    @property
    def demo_mode(self) -> bool:
        return self.auth_mode == "demo" and self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
