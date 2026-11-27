"""Importa las acciones de Interactive Brokers (Flex Query en CSV).

Uso: python scripts/cargar_ibkr.py            -> solo revisa, no escribe nada
     python scripts/cargar_ibkr.py --importar -> escribe en data/finanzas.sqlite3
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))  # para poder importar "finanzas"

from finanzas import actualizacion, db, importacion_ibkr  # noqa: E402

RUTA = Path(r"C:\finance_tracking\import_data\IBKR_trade.csv")

# Acciones que no cotizan en EE. UU.: Yahoo las busca con el sufijo de su bolsa.
TICKERS_YAHOO = {"IBE": "IBE.MC"}

importar = "--importar" in sys.argv
importacion_ibkr.importar_csv(
    RUTA,
    grupo="Interactive Brokers",
    tickers_yahoo=TICKERS_YAHOO,
    solo_ver=not importar,
)

if importar:  # deja los precios al día (histórico desde la primera compra y precio de ahora)
    print("Actualizando precios...")
    conn = db.conectar(importacion_ibkr.RUTA_DB)
    try:
        res = actualizacion.refrescar(conn)
    finally:
        conn.close()
    malos = [f for f in res["historicos"] + res["ahora"]["filas"] if f["estado"] == "error"]
    for f in malos:
        print(f"  {f['nombre']}: {f['mensaje']}")
    print(f"Precios actualizados ({len(malos)} errores).")
