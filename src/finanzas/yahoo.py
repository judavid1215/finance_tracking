"""Precio actual de fondos, ETF y acciones con yfinance (Yahoo Finance, gratis y no oficial).

Para Fondo y ETF se busca por ISIN; para Accion y Cripto, por ticker (ej. BTC-EUR).
"""

import sqlite3
from datetime import date
from decimal import Decimal

import yfinance as yf

from finanzas import instrumentos, precios

TIPOS_ID = ("ISIN", "TICKER")


def leer_precio(simbolo: str) -> tuple[date, Decimal, str]:
    """Devuelve (fecha, último cierre, divisa) del ISIN o ticker dado.

    Lanza ValueError si Yahoo no lo encuentra; los fallos de red también llegan como error.
    """
    ticker = yf.Ticker(simbolo)
    historico = ticker.history(period="5d")
    if historico.empty:
        raise ValueError(f"Yahoo no tiene precio para {simbolo}")
    divisa = ticker.fast_info["currency"]
    cierre = historico["Close"].iloc[-1]
    fecha = historico.index[-1].date()
    return fecha, Decimal(str(round(float(cierre), 4))), str(divisa).upper()


def consultar(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, Decimal]:
    """Pregunta a Yahoo el precio de ahora de un fondo, ETF, acción o cripto, SIN guardarlo.
    Devuelve (fecha, precio).

    Lanza ValueError si no es de esos tipos o si Yahoo da el precio en otra divisa
    (p. ej. el ETF cotiza en USD en esa bolsa y tu instrumento está en EUR).
    """
    inst = instrumentos.obtener(conn, instrumento_id)
    if inst is None or inst["id_tipo"] not in TIPOS_ID:
        raise ValueError("Solo se actualiza un fondo, ETF, acción o cripto con identificador")
    fecha, precio, divisa = leer_precio(inst["identificador"])
    if divisa != inst["divisa"]:
        raise ValueError(
            f"Yahoo da {inst['identificador']} en {divisa}, pero el instrumento está en "
            f"{inst['divisa']}; no se guarda"
        )
    return fecha, precio


def actualizar(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, Decimal]:
    """Como `consultar`, pero además guarda el precio en el histórico (con la fecha de Yahoo)."""
    fecha, precio = consultar(conn, instrumento_id)
    precios.anadir(conn, instrumento_id, fecha, precio)
    return fecha, precio


def leer_historico(simbolo: str, desde: date) -> tuple[list[tuple[date, Decimal]], str]:
    """Devuelve ([(fecha, cierre), ...], divisa): un cierre por cada día de mercado desde `desde`.

    Es el cierre sin ajustar por dividendos (auto_adjust=False), el precio al que se
    habría comprado o vendido ese día. Los días sin cotización (fines de semana, festivos)
    no aparecen. Lanza ValueError si Yahoo no tiene datos; los fallos de red llegan como error.
    """
    ticker = yf.Ticker(simbolo)
    historico = ticker.history(start=desde.isoformat(), auto_adjust=False)
    cierres = historico["Close"].dropna() if not historico.empty else historico
    if len(cierres) == 0:
        raise ValueError(f"Yahoo no tiene histórico para {simbolo} desde {desde:%d-%m-%Y}")
    divisa = ticker.fast_info["currency"]
    filas = [
        (indice.date(), Decimal(str(round(float(cierre), 4)))) for indice, cierre in cierres.items()
    ]
    return filas, str(divisa).upper()


def descargar_historico(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, date, int]:
    """Guarda el precio día a día desde la compra más antigua hasta hoy.

    Devuelve (primera fecha, última fecha, nº de días guardados). Los días que ya tenían
    precio se sustituyen. Mismos errores que `actualizar`; además ValueError si el
    instrumento no tiene compras.
    """
    inst = instrumentos.obtener(conn, instrumento_id)
    if inst is None or inst["id_tipo"] not in TIPOS_ID:
        raise ValueError("Solo se descarga de un fondo, ETF, acción o cripto con identificador")
    fila = conn.execute(
        "SELECT MIN(fecha) AS primera FROM compras WHERE instrumento_id = ?", (instrumento_id,)
    ).fetchone()
    if fila["primera"] is None:
        raise ValueError("El instrumento no tiene compras: no se sabe desde cuándo descargar")
    filas, divisa = leer_historico(inst["identificador"], date.fromisoformat(fila["primera"]))
    if divisa != inst["divisa"]:
        raise ValueError(
            f"Yahoo da {inst['identificador']} en {divisa}, pero el instrumento está en "
            f"{inst['divisa']}; no se guarda"
        )
    precios.anadir_muchos(conn, instrumento_id, filas)
    return filas[0][0], filas[-1][0], len(filas)
