"""Application settings, loaded from env vars and backend/.env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "dev"
    log_level: str = "INFO"
    # Console renderer in dev, JSON lines otherwise.
    log_json: bool = False

    # Port 5433: the compose Postgres publishes there because a Homebrew
    # postgresql@16 on this machine owns 127.0.0.1:5432.
    database_url: str = (
        "postgresql+asyncpg://caremesh:caremesh_dev_password@localhost:5433/caremesh"
    )

    cors_origins: list[str] = ["http://localhost:3000"]

    # The dev default is intentionally not a secret. Anything but dev fails
    # closed at startup if this value is still in place.
    jwt_secret: str = "dev-only-not-a-secret"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604800

    def validate_for_environment(self) -> None:
        if self.environment != "dev" and self.jwt_secret == "dev-only-not-a-secret":
            raise RuntimeError("JWT_SECRET must be set outside dev")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_for_environment()
    return settings
