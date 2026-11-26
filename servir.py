"""Arranca la web para verla desde el móvil. Uso: python servir.py [puerto]

Escucha en toda la red local (0.0.0.0): abre http://<ip-de-la-raspberry>:8000 desde el móvil.
La web solo lee la base de datos; los precios se actualizan desde aquí: al arrancar y después
cada INTERVALO segundos mientras el servidor esté activo (histórico que falte + precio de ahora). También se actualiza justo después de importar un CSV.
"""

import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # para poder importar "finanzas"

from finanzas import actualizacion, db  # noqa: E402
from finanzas.web.app import crear_app  # noqa: E402

# FINANZAS_DB permite arrancar con otra base (ej. una de prueba) sin tocar la tuya.
RUTA_DB = Path(os.environ.get("FINANZAS_DB") or Path(__file__).parent / "data" / "finanzas.sqlite3")
INTERVALO = 30  # segundos entre actualizaciones
bloqueo = threading.Lock()  # una sola actualización a la vez (bucle e importación de CSV)
ultima = {"hora": None}  # cuándo terminó la última actualización (ISO UTC); la lee la web


def _errores(res: dict) -> list[str]:
    """Los fallos de una actualización, en texto (Yahoo puede fallar sin que sea grave)."""
    malos = [f"{f['nombre']}: {f['mensaje']}" for f in res["historicos"] + res["ahora"]["filas"] + res["horas"] + res["ticks"] if f["estado"] == "error"]
    malos += [f"{f['divisa']}/EUR: {f['mensaje']}" for f in res["divisas"] + res["ahora"]["divisas"] if f["estado"] == "error"]
    return malos


def actualizar() -> None:
    """Una actualización completa con su propia conexión (SQLite no comparte conexiones entre
    hilos). Nunca lanza: si falla, lo cuenta y la web sigue con lo que ya hay."""
    try:
        with bloqueo:
            conn = db.conectar(RUTA_DB)
            try:
                res = actualizacion.refrescar(conn)
            finally:
                conn.close()
    except Exception as e:  # noqa: BLE001 - el hilo no debe morir por un fallo de red o de base
        print(f"[actualización] fallo: {e}")
        return
    ultima["hora"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errores = _errores(res)
    print("[actualización] hecha" + (f" con {len(errores)} errores:" if errores else ""))
    for e in dict.fromkeys(errores):
        print(f"  {e}")


def _bucle(parar: threading.Event) -> None:
    """Una actualización cada INTERVALO segundos contados desde que empieza la anterior (si una
    dura más que el intervalo, la siguiente empieza nada más acabar)."""
    proximo = time.monotonic() + INTERVALO
    while not parar.wait(max(0, proximo - time.monotonic())):
        proximo = time.monotonic() + INTERVALO
        actualizar()


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Actualizando precios antes de arrancar (puede tardar)...")
    actualizar()
    threading.Thread(target=_bucle, args=(threading.Event(),), daemon=True).start()
    crear_app(RUTA_DB, actualizado=lambda: ultima["hora"], tras_importar=actualizar).run(host="0.0.0.0", port=puerto)
