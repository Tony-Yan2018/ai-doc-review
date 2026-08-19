from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./review.sqlite3"
    upload_dir: Path = Path("./uploads")
    max_upload_bytes: int = 20 * 1024 * 1024
    worker_poll_seconds: float = 2.0
    job_lease_seconds: int = 300
    job_retry_base_seconds: int = 5
    cors_origins: str = "http://localhost:5173"
    jwt_secret: str = "local-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    refresh_cookie_secure: bool = False

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
