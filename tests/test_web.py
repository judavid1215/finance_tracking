from datetime import date

import pytest

from finanzas import compras, db, grupos, instrumentos, precios
from finanzas.web.app import crear_app


@pytest.fixture
def cliente(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    conn = db.conectar(str(ruta))
    a = instrumentos.anadir(conn, "Fondo A", "cripto", "EUR")
    b = instrumentos.anadir(conn, "Sin operaciones", "cripto", "EUR")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, a, date(2026, 1, 1), "2", "10")
    compras.anadir(conn, a, date(2026, 1, 1), "1", "10", grupo_id=pension)
    for dia, precio in ((1, "10"), (5, "11"), (10, "12")):
        precios.anadir(conn, a, date(2026, 1, dia), precio)
    assert b
    conn.close()
    return crear_app(ruta, hoy=lambda: date(2026, 1, 10)).test_client()


def test_pagina_y_estaticos(cliente):
    assert b"<canvas" in cliente.get("/").data
    assert cliente.get("/static/app.js").status_code == 200


def test_opciones_solo_instrumentos_con_operaciones(cliente):
    o = cliente.get("/api/opciones").get_json()
    assert [i["nombre"] for i in o["instrumentos"]] == ["Fondo A"]
    pension = next(g["id"] for g in o["grupos"] if g["nombre"] == "Pension")
    personal = next(g["id"] for g in o["grupos"] if g["nombre"] == "Personal")
    assert sorted(o["instrumentos"][0]["grupos"]) == sorted([pension, personal])
    assert {g["nombre"] for g in o["grupos"]} == {"Personal", "Pension"}
    assert o["periodos"] == ["1D", "1S", "1M", "1A", "YTD", "MAX"]


def test_evolucion_total_y_por_grupo(cliente):
    r = cliente.get("/api/evolucion?periodo=max").get_json()
    assert r["periodo"] == "MAX" and r["desde"] == "2026-01-01" and r["hasta"] == "2026-01-10"
    assert r["divisa"] == "EUR"
    assert r["resumen"]["valor"] == 36.0  # 3 participaciones a 12
    assert r["resumen"]["ganancia"] == 6.0
    assert [p["fecha"] for p in r["puntos"]] == ["2026-01-01", "2026-01-05", "2026-01-10"]
    grupo = cliente.get("/api/opciones").get_json()["grupos"][0]  # Pension (orden alfabético)
    r = cliente.get(f"/api/evolucion?periodo=MAX&grupo={grupo['id']}").get_json()
    assert r["resumen"]["valor"] == 12.0


def test_evolucion_incluye_las_compras(cliente):
    r = cliente.get("/api/evolucion?periodo=MAX").get_json()
    assert r["aportaciones"] == [
        {"fecha": "2026-01-01", "importe": 30.0, "instrumentos": ["Fondo A"]}
    ]
    assert cliente.get("/api/evolucion?periodo=1S").get_json()["aportaciones"] == []


def test_periodo_recorta_y_ganancia_es_del_periodo(cliente):
    r = cliente.get("/api/evolucion?periodo=1S").get_json()  # corte 3 ene: base = 1 ene
    assert r["desde"] == "2026-01-05"
    assert r["resumen"]["ganancia"] == 6.0


def test_sin_datos_y_errores(cliente):
    r = cliente.get("/api/evolucion?periodo=1S&instrumento=999").get_json()
    assert r["puntos"] == [] and r["resumen"] is None
    assert cliente.get("/api/evolucion?periodo=2D").status_code == 400
    assert cliente.get("/api/evolucion?grupo=abc").status_code == 400
    assert cliente.get("/api/evolucion?grupo=todos&instrumento=").status_code == 200


def test_operaciones_arbol(cliente):
    g = cliente.get("/api/operaciones").get_json()["grupos"]
    assert [x["nombre"] for x in g] == ["Pension", "Personal"]  # también los grupos vacíos
    personal = next(x for x in g if x["nombre"] == "Personal")
    (fondo,) = personal["instrumentos"]  # "Sin operaciones" no aparece
    assert (fondo["nombre"], fondo["divisa"], fondo["tipo"]) == ("Fondo A", "EUR", "Cripto")
    assert fondo["operaciones"] == [
        {"tipo": "compra", "id": 1, "fecha": "2026-01-01", "participaciones": 2, "precio": 10, "comision": 0, "importe": 20}
    ]


def test_aportacion(cliente):
    r = cliente.get("/api/aportacion/1").get_json()  # 2 participaciones a 10 el 1 ene
    assert (r["instrumento"], r["grupo"], r["divisa"], r["aportado"]) == ("Fondo A", "Personal", "EUR", 20)
    assert [(p["fecha"], p["valor"]) for p in r["puntos"]] == [
        ("2026-01-01", 20), ("2026-01-05", 22), ("2026-01-10", 24)
    ]
    assert r["resumen"] == {"valor": 24, "ganancia": 4, "rentabilidad": pytest.approx(0.2)}
    assert r["hermanas"] == [{"id": 1, "fecha": "2026-01-01", "importe": 20}]
    assert cliente.get("/api/aportacion/999").status_code == 404


def test_estado_sin_actualizaciones(cliente):
    assert cliente.get("/api/estado").get_json() == {"actualizado": None}


def test_estado_con_hora(tmp_path):
    app = crear_app(tmp_path / "t.sqlite3", actualizado=lambda: "2026-01-10T14:32:00+00:00")
    assert app.test_client().get("/api/estado").get_json() == {"actualizado": "2026-01-10T14:32:00+00:00"}


def _ids(cliente):
    arbol = cliente.get("/api/operaciones").get_json()["grupos"]
    personal = next(g for g in arbol if g["nombre"] == "Personal")
    return personal["id"], personal["instrumentos"][0]["id"]


def test_anadir_y_borrar_compra(cliente):
    grupo, inst = _ids(cliente)
    cuerpo = {"tipo": "compra", "instrumento": inst, "grupo": grupo, "fecha": "2026-01-08",
              "participaciones": "1,5", "precio": "11.5", "comision": "0.25"}
    r = cliente.post("/api/operaciones", json=cuerpo)
    assert r.status_code == 201
    nuevo = r.get_json()["id"]

    def ops():
        arbol = cliente.get("/api/operaciones").get_json()["grupos"]
        return next(g for g in arbol if g["id"] == grupo)["instrumentos"][0]["operaciones"]

    op = next(o for o in ops() if o["id"] == nuevo and o["tipo"] == "compra")
    assert op["participaciones"] == 1.5 and op["comision"] == 0.25
    assert cliente.delete(f"/api/operaciones/compra/{nuevo}").status_code == 204
    assert all(not (o["id"] == nuevo and o["tipo"] == "compra") for o in ops())
    assert cliente.delete(f"/api/operaciones/compra/{nuevo}").status_code == 404


def test_venta_y_errores_al_escribir(cliente):
    grupo, inst = _ids(cliente)
    base = {"tipo": "venta", "instrumento": inst, "grupo": grupo, "fecha": "2026-01-09", "precio": "12"}
    assert cliente.post("/api/operaciones", json={**base, "participaciones": "100"}).status_code == 422
    ok = cliente.post("/api/operaciones", json={**base, "participaciones": "1"})
    assert ok.status_code == 201
    assert cliente.post("/api/operaciones", json={**base, "tipo": "x"}).status_code == 400
    assert cliente.post("/api/operaciones", json={**base, "fecha": "hoy"}).status_code == 400
    assert cliente.post("/api/operaciones", json={**base, "participaciones": "-1"}).status_code == 422
    assert cliente.post("/api/operaciones", json={**base, "participaciones": "1", "instrumento": 999}).status_code == 422
    assert cliente.delete(f"/api/operaciones/venta/{ok.get_json()['id']}").status_code == 204


def test_borrar_compra_que_deja_venta_sin_cubrir(cliente):
    grupo, inst = _ids(cliente)
    v = {"tipo": "venta", "instrumento": inst, "grupo": grupo, "fecha": "2026-01-09",
         "participaciones": "2", "precio": "12"}
    assert cliente.post("/api/operaciones", json=v).status_code == 201
    compra = next(o for o in cliente.get("/api/operaciones").get_json()["grupos"]
                  if o["id"] == grupo)["instrumentos"][0]["operaciones"]
    id_compra = next(o["id"] for o in compra if o["tipo"] == "compra")
    assert cliente.delete(f"/api/operaciones/compra/{id_compra}").status_code == 422


def _ops(cliente, grupo):
    arbol = cliente.get("/api/operaciones").get_json()["grupos"]
    return next(g for g in arbol if g["id"] == grupo)["instrumentos"][0]["operaciones"]


def test_editar_compra(cliente):
    grupo, _ = _ids(cliente)
    compra = next(o for o in _ops(cliente, grupo) if o["tipo"] == "compra")
    cuerpo = {"fecha": "2026-01-02", "participaciones": "3,5", "precio": "9.5", "comision": "1"}
    assert cliente.put(f"/api/operaciones/compra/{compra['id']}", json=cuerpo).status_code == 204
    nueva = next(o for o in _ops(cliente, grupo) if o["tipo"] == "compra")
    assert (nueva["fecha"], nueva["participaciones"], nueva["precio"], nueva["comision"]) == (
        "2026-01-02", 3.5, 9.5, 1.0)
    assert cliente.put("/api/operaciones/compra/9999", json=cuerpo).status_code == 404
    assert cliente.put(f"/api/operaciones/compra/{compra['id']}", json={**cuerpo, "precio": "0"}).status_code == 422
    assert cliente.put(f"/api/operaciones/compra/{compra['id']}", json={**cuerpo, "fecha": "x"}).status_code == 400


def test_editar_que_deja_venta_sin_cubrir(cliente):
    grupo, inst = _ids(cliente)
    v = {"tipo": "venta", "instrumento": inst, "grupo": grupo, "fecha": "2026-01-09",
         "participaciones": "2", "precio": "12"}
    id_venta = cliente.post("/api/operaciones", json=v).get_json()["id"]
    compra = next(o for o in _ops(cliente, grupo) if o["tipo"] == "compra")
    # bajar la compra a 1 participación dejaría la venta de 2 sin cubrir
    r = cliente.put(f"/api/operaciones/compra/{compra['id']}",
                    json={"fecha": "2026-01-01", "participaciones": "1", "precio": "10"})
    assert r.status_code == 422
    assert next(o for o in _ops(cliente, grupo) if o["tipo"] == "compra")["participaciones"] == 2.0
    # y subir la venta por encima de lo comprado también se rechaza
    r = cliente.put(f"/api/operaciones/venta/{id_venta}",
                    json={"fecha": "2026-01-09", "participaciones": "5", "precio": "12"})
    assert r.status_code == 422
    ok = cliente.put(f"/api/operaciones/venta/{id_venta}",
                     json={"fecha": "2026-01-09", "participaciones": "1", "precio": "13"})
    assert ok.status_code == 204


CSV = (
    "Fecha de la orden;ISIN;Importe estimado;Nº de participaciones;Estado\n"
    "05/08/2026;IE00BYX5NX33;320 EUR;20;Finalizada\n"
    "04/06/2026;IE00BYX5NX33;100 EUR;10,5;Finalizada\n"
    "23/11/2026;IE00BYX5NX33;890 EUR;;En curso\n"
)


def _csv(texto=CSV, **campos):
    import io

    return {"archivo": (io.BytesIO(texto.encode("utf-8")), "ordenes.csv"), "grupo": "Pension", **campos}


def test_importar_csv_vista_previa_e_importacion(cliente):
    r = cliente.post("/api/importar/vista-previa", data=_csv())
    assert r.status_code == 200
    p = r.get_json()
    assert (p["isin"], p["divisa"], p["existente"], p["ya_importado"], p["ignoradas"]) == (
        "IE00BYX5NX33", "EUR", None, False, 1)
    assert [c["fecha"] for c in p["compras"]] == ["2026-06-04", "2026-08-05"]
    assert cliente.get("/api/operaciones").get_json()["grupos"][0]["instrumentos"][0]["nombre"] == "Fondo A"
    assert len(cliente.get("/api/operaciones").get_json()["grupos"][0]["instrumentos"]) == 1  # no guardó nada

    assert cliente.post("/api/importar", data=_csv()).status_code == 422  # falta el nombre
    ok = cliente.post("/api/importar", data=_csv(nombre="Fidelity", ticker_yahoo="abc.f"))
    assert ok.status_code == 201
    pension = next(g for g in cliente.get("/api/operaciones").get_json()["grupos"] if g["nombre"] == "Pension")
    nuevo = next(i for i in pension["instrumentos"] if i["nombre"] == "Fidelity")
    assert len(nuevo["operaciones"]) == 2
    # reimportar en el mismo grupo se rechaza; la vista previa lo avisa
    assert cliente.post("/api/importar/vista-previa", data=_csv()).get_json()["ya_importado"] is True
    assert cliente.post("/api/importar", data=_csv(nombre="Fidelity")).status_code == 422
    # en otro grupo, el instrumento ya existe y se reutiliza (el nombre enviado se ignora)
    otro = cliente.post("/api/importar", data=_csv(grupo="Nuevo", nombre="Otro"))
    assert otro.status_code == 201 and "Fidelity" in otro.get_json()["resumen"]


def test_importar_csv_errores(cliente):
    assert cliente.post("/api/importar/vista-previa", data={"grupo": "Pension"}).status_code == 400
    malo = CSV.replace("320 EUR", "320")
    assert cliente.post("/api/importar/vista-previa", data=_csv(malo)).status_code == 422
    mezcla = CSV.replace("04/06/2026;IE00BYX5NX33", "04/06/2026;IE000ZYRH0Q7")
    assert cliente.post("/api/importar/vista-previa", data=_csv(mezcla)).status_code == 422


def test_borrar_instrumento_entero(cliente):
    grupo, inst = _ids(cliente)
    assert cliente.delete(f"/api/instrumentos/{inst}").status_code == 204
    assert all(i["id"] != inst for g in cliente.get("/api/operaciones").get_json()["grupos"]
               for i in g["instrumentos"])
    assert cliente.delete(f"/api/instrumentos/{inst}").status_code == 404


def test_importar_csv_actualiza_precios_despues(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    db.conectar(str(ruta)).close()
    llamadas = []
    c = crear_app(ruta, tras_importar=lambda: llamadas.append(1)).test_client()
    assert c.post("/api/importar", data=_csv(nombre="X")).status_code == 201
    assert llamadas == [1]
    assert c.post("/api/importar", data=_csv(nombre="X")).status_code == 422  # ya importado
    assert llamadas == [1]  # si falla no se actualiza


def test_crear_y_borrar_grupo(cliente):
    r = cliente.post("/api/grupos", json={"nombre": "Nuevo"})
    assert r.status_code == 201
    nuevo = r.get_json()["id"]
    assert cliente.post("/api/grupos", json={"nombre": "Nuevo"}).status_code == 422
    assert cliente.post("/api/grupos", json={"nombre": "  "}).status_code == 422
    assert any(g["id"] == nuevo for g in cliente.get("/api/operaciones").get_json()["grupos"])
    grupo, _ = _ids(cliente)  # tiene operaciones: no se puede borrar
    assert cliente.delete(f"/api/grupos/{grupo}").status_code == 422
    assert cliente.delete(f"/api/grupos/{nuevo}").status_code == 204
    assert cliente.delete(f"/api/grupos/{nuevo}").status_code == 404


def test_borrar_grupo_con_operaciones(cliente):
    grupo, inst = _ids(cliente)
    assert cliente.delete(f"/api/grupos/{grupo}").status_code == 422
    assert cliente.delete(f"/api/grupos/{grupo}?con_operaciones=1").status_code == 204
    arbol = cliente.get("/api/operaciones").get_json()["grupos"]
    assert all(g["id"] != grupo for g in arbol)
    assert any(i["id"] == inst for g in arbol for i in g["instrumentos"])  # sigue en el otro grupo


def test_evolucion_indica_la_divisa_de_la_serie(tmp_path):
    ruta = tmp_path / "usd.sqlite3"
    conn = db.conectar(str(ruta))
    nvda = instrumentos.anadir(conn, "NVIDIA", "accion", "USD", "NVDA")
    ibe = instrumentos.anadir(conn, "Iberdrola", "accion", "EUR", "IBE")
    for i in (nvda, ibe):
        compras.anadir(conn, i, date(2026, 1, 1), "1", "10")
        precios.anadir(conn, i, date(2026, 1, 1), "10")
    conn.execute("INSERT INTO tipos_cambio VALUES ('USD', '2026-01-01', '0.5')")
    conn.commit()
    conn.close()
    c = crear_app(ruta, hoy=lambda: date(2026, 1, 10)).test_client()
    solo = c.get(f"/api/evolucion?periodo=MAX&instrumento={nvda}").get_json()
    assert solo["divisa"] == "USD" and solo["resumen"]["valor"] == 10.0  # sin convertir
    todos = c.get("/api/evolucion?periodo=MAX").get_json()
    assert todos["divisa"] == "EUR" and todos["resumen"]["valor"] == 15.0  # 10*0.5 + 10


def test_mover_instrumento_de_grupo(cliente):
    o = cliente.get("/api/opciones").get_json()
    fondo = o["instrumentos"][0]["id"]
    pension = next(g["id"] for g in o["grupos"] if g["nombre"] == "Pension")
    personal = next(g["id"] for g in o["grupos"] if g["nombre"] == "Personal")
    antes = cliente.get(f"/api/evolucion?periodo=MAX&grupo={personal}").get_json()
    r = cliente.post(
        f"/api/instrumentos/{fondo}/mover", json={"origen": pension, "destino": personal}
    )
    assert r.status_code == 200 and r.get_json()["movidas"] >= 1
    arbol = cliente.get("/api/operaciones").get_json()["grupos"]
    por_nombre = {g["nombre"]: g["instrumentos"] for g in arbol}
    assert por_nombre["Pension"] == [] and len(por_nombre["Personal"]) == 1
    despues = cliente.get(f"/api/evolucion?periodo=MAX&grupo={personal}").get_json()
    assert despues["resumen"]["valor"] > antes["resumen"]["valor"]  # ahora suma lo de Pension


def test_mover_instrumento_rechaza_peticiones_invalidas(cliente):
    o = cliente.get("/api/opciones").get_json()
    fondo = o["instrumentos"][0]["id"]
    personal = next(g["id"] for g in o["grupos"] if g["nombre"] == "Personal")
    assert cliente.post(f"/api/instrumentos/{fondo}/mover", json={}).status_code == 400
    mismo = {"origen": personal, "destino": personal}
    assert cliente.post(f"/api/instrumentos/{fondo}/mover", json=mismo).status_code == 422
    inexistente = {"origen": personal, "destino": 999}
    assert cliente.post(f"/api/instrumentos/{fondo}/mover", json=inexistente).status_code == 422


def _csv_ibkr():
    cab = (
        '"CurrencyPrimary","FXRateToBase","AssetClass","Symbol","Description","Conid","ISIN",'
        '"TradeID","DateTime","TradeDate","Quantity","TradeMoney","IBCommission",'
        '"IBCommissionCurrency","NetCash","OrigTradePrice","Buy/Sell","IBOrderID","TransactionID"'
    )
    filas = [
        '"USD","1","STK","NVDA","NVIDIA CORP","1","US67066G1040","1","20260102;093000",'
        '"20260102","2","200","-0.5","USD","-200.5","0","BUY","7","9"',
        '"USD","1","CASH","EUR.USD","EUR.USD","1","","2","20260102;093000","20260102",'
        '"-1","-1","0","EUR","0","0","SELL","8","10"',
    ]
    return "\n".join([cab, *filas]).encode()


def test_importar_csv_de_ibkr_por_la_web(cliente):
    import io

    def subir(url):
        datos = {"archivo": (io.BytesIO(_csv_ibkr()), "ibkr.csv"), "grupo": "Interactive Brokers"}
        return cliente.post(url, data=datos, content_type="multipart/form-data")

    r = subir("/api/importar/vista-previa")
    previa = r.get_json()
    assert r.status_code == 200 and previa["formato"] == "ibkr"
    assert previa["operaciones"] == [
        {
            "fecha": "2026-01-02",
            "simbolo": "NVDA",
            "lado": "BUY",
            "participaciones": 2.0,
            "precio": 100.0,
            "divisa": "USD",
        }
    ]
    assert previa["nuevos"] == ["NVIDIA CORP"] and previa["ignoradas"] == 1
    assert subir("/api/importar").status_code == 201
    grupo = next(
        g for g in cliente.get("/api/operaciones").get_json()["grupos"]
        if g["nombre"] == "Interactive Brokers"
    )
    assert [i["nombre"] for i in grupo["instrumentos"]] == ["NVIDIA CORP"]
    otra = subir("/api/importar/vista-previa").get_json()  # reimportar: ya no hay nada nuevo
    assert otra["operaciones"] == [] and otra["repetidas"] == 1
