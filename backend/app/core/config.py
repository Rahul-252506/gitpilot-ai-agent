"""Application configuration loaded from environment variables.

Secrets (GitHub token, LLM API keys) are read exclusively from the
environment and never exposed through the API, logs, or database.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env files so local secrets never need to live in the shell or in code.
# Precedence: real environment variables always win over .env values.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
load_dotenv(_BACKEND_ROOT / ".env", override=False)
load_dotenv(Path(os.getcwd()) / ".env", override=False)


class Settings:
    """Runtime settings. Values come from environment variables with
    sensible local-development defaults; empty secrets simply mean the
    corresponding external service is unavailable until configured.
    """

    def __init__(self) -> None:
        # --- Secrets (never log, never serialize) ---
        self.github_token: str = os.getenv("GITHUB_TOKEN", "").strip()
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()

        # --- LLM provider ---
        # "gemini" (real), "openai" (real), or "mock" (deterministic, for
        # tests / offline demo). Defaults to "mock" so the backend boots
        # without credentials and fails clearly if a real provider is
        # requested without its key.
        self.llm_provider: str = os.getenv("LLM_PROVIDER", "mock").strip().lower()
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip()
        self.llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))

        # --- GitHub ---
        self.github_api_base_url: str = os.getenv(
            "GITHUB_API_BASE_URL", "https://api.github.com"
        ).strip().rstrip("/")
        self.github_timeout_seconds: float = float(
            os.getenv("GITHUB_TIMEOUT_SECONDS", "15")
        )

        # --- Agent limits ---
        self.agent_max_steps: int = int(os.getenv("AGENT_MAX_STEPS", "20"))
        self.agent_timeout_seconds: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
        self.tool_max_output_chars: int = int(
            os.getenv("TOOL_MAX_OUTPUT_CHARS", "8000")
        )
        self.structured_output_retries: int = int(
            os.getenv("STRUCTURED_OUTPUT_RETRIES", "2")
        )

        # --- App ---
        self.database_path: str = os.getenv(
            "GITPILOT_DATABASE_PATH", os.path.join(os.getcwd(), "gitpilot.db")
        )
        # Comma-separated list of allowed browser origins for CORS.
        self.frontend_origin: str = os.getenv(
            "FRONTEND_ORIGIN",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        self.log_level: str = os.getenv("GITPILOT_LOG_LEVEL", "INFO").strip().upper()

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def github_configured(self) -> bool:
        return bool(self.github_token)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        return False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()