"""Resumen de cartera por instrumento a partir de compras y ventas. Todo en Decimal."""

import sqlite3
from decimal import Decimal

from finanzas import compras, divisas, instrumentos, posicion, precios


def resumen(conn: sqlite3.Connection) -> list[dict]:
    """Una fila por instrumento con participaciones en cartera: participaciones, invertido
    y precio medio (coste medio ponderado, ver posicion.py). Un instrumento vendido por
    completo no aparece.

    Cada fila lleva su divisa (los importes van en la divisa del instrumento; total() da euros).

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
            "divisa": instrumentos.obtener(conn, instrumento_id)["divisa"],
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


def total(conn: sqlite3.Connection) -> dict:
    """Total de la cartera en euros: invertido, valor, ganancia y rentabilidad.

    Cada instrumento se convierte con el último tipo de cambio guardado (ver divisas.py), tanto
    el valor como lo invertido; es decir, no refleja lo que valía el dólar al comprar, sino
    cuánto vale hoy lo que pusiste. Solo cuentan los instrumentos con precio y, si no están en
    euros, con tipo de cambio: el resto va en "excluidos" como (nombre, motivo), para que el
    total no mezcle instrumentos valorados y sin valorar. Sin nada valorado, los totales son None.
    """
    invertido = valor = Decimal(0)
    contados = 0
    excluidos = []
    for f in resumen(conn):
        if f["valor_actual"] is None:
            excluidos.append((f["instrumento"], "sin precio"))
            continue
        tasa = divisas.ultima(conn, f["divisa"])
        if tasa is None:
            excluidos.append((f["instrumento"], f"sin tipo de cambio {f['divisa']}/EUR"))
            continue
        invertido += f["invertido"] * tasa
        valor += f["valor_actual"] * tasa
        contados += 1
    resultado = {"invertido": None, "valor": None, "ganancia": None, "rentabilidad": None}
    resultado["excluidos"] = excluidos
    if contados:
        resultado.update(invertido=invertido, valor=valor, ganancia=valor - invertido)
        resultado["rentabilidad"] = (valor - invertido) / invertido if invertido else None
    return resultado
