from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Application configuration. Every value comes from backend/.env (or a
    real environment variable of the same name, e.g. on Vercel) -- there are
    no defaults, so a missing variable fails at startup instead of silently
    falling back to something else.

    See ../../.env.example for the full list of variables and what they do.
    """

    ENVIRONMENT: str

    # --- Database ---
    DATABASE_URL: str

    # --- External authentication service ---
    # This platform does not store credentials. All signup/login/2FA/password
    # flows are proxied to this external auth service; see AUTH_INTEGRATION.md.
    AUTH_SERVICE_BASE_URL: str
    AUTH_SERVICE_TIMEOUT_SECONDS: float
    # How long a validated token's /v1/auth/me result is cached in-memory,
    # to avoid re-validating against the auth service on every autosave call.
    AUTH_CACHE_TTL_SECONDS: int

    # Cookie our backend sets on the browser after proxying a successful
    # login. It carries the auth-service session JWT, but the frontend never
    # reads or handles that JWT directly (httpOnly). Set SECURE=true behind HTTPS.
    SESSION_COOKIE_NAME: str
    SESSION_COOKIE_SECURE: bool
    SESSION_COOKIE_SAMESITE: str

    # JSON list, e.g. ["http://localhost:5173","http://127.0.0.1:5173"]
    CORS_ALLOWED_ORIGINS: list[str]

    # --- AI explanations ---
    # Any OpenAI-compatible server (vLLM, Ollama, LM Studio, Together, ...).
    # Leave LLM_BASE_URL empty (LLM_BASE_URL=) to disable the feature entirely.
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str
    LLM_TIMEOUT_SECONDS: float
    # SDK-level retries (with backoff) -- mainly for 429s on free-tier models.
    LLM_MAX_RETRIES: int
    # Sends {"reasoning": {"enabled": true}} (OpenRouter-style). Better answers
    # on maths/reasoning, but slower and costs more tokens.
    LLM_REASONING: bool

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")


settings = Settings()
