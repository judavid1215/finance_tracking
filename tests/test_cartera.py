from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, grupos, instrumentos


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


def _comprar_valorado(conn, nombre, tipo, divisa, ident, precio):
    from finanzas import precios

    id_ = instrumentos.anadir(conn, nombre, tipo, divisa, ident)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    precios.anadir(conn, id_, date(2026, 11, 20), precio)
    return id_


def test_reparto_por_instrumento_y_tipo(conn):
    from finanzas import divisas

    _comprar_valorado(conn, "Bitcoin", "cripto", "EUR", None, "30")
    _comprar_valorado(conn, "Apple", "accion", "USD", "AAPL", "100")  # 100 USD = 70 EUR
    divisas.guardar(conn, "USD", date(2026, 11, 20), "0.7")
    r = cartera.reparto(conn, "instrumento")
    assert r["valor"] == Decimal("100.0")
    assert [(f["grupo"], f["porcentaje"]) for f in r["filas"]] == [
        ("Apple", Decimal("70")),
        ("Bitcoin", Decimal("30")),
    ]
    por_tipo = cartera.reparto(conn, "tipo")
    assert [f["porcentaje"] for f in por_tipo["filas"]] == [Decimal("70"), Decimal("30")]
    por_divisa = cartera.reparto(conn, "divisa")
    assert {f["grupo"]: f["porcentaje"] for f in por_divisa["filas"]} == {
        "USD": Decimal("70"),
        "EUR": Decimal("30"),
    }


def test_reparto_excluye_y_valida(conn):
    id_ = instrumentos.anadir(conn, "SinPrecio", "cripto", "EUR")
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    r = cartera.reparto(conn)
    assert r == {"valor": None, "filas": [], "excluidos": [("SinPrecio", "sin precio")]}
    with pytest.raises(ValueError):
        cartera.reparto(conn, "otra")


def test_por_grupo(conn):
    from finanzas import precios

    fondo = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    precios.anadir(conn, fondo, date(2026, 11, 20), "15")
    laura = grupos.anadir(conn, "Laura")
    grupos.anadir(conn, "Vacio")
    compras.anadir(conn, fondo, date(2026, 1, 1), "2", "10")  # Personal: invierte 20, vale 30
    compras.anadir(conn, fondo, date(2026, 1, 1), "4", "10", grupo_id=laura)  # 40 -> 60
    r = cartera.por_grupo(conn)
    assert [(f["grupo"], f["invertido"], f["valor"], f["ganancia"]) for f in r] == [
        ("Laura", Decimal("40"), Decimal("60"), Decimal("20")),
        ("Personal", Decimal("20"), Decimal("30"), Decimal("10")),
    ]
    assert [f["rentabilidad"] for f in r] == [Decimal("0.5"), Decimal("0.5")]
    assert cartera.total(conn)["valor"] == Decimal("90")


def test_por_grupo_sin_precio(conn):
    id_ = instrumentos.anadir(conn, "SinPrecio", "cripto", "EUR")
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    [f] = cartera.por_grupo(conn)
    assert f["valor"] is None and f["excluidos"] == [("SinPrecio", "sin precio")]
