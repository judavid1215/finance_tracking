"""API y página web de solo lectura.

- GET /                 la página (static/index.html)
- GET /api/opciones     grupos e instrumentos con operaciones (y en qué grupos), para los selectores
- GET /api/estado       cuándo se actualizaron los precios por última vez (ISO UTC o null)
- GET /api/evolucion    ?periodo=1D|1S|1M|1A|YTD|MAX &grupo=<id> &instrumento=<id>
                        (incluye las compras del periodo, para marcarlas en el gráfico; todo va en la divisa
                        de "divisa": la del instrumento si todos los elegidos comparten una, si no EUR)
- GET /api/operaciones  grupos > instrumentos (con su tipo) > operaciones (compras y ventas, con su id), para la pestaña Operaciones
- POST /api/operaciones  añade una compra o venta; DELETE /api/operaciones/<tipo>/<id> la borra
  PUT /api/operaciones/<tipo>/<id>  edita fecha, participaciones, precio y comisión
- POST /api/grupos  (JSON: nombre) crea un grupo; DELETE /api/grupos/<id> lo borra si está vacío (con ?con_operaciones=1, también sus operaciones)
- DELETE /api/instrumentos/<id>  borra el instrumento con todas sus operaciones y precios
- POST /api/instrumentos/<id>/mover  (JSON: origen, destino = ids de grupo) pasa todas sus operaciones
  del grupo de origen al de destino (si el destino ya lo tiene, se suman)
- POST /api/importar/vista-previa  (multipart: archivo, grupo) lee un CSV sin guardar: de órdenes de
  MyInvestor (un fondo) o de Flex Query de Interactive Brokers (acciones, formato "ibkr")
  POST /api/importar  (multipart: archivo, grupo, nombre, ticker_yahoo) lo importa al grupo
- GET /api/aportacion/<id>  evolución de una compra concreta, en la divisa del instrumento

Las cantidades salen como números normales (float): son solo para dibujar el gráfico; los
cálculos siguen haciéndose en Decimal.
"""

import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from flask import Flask, abort, jsonify, request

from finanzas import (
    aportacion,
    compras,
    db,
    evolucion,
    grupos as grupos_,
    importacion,
    importacion_ibkr,
    instrumentos,
    mercado,
    periodos,
    ventas,
)


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


def crear_app(
    ruta_db: str | Path, hoy=date.today, actualizado=lambda: None, tras_importar=lambda: None
) -> Flask:
    """`hoy` es una función (para poder fijar la fecha en los tests). `actualizado` devuelve
    cuándo se actualizaron los precios por última vez (texto ISO en UTC) o None si no se sabe.
    `tras_importar` se llama después de importar un CSV (sin argumentos, ya con los datos
    guardados): el servidor lo usa para bajar enseguida el histórico y los precios del fondo."""
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
        intradia = periodo.upper() == periodos.INTRADIA
        conn = abrir()
        try:
            try:
                grupo, instrumento = _entero("grupo"), _entero("instrumento")
                divisa = evolucion.moneda(conn, grupo, instrumento)
                if intradia:
                    filas = evolucion.serie_intradia(conn, grupo, instrumento)
                    compras = []
                else:
                    filas = evolucion.serie(conn, grupo, instrumento)
                    compras = evolucion.aportaciones(conn, grupo, instrumento)
            except ValueError as e:  # p. ej. falta el tipo de cambio de una divisa
                abort(422, str(e))
        finally:
            conn.close()
        if intradia:
            r = periodos.recortar_dia(filas)
        else:
            r = periodos.recortar(filas, periodo, hoy(), compras)
        resumen = r["resumen"]
        # Con un instrumento concreto: su último precio (para compararlo con el banco).
        precio = None
        if instrumento is not None and r["hasta"]:
            conn = abrir()
            try:
                if intradia:  # el último tick (con su hora), no el cierre diario
                    f = conn.execute(
                        "SELECT p.momento, p.precio, i.divisa FROM precios_mercado p "
                        "JOIN instrumentos i ON i.id = p.instrumento_id "
                        "WHERE p.instrumento_id = ? AND p.momento <= ? "
                        "ORDER BY p.momento DESC LIMIT 1",
                        (instrumento, mercado.formatear(r["hasta"])),
                    ).fetchone()
                else:
                    f = conn.execute(
                        "SELECT p.fecha, p.precio, i.divisa FROM precios p "
                        "JOIN instrumentos i ON i.id = p.instrumento_id "
                        "WHERE p.instrumento_id = ? AND p.fecha <= ? ORDER BY p.fecha DESC LIMIT 1",
                        (instrumento, r["hasta"].isoformat()),
                    ).fetchone()
            finally:
                conn.close()
            if f:
                precio = {"fecha": f[0], "valor": float(f[1]), "divisa": f[2]}
        return jsonify(
            {
                "precio": precio,
                "periodo": periodo.upper(),
                "divisa": divisa,
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
            info = {r["id"]: r for r in conn.execute("SELECT id, divisa, tipo FROM instrumentos")}
            arbol = {r["id"]: {"id": r["id"], "nombre": r["nombre"], "instrumentos": {}}
                     for r in conn.execute("SELECT id, nombre FROM grupos ORDER BY nombre")}
            for tipo, filas in (("compra", compras.listar(conn)), ("venta", ventas.listar(conn))):
                for o in filas:
                    instr = arbol[o["grupo_id"]]["instrumentos"].setdefault(
                        o["instrumento_id"],
                        {"id": o["instrumento_id"], "nombre": o["instrumento"],
                         "divisa": info[o["instrumento_id"]]["divisa"],
                         "tipo": info[o["instrumento_id"]]["tipo"], "operaciones": []},
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

    @app.post("/api/operaciones")
    def crear_operacion():
        """JSON: tipo (compra|venta), instrumento, grupo, fecha (AAAA-MM-DD), participaciones,
        precio, comision (opcional). Los números van como texto para no perder precisión."""
        d = request.get_json(silent=True) or {}
        modulo = {"compra": compras, "venta": ventas}.get(d.get("tipo"))
        if modulo is None:
            abort(400, "tipo debe ser 'compra' o 'venta'")
        try:
            fecha = date.fromisoformat(str(d.get("fecha")))
            instrumento, grupo = int(d.get("instrumento")), int(d.get("grupo"))
        except (ValueError, TypeError):
            abort(400, "fecha, instrumento o grupo no válidos")
        conn = abrir()
        try:
            try:
                id_ = modulo.anadir(
                    conn, instrumento, fecha, d.get("participaciones"), d.get("precio"),
                    d.get("comision") or 0, grupo_id=grupo,
                )
            except (ValueError, TypeError) as e:
                abort(422, str(e))
            except sqlite3.IntegrityError:
                abort(422, "El instrumento o el grupo no existen")
        finally:
            conn.close()
        return jsonify({"id": id_}), 201

    @app.put("/api/operaciones/<tipo>/<int:op_id>")
    def editar_operacion(tipo, op_id):
        """JSON: fecha, participaciones, precio, comision. El instrumento y el grupo no cambian."""
        modulo = {"compra": compras, "venta": ventas}.get(tipo)
        if modulo is None:
            abort(404, "tipo desconocido")
        d = request.get_json(silent=True) or {}
        try:
            fecha = date.fromisoformat(str(d.get("fecha")))
        except ValueError:
            abort(400, "fecha no válida")
        conn = abrir()
        try:
            try:
                existia = modulo.editar(
                    conn, op_id, fecha, d.get("participaciones"), d.get("precio"),
                    d.get("comision") or 0,
                )
            except (ValueError, TypeError) as e:  # datos no válidos o ventas que quedarían sin cubrir
                abort(422, str(e))
        finally:
            conn.close()
        if not existia:
            abort(404, "No existe esa operación")
        return "", 204

    @app.delete("/api/operaciones/<tipo>/<int:op_id>")
    def borrar_operacion(tipo, op_id):
        modulo = {"compra": compras, "venta": ventas}.get(tipo)
        if modulo is None:
            abort(404, "tipo desconocido")
        conn = abrir()
        try:
            try:
                existia = modulo.borrar(conn, op_id)
            except ValueError as e:  # borrar la compra dejaría ventas sin cubrir
                abort(422, str(e))
        finally:
            conn.close()
        if not existia:
            abort(404, "No existe esa operación")
        return "", 204

    def _csv_subido():
        """El fichero CSV subido en el formulario (400 si no viene)."""
        archivo = request.files.get("archivo")
        if archivo is None or not archivo.filename:
            abort(400, "falta el fichero CSV")
        return archivo

    @app.post("/api/importar/vista-previa")
    def importar_vista_previa():
        archivo, grupo = _csv_subido(), request.form.get("grupo", "")
        conn = abrir()
        try:
            with tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / "ordenes.csv"
                archivo.save(ruta)
                try:
                    if importacion_ibkr.es_flex_query(ruta):
                        plan = importacion_ibkr.preparar(conn, ruta, grupo)
                        return jsonify(importacion_ibkr.a_json(plan))
                    p = importacion.previsualizar(conn, ruta, grupo)
                except (ValueError, UnicodeDecodeError) as e:
                    abort(422, str(e))
        finally:
            conn.close()
        return jsonify(
            {
                "isin": p["isin"],
                "divisa": p["divisa"],
                "existente": p["existente"],
                "ya_importado": p["ya_importado"],
                "ignoradas": p["ignoradas"],
                "invertido": _num(p["invertido"]),
                "compras": [
                    {"fecha": f.isoformat(), "participaciones": _num(n), "precio": _num(pr)}
                    for f, n, pr in p["compras"]
                ],
            }
        )

    @app.post("/api/importar")
    def importar_csv():
        archivo, grupo = _csv_subido(), request.form.get("grupo", "")
        nombre = request.form.get("nombre", "")
        conn = abrir()
        try:
            with tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / "ordenes.csv"
                archivo.save(ruta)
                try:
                    if importacion_ibkr.es_flex_query(ruta):  # acciones de Interactive Brokers
                        plan = importacion_ibkr.preparar(conn, ruta, grupo)
                        importacion_ibkr.aplicar(conn, plan)
                        resumen = importacion_ibkr.resumen(plan)
                    else:
                        p = importacion.previsualizar(conn, ruta, grupo)  # ISIN y divisa, del fichero
                        plan = importacion.importar(
                            conn, ruta, p["isin"], p["existente"] or nombre, p["divisa"],
                            request.form.get("ticker_yahoo"), grupo,
                        )
                        resumen = importacion.resumen(plan)
                except (ValueError, UnicodeDecodeError) as e:  # incluye FondoYaImportado
                    abort(422, str(e))
        finally:
            conn.close()
        tras_importar()  # sin precios no se puede dibujar nada: se bajan ya
        return jsonify({"resumen": resumen}), 201

    @app.post("/api/grupos")
    def crear_grupo():
        d = request.get_json(silent=True) or {}
        conn = abrir()
        try:
            try:
                id_ = grupos_.anadir(conn, str(d.get("nombre") or ""))
            except ValueError as e:  # nombre vacío o repetido
                abort(422, str(e))
        finally:
            conn.close()
        return jsonify({"id": id_}), 201

    @app.delete("/api/grupos/<int:grupo_id>")
    def borrar_grupo(grupo_id):
        conn = abrir()
        try:
            try:
                if request.args.get("con_operaciones") == "1":
                    existia = grupos_.borrar_con_operaciones(conn, grupo_id)
                else:
                    existia = grupos_.borrar(conn, grupo_id)
            except ValueError as e:  # todavía tiene compras o ventas
                abort(422, str(e))
        finally:
            conn.close()
        if not existia:
            abort(404, "No existe ese grupo")
        return "", 204

    @app.delete("/api/instrumentos/<int:instrumento_id>")
    def borrar_instrumento(instrumento_id):
        conn = abrir()
        try:
            existia = instrumentos.borrar_con_operaciones(conn, instrumento_id)
        finally:
            conn.close()
        if not existia:
            abort(404, "No existe ese instrumento")
        return "", 204

    @app.post("/api/instrumentos/<int:instrumento_id>/mover")
    def mover_instrumento(instrumento_id):
        d = request.get_json(silent=True) or {}
        try:
            origen, destino = int(d["origen"]), int(d["destino"])
        except (KeyError, TypeError, ValueError):
            abort(400, "faltan los grupos de origen y destino")
        conn = abrir()
        try:
            try:
                movidas = grupos_.mover_instrumento(conn, instrumento_id, origen, destino)
            except ValueError as e:  # mismo grupo, destino inexistente o nada que mover
                abort(422, str(e))
        finally:
            conn.close()
        return jsonify({"movidas": movidas})

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
