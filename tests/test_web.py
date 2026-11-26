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
    assert o["periodos"] == ["1S", "1M", "1A", "YTD", "MAX"]


def test_evolucion_total_y_por_grupo(cliente):
    r = cliente.get("/api/evolucion?periodo=max").get_json()
    assert r["periodo"] == "MAX" and r["desde"] == "2026-01-01" and r["hasta"] == "2026-01-10"
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
    assert (fondo["nombre"], fondo["divisa"]) == ("Fondo A", "EUR")
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
