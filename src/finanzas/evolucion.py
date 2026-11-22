"""Evolución diaria de la cartera en euros: cuánto tenías invertido y cuánto valía cada día.

Cada día lleva, por instrumento y grupo, la posición de ese día (coste medio, ver posicion.py)
y el último precio guardado hasta ese día (si un día no cotiza, vale el precio anterior). Los
días de la serie son los días con precio de algún instrumento, desde la primera operación.

- Si un instrumento todavía no tiene precio en esa fecha (p. ej. se compró en festivo y su
  primer precio llega unos días después), vale lo que costó: ni gana ni pierde.
- Como en cartera.total(), cada día se convierte a euros con el tipo de cambio de ese día
  (el último guardado hasta entonces; antes del primero se usa el primero). Con una divisa sin
  ningún tipo de cambio guardado se lanza ValueError.
- Todo en Decimal.
"""

import sqlite3
from bisect import bisect_right
from datetime import date
from decimal import Decimal

from finanzas import divisas, posicion


def _carga(conn, sql, params):
    fechas, valores = [], []
    for f in conn.execute(sql, params):
        fechas.append(date.fromisoformat(f[0]))
        valores.append(Decimal(f[1]))
    return fechas, valores


def _hasta(fechas, valores, dia):
    """Último valor con fecha <= dia, o None si todavía no hay ninguno."""
    i = bisect_right(fechas, dia)
    return valores[i - 1] if i else None


def _tasas(conn, divisa):
    if divisa == divisas.BASE:
        return None
    fechas, valores = _carga(
        conn, "SELECT fecha, tasa FROM tipos_cambio WHERE divisa = ? ORDER BY fecha", (divisa,)
    )
    if not fechas:
        raise ValueError(f"Falta el tipo de cambio {divisa}/{divisas.BASE}: descarga el histórico")
    return fechas, valores


def serie(conn: sqlite3.Connection, grupo_id: int | None = None) -> list[dict]:
    """Una fila por día: {"fecha", "invertido", "valor", "ganancia", "rentabilidad"} en euros
    (rentabilidad en tanto por uno, None si no había nada invertido). Con grupo_id solo cuenta
    ese grupo. Sin operaciones o sin precios, devuelve una lista vacía."""
    pares = conn.execute(
        "SELECT instrumento_id, grupo_id FROM compras UNION SELECT instrumento_id, grupo_id "
        "FROM ventas ORDER BY 1, 2"
    ).fetchall()
    posiciones = []  # (divisa, pasos, precios, tasas)
    inicio = None
    dias = set()
    for instrumento_id, g in pares:
        if grupo_id is not None and g != grupo_id:
            continue
        pasos = posicion.historial(conn, instrumento_id, g)
        pasos = [(date.fromisoformat(f), n, inv) for f, n, inv in pasos]
        divisa = conn.execute(
            "SELECT divisa FROM instrumentos WHERE id = ?", (instrumento_id,)
        ).fetchone()[0]
        pf, pv = _carga(
            conn,
            "SELECT fecha, precio FROM precios WHERE instrumento_id = ? ORDER BY fecha",
            (instrumento_id,),
        )
        posiciones.append((divisa, [p[0] for p in pasos], pasos, pf, pv, _tasas(conn, divisa)))
        dias.update(pf)
        if inicio is None or pasos[0][0] < inicio:
            inicio = pasos[0][0]
    if inicio is None:
        return []
    dias = sorted(d for d in dias if d >= inicio)
    resultado = []
    for dia in dias:
        invertido = valor = Decimal(0)
        for divisa, fechas_op, pasos, pf, pv, tasas in posiciones:
            i = bisect_right(fechas_op, dia)
            if not i:
                continue
            _, participaciones, coste = pasos[i - 1]
            if participaciones == 0:
                continue
            precio = _hasta(pf, pv, dia)
            valor_pos = coste if precio is None else participaciones * precio
            if tasas is None:
                tasa = Decimal(1)
            else:
                tasa = _hasta(tasas[0], tasas[1], dia) or tasas[1][0]
            invertido += coste * tasa
            valor += valor_pos * tasa
        resultado.append(
            {
                "fecha": dia,
                "invertido": invertido,
                "valor": valor,
                "ganancia": valor - invertido,
                "rentabilidad": (valor - invertido) / invertido if invertido else None,
            }
        )
    return resultado


def mensual(filas: list[dict]) -> list[dict]:
    """Resumen de una serie diaria: el último día de cada mes con datos (el último mes puede
    estar a medias, y entonces es el último día disponible)."""
    ultimos: dict[tuple[int, int], dict] = {}
    for f in filas:
        ultimos[(f["fecha"].year, f["fecha"].month)] = f
    return list(ultimos.values())
