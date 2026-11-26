"""Rellena la base con compras y ventas de ejemplo: Bitcoin, MSCI World, S&P 500, NVIDIA, Apple
y un plan de pensiones.

Uso: python scripts/rellenar_datos.py [ruta_de_la_base]
Sin ruta usa data/finanzas.sqlite3; para no mezclar datos de prueba con los tuyos, pasa otra
(ej. data/demo.sqlite3) y arranca la web con la variable FINANZAS_DB apuntando a ella.
Las fechas, las cantidades y las comisiones (0–1 %, en la divisa del instrumento) son
inventadas, pero los precios son reales: cada operación se hace el primer día de mercado desde
su fecha de ejemplo, al cierre que Yahoo tuvo ese día. Necesita conexión; si Yahoo falla con un
instrumento, se omite sin crearlo y se puede reintentar ejecutando el script otra vez.
El plan de pensiones no tiene histórico (Quefondos no lo da), así que sus precios sí son
inventados. Cada instrumento recibe 12 compras mensuales y 2 ventas (las de los meses que
todavía no tienen un día de mercado cerrado se saltan).
No se guarda ningún precio actual: el del momento se consulta al abrir la aplicación y el
histórico se baja con la opción 17.
Si un instrumento ya existe, no se toca ni se le añaden compras ni ventas (así se puede
ejecutar varias veces sin duplicar); para empezar de cero, borra data/finanzas.sqlite3.
"""

import random
import sys
from datetime import date
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from finanzas import compras, db, instrumentos, ventas, yahoo  # noqa: E402

RUTA_DB = RAIZ / "data" / "finanzas.sqlite3"

# nombre, tipo, divisa, identificador (ISIN, ticker o código DGS), precio inicial (solo para el
# plan, que no tiene histórico real), decimales de participaciones
CARTERAS = [
    ("Bitcoin", "Cripto", "EUR", "BTC-EUR", Decimal("30000"), 8),
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


def precio_real(historico: list, desde: date) -> tuple[date, Decimal] | None:
    """(fecha, cierre) del primer día de mercado desde `desde`, o None si aún no hay ninguno."""
    return next(((f, p) for f, p in historico if f >= desde), None)


def rellenar(conn, rng: random.Random, hoy: date | None = None) -> None:
    hoy = hoy or date.today()
    for nombre, tipo, divisa, identificador, precio, decimales in CARTERAS:
        real = tipo != "Plan_pensiones"
        historico = []
        if real:
            try:
                historico, divisa_yahoo = yahoo.leer_historico(identificador, fecha_mes(MESES - 1))
            except (ValueError, OSError) as e:
                print(f"Se omite {nombre}: no se pudo leer el histórico de Yahoo ({e})")
                continue
            if divisa_yahoo != divisa:
                print(f"Se omite {nombre}: Yahoo lo da en {divisa_yahoo} y no en {divisa}")
                continue
            historico = [(f, p) for f, p in historico if f < hoy]  # el de hoy puede ir a medias
        try:
            id_ = instrumentos.anadir(conn, nombre, tipo, divisa, identificador)
        except ValueError as e:
            print(f"Se omite {nombre}: {e}")
            continue
        quantum = Decimal(1).scaleb(-decimales)
        en_cartera = Decimal(0)  # participaciones que se tienen en cada momento
        n_compras = n_ventas = 0
        for atras in range(MESES - 1, -1, -1):
            fecha_compra = fecha_mes(atras)
            if real:
                dia = precio_real(historico, fecha_compra)
                if dia is None:
                    continue  # todavía no hay día de mercado cerrado desde esa fecha
                fecha_compra, precio = dia
            else:
                # Precio inventado: varía como mucho un ±8 % respecto al mes anterior.
                precio = (precio * (1 + Decimal(rng.randint(-8, 8)) / 100)).quantize(
                    Decimal("0.01")
                )
            invertido = Decimal(rng.randrange(100, 501, 25))  # 100–500 € en pasos de 25
            participaciones = (invertido / precio).quantize(quantum, rounding=ROUND_DOWN)
            comision_compra = comision(participaciones * precio, rng)
            compras.anadir(conn, id_, fecha_compra, participaciones, precio, comision_compra)
            en_cartera += participaciones
            n_compras += 1
            if atras in MESES_CON_VENTA:
                # Vende entre el 25 % y el 50 % de lo que tiene, a partir del día 20.
                fecha_venta = fecha_mes(atras).replace(day=20)
                if real:
                    dia = precio_real(historico, fecha_venta)
                    if dia is None:
                        continue
                    fecha_venta, precio_venta = dia
                else:
                    precio_venta = (precio * (1 + Decimal(rng.randint(-5, 5)) / 100)).quantize(
                        Decimal("0.01")
                    )
                parte = Decimal(rng.randint(25, 50)) / 100
                a_vender = (en_cartera * parte).quantize(quantum, rounding=ROUND_DOWN)
                comision_venta = comision(a_vender * precio_venta, rng)
                ventas.anadir(conn, id_, fecha_venta, a_vender, precio_venta, comision_venta)
                en_cartera -= a_vender
                n_ventas += 1
        origen = "precios reales de Yahoo" if real else "precios inventados"
        print(f"{nombre}: {n_compras} compras y {n_ventas} ventas añadidas ({origen})")


def main() -> None:
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else RUTA_DB
    conn = db.conectar(ruta)
    rellenar(conn, random.Random())
    conn.close()
    print(f"Hecho. Base de datos: {ruta}")


if __name__ == "__main__":
    main()
