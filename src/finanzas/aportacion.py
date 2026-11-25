"""Evolución de una aportación (una compra) desde el día que se hizo hasta hoy.

Todo en la divisa del instrumento (no se convierte a euros) y sin tener en cuenta las ventas:
es lo que habría pasado si esa compra se hubiera mantenido entera.

- aportado = participaciones * precio + comisión (la comisión cuenta como parte del coste).
- valor de cada día = participaciones * último precio guardado hasta ese día.
- Los días de la serie son el día de la compra y los días con precio desde entonces. Si todavía
  no hay ningún precio, ese día vale lo que costó: ni gana ni pierde.
- Todo en Decimal.
"""

import sqlite3
from datetime import date
from decimal import Decimal

from finanzas.evolucion import _carga, _hasta


def serie(conn: sqlite3.Connection, compra_id: int) -> dict | None:
    """Devuelve la compra y su evolución, o None si la compra no existe:

    {"instrumento", "grupo", "divisa", "fecha", "participaciones", "precio", "comision",
     "aportado", "puntos": [{"fecha", "valor", "ganancia", "rentabilidad"}, ...]}
    """
    fila = conn.execute(
        "SELECT c.instrumento_id, c.fecha, c.participaciones, c.precio, c.comision, "
        "i.nombre AS instrumento, i.divisa, g.nombre AS grupo "
        "FROM compras c JOIN instrumentos i ON i.id = c.instrumento_id "
        "JOIN grupos g ON g.id = c.grupo_id WHERE c.id = ?",
        (compra_id,),
    ).fetchone()
    if fila is None:
        return None
    inicio = date.fromisoformat(fila["fecha"])
    n, precio, comision = (Decimal(fila[k]) for k in ("participaciones", "precio", "comision"))
    aportado = n * precio + comision
    fechas, valores = _carga(
        conn,
        "SELECT fecha, precio FROM precios WHERE instrumento_id = ? ORDER BY fecha",
        (fila["instrumento_id"],),
    )
    dias = sorted({inicio, *(f for f in fechas if f >= inicio)})
    puntos = []
    for dia in dias:
        p = _hasta(fechas, valores, dia)
        valor = aportado if p is None else n * p
        puntos.append(
            {
                "fecha": dia,
                "valor": valor,
                "ganancia": valor - aportado,
                "rentabilidad": (valor - aportado) / aportado,
            }
        )
    return {
        "instrumento": fila["instrumento"],
        "grupo": fila["grupo"],
        "divisa": fila["divisa"],
        "fecha": inicio,
        "participaciones": n,
        "precio": precio,
        "comision": comision,
        "aportado": aportado,
        "puntos": puntos,
    }
