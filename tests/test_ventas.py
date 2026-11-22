import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, instrumentos, ventas


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


@pytest.fixture
def inst(conn):
    return instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")


def test_anadir_y_listar(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "100")
    id_ = ventas.anadir(conn, inst, date(2026, 3, 15), "1,5", "150", "2")
    assert ventas.listar(conn) == [
        {
            "id": id_,
            "instrumento_id": inst,
            "instrumento": "Bitcoin",
            "grupo_id": 1,
            "grupo": "Personal",
            "fecha": date(2026, 3, 15),
            "participaciones": Decimal("1.5"),
            "precio": Decimal("150"),
            "comision": Decimal("2"),
        }
    ]


def test_comision_de_venta_por_defecto_cero_y_no_negativa(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), 5, 10)
    ventas.anadir(conn, inst, date(2026, 2, 1), 1, 10)
    assert ventas.listar(conn)[0]["comision"] == Decimal("0")
    with pytest.raises(ValueError):
        ventas.anadir(conn, inst, date(2026, 2, 2), 1, 10, "-1")


def test_comision_de_compra_encarece_el_coste_y_la_de_venta_no(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "100", "10")  # coste 210
    ventas.anadir(conn, inst, date(2026, 2, 1), "1", "150", "5")  # quita la mitad: 105
    [fila] = cartera.resumen(conn)
    assert (fila["participaciones"], fila["invertido"]) == (Decimal("1"), Decimal("105"))
    assert fila["precio_medio"] == Decimal("105")


def test_borrar(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    id_ = ventas.anadir(conn, inst, date(2026, 2, 1), 1, 10)
    assert ventas.borrar(conn, id_) is True
    assert ventas.borrar(conn, id_) is False
    assert ventas.listar(conn) == []


@pytest.mark.parametrize("malo", [0.5, True, None])
def test_rechaza_float_bool_none(conn, inst, malo):
    compras.anadir(conn, inst, date(2026, 1, 1), 5, 10)
    with pytest.raises(TypeError):
        ventas.anadir(conn, inst, date(2026, 2, 1), malo, 10)


def test_instrumento_inexistente(conn):
    with pytest.raises(sqlite3.IntegrityError):
        ventas.anadir(conn, 999, date(2026, 1, 1), 1, 10)


def test_no_se_borra_instrumento_con_ventas(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    ventas.anadir(conn, inst, date(2026, 2, 1), 1, 10)
    with pytest.raises(sqlite3.IntegrityError):
        instrumentos.borrar(conn, inst)


# --- Posición (coste medio) ---


def test_venta_quita_participaciones_al_precio_medio(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "100")
    compras.anadir(conn, inst, date(2026, 2, 1), "2", "200")  # precio medio 150
    ventas.anadir(conn, inst, date(2026, 3, 1), "3", "300")
    [fila] = cartera.resumen(conn)
    assert fila["participaciones"] == Decimal("1")
    assert fila["invertido"] == Decimal("150")
    assert fila["precio_medio"] == Decimal("150")


def test_compra_posterior_a_la_venta_cambia_el_precio_medio(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "100")
    ventas.anadir(conn, inst, date(2026, 2, 1), "1", "500")  # queda 1 a 100
    compras.anadir(conn, inst, date(2026, 3, 1), "1", "300")
    [fila] = cartera.resumen(conn)
    assert (fila["participaciones"], fila["invertido"]) == (Decimal("2"), Decimal("400"))
    assert fila["precio_medio"] == Decimal("200")


def test_misma_fecha_cuenta_primero_la_compra(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    ventas.anadir(conn, inst, date(2026, 1, 1), "1", "100")  # se puede: la compra va antes
    assert cartera.resumen(conn) == []


def test_decimales_exactos(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "1", "0.1")
    for _ in range(10):  # con float, 10 x 0.1 no sumaría exactamente 1
        ventas.anadir(conn, inst, date(2026, 2, 1), "0.1", "0.2")
    assert cartera.resumen(conn) == []  # se vendió justo todo


def test_no_se_puede_vender_mas_de_lo_comprado(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    with pytest.raises(ValueError, match="solo hay"):
        ventas.anadir(conn, inst, date(2026, 2, 1), "2", "100")
    assert ventas.listar(conn) == []  # no se guardó


def test_no_se_puede_vender_antes_de_comprar(conn, inst):
    compras.anadir(conn, inst, date(2026, 2, 1), "1", "100")
    with pytest.raises(ValueError):
        ventas.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    assert ventas.listar(conn) == []


def test_no_se_borra_compra_si_deja_una_venta_sin_cubrir(conn, inst):
    c = compras.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    ventas.anadir(conn, inst, date(2026, 2, 1), "1", "100")
    with pytest.raises(ValueError, match="no se puede borrar"):
        compras.borrar(conn, c)
    assert len(compras.listar(conn)) == 1


def test_se_borra_compra_sin_ventas_que_dependan(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    extra = compras.anadir(conn, inst, date(2026, 5, 1), "1", "100")
    ventas.anadir(conn, inst, date(2026, 2, 1), "1", "100")
    assert compras.borrar(conn, extra) is True


def test_resumen_omite_instrumento_vendido_por_completo(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "1", "100")
    ventas.anadir(conn, inst, date(2026, 2, 1), "1", "150")
    assert cartera.resumen(conn) == []


def test_vista_ventas_detalle(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), "2", "10")
    ventas.anadir(conn, inst, date(2026, 3, 5), "1", "12")
    fila = conn.execute("SELECT * FROM ventas_detalle").fetchone()
    assert (fila["instrumento"], fila["fecha"]) == ("Bitcoin", "05-03-2026")
