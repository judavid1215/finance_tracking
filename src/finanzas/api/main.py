"""Punto de entrada: `uvicorn finanzas.api.main:app`."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from finanzas import __version__
from finanzas.api.salud import router as salud_router
from finanzas.config import Settings, get_settings
from finanzas.persistencia.db import build_engine
from finanzas.persistencia.esquema import upgrade_to_head
from finanzas.tareas.planificador import crear_planificador

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        engine = build_engine(settings.db_path)
        upgrade_to_head(engine)
        scheduler = crear_planificador(settings.tz)
        scheduler.start()
        app.state.engine = engine
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            engine.dispose()

    app = FastAPI(title="Finanzas", version=__version__, lifespan=lifespan)
    app.include_router(salud_router)
    # Debe ir al final: el montaje en "/" captura todo lo que no coincida con otra ruta.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
