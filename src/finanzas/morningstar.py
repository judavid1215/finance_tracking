"""Último precio de un fondo o ETF según Morningstar, por ISIN (sin clave, sin ChromeDriver).

Usa el servicio público que alimenta sus propias fichas (lt.morningstar.com). A veces va uno o
dos días por delante de Yahoo; `yahoo.consultar` se queda con el más reciente. Solo librería
estándar. Si Morningstar cambia el servicio, `leer_precio` lanza ValueError y se sigue con Yahoo.
"""

import re
import urllib.request
from datetime import date, datetime
from decimal import Decimal

_URL = (
    "https://lt.morningstar.com/api/rest.svc/klr5zyak8x/security_details/{isin}"
    "?idtype=ISIN&viewId=snapshot&outputType=json"
)
_ULTIMO = re.compile(
    r'<LastPrice\s+date="(\d{2}-\d{2}-\d{4})[^"]*"\s+currency="([A-Z]{3})"[^>]*>\s*([\d.]+)\s*<'
)


def leer_precio(isin: str, xml: str | None = None) -> tuple[date, Decimal, str]:
    """Devuelve (fecha, último valor liquidativo, divisa) del ISIN dado.

    Si se pasa `xml`, no descarga nada (útil para tests). Lanza ValueError si Morningstar no
    conoce el ISIN o no trae precio, y OSError si falla la descarga.
    """
    if xml is None:
        peticion = urllib.request.Request(
            _URL.format(isin=isin), headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(peticion, timeout=15) as r:
            xml = r.read().decode("utf-8", errors="replace")
    m = _ULTIMO.search(xml)
    if not m:
        raise ValueError(f"Morningstar no tiene precio para {isin}")
    return datetime.strptime(m.group(1), "%d-%m-%Y").date(), Decimal(m.group(3)), m.group(2)
