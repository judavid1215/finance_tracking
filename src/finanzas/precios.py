"""Precios de mercado puestos a mano. Siempre Decimal."""

import sqlite3
from datetime import date, timedelta
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


def anadir_muchos(conn: sqlite3.Connection, instrumento_id: int, filas: list) -> int:
    """Guarda varios (fecha, precio) de golpe; los días que ya existían se sustituyen.

    Devuelve cuántas filas guardó. Mismos errores que `anadir`; si una fila falla no se
    guarda ninguna.
    """
    datos = []
    for fecha, precio in filas:
        if not isinstance(fecha, date):
            raise TypeError("fecha: usa datetime.date")
        datos.append((instrumento_id, fecha.isoformat(), str(_decimal(precio, "precio"))))
    with conn:
        conn.executemany(
            "INSERT INTO precios (instrumento_id, fecha, precio) VALUES (?,?,?) "
            "ON CONFLICT (instrumento_id, fecha) DO UPDATE SET precio = excluded.precio",
            datos,
        )
    return len(datos)


# Si lo guardado empieza más tarde que la primera compra + estos días, se vuelve a bajar todo
# (p. ej. se añadió después una compra más antigua). Un margen, porque una compra en fin de
# semana o festivo tiene su primer precio unos días después.
MARGEN_INICIO = 7


def desde_descarga(primera_compra: date, guardado: tuple[date, date] | None) -> date:
    """Desde qué fecha hay que descargar el histórico de un instrumento o divisa.

    `guardado` es (primera fecha, última fecha) de lo que ya hay en la base, o None si no hay
    nada. Sin datos, o con datos que empiezan tarde, se baja desde la primera compra; si no,
    desde la última fecha guardada (se vuelve a bajar ese día por si estaba a medias).
    """
    if guardado is None or guardado[0] > primera_compra + timedelta(days=MARGEN_INICIO):
        return primera_compra
    return guardado[1]


def rango(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, date] | None:
    """(primera fecha, última fecha) con precio guardado del instrumento, o None si no hay."""
    fila = conn.execute(
        "SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM precios WHERE instrumento_id = ?",
        (instrumento_id,),
    ).fetchone()
    return (date.fromisoformat(fila["a"]), date.fromisoformat(fila["b"])) if fila["a"] else None
