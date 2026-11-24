"""Recorta una serie diaria (evolucion.serie) a un periodo: 1S, 1M, 1A, YTD o Max.

Para cada día del periodo se calcula la ganancia *dentro del periodo*: la ganancia de ese día
menos la que había justo antes de empezar (la del último día con datos hasta la fecha de
inicio; 0 si la cartera todavía no existía). Así, aportar dinero no cuenta como ganancia.

La rentabilidad del periodo es esa ganancia entre el capital con el que se partió: el valor al
empezar más lo que se haya aportado después (el aumento de lo invertido, si lo hubo). Es una
aproximación sencilla; la rentabilidad ponderada por tiempo (TWR) queda para más adelante.
"""

import calendar
from bisect import bisect_left
from datetime import date, timedelta
from decimal import Decimal

PERIODOS = ("1S", "1M", "1A", "YTD", "MAX")


def _restar(dia: date, anios: int = 0, meses: int = 0) -> date:
    """dia menos anios/meses, ajustando el día si el mes de destino es más corto (31 mar - 1 mes
    = 28/29 feb)."""
    total = dia.year * 12 + dia.month - 1 - anios * 12 - meses
    anio, mes = divmod(total, 12)
    mes += 1
    return date(anio, mes, min(dia.day, calendar.monthrange(anio, mes)[1]))


def inicio(periodo: str, hoy: date) -> date | None:
    """Fecha justo antes de empezar el periodo (el periodo cubre los días posteriores), o None
    para el máximo. Lanza ValueError con un periodo desconocido."""
    periodo = periodo.upper()
    if periodo == "1S":
        return hoy - timedelta(days=7)
    if periodo == "1M":
        return _restar(hoy, meses=1)
    if periodo == "1A":
        return _restar(hoy, anios=1)
    if periodo == "YTD":
        return date(hoy.year - 1, 12, 31)
    if periodo == "MAX":
        return None
    raise ValueError(f"Periodo desconocido: {periodo!r} (usa {', '.join(PERIODOS)})")


def recortar(
    filas: list[dict], periodo: str, hoy: date | None = None, aportaciones: list[dict] | None = None
) -> dict:
    """Devuelve {"desde", "hasta", "puntos", "resumen", "aportaciones"}.

    puntos: una fila por día del periodo con fecha, invertido, valor, ganancia (del periodo) y
    rentabilidad (del periodo, tanto por uno; None si no había capital).
    resumen: valor, invertido, ganancia y rentabilidad al final del periodo (None si no hay
    días en el periodo).
    aportaciones: las compras de evolucion.aportaciones() hechas dentro del periodo, cada una en
    el primer día del gráfico desde su fecha (una compra en festivo cae en el día siguiente con
    precio) y juntando las del mismo día: {"fecha", "importe", "instrumentos"}.
    """
    hoy = hoy or date.today()
    corte = inicio(periodo, hoy)
    base = None  # última fila hasta el corte
    dentro = []
    for f in filas:
        if f["fecha"] > hoy:
            break
        if corte is not None and f["fecha"] <= corte:
            base = f
        else:
            dentro.append(f)
    cero = Decimal(0)
    ganancia_base = base["ganancia"] if base else cero
    valor_base = base["valor"] if base else cero
    invertido_base = base["invertido"] if base else cero
    puntos = []
    for f in dentro:
        ganancia = f["ganancia"] - ganancia_base
        capital = valor_base + max(f["invertido"] - invertido_base, cero)
        puntos.append(
            {
                "fecha": f["fecha"],
                "invertido": f["invertido"],
                "valor": f["valor"],
                "ganancia": ganancia,
                "rentabilidad": ganancia / capital if capital else None,
            }
        )
    ultimo = puntos[-1] if puntos else None
    fechas = [p["fecha"] for p in puntos]
    por_dia: dict[date, dict] = {}
    for a in aportaciones or []:
        if a["fecha"] > hoy or (corte is not None and a["fecha"] <= corte):
            continue
        i = bisect_left(fechas, a["fecha"])
        if i == len(fechas):
            continue  # compra posterior al último día con precio: todavía no hay dónde ponerla
        nuevo = {"fecha": fechas[i], "importe": cero, "instrumentos": []}
        dia = por_dia.setdefault(fechas[i], nuevo)
        dia["importe"] += a["importe"]
        if a["instrumento"] not in dia["instrumentos"]:
            dia["instrumentos"].append(a["instrumento"])
    return {
        "desde": dentro[0]["fecha"] if dentro else None,
        "hasta": ultimo["fecha"] if ultimo else None,
        "puntos": puntos,
        "resumen": ultimo
        and {k: ultimo[k] for k in ("valor", "invertido", "ganancia", "rentabilidad")},
        "aportaciones": list(por_dia.values()),
    }
