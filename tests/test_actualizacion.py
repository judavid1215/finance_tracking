from datetime import date
from decimal import Decimal

import pytest

from finanzas import actualizacion, compras, db, instrumentos, precios, quefondos, ventas, yahoo

HOY = date(2026, 11, 22)


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def comprar(conn, nombre, tipo, ident=None, divisa="EUR"):
    id_ = instrumentos.anadir(conn, nombre, tipo, divisa, ident)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    return id_


def falso_yahoo(monkeypatch, fecha=date(2026, 11, 20), fallar=()):
    def actualizar(conn, id_):
        if id_ in fallar:
            raise ValueError("Yahoo no tiene precio")
        precios.anadir(conn, id_, fecha, "12")
        return fecha, Decimal("12")

    monkeypatch.setattr(yahoo, "actualizar", actualizar)


def test_actualiza_y_resume(conn, monkeypatch):
    falso_yahoo(monkeypatch)
    etf = comprar(conn, "ETF", "etf", "IE00BYX5NX33")
    res = actualizacion.actualizar_todos(conn, HOY)
    assert res["sin_posicion"] == 0
    [fila] = res["filas"]
    assert fila["estado"] == "ok" and fila["precio"] == Decimal("12")
    assert fila["antiguo"] is False
    assert precios.ultimo(conn, etf) == Decimal("12")


def test_ignora_instrumentos_sin_posicion(conn, monkeypatch):
    falso_yahoo(monkeypatch)
    comprar(conn, "Tengo", "etf", "IE00BYX5NX33")
    vendido = comprar(conn, "Vendido", "etf", "IE00B4L5Y983")
    ventas.anadir(conn, vendido, date(2026, 2, 1), "1", "11")
    instrumentos.anadir(conn, "Nunca comprado", "etf", "EUR", "IE00B3RBWM25")
    res = actualizacion.actualizar_todos(conn, HOY)
    assert [f["nombre"] for f in res["filas"]] == ["Tengo"]
    assert res["sin_posicion"] == 2
    assert precios.ultimo(conn, vendido) is None


def test_precio_antiguo(conn, monkeypatch):
    falso_yahoo(monkeypatch, fecha=date(2026, 11, 10))
    comprar(conn, "ETF", "etf", "IE00BYX5NX33")
    [fila] = actualizacion.actualizar_todos(conn, HOY)["filas"]
    assert fila["estado"] == "ok" and fila["antiguo"] is True


def test_limite_de_antiguedad(conn, monkeypatch):
    falso_yahoo(monkeypatch, fecha=date(2026, 11, 17))  # 5 días: aún vale
    comprar(conn, "ETF", "etf", "IE00BYX5NX33")
    [fila] = actualizacion.actualizar_todos(conn, HOY)["filas"]
    assert fila["antiguo"] is False


def test_error_no_corta_el_resto(conn, monkeypatch):
    mal = comprar(conn, "A mal", "etf", "IE00BYX5NX33")
    comprar(conn, "B bien", "etf", "IE00B4L5Y983")
    falso_yahoo(monkeypatch, fallar={mal})
    a, b = actualizacion.actualizar_todos(conn, HOY)["filas"]
    assert a["estado"] == "error" and "Yahoo" in a["mensaje"]
    assert b["estado"] == "ok"


def test_error_de_red(conn, monkeypatch):
    def caer(conn, id_):
        raise OSError("sin conexión")

    monkeypatch.setattr(quefondos, "actualizar", caer)
    comprar(conn, "Plan", "plan_pensiones", "N5396")
    [fila] = actualizacion.actualizar_todos(conn, HOY)["filas"]
    assert fila["estado"] == "error" and "sin conexión" in fila["mensaje"]


def test_cripto_sin_ticker_se_omite(conn, monkeypatch):
    falso_yahoo(monkeypatch)
    comprar(conn, "Bitcoin", "cripto")
    [fila] = actualizacion.actualizar_todos(conn, HOY)["filas"]
    assert fila["estado"] == "omitido"
