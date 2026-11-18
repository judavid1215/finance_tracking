"""Configuración por variables de entorno (y .env si existe)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: str = "/data/db/finanzas.sqlite3"  # DB_PATH
    tz: str = "Europe/Madrid"  # TZ


def get_settings() -> Settings:
    return Settings()
