from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finanzas import compras, db, evolucion, instrumentos, periodos, precios, ventas
from finanzas.web.app import crear_app


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def tick(conn, id_, momento, precio):
    conn.execute(
        "INSERT INTO precios_mercado (instrumento_id, momento, precio) VALUES (?,?,?)",
        (id_, momento, precio),
    )
    conn.commit()


def test_sin_ticks_no_hay_serie(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    compras.anadir(conn, id_, date(2026, 11, 1), "1", "100")
    assert evolucion.serie_intradia(conn) == []


def test_serie_del_dia_con_base_al_empezar_la_ventana(conn):
    btc = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    compras.anadir(conn, btc, date(2026, 11, 1), "2", "100")
    tick(conn, btc, "2026-11-24T08:00:00Z", "100")  # fuera de la ventana de 24 h
    tick(conn, btc, "2026-11-25T10:00:00Z", "110")  # justo dentro
    tick(conn, btc, "2026-11-26T09:00:00Z", "120")
    filas = evolucion.serie_intradia(conn)
    # base (inicio de la ventana: 25-11 09:00, vale el último tick anterior) + 2 instantes
    assert [f["fecha"] for f in filas] == [
        datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
        datetime(2026, 11, 25, 10, 0, tzinfo=UTC),
        datetime(2026, 11, 26, 9, 0, tzinfo=UTC),
    ]
    assert [f["valor"] for f in filas] == [Decimal(200), Decimal(220), Decimal(240)]
    assert all(f["invertido"] == Decimal(200) for f in filas)
    r = periodos.recortar_dia(filas)
    assert [p["ganancia"] for p in r["puntos"]] == [Decimal(20), Decimal(40)]  # del día
    assert r["resumen"]["valor"] == Decimal(240)
    assert r["aportaciones"] == []


def test_los_fondos_valen_su_precio_diario_y_las_acciones_su_tick(conn):
    btc = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    fondo = instrumentos.anadir(conn, "Fondo", "fondo", "EUR", "LU0996175948")
    for i in (btc, fondo):
        compras.anadir(conn, i, date(2026, 11, 1), "1", "100")
    precios.anadir(conn, fondo, date(2026, 11, 25), "50")
    tick(conn, btc, "2026-11-26T09:00:00Z", "110")
    tick(conn, btc, "2026-11-26T09:02:00Z", "112")
    filas = evolucion.serie_intradia(conn)
    assert [f["valor"] for f in filas][-2:] == [Decimal(160), Decimal(162)]


def test_filtra_por_instrumento_y_respeta_las_ventas(conn):
    a = instrumentos.anadir(conn, "A", "cripto", "EUR", "A-EUR")
    b = instrumentos.anadir(conn, "B", "cripto", "EUR", "B-EUR")
    compras.anadir(conn, a, date(2026, 11, 1), "2", "10")
    compras.anadir(conn, b, date(2026, 11, 1), "1", "10")
    ventas.anadir(conn, a, date(2026, 11, 26), "2", "10")  # vende todo hoy
    tick(conn, a, "2026-11-26T09:00:00Z", "10")
    tick(conn, b, "2026-11-26T09:00:00Z", "30")
    solo_b = evolucion.serie_intradia(conn, instrumento_id=b)
    assert solo_b[-1]["valor"] == Decimal(30)
    todo = evolucion.serie_intradia(conn)
    assert todo[-1]["valor"] == Decimal(30)  # lo de A ya está vendido


def test_usd_se_convierte_al_cambio_del_dia(conn):
    nvda = instrumentos.anadir(conn, "NVIDIA", "accion", "USD", "NVDA")
    compras.anadir(conn, nvda, date(2026, 11, 1), "1", "100")
    conn.execute("INSERT INTO tipos_cambio (divisa, fecha, tasa) VALUES ('USD','2026-11-25','0.8')")
    conn.commit()
    tick(conn, nvda, "2026-11-26T15:00:00Z", "150")
    assert evolucion.serie_intradia(conn)[-1]["valor"] == Decimal("120.0")


@pytest.fixture
def cliente(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    c = db.conectar(str(ruta))
    btc = instrumentos.anadir(c, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    compras.anadir(c, btc, date(2026, 11, 1), "2", "100")
    tick(c, btc, "2026-11-26T09:00:00Z", "110")
    tick(c, btc, "2026-11-26T09:02:00Z", "120")
    c.close()
    return crear_app(ruta, hoy=lambda: date(2026, 11, 26)).test_client(), btc


def test_api_periodo_dia(cliente):
    http, btc = cliente
    r = http.get(f"/api/evolucion?periodo=1D&instrumento={btc}").get_json()
    assert r["periodo"] == "1D"
    assert [p["valor"] for p in r["puntos"]] == [220, 240]
    assert r["puntos"][0]["fecha"].startswith("2026-11-26T09:00:00")
    assert r["precio"]["valor"] == 120 and r["precio"]["fecha"] == "2026-11-26T09:02:00Z"
    assert r["aportaciones"] == []


def test_api_dia_sin_ticks_viene_vacio(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    c = db.conectar(str(ruta))
    f = instrumentos.anadir(c, "Fondo", "fondo", "EUR", "LU0996175948")
    compras.anadir(c, f, date(2026, 11, 1), "1", "10")
    c.close()
    http = crear_app(ruta, hoy=lambda: date(2026, 11, 26)).test_client()
    r = http.get("/api/evolucion?periodo=1D").get_json()
    assert r["puntos"] == [] and r["resumen"] is None and r["precio"] is None
