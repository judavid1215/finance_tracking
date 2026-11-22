"""Posición actual de un instrumento: participaciones e invertido. Todo en Decimal.

Se usa el coste medio ponderado: una compra suma participaciones e importe; una venta quita
participaciones al mismo precio medio que había (no lo cambia). Las operaciones se recorren
por fecha y, con la misma fecha, primero las compras y luego las ventas.

La comisión de una compra encarece el coste (se suma a lo invertido). La de una venta no
cambia la posición: solo se guarda (servirá para calcular la ganancia realizada).
"""

import sqlite3
from decimal import Decimal

_MOVIMIENTOS = """
SELECT 'compra' AS tipo, 0 AS orden, id, fecha, participaciones, precio, comision
FROM compras WHERE instrumento_id = :id
UNION ALL
SELECT 'venta', 1, id, fecha, participaciones, precio, comision
FROM ventas WHERE instrumento_id = :id
ORDER BY fecha, orden, id
"""


def calcular(conn: sqlite3.Connection, instrumento_id: int) -> dict:
    """Devuelve {"participaciones": ..., "invertido": ...} tras todas las operaciones.

    Lanza ValueError si en algún momento se vende más de lo que había.
    """
    participaciones = Decimal(0)
    invertido = Decimal(0)
    for m in conn.execute(_MOVIMIENTOS, {"id": instrumento_id}):
        n = Decimal(m["participaciones"])
        if m["tipo"] == "compra":
            participaciones += n
            invertido += n * Decimal(m["precio"]) + Decimal(m["comision"])
            continue
        if n > participaciones:
            raise ValueError(
                f"venta {m['id']} ({m['fecha']}): "
                f"solo hay {participaciones} participaciones hasta esa fecha"
            )
        invertido = invertido * (participaciones - n) / participaciones
        participaciones -= n
    return {"participaciones": participaciones, "invertido": invertido}
