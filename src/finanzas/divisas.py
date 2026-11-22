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


def leer_historico(divisa: str, desde: date) -> list[tuple[date, Decimal]]:
    """Devuelve [(fecha, EUR por 1 unidad de la divisa), ...] de cada día de mercado desde `desde`.

    Lanza ValueError si Yahoo no tiene datos; los fallos de red llegan como error.
    """
    divisa = divisa.upper()
    historico = yf.Ticker(f"{divisa}{BASE}=X").history(start=desde.isoformat())
    cierres = historico["Close"].dropna() if not historico.empty else historico
    if len(cierres) == 0:
        raise ValueError(f"Yahoo no tiene histórico de {divisa}/{BASE} desde {desde:%d-%m-%Y}")
    return [(i.date(), Decimal(str(round(float(c), 6)))) for i, c in cierres.items()]


def descargar_historico(conn: sqlite3.Connection, divisa: str) -> tuple[date, date, int]:
    """Guarda el tipo de cambio día a día desde la primera compra en esa divisa hasta hoy.

    Devuelve (primera fecha, última fecha, nº de días guardados); los días que ya existían se
    sustituyen. Lanza ValueError si es EUR o si no hay compras en esa divisa.
    """
    divisa = divisa.upper()
    if divisa == BASE:
        raise ValueError(f"{BASE} es la divisa base: no tiene tipo de cambio")
    fila = conn.execute(
        "SELECT MIN(c.fecha) AS primera FROM compras c "
        "JOIN instrumentos i ON i.id = c.instrumento_id WHERE i.divisa = ?",
        (divisa,),
    ).fetchone()
    if fila["primera"] is None:
        raise ValueError(f"No hay compras en {divisa}: no se sabe desde cuándo descargar")
    filas = leer_historico(divisa, date.fromisoformat(fila["primera"]))
    datos = []
    for fecha, tasa in filas:
        if not tasa > 0:
            raise ValueError("tasa: debe ser mayor que 0")
        datos.append((divisa, fecha.isoformat(), str(tasa)))
    with conn:
        conn.executemany(
            "INSERT INTO tipos_cambio (divisa, fecha, tasa) VALUES (?,?,?) "
            "ON CONFLICT (divisa, fecha) DO UPDATE SET tasa = excluded.tasa",
            datos,
        )
    return filas[0][0], filas[-1][0], len(filas)
