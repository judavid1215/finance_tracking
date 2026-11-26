"""Importa a la base las órdenes de compra de los CSV "Órdenes" de MyInvestor.

Uso:
    from finanzas.importacion import importar_csv
    importar_csv("Fidelity MSCI World", "IE00BYX5NX33", "EUR", r"C:\ruta\fichero.csv")
Un fondo por llamada.

Columnas del CSV: Fecha de la orden; ISIN; Importe estimado ("105 EUR"); Nº de participaciones
(coma decimal); Estado. Cada orden "Finalizada" es una compra: fecha, participaciones y
precio = importe / participaciones (comisión 0). Las órdenes "En curso" y "Rechazada" se
ignoran (no hay participaciones asignadas) y se cuentan en el resumen.

Todo o nada: si falla cualquier fila no se escribe nada y se listan todos los errores.
Si el fondo ya tiene compras en el grupo, se rechaza (para reimportarlo hay que borrarlas
antes). Si ya existe el instrumento con ese ISIN y sin compras, se reutiliza.
"""

import csv
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from finanzas import compras, db, grupos, instrumentos

RUTA_DB = Path(__file__).resolve().parents[2] / "data" / "finanzas.sqlite3"

CABECERA = ["Fecha de la orden", "ISIN", "Importe estimado", "Nº de participaciones", "Estado"]
IGNORADOS = {"En curso", "Rechazada"}  # órdenes sin participaciones asignadas
DECIMALES = Decimal("0.000001")  # participaciones y precio: 6 decimales (el máximo es 8)


class FondoYaImportado(ValueError):
    """El fondo ya tiene compras en la base."""


def normalizar_isin(isin: str) -> str:
    isin = isin.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        raise ValueError(f"ISIN no válido: {isin!r}")
    return isin


def _numero(texto: str) -> Decimal:
    """Número con coma o punto decimal, sin separador de miles ("22,41", "4826.56")."""
    try:
        return Decimal(texto.strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"número no válido: {texto!r}") from None


def _importe(texto: str) -> tuple[Decimal, str]:
    """Separa "105 EUR" en (105, "EUR")."""
    partes = texto.split()
    if len(partes) != 2 or not re.fullmatch(r"[A-Za-z]{3}", partes[1]):
        raise ValueError(f"importe no válido: {texto!r} (se espera algo como '105 EUR')")
    return _numero(partes[0]), partes[1].upper()


def leer_csv(ruta: Path) -> tuple[list[dict], int]:
    """Lee las órdenes del CSV (separador ';', fechas dd/mm/aaaa).

    Devuelve (órdenes, ignoradas): las órdenes Finalizadas y cuántas se han saltado.
    Lanza ValueError con todos los problemas encontrados, uno por línea.
    """
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = [fila for fila in csv.reader(f, delimiter=";") if fila]
    if not filas or [c.strip() for c in filas[0]] != CABECERA:
        raise ValueError(f"la cabecera debe ser: {';'.join(CABECERA)}")
    ordenes, errores, ignoradas = [], [], 0
    for n, fila in enumerate(filas[1:], start=2):
        try:
            if len(fila) != 5:
                raise ValueError("debe tener 5 columnas")
            estado = fila[4].strip()
            if estado in IGNORADOS:
                ignoradas += 1
                continue
            if estado != "Finalizada":
                raise ValueError(f"estado desconocido: {estado!r}")
            fecha = datetime.strptime(fila[0].strip(), "%d/%m/%Y").date()
            importe, divisa = _importe(fila[2])
            participaciones = _numero(fila[3])
            if importe <= 0 or participaciones <= 0:
                raise ValueError("importe y participaciones deben ser mayores que 0")
            ordenes.append(
                {
                    "fecha": fecha,
                    "isin": fila[1].strip().upper(),
                    "importe": importe,
                    "divisa": divisa,
                    "participaciones": participaciones,
                }
            )
        except ValueError as e:
            errores.append(f"línea {n}: {e}")
    if errores:
        raise ValueError("\n".join(errores))
    if not ordenes:
        raise ValueError("no tiene ninguna orden finalizada")
    return ordenes, ignoradas


def previsualizar(conn, ruta: Path, grupo: str) -> dict:
    """Lee un CSV sin pedir el ISIN ni la divisa (salen del fichero) y dice qué se importaría.

    Devuelve isin, divisa, existente (nombre del instrumento si ya existe, o None), ya_importado
    (si ya tiene compras en el grupo), compras (fecha, participaciones, precio), ignoradas e
    invertido. No escribe nada. Lanza ValueError si el CSV está mal o mezcla ISIN o divisas.
    """
    try:
        ordenes, ignoradas = leer_csv(Path(ruta))
    except OSError as e:
        raise ValueError(f"no se puede leer el fichero: {e.strerror}") from None
    isines = sorted({o["isin"] for o in ordenes})
    divisas = sorted({o["divisa"] for o in ordenes})
    if len(isines) > 1 or len(divisas) > 1:
        raise ValueError("el CSV debe tener un solo fondo y una sola divisa")
    isin, divisa = normalizar_isin(isines[0]), divisas[0]
    existente = next((i for i in instrumentos.listar(conn) if i["identificador"] == isin), None)
    g = grupos.obtener_por_nombre(conn, grupo.strip())
    ya = bool(existente and g and compras.listar(conn, existente["id"], g["id"]))
    return {
        "isin": isin,
        "divisa": divisa,
        "existente": existente["nombre"] if existente else None,
        "ya_importado": ya,
        "compras": sorted(
            (
                o["fecha"],
                o["participaciones"].quantize(DECIMALES, ROUND_HALF_UP),
                (o["importe"] / o["participaciones"]).quantize(DECIMALES, ROUND_HALF_UP),
            )
            for o in ordenes
        ),
        "ignoradas": ignoradas,
        "invertido": sum(o["importe"] for o in ordenes),
    }


def preparar(
    ruta: Path,
    isin: str,
    nombre: str,
    divisa: str,
    conn,
    ticker_yahoo=None,
    grupo: str = grupos.GRUPO_POR_DEFECTO,
) -> dict:
    """Valida un CSV y calcula sus compras, sin escribir nada. Lanza ValueError si algo falla."""
    isin = normalizar_isin(isin)
    nombre = nombre.strip()
    divisa = divisa.strip().upper()
    grupo = grupo.strip()
    if not nombre:
        raise ValueError("falta el nombre del fondo")
    if not grupo:
        raise ValueError("falta el grupo")
    if not re.fullmatch(r"[A-Z]{3}", divisa):
        raise ValueError(f"divisa no válida: {divisa!r} (se espera un código como EUR)")
    try:
        ordenes, ignoradas = leer_csv(ruta)
    except OSError as e:
        raise ValueError(f"no se puede leer {ruta}: {e.strerror}") from None
    errores = []
    for o in ordenes:
        if o["isin"] != isin:
            errores.append(f"el CSV es del ISIN {o['isin']} y has indicado {isin}")
        if o["divisa"] != divisa:
            errores.append(f"el CSV está en {o['divisa']} y has indicado {divisa}")
    if errores:
        raise ValueError("\n".join(dict.fromkeys(errores)))
    existente = next((i for i in instrumentos.listar(conn) if i["identificador"] == isin), None)
    grupo_existente = grupos.obtener_por_nombre(conn, grupo)
    if grupo_existente:
        grupo = grupo_existente["nombre"]
    if (
        existente
        and grupo_existente
        and compras.listar(conn, existente["id"], grupo_existente["id"])
    ):
        raise FondoYaImportado(
            f"{existente['nombre']} ya tiene compras en el grupo {grupo}; "
            "bórralas antes de reimportar"
        )
    ticker_yahoo = (ticker_yahoo or "").strip().upper() or None
    operaciones = [
        (
            o["fecha"],
            o["participaciones"].quantize(DECIMALES, ROUND_HALF_UP),
            (o["importe"] / o["participaciones"]).quantize(DECIMALES, ROUND_HALF_UP),
        )
        for o in ordenes
    ]
    return {
        "isin": isin,
        "nombre": nombre,
        "divisa": divisa,
        "ticker_yahoo": ticker_yahoo,
        "grupo": grupo,
        "id": existente["id"] if existente else None,
        "compras": sorted(operaciones),
        "ignoradas": ignoradas,
        "invertido": sum(o["importe"] for o in ordenes),
    }


def aplicar(conn, plan: dict) -> None:
    """Escribe el plan; si algo falla deshace todo lo escrito y relanza el error."""
    id_ = plan["id"]
    creado = id_ is None
    grupo_id = None
    grupo_creado = False
    try:
        grupo_id, grupo_creado = grupos.obtener_o_crear(conn, plan["grupo"])
        plan["grupo_creado"] = grupo_creado
        if creado:
            id_ = instrumentos.anadir(
                conn, plan["nombre"], "Fondo", plan["divisa"], plan["isin"], plan["ticker_yahoo"]
            )
        elif plan["ticker_yahoo"]:
            instrumentos.asignar_ticker_yahoo(conn, id_, plan["ticker_yahoo"])
        for fecha, participaciones, precio in plan["compras"]:
            compras.anadir(conn, id_, fecha, participaciones, precio, grupo_id=grupo_id)
    except Exception:
        if id_ is not None and grupo_id is not None:
            conn.execute(
                "DELETE FROM compras WHERE instrumento_id = ? AND grupo_id = ?", (id_, grupo_id)
            )
            conn.commit()
        if creado and id_ is not None:
            instrumentos.borrar(conn, id_)
        if grupo_creado:
            grupos.borrar(conn, grupo_id)
        raise


def importar(
    conn,
    ruta: Path,
    isin: str,
    nombre: str,
    divisa: str,
    ticker_yahoo: str | None = None,
    grupo: str = grupos.GRUPO_POR_DEFECTO,
) -> dict:
    """Valida el CSV y, si no hay ningún error, lo escribe en el grupo indicado.

    Devuelve el plan (compras calculadas...). Lanza ValueError si algo falla.
    """
    plan = preparar(Path(ruta), isin, nombre, divisa, conn, ticker_yahoo, grupo)
    aplicar(conn, plan)
    return plan


def resumen(plan: dict) -> str:
    """Texto de una línea con lo importado de un fondo."""
    texto = (
        f"{plan['nombre']} [{plan['grupo']}]: {len(plan['compras'])} compras, "
        f"{sum(c[1] for c in plan['compras'])} participaciones, invertido {plan['invertido']} "
        f"{plan['divisa']}"
    )
    if plan["ignoradas"]:
        texto += f", {plan['ignoradas']} orden(es) en curso o rechazadas ignoradas"
    return texto


def importar_csv(
    nombre: str,
    isin: str,
    divisa: str,
    ruta: str | Path,
    grupo: str = grupos.GRUPO_POR_DEFECTO,
    ruta_db: str | Path = RUTA_DB,
    ticker_yahoo: str | None = None,
) -> dict | None:
    """Importa un CSV de órdenes de MyInvestor como un fondo, imprime un resumen y devuelve el plan.

    `grupo` es el grupo (Personal, Pension...) al que van las compras; si no existe, se crea. Un
    mismo fondo se puede importar en varios grupos.
    Si el fondo ya tiene compras en ese grupo, avisa, no hace nada y devuelve None (así se puede
    repetir una serie de llamadas sin que se pare). Con cualquier otro problema lanza ValueError
    sin escribir nada: ISIN, nombre o divisa no válidos o distintos de los del CSV, CSV mal
    formado...
    `ruta_db` es la base de datos a usar. `ticker_yahoo` (opcional, ej. "0P00009PQ4.F") es el
    símbolo con el que se buscan precios e histórico en Yahoo cuando el ISIN no da datos; el
    fondo se guarda siempre con su ISIN como identificador.
    """
    conn = db.conectar(ruta_db)
    try:
        plan = importar(conn, Path(ruta), isin, nombre, divisa, ticker_yahoo, grupo)
    except FondoYaImportado as e:
        print(f"AVISO: {e}. No se importa de nuevo.")
        return None
    finally:
        conn.close()
    print(resumen(plan))
    if plan["grupo_creado"]:
        print(f"Se ha creado el grupo '{plan['grupo']}'.")
    print("Hecho.")
    return plan
