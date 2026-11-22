"""Añadir, borrar y consultar ventas. Participaciones y precio son siempre Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal

from finanzas import posicion
from finanzas.compras import _decimal

_SELECT = """
SELECT v.*, i.nombre AS instrumento
FROM ventas v JOIN instrumentos i ON i.id = v.instrumento_id
"""


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "instrumento_id": fila["instrumento_id"],
        "instrumento": fila["instrumento"],
        "fecha": date.fromisoformat(fila["fecha"]),
        "participaciones": Decimal(fila["participaciones"]),
        "precio": Decimal(fila["precio"]),
        "comision": Decimal(fila["comision"]),
    }


def anadir(
    conn: sqlite3.Connection, instrumento_id: int, fecha: date, participaciones, precio, comision=0
):
    """Inserta una venta y devuelve su id.

    La comisión (0 por defecto) va en la divisa del instrumento, igual que el precio.
    Lanza sqlite3.IntegrityError si el instrumento no existe; ValueError/TypeError si los
    números o la fecha no son válidos; ValueError si no hay participaciones suficientes
    hasta esa fecha. Si se rechaza, no se guarda nada.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    cur = conn.execute(
        "INSERT INTO ventas (instrumento_id, fecha, participaciones, precio, comision)"
        " VALUES (?,?,?,?,?)",
        (
            instrumento_id,
            fecha.isoformat(),
            str(_decimal(participaciones, "participaciones")),
            str(_decimal(precio, "precio")),
            str(_decimal(comision, "comision", permitir_cero=True)),
        ),
    )
    try:
        posicion.calcular(conn, instrumento_id)  # comprueba que nunca se vende de más
    except ValueError:
        conn.rollback()
        raise
    conn.commit()
    return cur.lastrowid


def borrar(conn: sqlite3.Connection, id: int) -> bool:
    """Borra por id. Devuelve True si existía."""
    cur = conn.execute("DELETE FROM ventas WHERE id = ?", (id,))
    conn.commit()
    return cur.rowcount == 1


def listar(conn: sqlite3.Connection, instrumento_id: int | None = None) -> list[dict]:
    """Devuelve las ventas con el nombre del instrumento, ordenadas por fecha."""
    if instrumento_id is None:
        filas = conn.execute(_SELECT + " ORDER BY v.fecha, v.id").fetchall()
    else:
        filas = conn.execute(
            _SELECT + " WHERE v.instrumento_id = ? ORDER BY v.fecha, v.id", (instrumento_id,)
        ).fetchall()
    return [_a_dict(f) for f in filas]
