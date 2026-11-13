"""Application configuration module."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    app_name: str = "FlowGuard"
    app_version: str = "0.1.0"
    app_description: str = "A Configurable Workflow Decision Platform"
    debug: bool = True
    api_v1_str: str = "/api/v1"
    database_url: str = "sqlite:///./flowguard.db"

    model_config = SettingsConfigDict(case_sensitive=True)


settings: Settings = Settings()
