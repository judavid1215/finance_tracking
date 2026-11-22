"""Añadir, borrar y consultar compras. Participaciones y precio son siempre Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation


def _decimal(valor, campo: str) -> Decimal:
    """Convierte a Decimal positivo con como máximo 8 decimales (nunca float).

    En texto se acepta coma o punto decimal: '1,5' y '1.5' son lo mismo.
    """
    if isinstance(valor, bool) or not isinstance(valor, Decimal | int | str):
        raise TypeError(f"{campo}: usa Decimal, int o str, no {type(valor).__name__}")
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        d = Decimal(valor)
    except InvalidOperation:
        raise ValueError(f"{campo}: número no válido: {valor!r}") from None
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{campo}: debe ser un número mayor que 0")
    if d.as_tuple().exponent < -8:
        raise ValueError(f"{campo}: máximo 8 decimales")  # así no se pierde precisión
    return d


_SELECT = """
SELECT c.*, i.nombre AS instrumento
FROM compras c JOIN instrumentos i ON i.id = c.instrumento_id
"""


def _a_dict(fila: sqlite3.Row) -> dict:
    return {
        "id": fila["id"],
        "instrumento_id": fila["instrumento_id"],
        "instrumento": fila["instrumento"],
        "fecha": date.fromisoformat(fila["fecha"]),
        "participaciones": Decimal(fila["participaciones"]),
        "precio": Decimal(fila["precio"]),
    }


def anadir(conn: sqlite3.Connection, instrumento_id: int, fecha: date, participaciones, precio):
    """Inserta una compra y devuelve su id.

    Lanza sqlite3.IntegrityError si el instrumento no existe; ValueError/TypeError si los
    números o la fecha no son válidos.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    cur = conn.execute(
        "INSERT INTO compras (instrumento_id, fecha, participaciones, precio) VALUES (?,?,?,?)",
        (
            instrumento_id,
            fecha.isoformat(),
            str(_decimal(participaciones, "participaciones")),
            str(_decimal(precio, "precio")),
        ),
    )
    conn.commit()
    return cur.lastrowid


def borrar(conn: sqlite3.Connection, id: int) -> bool:
    """Borra por id. Devuelve True si existía."""
    cur = conn.execute("DELETE FROM compras WHERE id = ?", (id,))
    conn.commit()
    return cur.rowcount == 1


def listar(conn: sqlite3.Connection, instrumento_id: int | None = None) -> list[dict]:
    """Devuelve las compras con el nombre del instrumento, ordenadas por fecha."""
    if instrumento_id is None:
        filas = conn.execute(_SELECT + " ORDER BY c.fecha, c.id").fetchall()
    else:
        filas = conn.execute(
            _SELECT + " WHERE c.instrumento_id = ? ORDER BY c.fecha, c.id", (instrumento_id,)
        ).fetchall()
    return [_a_dict(f) for f in filas]
