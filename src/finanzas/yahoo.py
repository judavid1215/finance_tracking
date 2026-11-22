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


def actualizar(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, Decimal]:
    """Descarga y guarda el precio de un fondo, ETF o acción. Devuelve (fecha, precio).

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
    precios.anadir(conn, instrumento_id, fecha, precio)
    return fecha, precio
