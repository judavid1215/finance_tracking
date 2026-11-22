from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, divisas, evolucion, grupos, instrumentos, precios, ventas


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def _btc(conn, nombre="Bitcoin", divisa="EUR"):
    return instrumentos.anadir(conn, nombre, "cripto", divisa)


def test_sin_datos(conn):
    assert evolucion.serie(conn) == []
    id_ = _btc(conn)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    assert evolucion.serie(conn) == []  # sin precios no hay días


def test_valor_por_dia_con_precio_arrastrado(conn):
    id_ = _btc(conn)
    compras.anadir(conn, id_, date(2026, 1, 1), "2", "10")  # 20
    precios.anadir(conn, id_, date(2026, 1, 1), "10")
    precios.anadir(conn, id_, date(2026, 1, 2), "12")
    compras.anadir(conn, id_, date(2026, 1, 3), "1", "20")  # +20 -> 3 part., 40 invertido
    precios.anadir(conn, id_, date(2026, 1, 4), "20")
    s = evolucion.serie(conn)
    assert [(f["fecha"].day, f["invertido"], f["valor"]) for f in s] == [
        (1, Decimal("20"), Decimal("20")),
        (2, Decimal("20"), Decimal("24")),
        (4, Decimal("40"), Decimal("60")),
    ]
    assert s[-1]["rentabilidad"] == Decimal("0.5")


def test_antes_del_primer_precio_vale_lo_que_costo(conn):
    id_ = _btc(conn)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    precios.anadir(conn, id_, date(2026, 1, 5), "15")
    otro = _btc(conn, "Otro")
    compras.anadir(conn, otro, date(2026, 1, 3), "1", "100")
    precios.anadir(conn, otro, date(2026, 1, 3), "100")
    precios.anadir(conn, otro, date(2026, 1, 4), "100")
    s = {f["fecha"].day: f for f in evolucion.serie(conn)}
    assert s[3]["valor"] == Decimal("110")  # el primero sigue a coste (10) + el otro (100)
    assert s[5]["valor"] == Decimal("115")


def test_venta_y_grupo(conn):
    id_ = _btc(conn)
    laura = grupos.anadir(conn, "Laura")
    compras.anadir(conn, id_, date(2026, 1, 1), "2", "10")
    compras.anadir(conn, id_, date(2026, 1, 1), "4", "10", grupo_id=laura)
    ventas.anadir(conn, id_, date(2026, 1, 2), "1", "10")
    for d in (1, 2):
        precios.anadir(conn, id_, date(2026, 1, d), "10")
    todo = evolucion.serie(conn)
    assert (todo[-1]["invertido"], todo[-1]["valor"]) == (Decimal("50"), Decimal("50"))
    solo = evolucion.serie(conn, laura)
    assert (solo[-1]["invertido"], solo[-1]["valor"]) == (Decimal("40"), Decimal("40"))


def test_divisa_con_tipo_de_cambio_del_dia(conn):
    id_ = _btc(conn, "Apple", "USD")
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "100")
    precios.anadir(conn, id_, date(2026, 1, 1), "100")
    precios.anadir(conn, id_, date(2026, 1, 3), "100")
    divisas.guardar(conn, "USD", date(2026, 1, 2), "0.5")  # el primer día usa el primero
    divisas.guardar(conn, "USD", date(2026, 1, 3), "0.8")
    s = evolucion.serie(conn)
    assert [f["valor"] for f in s] == [Decimal("50"), Decimal("80")]


def test_divisa_sin_tipo_de_cambio(conn):
    id_ = _btc(conn, "Apple", "USD")
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "100")
    with pytest.raises(ValueError, match="USD"):
        evolucion.serie(conn)


def test_ultimo_dia_coincide_con_total(conn):
    id_ = _btc(conn)
    compras.anadir(conn, id_, date(2026, 1, 1), "2", "10")
    ventas.anadir(conn, id_, date(2026, 1, 3), "1", "15")
    precios.anadir(conn, id_, date(2026, 1, 1), "10")
    precios.anadir(conn, id_, date(2026, 1, 5), "30")
    t = cartera.total(conn)
    f = evolucion.serie(conn)[-1]
    assert (f["invertido"], f["valor"]) == (t["invertido"], t["valor"])


def test_mensual(conn):
    id_ = _btc(conn)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    for d in (date(2026, 1, 1), date(2026, 1, 30), date(2026, 2, 2), date(2026, 2, 27), date(2026, 3, 2)):
        precios.anadir(conn, id_, d, "10")
    assert [f["fecha"] for f in evolucion.mensual(evolucion.serie(conn))] == [
        date(2026, 1, 30),
        date(2026, 2, 27),
        date(2026, 3, 2),
    ]
