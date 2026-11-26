"""Añadir, editar, borrar y consultar compras. Participaciones y precio son siempre Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation

from finanzas import grupos, posicion


def _decimal(valor, campo: str, permitir_cero: bool = False) -> Decimal:
    """Convierte a Decimal positivo con como máximo 8 decimales (nunca float).

    En texto se acepta coma o punto decimal: '1,5' y '1.5' son lo mismo.
    Con permitir_cero=True el 0 también vale (para las comisiones); los negativos, nunca.
    """
    if isinstance(valor, bool) or not isinstance(valor, Decimal | int | str):
        raise TypeError(f"{campo}: usa Decimal, int o str, no {type(valor).__name__}")
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
    try:
        d = Decimal(valor)
    except InvalidOperation:
        raise ValueError(f"{campo}: número no válido: {valor!r}") from None
    if not d.is_finite() or d < 0 or (d == 0 and not permitir_cero):
        requisito = "no negativo" if permitir_cero else "mayor que 0"
        raise ValueError(f"{campo}: debe ser un número {requisito}")
    if d.as_tuple().exponent < -8:
        raise ValueError(f"{campo}: máximo 8 decimales")  # así no se pierde precisión
    return d


_SELECT = """
SELECT c.*, i.nombre AS instrumento, g.nombre AS grupo
FROM compras c
JOIN instrumentos i ON i.id = c.instrumento_id
JOIN grupos g ON g.id = c.grupo_id
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
    """Inserta una compra y devuelve su id.

    `grupo_id` es el grupo de la compra (ver grupos.py); sin él, el grupo por defecto "Personal".

    La comisión (0 por defecto) va en la divisa del instrumento, igual que el precio.
    Lanza sqlite3.IntegrityError si el instrumento no existe; ValueError/TypeError si los
    números o la fecha no son válidos.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    if grupo_id is None:
        grupo_id = grupos.por_defecto(conn)
    cur = conn.execute(
        "INSERT INTO compras (instrumento_id, grupo_id, fecha, participaciones, precio, comision)"
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
    conn.commit()
    return cur.lastrowid


def borrar(conn: sqlite3.Connection, id: int) -> bool:
    """Borra por id. Devuelve True si existía.

    Lanza ValueError (y no borra) si alguna venta dejaría de estar cubierta por las compras.
    """
    fila = conn.execute(
        "SELECT instrumento_id, grupo_id FROM compras WHERE id = ?", (id,)
    ).fetchone()
    if fila is None:
        return False
    conn.execute("DELETE FROM compras WHERE id = ?", (id,))
    try:
        posicion.calcular(conn, fila["instrumento_id"], fila["grupo_id"])
    except ValueError as e:
        conn.rollback()
        raise ValueError(f"no se puede borrar la compra: {e}") from None
    conn.commit()
    return True


def editar(
    conn: sqlite3.Connection, id: int, fecha: date, participaciones, precio, comision=0
) -> bool:
    """Cambia fecha, participaciones, precio y comisión de una compra (el instrumento y el grupo
    no se tocan). Devuelve True si existía.

    Lanza ValueError/TypeError si los datos no son válidos, y ValueError (sin guardar nada) si
    el cambio dejaría alguna venta sin cubrir por las compras.
    """
    if not isinstance(fecha, date):
        raise TypeError("fecha: usa datetime.date")
    fila = conn.execute(
        "SELECT instrumento_id, grupo_id FROM compras WHERE id = ?", (id,)
    ).fetchone()
    if fila is None:
        return False
    conn.execute(
        "UPDATE compras SET fecha = ?, participaciones = ?, precio = ?, comision = ? WHERE id = ?",
        (
            fecha.isoformat(),
            str(_decimal(participaciones, "participaciones")),
            str(_decimal(precio, "precio")),
            str(_decimal(comision, "comision", permitir_cero=True)),
            id,
        ),
    )
    try:
        posicion.calcular(conn, fila["instrumento_id"], fila["grupo_id"])
    except ValueError:
        conn.rollback()
        raise
    conn.commit()
    return True


def listar(
    conn: sqlite3.Connection, instrumento_id: int | None = None, grupo_id: int | None = None
) -> list[dict]:
    """Devuelve las compras con el nombre del instrumento y del grupo, ordenadas por fecha.
    Opcionalmente solo las de un instrumento y/o un grupo."""
    filas = conn.execute(
        _SELECT + " WHERE (:i IS NULL OR c.instrumento_id = :i) AND (:g IS NULL OR c.grupo_id = :g)"
        " ORDER BY c.fecha, c.id",
        {"i": instrumento_id, "g": grupo_id},
    ).fetchall()
    return [_a_dict(f) for f in filas]
