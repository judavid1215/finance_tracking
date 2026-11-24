"""API y página web de solo lectura.

- GET /                 la página (static/index.html)
- GET /api/opciones     grupos e instrumentos con operaciones (y en qué grupos), para los selectores
- GET /api/evolucion    ?periodo=1S|1M|1A|YTD|MAX &grupo=<id> &instrumento=<id>
                        (incluye las compras del periodo, para marcarlas en el gráfico)

Las cantidades salen como números normales (float): son solo para dibujar el gráfico; los
cálculos siguen haciéndose en Decimal.
"""

from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, request

from finanzas import db, evolucion, periodos


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


def crear_app(ruta_db: str | Path, hoy=date.today) -> Flask:
    """`hoy` es una función (para poder fijar la fecha en los tests)."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    def abrir():
        return db.conectar(str(ruta_db))

    @app.get("/")
    def pagina():
        return app.send_static_file("index.html")

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

    return app
