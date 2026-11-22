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
    instrumentos,
    precios,
    quefondos,
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
13) Actualizar precio de un plan de pensiones (web)
15) Poner/cambiar identificador (ej. BTC-EUR a una cripto)
14) Actualizar precios de todo lo que se pueda (fondos, ETF, acciones y planes)
--- ---
0) Salir
"""


def mostrar_instrumentos(filas):
    if not filas:
        print("(vacío)")
    for f in filas:
        ident = f"{f['id_tipo']} {f['identificador']}" if f["identificador"] else "-"
        print(f"{f['id']:>3} | {f['nombre']:<25} | {f['tipo']:<15} | {f['divisa']} | {ident}")


def mostrar_compras(lista):
    if not lista:
        print("(vacío)")
    for c in lista:
        print(
            f"{c['id']:>3} | {c['instrumento']:<20} | {c['fecha']:%d-%m-%Y} | "
            f"{c['participaciones']} part. x {c['precio']} | comisión {c['comision']}"
        )


def mostrar_cartera(filas):
    if not filas:
        print("(vacío)")
    for f in filas:
        linea = (
            f"{f['instrumento']:<20} | {f['participaciones']} part. | "
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


def resumen_cartera(conn):
    mostrar_cartera(cartera.resumen(conn))
    mostrar_total(cartera.total(conn))


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
    id_ = compras.anadir(conn, instrumento_id, fecha, participaciones, precio, comision)
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
    id_ = ventas.anadir(conn, instrumento_id, fecha, participaciones, precio, comision)
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


def actualizar_todos(conn):
    res = actualizacion.actualizar_todos(conn)
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
    acciones = {
        "1": lambda: anadir_instrumento(conn),
        "2": lambda: mostrar_instrumentos(instrumentos.listar(conn)),
        "3": lambda: mostrar_instrumentos(instrumentos.listar(conn, input("Tipo: ").strip())),
        "4": lambda: borrar_con_id(conn, instrumentos),
        "5": lambda: anadir_compra(conn),
        "6": lambda: listar_compras(conn),
        "7": lambda: borrar_con_id(conn, compras),
        "8": lambda: resumen_cartera(conn),
        "9": lambda: poner_precio(conn),
        "10": lambda: anadir_venta(conn),
        "11": lambda: listar_ventas(conn),
        "12": lambda: borrar_con_id(conn, ventas),
        "13": lambda: actualizar_plan(conn),
        "14": lambda: actualizar_todos(conn),
        "15": lambda: poner_identificador(conn),
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
    main()
