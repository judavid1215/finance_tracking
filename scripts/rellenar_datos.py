"""Rellena la base con datos inventados: Bitcoin, MSCI World, S&P 500, NVIDIA y Apple.

Uso: python scripts/rellenar_datos.py
Los ISIN, precios e importes son inventados (los tickers son reales). Si un instrumento ya
existe, no se toca ni se le añaden compras (así se puede ejecutar varias veces sin duplicar).
"""

import random
import sys
from datetime import date
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from finanzas import compras, db, instrumentos  # noqa: E402

RUTA_DB = RAIZ / "data" / "finanzas.sqlite3"

# nombre, tipo, divisa, identificador (ISIN inventado o ticker), precio inicial,
# decimales de participaciones
CARTERAS = [
    ("Bitcoin", "Cripto", "EUR", None, Decimal("30000"), 8),
    ("MSCI World", "ETF", "EUR", "IE00FAKE0001", Decimal("85"), 4),
    ("S&P 500", "ETF", "EUR", "IE00FAKE0002", Decimal("110"), 4),
    ("NVIDIA", "Accion", "USD", "NVDA", Decimal("120"), 4),
    ("Apple", "Accion", "USD", "AAPL", Decimal("180"), 4),
]
MESES = 12  # una compra al mes, terminando en el mes actual


def fecha_mes(atras: int) -> date:
    """Día 5 del mes actual menos `atras` meses."""
    hoy = date.today()
    mes = hoy.year * 12 + hoy.month - 1 - atras
    return date(mes // 12, mes % 12 + 1, 5)


def rellenar(conn, rng: random.Random) -> None:
    for nombre, tipo, divisa, identificador, precio, decimales in CARTERAS:
        try:
            id_ = instrumentos.anadir(conn, nombre, tipo, divisa, identificador)
        except ValueError as e:
            print(f"Se omite {nombre}: {e}")
            continue
        quantum = Decimal(1).scaleb(-decimales)
        for atras in range(MESES - 1, -1, -1):
            # El precio varía como mucho un ±8 % (±20 % en cripto) respecto al mes anterior.
            tope = 20 if tipo == "Cripto" else 8
            precio = (precio * (1 + Decimal(rng.randint(-tope, tope)) / 100)).quantize(
                Decimal("0.01")
            )
            invertido = Decimal(rng.randrange(100, 501, 25))  # 100–500 € en pasos de 25
            participaciones = (invertido / precio).quantize(quantum, rounding=ROUND_DOWN)
            compras.anadir(conn, id_, fecha_mes(atras), participaciones, precio)
        print(f"{nombre}: {MESES} compras añadidas")


def main() -> None:
    conn = db.conectar(RUTA_DB)
    rellenar(conn, random.Random())
    conn.close()
    print(f"Hecho. Base de datos: {RUTA_DB}")


if __name__ == "__main__":
    main()
