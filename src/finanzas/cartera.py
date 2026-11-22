"""Resumen de cartera por instrumento a partir de compras y ventas. Todo en Decimal."""

import sqlite3
from decimal import Decimal

from finanzas import compras, divisas, instrumentos, posicion, precios


def _precio(conn, instrumento_id, vivos):
    if vivos and instrumento_id in vivos.get("precios", {}):
        return vivos["precios"][instrumento_id]
    return precios.ultimo(conn, instrumento_id)


def _tasa(conn, divisa, vivos):
    if vivos and divisa.upper() in vivos.get("tasas", {}):
        return vivos["tasas"][divisa.upper()]
    return divisas.ultima(conn, divisa)


def resumen(
    conn: sqlite3.Connection, vivos: dict | None = None, grupo_id: int | None = None
) -> list[dict]:
    """Una fila por instrumento y grupo con participaciones en cartera: participaciones,
    invertido y precio medio (coste medio ponderado, ver posicion.py). Lo vendido por
    completo no aparece. Con grupo_id solo salen las filas de ese grupo.

    Cada fila lleva su divisa (los importes van en la divisa del instrumento; total() da euros).

    `vivos` (ver actualizacion.consultar_todos) son los precios de este momento: tienen
    preferencia sobre el último precio guardado. Sin él, o para lo que no traiga, se usa el
    último precio guardado.

    Si hay un precio (vivo o guardado), añade precio_actual, valor_actual, ganancia (valor menos
    invertido) y rentabilidad (ganancia / invertido, en tanto por uno); si no, son None.

    Se calcula en Python con Decimal (SQLite sumaría los textos como float y perdería precisión).
    Ordenado por nombre del instrumento.
    """
    pares = {
        (c["instrumento_id"], c["grupo_id"]): (c["instrumento"], c["grupo"])
        for c in compras.listar(conn, grupo_id=grupo_id)
    }
    filas = []
    for (instrumento_id, id_grupo), (nombre, grupo) in pares.items():
        pos = posicion.calcular(conn, instrumento_id, id_grupo)
        if pos["participaciones"] == 0:
            continue
        inst = instrumentos.obtener(conn, instrumento_id)
        fila = {
            "instrumento_id": instrumento_id,
            "instrumento": nombre,
            "grupo_id": id_grupo,
            "grupo": grupo,
            "tipo": inst["tipo"],
            "divisa": inst["divisa"],
            "participaciones": pos["participaciones"],
            "invertido": pos["invertido"],
            "precio_medio": pos["invertido"] / pos["participaciones"],
        }
        actual = _precio(conn, instrumento_id, vivos)
        fila["precio_actual"] = actual
        fila["valor_actual"] = fila["ganancia"] = fila["rentabilidad"] = None
        if actual is not None:
            fila["valor_actual"] = fila["participaciones"] * actual
            fila["ganancia"] = fila["valor_actual"] - fila["invertido"]
            fila["rentabilidad"] = fila["ganancia"] / fila["invertido"]
        filas.append(fila)
    return sorted(filas, key=lambda f: (f["instrumento"].lower(), f["grupo"].lower()))


def _valoradas(
    conn: sqlite3.Connection, vivos: dict | None = None, grupo_id: int | None = None
) -> tuple[list[tuple[dict, Decimal]], list[tuple[str, str]]]:
    """Filas de resumen() con precio y, si no están en euros, con tipo de cambio, junto con su
    tasa a euros; el resto va en la segunda lista como (nombre, motivo)."""
    valoradas = []
    excluidos = []
    for f in resumen(conn, vivos, grupo_id):
        if f["valor_actual"] is None:
            excluidos.append((f["instrumento"], "sin precio"))
            continue
        tasa = _tasa(conn, f["divisa"], vivos)
        if tasa is None:
            excluidos.append((f["instrumento"], f"sin tipo de cambio {f['divisa']}/EUR"))
            continue
        valoradas.append((f, tasa))
    return valoradas, excluidos


def total(conn: sqlite3.Connection, vivos: dict | None = None, grupo_id: int | None = None) -> dict:
    """Total de la cartera en euros: invertido, valor, ganancia y rentabilidad.

    Cada instrumento se convierte con el tipo de cambio vivo o, si no hay, el último guardado
    (ver divisas.py), tanto el valor como lo invertido; es decir, no refleja lo que valía el
    dólar al comprar, sino cuánto vale hoy lo que pusiste. Solo cuentan los instrumentos con
    precio y, si no están en euros, con tipo de cambio: el resto va en "excluidos" como
    (nombre, motivo), para que el total no mezcle instrumentos valorados y sin valorar. Sin nada
    valorado, los totales son None.
    """
    valoradas, excluidos = _valoradas(conn, vivos, grupo_id)
    invertido = sum((f["invertido"] * tasa for f, tasa in valoradas), Decimal(0))
    valor = sum((f["valor_actual"] * tasa for f, tasa in valoradas), Decimal(0))
    resultado = {"invertido": None, "valor": None, "ganancia": None, "rentabilidad": None}
    resultado["excluidos"] = excluidos
    if valoradas:
        resultado.update(invertido=invertido, valor=valor, ganancia=valor - invertido)
        resultado["rentabilidad"] = (valor - invertido) / invertido if invertido else None
    return resultado


AGRUPACIONES = ("instrumento", "tipo", "divisa", "grupo")


def reparto(conn: sqlite3.Connection, por: str = "instrumento", vivos: dict | None = None) -> dict:
    """Reparto de la cartera en porcentaje del valor en euros, agrupado por "instrumento",
    "tipo" (fondo, ETF, acción...), "divisa" (la del instrumento, no la de su activo subyacente)
    o "grupo" (Personal, Pension...).

    Devuelve {"valor": total en EUR (None si nada valorado), "filas": [...], "excluidos": [...]}.
    Cada fila lleva grupo, valor (EUR) y porcentaje (tanto por cien), de mayor a menor peso.
    Usa los mismos criterios que total(): lo que no tiene precio o tipo de cambio no cuenta y va
    en "excluidos", así que los porcentajes suman 100 sobre lo valorado.
    """
    if por not in AGRUPACIONES:
        raise ValueError(f"Agrupación no válida: {por!r} (usa {', '.join(AGRUPACIONES)})")
    valoradas, excluidos = _valoradas(conn, vivos)
    grupos: dict[str, Decimal] = {}
    for f, tasa in valoradas:
        grupos[f[por]] = grupos.get(f[por], Decimal(0)) + f["valor_actual"] * tasa
    valor = sum(grupos.values(), Decimal(0))
    filas = [
        {"grupo": g, "valor": v, "porcentaje": v / valor * 100 if valor else Decimal(0)}
        for g, v in grupos.items()
    ]
    filas.sort(key=lambda f: (-f["valor"], f["grupo"].lower()))
    return {"valor": valor if valoradas else None, "filas": filas, "excluidos": excluidos}
