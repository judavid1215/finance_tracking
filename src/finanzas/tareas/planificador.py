"""Planificador y job de ejemplo."""

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("finanzas.tareas")


def latido() -> None:
    """Job de ejemplo: una línea de log por minuto para comprobar que el planificador funciona."""
    logger.info("latido del planificador")


def crear_planificador(tz: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(tz))
    scheduler.add_job(latido, "interval", minutes=1, id="latido", max_instances=1, coalesce=True)
    return scheduler
