"""Rellena la base con datos inventados: Bitcoin, MSCI World, S&P 500, NVIDIA, Apple
y un plan de pensiones.

Uso: python scripts/rellenar_datos.py
Los precios e importes son inventados (los ISIN de los ETF, los tickers y el código DGS del
plan son reales). Cada instrumento recibe
12 compras mensuales y 2 ventas, con comisiones del 0–1 % en la divisa del instrumento.
Si un instrumento ya existe, no se toca ni se le añaden compras ni ventas (así se puede
ejecutar varias veces sin duplicar).
"""

import random
import sys
from datetime import date
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from finanzas import compras, db, instrumentos, precios, ventas  # noqa: E402

RUTA_DB = RAIZ / "data" / "finanzas.sqlite3"

# nombre, tipo, divisa, identificador (ISIN, ticker o código DGS), precio inicial,
# decimales de participaciones
CARTERAS = [
    ("Bitcoin", "Cripto", "EUR", "BTC-EUR", Decimal("30000"), 8),
    ("MSCI World", "ETF", "EUR", "IE00BYX5NX33", Decimal("85"), 4),
    ("S&P 500", "ETF", "EUR", "IE00B5BMR087", Decimal("110"), 4),
    ("NVIDIA", "Accion", "USD", "NVDA", Decimal("120"), 4),
    ("Apple", "Accion", "USD", "AAPL", Decimal("180"), 4),
    ("MyInvestor Indexado Global PP", "Plan_pensiones", "EUR", "N5396", Decimal("19"), 4),
]
MESES = 12  # una compra al mes, terminando en el mes actual
MESES_CON_VENTA = (7, 3)  # meses atrás en los que, además de comprar, se vende una parte


def fecha_mes(atras: int) -> date:
    """Día 5 del mes actual menos `atras` meses."""
    hoy = date.today()
    mes = hoy.year * 12 + hoy.month - 1 - atras
    return date(mes // 12, mes % 12 + 1, 5)


def comision(importe: Decimal, rng: random.Random) -> Decimal:
    """Entre el 0 % y el 1 % del importe (en su misma divisa); una de cada cuatro, sin comisión."""
    if rng.random() < 0.25:
        return Decimal(0)
    return (importe * Decimal(rng.randint(0, 100)) / 10000).quantize(Decimal("0.01"))


def rellenar(conn, rng: random.Random) -> None:
    for nombre, tipo, divisa, identificador, precio, decimales in CARTERAS:
        try:
            id_ = instrumentos.anadir(conn, nombre, tipo, divisa, identificador)
        except ValueError as e:
            print(f"Se omite {nombre}: {e}")
            continue
        quantum = Decimal(1).scaleb(-decimales)
        en_cartera = Decimal(0)  # participaciones que se tienen en cada momento
        n_ventas = 0
        for atras in range(MESES - 1, -1, -1):
            # El precio varía como mucho un ±8 % (±20 % en cripto) respecto al mes anterior.
            tope = 20 if tipo == "Cripto" else 8
            precio = (precio * (1 + Decimal(rng.randint(-tope, tope)) / 100)).quantize(
                Decimal("0.01")
            )
            invertido = Decimal(rng.randrange(100, 501, 25))  # 100–500 € en pasos de 25
            participaciones = (invertido / precio).quantize(quantum, rounding=ROUND_DOWN)
            comision_compra = comision(participaciones * precio, rng)
            compras.anadir(conn, id_, fecha_mes(atras), participaciones, precio, comision_compra)
            en_cartera += participaciones
            if atras in MESES_CON_VENTA:
                # Vende entre el 25 % y el 50 % de lo que tiene, el día 20 (tras la compra del 5).
                parte = Decimal(rng.randint(25, 50)) / 100
                a_vender = (en_cartera * parte).quantize(quantum, rounding=ROUND_DOWN)
                precio_venta = (precio * (1 + Decimal(rng.randint(-5, 5)) / 100)).quantize(
                    Decimal("0.01")
                )
                comision_venta = comision(a_vender * precio_venta, rng)
                fecha_venta = fecha_mes(atras).replace(day=20)
                ventas.anadir(conn, id_, fecha_venta, a_vender, precio_venta, comision_venta)
                en_cartera -= a_vender
                n_ventas += 1
        precios.anadir(conn, id_, date.today(), precio)  # precio actual = el último simulado
        print(f"{nombre}: {MESES} compras, {n_ventas} ventas y precio actual añadidos")


def main() -> None:
    conn = db.conectar(RUTA_DB)
    rellenar(conn, random.Random())
    conn.close()
    print(f"Hecho. Base de datos: {RUTA_DB}")


if __name__ == "__main__":
    main()
