"""Tipos de cambio a euros, descargados de Yahoo Finance (símbolo USDEUR=X). Todo en Decimal."""

import sqlite3
from datetime import date
from decimal import Decimal

import yfinance as yf

from finanzas import precios

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


def leer_historico(
    divisa: str, desde: date, permitir_vacio: bool = False
) -> list[tuple[date, Decimal]]:
    """Devuelve [(fecha, EUR por 1 unidad de la divisa), ...] de cada día de mercado desde `desde`.

    Si Yahoo no tiene datos lanza ValueError, salvo con permitir_vacio=True, que devuelve [].
    Los fallos de red llegan como error.
    """
    divisa = divisa.upper()
    historico = yf.Ticker(f"{divisa}{BASE}=X").history(start=desde.isoformat())
    cierres = historico["Close"].dropna() if not historico.empty else historico
    if len(cierres) == 0 and not permitir_vacio:
        raise ValueError(f"Yahoo no tiene histórico de {divisa}/{BASE} desde {desde:%d-%m-%Y}")
    return [(i.date(), Decimal(str(round(float(c), 6)))) for i, c in cierres.items()]


def descargar_historico(
    conn: sqlite3.Connection, divisa: str, hoy: date | None = None
) -> tuple[date | None, date | None, int]:
    """Guarda los tipos de cambio diarios que faltan, desde la primera compra en esa divisa
    hasta ayer. La primera vez baja todo; después, solo desde el último día guardado. Hoy no se
    guarda (puede estar a medias; el cambio del momento se usa en vivo).

    Devuelve (primera fecha nueva, última fecha nueva, nº de días nuevos); si no había nada
    nuevo, (None, None, 0). Lanza ValueError si es EUR o si no hay compras en esa divisa.
    """
    hoy = hoy or date.today()
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
    guardado = _rango(conn, divisa)
    desde = precios.desde_descarga(date.fromisoformat(fila["primera"]), guardado)
    if desde >= hoy:
        return None, None, 0
    filas = [f for f in leer_historico(divisa, desde, permitir_vacio=bool(guardado)) if f[0] < hoy]
    if not filas:
        if guardado:
            return None, None, 0
        raise ValueError(f"Yahoo no tiene histórico de {divisa}/{BASE} hasta ayer")
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
    nuevas = [f for f, _ in filas if guardado is None or f > guardado[1]]
    return (nuevas[0], nuevas[-1], len(nuevas)) if nuevas else (None, None, 0)


def _rango(conn: sqlite3.Connection, divisa: str) -> tuple[date, date] | None:
    fila = conn.execute(
        "SELECT MIN(fecha) AS a, MAX(fecha) AS b FROM tipos_cambio WHERE divisa = ?", (divisa,)
    ).fetchone()
    return (date.fromisoformat(fila["a"]), date.fromisoformat(fila["b"])) if fila["a"] else None
