"""Consulta de una vez el precio de todo lo que hay en cartera (Yahoo y Quefondos).

Lo de Yahoo (precios y tipos de cambio) es "en vivo": se devuelve para calcular con ello pero
NO se guarda en el histórico (eso lo hace `descargar_historicos`). Los planes de pensiones sí
se guardan: su valor liquidativo es oficial, diario y Quefondos no da histórico.
"""

import sqlite3
from datetime import date

from finanzas import cartera, divisas, instrumentos, quefondos, yahoo

# Un precio más viejo que esto se guarda igualmente, pero se marca como antiguo.
# (Fin de semana largo = 4 días; los planes de pensiones llegan con un par de días de retraso.)
DIAS_ANTIGUO = 5


def _consulta(id_tipo, guardar=False):
    if id_tipo == "DGS":
        return quefondos.actualizar  # guarda el valor liquidativo
    if id_tipo in yahoo.TIPOS_ID:
        return yahoo.actualizar if guardar else yahoo.consultar
    return None


def consultar_todos(
    conn: sqlite3.Connection, hoy: date | None = None, guardar: bool = False
) -> dict:
    """Consulta el precio de ahora de cada instrumento con participaciones en cartera.

    Los instrumentos que ya no tienes (vendidos del todo o sin compras) no se tocan.
    Después consulta el tipo de cambio a euros de cada divisa distinta del euro que haya en
    la cartera. Nada de Yahoo se guarda (ver el principio del módulo), salvo con guardar=True
    (lo usa `refrescar`): entonces precios y tipos de cambio de ahora se guardan en el histórico.
    Devuelve {"filas": [...], "sin_posicion": n, "divisas": [...], "vivos": {...}}, donde
    "vivos" es {"precios": {instrumento_id: precio}, "tasas": {divisa: tasa}}: lo que hay que
    pasar a `cartera.resumen/total/reparto` para calcular con los valores de este momento.
    Cada fila lleva "nombre" y "estado":
    "ok" (con "fecha", "precio" y "antiguo"), "error" (con "mensaje") u "omitido"
    (sin identificador para descargar el precio). Cada divisa lleva "divisa" y "estado"
    ("ok" con "fecha" y "tasa", o "error" con "mensaje").
    """
    hoy = hoy or date.today()
    resumen = cartera.resumen(conn)
    en_cartera = {f["instrumento_id"] for f in resumen}
    todos = instrumentos.listar(conn)
    filas = []
    vivos = {"precios": {}, "tasas": {}}
    for inst in todos:
        if inst["id"] not in en_cartera:
            continue
        fila = {"nombre": inst["nombre"]}
        filas.append(fila)
        consulta = _consulta(inst["id_tipo"], guardar)
        if consulta is None:
            fila.update(estado="omitido", mensaje="sin identificador")
            continue
        try:
            fecha, precio = consulta(conn, inst["id"])
        except (ValueError, OSError) as e:
            fila.update(estado="error", mensaje=str(e))
            continue
        fila.update(
            estado="ok",
            fecha=fecha,
            precio=precio,
            antiguo=(hoy - fecha).days > DIAS_ANTIGUO,
        )
        vivos["precios"][inst["id"]] = precio
    filas_divisas = _consultar_divisas(conn, {f["divisa"] for f in resumen}, guardar)
    vivos["tasas"] = {d["divisa"]: d["tasa"] for d in filas_divisas if d["estado"] == "ok"}
    return {
        "filas": filas,
        "sin_posicion": len(todos) - len(en_cartera),
        "divisas": filas_divisas,
        "vivos": vivos,
    }


def _consultar_divisas(conn, usadas, guardar=False):
    filas = []
    for divisa in sorted(usadas - {divisas.BASE}):
        try:
            fecha, tasa = divisas.actualizar(conn, divisa) if guardar else divisas.leer_tasa(divisa)
        except (ValueError, OSError) as e:
            filas.append({"divisa": divisa, "estado": "error", "mensaje": str(e)})
        else:
            filas.append({"divisa": divisa, "estado": "ok", "fecha": fecha, "tasa": tasa})
    return filas


def descargar_historicos(conn: sqlite3.Connection) -> list[dict]:
    """Descarga el histórico diario que falta (la primera vez desde la primera compra, luego
    solo los días nuevos) de cada fondo, ETF, acción y cripto con compras. Sigue si uno falla.
    Cada fila lleva "nombre" y "estado": "ok" (con "desde", "hasta" y "dias" nuevos; 0 si ya
    estaba al día) o "error" (con "mensaje"). Los planes de pensiones no entran."""
    filas = []
    for inst in instrumentos.listar(conn):
        if inst["id_tipo"] not in yahoo.TIPOS_ID:
            continue
        tiene_compras = conn.execute(
            "SELECT 1 FROM compras WHERE instrumento_id = ? LIMIT 1", (inst["id"],)
        ).fetchone()
        if not tiene_compras:
            continue
        fila = {"nombre": inst["nombre"]}
        filas.append(fila)
        try:
            desde, hasta, dias = yahoo.descargar_historico(conn, inst["id"])
        except (ValueError, OSError) as e:
            fila.update(estado="error", mensaje=str(e))
        else:
            fila.update(estado="ok", desde=desde, hasta=hasta, dias=dias)
    return filas


def descargar_historicos_divisas(conn: sqlite3.Connection) -> list[dict]:
    """Descarga el tipo de cambio diario a euros que falta (como `descargar_historicos`) de
    cada divisa distinta del euro en la que hayas comprado algo. Sigue si una falla. Cada fila
    lleva "divisa" y "estado": "ok" (con "desde", "hasta" y "dias" nuevos) o "error"."""
    usadas = conn.execute(
        "SELECT DISTINCT i.divisa FROM instrumentos i "
        "JOIN compras c ON c.instrumento_id = i.id WHERE i.divisa != ? ORDER BY i.divisa",
        (divisas.BASE,),
    ).fetchall()
    filas = []
    for (divisa,) in usadas:
        fila = {"divisa": divisa}
        filas.append(fila)
        try:
            desde, hasta, dias = divisas.descargar_historico(conn, divisa)
        except (ValueError, OSError) as e:
            fila.update(estado="error", mensaje=str(e))
        else:
            fila.update(estado="ok", desde=desde, hasta=hasta, dias=dias)
    return filas


def refrescar(conn: sqlite3.Connection) -> dict:
    """Deja la base al día para la web: baja el histórico que falte (hasta ayer) y guarda el
    precio y el tipo de cambio de ahora (el día de hoy, que se sustituye en cada llamada y se
    cierra con el histórico del día siguiente). Devuelve {"historicos", "divisas", "ahora"}
    con los resultados de cada paso."""
    return {
        "historicos": descargar_historicos(conn),
        "divisas": descargar_historicos_divisas(conn),
        "ahora": consultar_todos(conn, guardar=True),
    }
