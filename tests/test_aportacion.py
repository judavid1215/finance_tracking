from datetime import date
from decimal import Decimal

import pytest

from finanzas import aportacion, compras, db, grupos, instrumentos, precios, ventas


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def _inst(conn, nombre="Fondo A", divisa="EUR"):
    return instrumentos.anadir(conn, nombre, "cripto", divisa)


def test_compra_inexistente(conn):
    assert aportacion.serie(conn, 999) is None


def test_valor_diario_y_aportado_con_comision(conn):
    i = _inst(conn)
    c = compras.anadir(conn, i, date(2026, 1, 2), "2", "10", comision="1")  # aportado 21
    precios.anadir(conn, i, date(2026, 1, 1), "9")  # anterior a la compra: no cuenta
    precios.anadir(conn, i, date(2026, 1, 2), "10")
    precios.anadir(conn, i, date(2026, 1, 5), "12")
    s = aportacion.serie(conn, c)
    assert s["aportado"] == Decimal("21")
    assert [(p["fecha"].day, p["valor"], p["ganancia"]) for p in s["puntos"]] == [
        (2, Decimal("20"), Decimal("-1")),
        (5, Decimal("24"), Decimal("3")),
    ]
    assert s["puntos"][-1]["rentabilidad"] == Decimal("3") / Decimal("21")
    assert (s["instrumento"], s["grupo"], s["divisa"]) == ("Fondo A", "Personal", "EUR")


def test_sin_precio_el_dia_de_la_compra_vale_lo_que_costo(conn):
    i = _inst(conn)
    c = compras.anadir(conn, i, date(2026, 1, 1), "1", "10")  # compra en festivo
    precios.anadir(conn, i, date(2026, 1, 4), "11")
    p = aportacion.serie(conn, c)["puntos"]
    assert [(x["fecha"].day, x["valor"]) for x in p] == [(1, Decimal("10")), (4, Decimal("11"))]
    assert p[0]["ganancia"] == 0 and p[0]["rentabilidad"] == 0


def test_sin_ningun_precio_un_solo_punto(conn):
    i = _inst(conn)
    c = compras.anadir(conn, i, date(2026, 1, 1), "1", "10")
    assert len(aportacion.serie(conn, c)["puntos"]) == 1


def test_se_ignoran_ventas_y_otras_compras(conn):
    i = _inst(conn)
    otro = grupos.anadir(conn, "Otro")
    c = compras.anadir(conn, i, date(2026, 1, 1), "2", "10")
    compras.anadir(conn, i, date(2026, 1, 2), "5", "10", grupo_id=otro)
    ventas.anadir(conn, i, date(2026, 1, 3), "2", "11")
    precios.anadir(conn, i, date(2026, 1, 1), "10")
    precios.anadir(conn, i, date(2026, 1, 4), "15")
    s = aportacion.serie(conn, c)
    assert s["aportado"] == Decimal("20")
    assert s["puntos"][-1]["valor"] == Decimal("30")  # 2 participaciones * 15, aunque se vendieran


def test_se_queda_en_la_divisa_del_instrumento(conn):
    i = _inst(conn, "Acción USD", "USD")  # sin tipo de cambio guardado: no hace falta
    c = compras.anadir(conn, i, date(2026, 1, 1), "1", "100")
    precios.anadir(conn, i, date(2026, 1, 1), "100")
    precios.anadir(conn, i, date(2026, 1, 2), "110")
    s = aportacion.serie(conn, c)
    assert s["divisa"] == "USD" and s["puntos"][-1]["valor"] == Decimal("110")


def test_hermanas_mismo_instrumento_y_grupo(conn):
    i, otro_inst = _inst(conn), _inst(conn, "Fondo B")
    laura = grupos.anadir(conn, "Laura")
    a = compras.anadir(conn, i, date(2026, 1, 1), "1", "10")
    b = compras.anadir(conn, i, date(2026, 3, 1), "2", "10", comision="1")
    compras.anadir(conn, i, date(2026, 2, 1), "1", "10", grupo_id=laura)  # otro grupo
    compras.anadir(conn, otro_inst, date(2026, 2, 1), "1", "10")  # otro instrumento
    h = aportacion.serie(conn, a)["hermanas"]
    assert [(x["id"], x["importe"]) for x in h] == [(b, Decimal("21")), (a, Decimal("10"))]
    assert aportacion.serie(conn, b)["hermanas"] == h  # la misma lista desde cualquiera
