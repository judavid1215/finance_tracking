import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, instrumentos, precios


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


@pytest.fixture
def inst(conn):
    return instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")


def test_sin_precio(conn, inst):
    assert precios.ultimo(conn, inst) is None


def test_ultimo_es_el_mas_reciente(conn, inst):
    precios.anadir(conn, inst, date(2026, 2, 1), "200")
    precios.anadir(conn, inst, date(2026, 1, 1), "100")
    assert precios.ultimo(conn, inst) == Decimal("200")


def test_mismo_dia_sustituye(conn, inst):
    precios.anadir(conn, inst, date(2026, 1, 1), "100")
    precios.anadir(conn, inst, date(2026, 1, 1), "150,5")
    assert precios.ultimo(conn, inst) == Decimal("150.5")


def test_rechaza_invalidos(conn, inst):
    with pytest.raises(ValueError):
        precios.anadir(conn, inst, date(2026, 1, 1), "0")
    with pytest.raises(TypeError):
        precios.anadir(conn, inst, "2026-01-01", "1")
    with pytest.raises(sqlite3.IntegrityError):
        precios.anadir(conn, 999, date(2026, 1, 1), "1")


def test_cartera_con_precio_actual(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "100")
    [fila] = cartera.resumen(conn)
    assert fila["precio_actual"] is None and fila["ganancia"] is None
    precios.anadir(conn, inst, date(2026, 3, 1), "150")
    [fila] = cartera.resumen(conn)
    assert fila["valor_actual"] == Decimal("300")
    assert fila["ganancia"] == Decimal("100")
    assert fila["rentabilidad"] == Decimal("0.5")


def test_anadir_muchos_sustituye_y_cuenta(conn, inst):
    precios.anadir(conn, inst, date(2026, 1, 2), "1")
    n = precios.anadir_muchos(
        conn, inst, [(date(2026, 1, 2), Decimal("5")), (date(2026, 1, 5), Decimal("6"))]
    )
    assert n == 2
    assert precios.ultimo(conn, inst) == Decimal("6")
    total = conn.execute("SELECT COUNT(*) FROM precios").fetchone()[0]
    assert total == 2


def test_anadir_muchos_todo_o_nada(conn, inst):
    with pytest.raises(ValueError):
        precios.anadir_muchos(conn, inst, [(date(2026, 1, 2), "5"), (date(2026, 1, 5), "-1")])
    assert precios.ultimo(conn, inst) is None
