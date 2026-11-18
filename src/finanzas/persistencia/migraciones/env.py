from alembic import context

from finanzas.config import get_settings
from finanzas.persistencia.db import build_engine

config = context.config

if context.is_offline_mode():
    raise RuntimeError("Las migraciones offline no están soportadas.")

# Desde la app se inyecta el motor; desde la CLI de alembic se construye con la configuración.
engine = config.attributes.get("engine") or build_engine(get_settings().db_path)

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
