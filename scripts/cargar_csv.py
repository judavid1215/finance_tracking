"""Importa por CSV los fondos de MyInvestor. Uso: python scripts/cargar_csv.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))  # para poder importar "finanzas"

from finanzas import importacion  # noqa: E402

path_msci = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo IE00BYX5NX33.csv"
importacion.importar_csv(
    nombre="Fidelity MSCI World Index Fund P-ACC-EUR",
    isin="IE00BYX5NX33",
    divisa="EUR",
    ruta=path_msci,grupo="Cartera principal"
)

path_axa = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo FR0000447823.csv"
importacion.importar_csv(
    nombre="AXA Trésor Court Terme C", isin="FR0000447823", divisa="EUR", ruta=path_axa,grupo="Cartera principal"
)

path_ishares = (
    r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo IE000ZYRH0Q7.csv"
)
importacion.importar_csv(
    nombre="iShares Developed World Index Fund (IE) Class S",
    isin="IE000ZYRH0Q7",
    divisa="EUR",
    ruta=path_ishares,grupo="Cartera principal"
)

path_dnb = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo LU0302296495.csv"
importacion.importar_csv(
    nombre="DNB Fund - Technology A EUR (Acc)",
    ticker_yahoo="0P00009PQ4.F",
    isin="LU0302296495",
    divisa="EUR",
    ruta=path_dnb,grupo="Cartera principal"
)

path_amundi = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo LU0996175948.csv"
importacion.importar_csv(
    nombre="Amundi Core MSCI Emerging Markets",
    isin="LU0996175948",
    divisa="EUR",
    ruta=path_amundi,grupo="Cartera principal"
)

path_Laura = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo IE00BYX5NX33 Laura.csv"
importacion.importar_csv(
    nombre="Fidelity MSCI World Index Fund P-ACC-EUR",
    isin="IE00BYX5NX33",
    divisa="EUR",
    ruta=path_Laura,grupo="Inversiones Laura"
)
