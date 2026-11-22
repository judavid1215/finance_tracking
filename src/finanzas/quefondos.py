"""Precio actual de planes de pensiones, leído de la web de Quefondos (sin API).

Solo usa la librería estándar. Si Quefondos cambia su página, `leer_precio` lanzará
ValueError y habrá que ajustar las expresiones de abajo.
"""

import re
import sqlite3
import urllib.request
from datetime import date, datetime
from decimal import Decimal

from finanzas import instrumentos, precios

_URL = "https://www.quefondos.com/es/planes/ficha.html?isin={codigo}"
_VALOR = re.compile(r"Valor liquidativo:\s*</span>\s*<span[^>]*>\s*([\d.,]+)\s*EUR", re.I)
_FECHA = re.compile(r"Fecha:\s*</span>\s*<span[^>]*>\s*(\d{2}/\d{2}/\d{4})", re.I)


def leer_precio(codigo: str, html: str | None = None) -> tuple[date, Decimal]:
    """Devuelve (fecha, valor liquidativo) del plan con ese código DGS (p. ej. N5396).

    Si se pasa `html`, no descarga nada (útil para tests). Lanza ValueError si no encuentra
    el dato y OSError si falla la descarga.
    """
    if html is None:
        peticion = urllib.request.Request(
            _URL.format(codigo=codigo), headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(peticion, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    valor, fecha = _VALOR.search(html), _FECHA.search(html)
    if not valor or not fecha:
        raise ValueError(f"No encuentro el valor liquidativo de {codigo} en Quefondos")
    # Formato español: 19.607,89 -> 19607.89 (en la práctica solo trae la coma decimal).
    numero = valor.group(1).replace(".", "").replace(",", ".")
    return datetime.strptime(fecha.group(1), "%d/%m/%Y").date(), Decimal(numero)


def actualizar(conn: sqlite3.Connection, instrumento_id: int) -> tuple[date, Decimal]:
    """Descarga y guarda el precio de un plan de pensiones. Devuelve (fecha, precio).

    Lanza ValueError si el instrumento no existe o no es un plan de pensiones.
    """
    inst = instrumentos.obtener(conn, instrumento_id)
    if inst is None or inst["id_tipo"] != "DGS":
        raise ValueError("Solo se puede actualizar un plan de pensiones (con código DGS)")
    fecha, precio = leer_precio(inst["identificador"])
    precios.anadir(conn, instrumento_id, fecha, precio)
    return fecha, precio
