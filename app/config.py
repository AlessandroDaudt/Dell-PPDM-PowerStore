from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="APP_", case_sensitive=False, extra="ignore"
    )

    app_name: str = "SANFlow Dell"
    secret_key: str = Field(default="development-only-change-me", min_length=16)
    admin_username: str = "admin"
    admin_password: str = "admin"
    database_url: str = "sqlite:///./data/sanflow.db"
    default_dry_run: bool = True
    log_level: str = "INFO"
    ansible_playbook: Path = Path("playbooks/brocade_zoning.yml")
    ansible_timeout: int = 600
    ppdm_discovery_timeout: int = 180
    ppdm_discovery_interval: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
