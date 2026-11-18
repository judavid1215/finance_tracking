from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from finanzas import __version__
from finanzas.persistencia.db import comprobar_db

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JSONResponse:
    try:
        database = comprobar_db(request.app.state.engine)
    except Exception as exc:  # cualquier fallo de BD = servicio degradado
        database = {"ok": False, "error": str(exc)}
    ok = database["ok"]
    content = {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "database": database,
    }
    return JSONResponse(status_code=200 if ok else 503, content=content)
