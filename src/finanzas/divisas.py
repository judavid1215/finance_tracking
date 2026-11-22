"""Tipos de cambio a euros, descargados de Yahoo Finance (símbolo USDEUR=X). Todo en Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal

import yfinance as yf

BASE = "EUR"


def leer_tasa(divisa: str) -> tuple[date, Decimal]:
    """Devuelve (fecha, EUR por 1 unidad de la divisa), p. ej. USD -> 0.92.

    Lanza ValueError si Yahoo no tiene el par; los fallos de red también llegan como error.
    """
    divisa = divisa.upper()
    historico = yf.Ticker(f"{divisa}{BASE}=X").history(period="5d")
    if historico.empty:
        raise ValueError(f"Yahoo no tiene tipo de cambio {divisa}/{BASE}")
    cierre = historico["Close"].iloc[-1]
    return historico.index[-1].date(), Decimal(str(round(float(cierre), 6)))


def guardar(conn: sqlite3.Connection, divisa: str, fecha: date, tasa) -> None:
    """Guarda el tipo de cambio de una divisa en una fecha (sustituye el de ese día)."""
    tasa = Decimal(str(tasa))
    if not tasa > 0:
        raise ValueError("tasa: debe ser mayor que 0")
    conn.execute(
        "INSERT INTO tipos_cambio (divisa, fecha, tasa) VALUES (?,?,?) "
        "ON CONFLICT (divisa, fecha) DO UPDATE SET tasa = excluded.tasa",
        (divisa.upper(), fecha.isoformat(), str(tasa)),
    )
    conn.commit()


def actualizar(conn: sqlite3.Connection, divisa: str) -> tuple[date, Decimal]:
    """Descarga y guarda el tipo de cambio de la divisa a euros. Devuelve (fecha, tasa)."""
    if divisa.upper() == BASE:
        raise ValueError(f"{BASE} es la divisa base: no tiene tipo de cambio")
    fecha, tasa = leer_tasa(divisa)
    guardar(conn, divisa, fecha, tasa)
    return fecha, tasa


def ultima(conn: sqlite3.Connection, divisa: str) -> Decimal | None:
    """EUR por 1 unidad de la divisa (la tasa más reciente), o None si no hay ninguna.
    Para EUR es siempre 1."""
    if divisa.upper() == BASE:
        return Decimal(1)
    fila = conn.execute(
        "SELECT tasa FROM tipos_cambio WHERE divisa = ? ORDER BY fecha DESC LIMIT 1",
        (divisa.upper(),),
    ).fetchone()
    return Decimal(fila["tasa"]) if fila else None
