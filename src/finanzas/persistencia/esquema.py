"""Aplica las migraciones de Alembic por código (se llama al arrancar la app)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine


def upgrade_to_head(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migraciones"))
    config.attributes["engine"] = engine
    command.upgrade(config, "head")
