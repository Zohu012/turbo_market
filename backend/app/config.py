from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://turbo:changeme@localhost:5432/turbo_market"
    sync_database_url: str = "postgresql+psycopg2://turbo:changeme@localhost:5432/turbo_market"
    redis_url: str = "redis://localhost:6379/0"
    admin_api_key: str = "changeme-admin-key"

    scraper_mode: str = "headless"
    cdp_url: str = "http://localhost:9222"
    delay_seconds: float = 1.5
    max_pages: int = 0

    azn_per_usd: float = 1.7

    full_scan_hour: int = 2
    full_scan_minute: int = 0


settings = Settings()
