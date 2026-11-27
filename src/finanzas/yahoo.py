"""Precio actual de fondos, ETF y acciones con yfinance (Yahoo Finance, gratis y no oficial).

Para Fondo y ETF se busca por ISIN; para Accion y Cripto, por ticker (ej. BTC-EUR).
"""

import sqlite3
from datetime import date
from decimal import Decimal

import yfinance as yf

from finanzas import instrumentos, morningstar, precios

TIPOS_ID = ("ISIN", "TICKER")


def simbolo(inst: sqlite3.Row) -> str:
    """Símbolo con el que se busca el instrumento en Yahoo: su ticker_yahoo o, si no tiene,
    su identificador (ISIN o ticker)."""
    return inst["ticker_yahoo"] or inst["identificador"]


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
    """Pregunta el precio de ahora de un fondo, ETF, acción o cripto, SIN guardarlo.
    Devuelve (fecha, precio). Fondos y ETF (con ISIN) se consultan también en Morningstar y
    se devuelve el dato más reciente de los dos; si una fuente falla se usa la otra.

    Lanza ValueError si no es de esos tipos o si Yahoo da el precio en otra divisa
    (p. ej. el ETF cotiza en USD en esa bolsa y tu instrumento está en EUR).
    """
    inst = instrumentos.obtener(conn, instrumento_id)
    if inst is None or inst["id_tipo"] not in TIPOS_ID:
        raise ValueError("Solo se actualiza un fondo, ETF, acción o cripto con identificador")
    try:
        fecha, precio, divisa = leer_precio(simbolo(inst))
        error = None
    except (ValueError, OSError) as e:
        fecha = precio = divisa = None
        error = e
    if error is None and divisa != inst["divisa"]:
        raise ValueError(
            f"Yahoo da {simbolo(inst)} en {divisa}, pero el instrumento está en "
            f"{inst['divisa']}; no se guarda"
        )
    if inst["id_tipo"] == "ISIN":
        # Morningstar suele publicar el valor liquidativo antes: gana si es más reciente.
        try:
            f_m, p_m, d_m = morningstar.leer_precio(inst["identificador"])
        except (ValueError, OSError):
            pass
        else:
            if d_m == inst["divisa"] and (fecha is None or f_m > fecha):
                return f_m, p_m
    if error is not None:
        raise error
    return fecha, precio


def actualizar(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, Decimal]:
    """Como `consultar`, pero además guarda el precio en el histórico (con la fecha de Yahoo)."""
    fecha, precio = consultar(conn, instrumento_id)
    precios.anadir(conn, instrumento_id, fecha, precio)
    return fecha, precio


def leer_historico(
    simbolo: str, desde: date, permitir_vacio: bool = False
) -> tuple[list[tuple[date, Decimal]], str | None]:
    """Devuelve ([(fecha, cierre), ...], divisa): un cierre por cada día de mercado desde `desde`.

    Es el cierre sin ajustar por dividendos (auto_adjust=False), el precio al que se
    habría comprado o vendido ese día. Los días sin cotización (fines de semana, festivos)
    no aparecen. Si Yahoo no tiene datos lanza ValueError, salvo con permitir_vacio=True, que
    devuelve ([], None). Los fallos de red llegan como error.
    """
    ticker = yf.Ticker(simbolo)
    historico = ticker.history(start=desde.isoformat(), auto_adjust=False)
    cierres = historico["Close"].dropna() if not historico.empty else historico
    if len(cierres) == 0:
        if permitir_vacio:
            return [], None
        raise ValueError(f"Yahoo no tiene histórico para {simbolo} desde {desde:%d-%m-%Y}")
    divisa = ticker.fast_info["currency"]
    filas = [
        (indice.date(), Decimal(str(round(float(cierre), 4)))) for indice, cierre in cierres.items()
    ]
    return filas, str(divisa).upper()


def _completar_con_morningstar(
    inst: sqlite3.Row,
    filas: list[tuple[date, Decimal]],
    guardado: tuple[date, date] | None,
    hoy: date,
) -> list[tuple[date, Decimal]]:
    """Añade el último valor liquidativo de Morningstar si es de un día que Yahoo aún no tiene.

    Morningstar solo da el último valor (no una serie): cubre el hueco de un día, no uno largo.
    Se ignora si falla, si está en otra divisa o si no es posterior a lo ya disponible.
    """
    try:
        fecha, precio, divisa = morningstar.leer_precio(inst["identificador"])
    except (ValueError, OSError):
        return filas
    ultimo = max([f for f, _ in filas] + ([guardado[1]] if guardado else []), default=None)
    if divisa != inst["divisa"] or fecha >= hoy or (ultimo is not None and fecha <= ultimo):
        return filas
    return [*filas, (fecha, precio)]


def descargar_historico(
    conn: sqlite3.Connection, instrumento_id: int, hoy: date | None = None
) -> tuple[date | None, date | None, int]:
    """Guarda los precios diarios que faltan, desde la compra más antigua hasta ayer.

    La primera vez baja desde la primera compra; después, solo desde el último día guardado.
    El día de hoy no se guarda: su cierre puede estar a medias (el precio del momento se usa
    en vivo, ver `consultar`); se guardará completo en la próxima descarga.
    Devuelve (primera fecha nueva, última fecha nueva, nº de días nuevos); si no había nada
    nuevo, (None, None, 0). Mismos errores que `actualizar`; además ValueError si el
    instrumento no tiene compras.
    """
    hoy = hoy or date.today()
    inst = instrumentos.obtener(conn, instrumento_id)
    if inst is None or inst["id_tipo"] not in TIPOS_ID:
        raise ValueError("Solo se descarga de un fondo, ETF, acción o cripto con identificador")
    fila = conn.execute(
        "SELECT MIN(fecha) AS primera FROM compras WHERE instrumento_id = ?", (instrumento_id,)
    ).fetchone()
    if fila["primera"] is None:
        raise ValueError("El instrumento no tiene compras: no se sabe desde cuándo descargar")
    guardado = precios.rango(conn, instrumento_id)
    desde = precios.desde_descarga(date.fromisoformat(fila["primera"]), guardado)
    if desde >= hoy:
        return None, None, 0
    filas, divisa = leer_historico(simbolo(inst), desde, permitir_vacio=bool(guardado))
    filas = [(f, p) for f, p in filas if f < hoy]
    if inst["id_tipo"] == "ISIN":
        filas = _completar_con_morningstar(inst, filas, guardado, hoy)
    if not filas:
        if guardado:
            return None, None, 0
        raise ValueError(f"Yahoo no tiene histórico para {simbolo(inst)} hasta ayer")
    if divisa != inst["divisa"]:
        raise ValueError(
            f"Yahoo da {simbolo(inst)} en {divisa}, pero el instrumento está en "
            f"{inst['divisa']}; no se guarda"
        )
    precios.anadir_muchos(conn, instrumento_id, filas)
    nuevas = [f for f, _ in filas if guardado is None or f > guardado[1]]
    return (nuevas[0], nuevas[-1], len(nuevas)) if nuevas else (None, None, 0)
