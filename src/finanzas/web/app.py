"""API y página web de solo lectura.

- GET /                 la página (static/index.html)
- GET /api/opciones     grupos e instrumentos con operaciones (y en qué grupos), para los selectores
- GET /api/estado       cuándo se actualizaron los precios por última vez (ISO UTC o null)
- GET /api/evolucion    ?periodo=1S|1M|1A|YTD|MAX &grupo=<id> &instrumento=<id>
                        (incluye las compras del periodo, para marcarlas en el gráfico)
- GET /api/operaciones  grupos > instrumentos > operaciones (compras y ventas, con su id), para la pestaña Operaciones
- GET /api/aportacion/<id>  evolución de una compra concreta, en la divisa del instrumento

Las cantidades salen como números normales (float): son solo para dibujar el gráfico; los
cálculos siguen haciéndose en Decimal.
"""

from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, request

from finanzas import aportacion, compras, db, evolucion, periodos, ventas


def _num(x):
    return None if x is None else float(x)


def _entero(nombre: str) -> int | None:
    valor = request.args.get(nombre)
    if valor in (None, "", "todos"):
        return None
    try:
        return int(valor)
    except ValueError:
        abort(400, f"'{nombre}' debe ser un número")


def crear_app(ruta_db: str | Path, hoy=date.today, actualizado=lambda: None) -> Flask:
    """`hoy` es una función (para poder fijar la fecha en los tests). `actualizado` devuelve
    cuándo se actualizaron los precios por última vez (texto ISO en UTC) o None si no se sabe."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    def abrir():
        return db.conectar(str(ruta_db))

    @app.get("/")
    def pagina():
        return app.send_static_file("index.html")

    @app.get("/api/estado")
    def estado():
        return jsonify({"actualizado": actualizado()})

    @app.get("/api/opciones")
    def opciones():
        conn = abrir()
        try:
            grupos = [
                {"id": r["id"], "nombre": r["nombre"]}
                for r in conn.execute("SELECT id, nombre FROM grupos ORDER BY nombre")
            ]
            en_grupos: dict[int, list[int]] = {}
            for inst_id, g in conn.execute(
                "SELECT instrumento_id, grupo_id FROM compras UNION "
                "SELECT instrumento_id, grupo_id FROM ventas ORDER BY 1, 2"
            ):
                en_grupos.setdefault(inst_id, []).append(g)
            instr = [
                {
                    "id": r["id"],
                    "nombre": r["nombre"],
                    "tipo": r["tipo"],
                    "grupos": en_grupos[r["id"]],
                }
                for r in conn.execute("SELECT id, nombre, tipo FROM instrumentos ORDER BY nombre")
                if r["id"] in en_grupos
            ]
        finally:
            conn.close()
        return jsonify({"grupos": grupos, "instrumentos": instr, "periodos": periodos.PERIODOS})

    @app.get("/api/evolucion")
    def datos():
        periodo = request.args.get("periodo", "1M")
        try:
            periodos.inicio(periodo, hoy())  # solo para validar el nombre
        except ValueError as e:
            abort(400, str(e))
        conn = abrir()
        try:
            try:
                grupo, instrumento = _entero("grupo"), _entero("instrumento")
                filas = evolucion.serie(conn, grupo, instrumento)
                compras = evolucion.aportaciones(conn, grupo, instrumento)
            except ValueError as e:  # p. ej. falta el tipo de cambio de una divisa
                abort(422, str(e))
        finally:
            conn.close()
        r = periodos.recortar(filas, periodo, hoy(), compras)
        resumen = r["resumen"]
        return jsonify(
            {
                "periodo": periodo.upper(),
                "desde": r["desde"] and r["desde"].isoformat(),
                "hasta": r["hasta"] and r["hasta"].isoformat(),
                "resumen": resumen and {k: _num(v) for k, v in resumen.items()},
                "puntos": [
                    {
                        "fecha": p["fecha"].isoformat(),
                        "valor": _num(p["valor"]),
                        "invertido": _num(p["invertido"]),
                        "ganancia": _num(p["ganancia"]),
                        "rentabilidad": _num(p["rentabilidad"]),
                    }
                    for p in r["puntos"]
                ],
                "aportaciones": [
                    {
                        "fecha": a["fecha"].isoformat(),
                        "importe": _num(a["importe"]),
                        "instrumentos": a["instrumentos"],
                    }
                    for a in r["aportaciones"]
                ],
            }
        )

    @app.get("/api/operaciones")
    def operaciones():
        conn = abrir()
        try:
            divisas = {r["id"]: r["divisa"] for r in conn.execute("SELECT id, divisa FROM instrumentos")}
            arbol = {r["id"]: {"id": r["id"], "nombre": r["nombre"], "instrumentos": {}}
                     for r in conn.execute("SELECT id, nombre FROM grupos ORDER BY nombre")}
            for tipo, filas in (("compra", compras.listar(conn)), ("venta", ventas.listar(conn))):
                for o in filas:
                    instr = arbol[o["grupo_id"]]["instrumentos"].setdefault(
                        o["instrumento_id"],
                        {"id": o["instrumento_id"], "nombre": o["instrumento"],
                         "divisa": divisas[o["instrumento_id"]], "operaciones": []},
                    )
                    instr["operaciones"].append(
                        {
                            "tipo": tipo,
                            "id": o["id"],
                            "fecha": o["fecha"].isoformat(),
                            "participaciones": _num(o["participaciones"]),
                            "precio": _num(o["precio"]),
                            "comision": _num(o["comision"]),
                            # compra: lo aportado (con comisión); venta: lo cobrado (menos comisión)
                            "importe": _num(
                                o["participaciones"] * o["precio"]
                                + (o["comision"] if tipo == "compra" else -o["comision"])
                            ),
                        }
                    )
        finally:
            conn.close()
        grupos_ = []
        for g in arbol.values():
            instrumentos = sorted(g["instrumentos"].values(), key=lambda x: x["nombre"].lower())
            for x in instrumentos:  # más recientes primero
                x["operaciones"].sort(key=lambda o: (o["fecha"], o["id"]), reverse=True)
            grupos_.append({"id": g["id"], "nombre": g["nombre"], "instrumentos": instrumentos})
        return jsonify({"grupos": grupos_})

    @app.get("/api/aportacion/<int:compra_id>")
    def datos_aportacion(compra_id):
        conn = abrir()
        try:
            a = aportacion.serie(conn, compra_id)
        finally:
            conn.close()
        if a is None:
            abort(404, "No existe esa compra")
        ultimo = a["puntos"][-1]
        return jsonify(
            {
                "instrumento": a["instrumento"],
                "grupo": a["grupo"],
                "divisa": a["divisa"],
                "fecha": a["fecha"].isoformat(),
                "participaciones": _num(a["participaciones"]),
                "precio": _num(a["precio"]),
                "comision": _num(a["comision"]),
                "aportado": _num(a["aportado"]),
                "resumen": {k: _num(ultimo[k]) for k in ("valor", "ganancia", "rentabilidad")},
                "hermanas": [
                    {"id": h["id"], "fecha": h["fecha"].isoformat(), "importe": _num(h["importe"])}
                    for h in a["hermanas"]
                ],
                "puntos": [
                    {k: p[k].isoformat() if k == "fecha" else _num(p[k]) for k in p}
                    for p in a["puntos"]
                ],
            }
        )

    return app
