from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized app configuration, loaded from environment variables / .env.

    See ../../.env.example for the full list of variables and what they do.
    """

    ENVIRONMENT: str = "development"

    # --- Database --------------------------------------------------------
    DATABASE_URL: str = (
        "postgresql+psycopg2://ssc_user:ssc_password@localhost:5432/ssc_cgl_platform"
    )

    # --- External authentication service ----------------------------------
    # This platform does not store credentials. All signup/login/2FA/password
    # flows are proxied to this external auth service; see AUTH_INTEGRATION.md.
    AUTH_SERVICE_BASE_URL: str = "https://authentication-api-zeta.vercel.app"
    AUTH_SERVICE_TIMEOUT_SECONDS: float = 10.0
    # How long a validated token's /v1/auth/me result is cached in-memory,
    # to avoid re-validating against the auth service on every autosave call.
    AUTH_CACHE_TTL_SECONDS: int = 60

    # Cookie our backend sets on the browser after proxying a successful
    # login. It carries the auth-service session JWT, but the frontend never
    # reads or handles that JWT directly (httpOnly). Defaults to insecure for
    # local HTTP dev -- set true behind HTTPS in production.
    SESSION_COOKIE_NAME: str = "ssc_cgl_session"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_SAMESITE: str = "lax"

    # Includes both localhost and 127.0.0.1 -- which one the browser actually
    # uses for the Vite dev server depends on the machine's DNS resolution,
    # so both are allowed to avoid an avoidable CORS mismatch.
    CORS_ALLOWED_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
