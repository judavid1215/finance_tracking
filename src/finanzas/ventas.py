"""Añadir, borrar y consultar ventas. Participaciones y precio son siempre Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal

from finanzas import grupos, posicion
from finanzas.compras import _decimal

_SELECT = """
SELECT v.*, i.nombre AS instrumento, g.nombre AS grupo
FROM ventas v
JOIN instrumentos i ON i.id = v.instrumento_id
JOIN grupos g ON g.id = v.grupo_id
"""


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "instrumento_id": fila["instrumento_id"],
        "instrumento": fila["instrumento"],
        "grupo_id": fila["grupo_id"],
        "grupo": fila["grupo"],
        "fecha": date.fromisoformat(fila["fecha"]),
        "participaciones": Decimal(fila["participaciones"]),
        "precio": Decimal(fila["precio"]),
        "comision": Decimal(fila["comision"]),
    }


def anadir(
    conn: sqlite3.Connection,
    instrumento_id: int,
    fecha: date,
    participaciones,
    precio,
    comision=0,
    grupo_id: int | None = None,
):
    """Inserta una venta y devuelve su id.

    `grupo_id` es el grupo de la venta (sin él, "Personal"); solo puede vender lo que ese
    grupo tiene comprado.

    La comisión (0 por defecto) va en la divisa del instrumento, igual que el precio.
    Lanza sqlite3.IntegrityError si el instrumento no existe; ValueError/TypeError si los
    números o la fecha no son válidos; ValueError si no hay participaciones suficientes
    hasta esa fecha. Si se rechaza, no se guarda nada.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    if grupo_id is None:
        grupo_id = grupos.por_defecto(conn)
    cur = conn.execute(
        "INSERT INTO ventas (instrumento_id, grupo_id, fecha, participaciones, precio, comision)"
        " VALUES (?,?,?,?,?,?)",
        (
            instrumento_id,
            grupo_id,
            fecha.isoformat(),
            str(_decimal(participaciones, "participaciones")),
            str(_decimal(precio, "precio")),
            str(_decimal(comision, "comision", permitir_cero=True)),
        ),
    )
    try:
        posicion.calcular(conn, instrumento_id, grupo_id)  # nunca se vende de más en el grupo
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


def listar(
    conn: sqlite3.Connection, instrumento_id: int | None = None, grupo_id: int | None = None
) -> list[dict]:
    """Devuelve las ventas con el nombre del instrumento y del grupo, ordenadas por fecha.
    Opcionalmente solo las de un instrumento y/o un grupo."""
    filas = conn.execute(
        _SELECT + " WHERE (:i IS NULL OR v.instrumento_id = :i) AND (:g IS NULL OR v.grupo_id = :g)"
        " ORDER BY v.fecha, v.id",
        {"i": instrumento_id, "g": grupo_id},
    ).fetchall()
    return [_a_dict(f) for f in filas]
