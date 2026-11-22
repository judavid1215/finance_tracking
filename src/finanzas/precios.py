"""Precios de mercado puestos a mano. Siempre Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal

from finanzas.compras import _decimal


def anadir(conn: sqlite3.Connection, instrumento_id: int, fecha: date, precio) -> None:
    """Guarda el precio de un instrumento en una fecha; si ya había uno ese día, lo sustituye.

    Lanza sqlite3.IntegrityError si el instrumento no existe; ValueError/TypeError si el
    precio o la fecha no son válidos.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    conn.execute(
        "INSERT INTO precios (instrumento_id, fecha, precio) VALUES (?,?,?) "
        "ON CONFLICT (instrumento_id, fecha) DO UPDATE SET precio = excluded.precio",
        (instrumento_id, fecha.isoformat(), str(_decimal(precio, "precio"))),
    )
    conn.commit()


def ultimo(conn: sqlite3.Connection, instrumento_id: int) -> Decimal | None:
    """Precio más reciente del instrumento, o None si no hay ninguno."""
    fila = conn.execute(
        "SELECT precio FROM precios WHERE instrumento_id = ? ORDER BY fecha DESC LIMIT 1",
        (instrumento_id,),
    ).fetchone()
    return Decimal(fila["precio"]) if fila else None
