"""Motor SQLite en modo WAL y comprobación de salud."""

from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, event, text


def build_engine(db_path: str) -> Engine:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def _configurar_conexion(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")  # seguro con WAL y más rápido
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def comprobar_db(engine: Engine) -> dict:
    """Lee de la BD y devuelve modo de journal y versión de esquema."""
    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar_one()
        consulta = text("SELECT version_num FROM alembic_version")
        version = conn.execute(consulta).scalar_one_or_none()
    return {"ok": True, "journal_mode": journal_mode, "schema_version": version}
