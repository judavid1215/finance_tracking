"""Menú de consola para probar la base de datos a mano. Uso: python main.py"""

import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # para poder importar "finanzas"

from finanzas import (  # noqa: E402
    actualizacion,
    cartera,
    compras,
    db,
    grupos,
    instrumentos,
    precios,
    quefondos,
    importacion,
    ventas,
)

# Siempre en <proyecto>/data/, se ejecute desde donde se ejecute.
RUTA_DB = Path(__file__).parent / "data" / "finanzas.sqlite3"

MENU = """
--- Instrumentos ---
1) Añadir instrumento
2) Listar todos
3) Listar por tipo
4) Borrar por id
--- Compras ---
5) Añadir compra
6) Listar compras (todas o de un instrumento)
7) Borrar compra por id
--- Ventas ---
10) Añadir venta
11) Listar ventas (todas o de un instrumento)
12) Borrar venta por id
--- Cartera ---
8) Resumen por instrumento y total en EUR
9) Poner precio actual
16) Reparto de la cartera en % (por instrumento, tipo o divisa)
13) Actualizar precio de un plan de pensiones (web)
15) Poner/cambiar identificador (ej. BTC-EUR a una cripto)
14) Consultar precios de ahora (fondos, ETF, acciones, planes); no se guardan en el histórico
19) Grupos (Personal, Pension...): listar, crear o borrar
18) Poner/quitar ticker de Yahoo (ej. 0P00009PQ4.F a un fondo; se usa en lugar del ISIN)
17) Descargar histórico diario de precios y tipos de cambio desde la primera compra (Yahoo)
--- ---
0) Salir
"""


def mostrar_instrumentos(filas):
    if not filas:
        print("(vacío)")
    for f in filas:
        ident = f"{f['id_tipo']} {f['identificador']}" if f["identificador"] else "-"
        if f["ticker_yahoo"]:
            ident += f" (Yahoo: {f['ticker_yahoo']})"
        print(f"{f['id']:>3} | {f['nombre']:<25} | {f['tipo']:<15} | {f['divisa']} | {ident}")


def mostrar_compras(lista):
    if not lista:
        print("(vacío)")
    for c in lista:
        print(
            f"{c['id']:>3} | {c['instrumento']:<20} | {c['grupo']:<10} | {c['fecha']:%d-%m-%Y} | "
            f"{c['participaciones']} part. x {c['precio']} | comisión {c['comision']}"
        )


def mostrar_cartera(filas):
    if not filas:
        print("(vacío)")
    for f in filas:
        linea = (
            f"{f['instrumento']:<20} | {f['grupo']:<10} | {f['participaciones']} part. | "
            f"invertido {f['invertido']:.2f} {f['divisa']} | precio medio {f['precio_medio']:.4f}"
        )
        if f["valor_actual"] is not None:
            linea += (
                f" | valor {f['valor_actual']:.2f} | ganancia {f['ganancia']:+.2f} "
                f"({f['rentabilidad']:+.1%})"
            )
        print(linea)


def mostrar_total(t):
    if t["valor"] is None:
        print("TOTAL en EUR: nada valorado todavía (faltan precios o tipos de cambio)")
    else:
        rent = f" ({t['rentabilidad']:+.1%})" if t["rentabilidad"] is not None else ""
        print(
            f"TOTAL en EUR: invertido {t['invertido']:.2f} | valor {t['valor']:.2f} | "
            f"ganancia {t['ganancia']:+.2f}{rent}"
        )
    for nombre, motivo in t["excluidos"]:
        print(f"  no cuenta en el total: {nombre} ({motivo})")


def resumen_cartera(conn, vivos):
    mostrar_cartera(cartera.resumen(conn, vivos))
    mostrar_total(cartera.total(conn, vivos))


def mostrar_reparto(r):
    if r["valor"] is None:
        print("Reparto: nada valorado todavía (faltan precios o tipos de cambio)")
    for f in r["filas"]:
        print(f"{f['grupo']:<25} | {f['valor']:>12.2f} EUR | {f['porcentaje']:>6.2f}%")
    for nombre, motivo in r["excluidos"]:
        print(f"  no cuenta en el reparto: {nombre} ({motivo})")


def reparto_cartera(conn, vivos):
    print("Agrupar por: 1) instrumento  2) tipo  3) divisa  4) grupo")
    por = {"1": "instrumento", "2": "tipo", "3": "divisa", "4": "grupo"}.get(
        input("Opción: ").strip()
    )
    if por is None:
        print("Opción no válida")
        return
    mostrar_reparto(cartera.reparto(conn, por, vivos))


def pedir_entero(texto):
    try:
        return int(input(texto))
    except ValueError:
        print("Escribe un número entero.")
        return None


def anadir_instrumento(conn):
    nombre = input("Nombre: ").strip()
    print("Tipos:", ", ".join(instrumentos.TIPOS))
    tipo = input("Tipo: ").strip()
    divisa = input("Divisa (3 letras, ej. EUR): ").strip().upper()
    identificador = None
    pide = instrumentos.IDENTIFICADOR_POR_TIPO.get(instrumentos.normalizar_tipo(tipo))
    if pide:
        opcional = " (vacío = ninguno)" if tipo.strip().lower() == "cripto" else ""
        identificador = input(f"{pide}{opcional}: ").strip()
    print("Añadido con id", instrumentos.anadir(conn, nombre, tipo, divisa, identificador))


def pedir_grupo(conn):
    """Pregunta el grupo por nombre; vacío = el de por defecto. Devuelve su id (o None)."""
    print("Grupos:", ", ".join(g["nombre"] for g in grupos.listar(conn)) or "(ninguno todavía)")
    nombre = input(f"Grupo (vacío = {grupos.GRUPO_POR_DEFECTO}): ").strip()
    if not nombre:
        return None
    grupo = grupos.obtener_por_nombre(conn, nombre)
    if grupo is None:
        raise ValueError(f"No existe el grupo '{nombre}'; créalo con la opción 19")
    return grupo["id"]


def gestionar_grupos(conn):
    for g in grupos.listar(conn):
        print(f"{g['id']:>3} | {g['nombre']}")
    accion = input("1) crear  2) borrar  (vacío = volver): ").strip()
    if accion == "1":
        print("Añadido con id", grupos.anadir(conn, input("Nombre: ")))
    elif accion == "2":
        id_ = pedir_entero("Id a borrar: ")
        if id_ is not None:
            print("Borrado" if grupos.borrar(conn, id_) else "No existe ese id")


def anadir_compra(conn):
    mostrar_instrumentos(instrumentos.listar(conn))
    instrumento_id = pedir_entero("Id del instrumento: ")
    if instrumento_id is None:
        return
    texto = input("Fecha de ejecución (DD-MM-AAAA): ").strip()
    fecha = datetime.strptime(texto, "%d-%m-%Y").date()
    participaciones = input("Número de participaciones (punto o coma): ").strip()
    precio = input("Precio por participación (punto o coma): ").strip()
    comision = input("Comisión en la divisa del instrumento (vacío = 0): ").strip() or "0"
    grupo_id = pedir_grupo(conn)
    id_ = compras.anadir(conn, instrumento_id, fecha, participaciones, precio, comision, grupo_id)
    print("Añadida con id", id_)


def anadir_venta(conn):
    mostrar_instrumentos(instrumentos.listar(conn))
    instrumento_id = pedir_entero("Id del instrumento: ")
    if instrumento_id is None:
        return
    texto = input("Fecha de ejecución (DD-MM-AAAA): ").strip()
    fecha = datetime.strptime(texto, "%d-%m-%Y").date()
    participaciones = input("Número de participaciones (punto o coma): ").strip()
    precio = input("Precio por participación (punto o coma): ").strip()
    comision = input("Comisión en la divisa del instrumento (vacío = 0): ").strip() or "0"
    grupo_id = pedir_grupo(conn)
    id_ = ventas.anadir(conn, instrumento_id, fecha, participaciones, precio, comision, grupo_id)
    print("Añadida con id", id_)


def listar_ventas(conn):
    texto = input("Id de instrumento (vacío = todos): ").strip()
    mostrar_compras(ventas.listar(conn, int(texto) if texto else None))


def poner_precio(conn):
    mostrar_instrumentos(instrumentos.listar(conn))
    instrumento_id = pedir_entero("Id del instrumento: ")
    if instrumento_id is None:
        return
    texto = input("Fecha (DD-MM-AAAA, vacío = hoy): ").strip()
    fecha = datetime.strptime(texto, "%d-%m-%Y").date() if texto else date.today()
    precios.anadir(conn, instrumento_id, fecha, input("Precio (punto o coma): ").strip())
    print("Guardado")


def actualizar_plan(conn):
    mostrar_instrumentos(instrumentos.listar(conn, "Plan_pensiones"))
    instrumento_id = pedir_entero("Id del plan: ")
    if instrumento_id is None:
        return
    try:
        fecha, precio = quefondos.actualizar(conn, instrumento_id)
    except OSError as e:
        print(f"No se pudo descargar: {e}")
        return
    print(f"Guardado: {precio} a {fecha:%d-%m-%Y}")


def poner_identificador(conn):
    mostrar_instrumentos(instrumentos.listar(conn))
    instrumento_id = pedir_entero("Id del instrumento: ")
    if instrumento_id is None:
        return
    instrumentos.asignar_identificador(conn, instrumento_id, input("Identificador: "))
    print("Guardado")


def poner_ticker_yahoo(conn):
    mostrar_instrumentos(instrumentos.listar(conn))
    instrumento_id = pedir_entero("Id del instrumento: ")
    if instrumento_id is None:
        return
    ticker = input("Ticker de Yahoo (vacío = quitar): ")
    instrumentos.asignar_ticker_yahoo(conn, instrumento_id, ticker)
    print("Guardado")


def consultar_todos(conn, vivos):
    res = actualizacion.consultar_todos(conn)
    vivos.clear()
    vivos.update(res["vivos"])
    ok = errores = omitidos = antiguos = 0
    for f in res["filas"]:
        if f["estado"] == "ok":
            ok += 1
            aviso = ""
            if f["antiguo"]:
                antiguos += 1
                aviso = "  <-- ANTIGUO"
            print(f"{f['nombre']}: {f['precio']} a {f['fecha']:%d-%m-%Y}{aviso}")
        elif f["estado"] == "error":
            errores += 1
            print(f"{f['nombre']}: no se pudo ({f['mensaje']})")
        else:
            omitidos += 1
            print(f"{f['nombre']}: se omite ({f['mensaje']})")
    for d in res["divisas"]:
        if d["estado"] == "ok":
            print(f"{d['divisa']}/EUR: {d['tasa']} a {d['fecha']:%d-%m-%Y}")
        else:
            print(f"{d['divisa']}/EUR: no se pudo ({d['mensaje']})")
    print(
        f"Resumen: {ok} actualizados ({antiguos} con precio antiguo), {errores} con error, "
        f"{omitidos} omitidos; {res['sin_posicion']} sin participaciones (no se tocan)"
    )


def _rango(f):
    if f["dias"] == 0:
        return "ya estaba al día"
    return f"{f['dias']} días nuevos ({f['desde']:%d-%m-%Y} a {f['hasta']:%d-%m-%Y})"


def descargar_historicos(conn):
    filas = actualizacion.descargar_historicos(conn)
    if not filas:
        print("No hay fondos, ETF, acciones o cripto con compras")
    for f in filas:
        if f["estado"] == "ok":
            print(f"{f['nombre']}: {_rango(f)}")
        else:
            print(f"{f['nombre']}: no se pudo ({f['mensaje']})")
    for f in actualizacion.descargar_historicos_divisas(conn):
        if f["estado"] == "ok":
            print(f"{f['divisa']}/EUR: {_rango(f)}")
        else:
            print(f"{f['divisa']}/EUR: no se pudo ({f['mensaje']})")


def listar_compras(conn):
    texto = input("Id de instrumento (vacío = todos): ").strip()
    mostrar_compras(compras.listar(conn, int(texto) if texto else None))


def borrar_con_id(conn, modulo):
    id_ = pedir_entero("Id a borrar: ")
    if id_ is not None:
        print("Borrado" if modulo.borrar(conn, id_) else "No existe ese id")


def main():
    conn = db.conectar(RUTA_DB)
    print(f"Base de datos: {RUTA_DB}")
    vivos = {}  # precios y tipos de cambio de este momento; solo en memoria, no van al histórico
    print("Consultando los precios de ahora...")
    consultar_todos(conn, vivos)
    acciones = {
        "1": lambda: anadir_instrumento(conn),
        "2": lambda: mostrar_instrumentos(instrumentos.listar(conn)),
        "3": lambda: mostrar_instrumentos(instrumentos.listar(conn, input("Tipo: ").strip())),
        "4": lambda: borrar_con_id(conn, instrumentos),
        "5": lambda: anadir_compra(conn),
        "6": lambda: listar_compras(conn),
        "7": lambda: borrar_con_id(conn, compras),
        "8": lambda: resumen_cartera(conn, vivos),
        "9": lambda: poner_precio(conn),
        "10": lambda: anadir_venta(conn),
        "11": lambda: listar_ventas(conn),
        "12": lambda: borrar_con_id(conn, ventas),
        "13": lambda: actualizar_plan(conn),
        "14": lambda: consultar_todos(conn, vivos),
        "15": lambda: poner_identificador(conn),
        "16": lambda: reparto_cartera(conn, vivos),
        "17": lambda: descargar_historicos(conn),
        "18": lambda: poner_ticker_yahoo(conn),
        "19": lambda: gestionar_grupos(conn),
    }
    while True:
        print(MENU)
        opcion = input("Opción: ").strip()
        if opcion == "0":
            break
        accion = acciones.get(opcion)
        if accion is None:
            print("Opción no válida")
            continue
        try:
            accion()
        except (sqlite3.IntegrityError, ValueError, TypeError) as e:
            # Errores esperados de datos inválidos; el menú sigue funcionando.
            print("Rechazado:", e)
    conn.close()


if __name__ == "__main__":    

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
        nombre="iShares Developed World Index Fund (IE) Class S",
        isin="IE000ZYRH0Q7",
        divisa="EUR",
        ruta=path_Laura,grupo="Inversiones Laura"
    )
    main()
