"""Importa por CSV las órdenes de los fondos de MyInvestor. Uso: python scripts/cargar_csv.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))  # para poder importar "finanzas"

from finanzas import importacion  # noqa: E402

CARPETA = Path(r"C:\finance_tracking\import_data")

importacion.importar_csv(
    nombre="Fidelity MSCI World Index Fund P-ACC-EUR",
    isin="IE00BYX5NX33",
    divisa="EUR",
    ruta=CARPETA / "Órdenes 291969 IE00BYX5NX33.csv",
    grupo="Cartera principal",
)

importacion.importar_csv(
    nombre="iShares Developed World Index Fund (IE) Class S",
    isin="IE000ZYRH0Q7",
    divisa="EUR",
    ruta=CARPETA / "Órdenes 291969 IE000ZYRH0Q7.csv",
    grupo="Cartera principal",
)

importacion.importar_csv(
    nombre="DNB Fund - Technology A EUR (Acc)",
    ticker_yahoo="0P00009PQ4.F",
    isin="LU0302296495",
    divisa="EUR",
    ruta=CARPETA / "Órdenes 291969 LU0302296495.csv",
    grupo="Cartera principal",
)

importacion.importar_csv(
    nombre="Amundi Core MSCI Emerging Markets",
    isin="LU0996175948",
    divisa="EUR",
    ruta=CARPETA / "Órdenes 291969 LU0996175948.csv",
    grupo="Cartera principal",
)

importacion.importar_csv(
    nombre="Fidelity MSCI World Index Fund P-ACC-EUR",
    isin="IE00BYX5NX33",
    divisa="EUR",
    ruta=CARPETA / "Órdenes 1279087 IE00BYX5NX33 Laura.csv",
    grupo="Inversiones Laura",
)

# AXA Trésor Court Terme C (FR0000447823): aún no hay CSV de órdenes; añadirlo cuando se descargue.
