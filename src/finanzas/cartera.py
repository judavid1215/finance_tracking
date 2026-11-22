"""Resumen de cartera por instrumento a partir de compras y ventas. Todo en Decimal."""

import sqlite3

from finanzas import compras, posicion, precios


def resumen(conn: sqlite3.Connection) -> list[dict]:
    """Una fila por instrumento con participaciones en cartera: participaciones, invertido
    y precio medio (coste medio ponderado, ver posicion.py). Un instrumento vendido por
    completo no aparece.

    Si hay un precio puesto a mano, añade precio_actual, valor_actual, ganancia (valor menos
    invertido) y rentabilidad (ganancia / invertido, en tanto por uno); si no, son None.

    Se calcula en Python con Decimal (SQLite sumaría los textos como float y perdería precisión).
    Ordenado por nombre del instrumento.
    """
    nombres = {c["instrumento_id"]: c["instrumento"] for c in compras.listar(conn)}
    filas = []
    for instrumento_id, nombre in nombres.items():
        pos = posicion.calcular(conn, instrumento_id)
        if pos["participaciones"] == 0:
            continue
        fila = {
            "instrumento_id": instrumento_id,
            "instrumento": nombre,
            "participaciones": pos["participaciones"],
            "invertido": pos["invertido"],
            "precio_medio": pos["invertido"] / pos["participaciones"],
        }
        actual = precios.ultimo(conn, instrumento_id)
        fila["precio_actual"] = actual
        fila["valor_actual"] = fila["ganancia"] = fila["rentabilidad"] = None
        if actual is not None:
            fila["valor_actual"] = fila["participaciones"] * actual
            fila["ganancia"] = fila["valor_actual"] - fila["invertido"]
            fila["rentabilidad"] = fila["ganancia"] / fila["invertido"]
        filas.append(fila)
    return sorted(filas, key=lambda f: f["instrumento"].lower())
