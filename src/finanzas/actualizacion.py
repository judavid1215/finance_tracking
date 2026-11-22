"""Actualiza de una vez el precio de todo lo que hay en cartera (Yahoo y Quefondos)."""

import sqlite3
from datetime import date

from finanzas import cartera, divisas, instrumentos, quefondos, yahoo

# Un precio más viejo que esto se guarda igualmente, pero se marca como antiguo.
# (Fin de semana largo = 4 días; los planes de pensiones llegan con un par de días de retraso.)
DIAS_ANTIGUO = 5


def _fuente(id_tipo):
    if id_tipo == "DGS":
        return quefondos
    if id_tipo in yahoo.TIPOS_ID:
        return yahoo
    return None


def actualizar_todos(conn: sqlite3.Connection, hoy: date | None = None) -> dict:
    """Actualiza el precio de cada instrumento con participaciones en cartera.

    Los instrumentos que ya no tienes (vendidos del todo o sin compras) no se tocan.
    Después actualiza el tipo de cambio a euros de cada divisa distinta del euro que haya en
    la cartera. Devuelve {"filas": [...], "sin_posicion": n, "divisas": [...]}.
    Cada fila lleva "nombre" y "estado":
    "ok" (con "fecha", "precio" y "antiguo"), "error" (con "mensaje") u "omitido"
    (sin identificador para descargar el precio). Cada divisa lleva "divisa" y "estado"
    ("ok" con "fecha" y "tasa", o "error" con "mensaje").
    """
    hoy = hoy or date.today()
    resumen = cartera.resumen(conn)
    en_cartera = {f["instrumento_id"] for f in resumen}
    todos = instrumentos.listar(conn)
    filas = []
    for inst in todos:
        if inst["id"] not in en_cartera:
            continue
        fila = {"nombre": inst["nombre"]}
        filas.append(fila)
        fuente = _fuente(inst["id_tipo"])
        if fuente is None:
            fila.update(estado="omitido", mensaje="sin identificador")
            continue
        try:
            fecha, precio = fuente.actualizar(conn, inst["id"])
        except (ValueError, OSError) as e:
            fila.update(estado="error", mensaje=str(e))
            continue
        fila.update(
            estado="ok",
            fecha=fecha,
            precio=precio,
            antiguo=(hoy - fecha).days > DIAS_ANTIGUO,
        )
    return {
        "filas": filas,
        "sin_posicion": len(todos) - len(en_cartera),
        "divisas": _actualizar_divisas(conn, {f["divisa"] for f in resumen}),
    }


def _actualizar_divisas(conn, usadas):
    filas = []
    for divisa in sorted(usadas - {divisas.BASE}):
        try:
            fecha, tasa = divisas.actualizar(conn, divisa)
        except (ValueError, OSError) as e:
            filas.append({"divisa": divisa, "estado": "error", "mensaje": str(e)})
        else:
            filas.append({"divisa": divisa, "estado": "ok", "fecha": fecha, "tasa": tasa})
    return filas
