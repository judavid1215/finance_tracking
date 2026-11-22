from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, instrumentos


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def test_sin_compras(conn):
    assert cartera.resumen(conn) == []


def test_suma_y_precio_medio(conn):
    btc = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    compras.anadir(conn, btc, date(2026, 1, 1), "2", "100")
    compras.anadir(conn, btc, date(2026, 2, 1), "1", "400")
    [fila] = cartera.resumen(conn)
    assert fila["instrumento"] == "Bitcoin"
    assert fila["participaciones"] == Decimal("3")
    assert fila["invertido"] == Decimal("600")
    assert fila["precio_medio"] == Decimal("200")


def test_decimales_exactos(conn):
    btc = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    for _ in range(10):
        compras.anadir(conn, btc, date(2026, 1, 1), "0.1", "0.1")
    [fila] = cartera.resumen(conn)
    assert fila["participaciones"] == Decimal("1.0")
    assert fila["invertido"] == Decimal("0.10")


def test_varios_instrumentos_ordenados(conn):
    b = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    a = instrumentos.anadir(conn, "Apple", "accion", "USD", "AAPL")
    compras.anadir(conn, b, date(2026, 1, 1), "1", "10")
    compras.anadir(conn, a, date(2026, 1, 1), "1", "20")
    assert [f["instrumento"] for f in cartera.resumen(conn)] == ["Apple", "Bitcoin"]
