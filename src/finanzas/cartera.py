"""Resumen de cartera por instrumento a partir de las compras. Todo en Decimal."""

import sqlite3
from decimal import Decimal

from finanzas import compras


def resumen(conn: sqlite3.Connection) -> list[dict]:
    """Una fila por instrumento con compras: participaciones, invertido y precio medio.

    Se suma en Python con Decimal (SQLite sumaría los textos como float y perdería precisión).
    Ordenado por nombre del instrumento.
    """
    por_instrumento: dict[int, dict] = {}
    for c in compras.listar(conn):
        fila = por_instrumento.setdefault(
            c["instrumento_id"],
            {
                "instrumento_id": c["instrumento_id"],
                "instrumento": c["instrumento"],
                "participaciones": Decimal(0),
                "invertido": Decimal(0),
            },
        )
        fila["participaciones"] += c["participaciones"]
        fila["invertido"] += c["participaciones"] * c["precio"]
    for fila in por_instrumento.values():
        fila["precio_medio"] = fila["invertido"] / fila["participaciones"]
    return sorted(por_instrumento.values(), key=lambda f: f["instrumento"].lower())
