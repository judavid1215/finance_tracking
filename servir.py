"""Arranca la web para verla desde el móvil. Uso: python servir.py [puerto]

Escucha en toda la red local (0.0.0.0): abre http://<ip-de-la-raspberry>:8000 desde el móvil.
Solo lee la base de datos; no modifica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # para poder importar "finanzas"

from finanzas.web.app import crear_app  # noqa: E402

RUTA_DB = Path(__file__).parent / "data" / "finanzas.sqlite3"

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    crear_app(RUTA_DB).run(host="0.0.0.0", port=puerto)
