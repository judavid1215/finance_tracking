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


def test_estado_sin_actualizaciones(cliente):
    assert cliente.get("/api/estado").get_json() == {"actualizado": None}


def test_estado_con_hora(tmp_path):
    app = crear_app(tmp_path / "t.sqlite3", actualizado=lambda: "2026-01-10T14:32:00+00:00")
    assert app.test_client().get("/api/estado").get_json() == {"actualizado": "2026-01-10T14:32:00+00:00"}
