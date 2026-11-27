from datetime import date
from decimal import Decimal

import pytest

from finanzas import cartera, compras, db, grupos, instrumentos, posicion, precios, ventas


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


@pytest.fixture
def fondo(conn):
    return instrumentos.anadir(conn, "DNB", "Fondo", "EUR", "LU0302296495")


def test_crear_listar_y_nombres_unicos(conn):
    personal = grupos.anadir(conn, " Personal ")
    grupos.anadir(conn, "Pension")
    assert [g["nombre"] for g in grupos.listar(conn)] == ["Pension", "Personal"]
    assert grupos.obtener_por_nombre(conn, "PERSONAL")["id"] == personal  # sin mayúsculas
    with pytest.raises(ValueError, match="Ya existe"):
        grupos.anadir(conn, "personal")
    with pytest.raises(ValueError, match="nombre"):
        grupos.anadir(conn, "  ")


def test_obtener_o_crear_y_por_defecto(conn):
    id_, creado = grupos.obtener_o_crear(conn, "Pension")
    assert creado and grupos.obtener_o_crear(conn, "pension") == (id_, False)
    por_defecto = grupos.por_defecto(conn)
    assert grupos.por_defecto(conn) == por_defecto
    assert grupos.obtener_por_nombre(conn, "Personal")["id"] == por_defecto


def test_compra_sin_grupo_va_al_grupo_por_defecto(conn, fondo):
    compras.anadir(conn, fondo, date(2026, 1, 5), 1, 10)
    assert compras.listar(conn)[0]["grupo"] == "Personal"


def test_mismo_fondo_en_dos_grupos_tiene_posiciones_separadas(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    compras.anadir(conn, fondo, date(2026, 1, 6), 4, 20, grupo_id=pension)
    assert posicion.calcular(conn, fondo, personal)["participaciones"] == 10
    assert posicion.calcular(conn, fondo, pension) == {
        "participaciones": Decimal(4),
        "invertido": Decimal(80),
    }
    assert posicion.calcular(conn, fondo)["participaciones"] == 14  # todos los grupos juntos
    assert [c["grupo"] for c in compras.listar(conn, grupo_id=pension)] == ["Pension"]


def test_no_se_vende_de_un_grupo_lo_que_solo_tiene_otro(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    with pytest.raises(ValueError, match="participaciones"):
        ventas.anadir(conn, fondo, date(2026, 2, 1), 1, 12, grupo_id=pension)
    assert ventas.listar(conn) == []
    ventas.anadir(conn, fondo, date(2026, 2, 1), 3, 12, grupo_id=personal)
    assert ventas.listar(conn, grupo_id=personal)[0]["grupo"] == "Personal"


def test_borrar_compra_se_comprueba_dentro_de_su_grupo(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    a = compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    compras.anadir(conn, fondo, date(2026, 1, 6), 10, 10, grupo_id=pension)
    ventas.anadir(conn, fondo, date(2026, 2, 1), 5, 12, grupo_id=personal)
    with pytest.raises(ValueError, match="no se puede borrar"):
        compras.borrar(conn, a)  # la compra del otro grupo no cubre esa venta
    assert len(compras.listar(conn)) == 2


def test_cartera_una_fila_por_instrumento_y_grupo(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    compras.anadir(conn, fondo, date(2026, 1, 6), 5, 10, grupo_id=pension)
    precios.anadir(conn, fondo, date(2026, 3, 1), 20)
    filas = cartera.resumen(conn)
    assert [(f["grupo"], f["participaciones"]) for f in filas] == [
        ("Pension", Decimal(5)),
        ("Personal", Decimal(10)),
    ]
    solo_pension = cartera.resumen(conn, grupo_id=pension)
    assert [f["grupo"] for f in solo_pension] == ["Pension"]
    assert cartera.total(conn)["valor"] == 300
    assert cartera.total(conn, grupo_id=pension)["valor"] == 100
    reparto = cartera.reparto(conn, "grupo")
    assert [(f["grupo"], f["porcentaje"].quantize(Decimal("0.01"))) for f in reparto["filas"]] == [
        ("Personal", Decimal("66.67")),
        ("Pension", Decimal("33.33")),
    ]
    # por instrumento se suman los dos grupos
    assert cartera.reparto(conn, "instrumento")["filas"][0]["valor"] == 300


def test_borrar_grupo_solo_si_no_tiene_operaciones(conn, fondo):
    vacio = grupos.anadir(conn, "Vacio")
    usado = grupos.anadir(conn, "Usado")
    compras.anadir(conn, fondo, date(2026, 1, 5), 1, 10, grupo_id=usado)
    with pytest.raises(ValueError, match="no se puede borrar"):
        grupos.borrar(conn, usado)
    assert grupos.borrar(conn, vacio) is True and grupos.borrar(conn, vacio) is False


def test_mover_instrumento_de_grupo(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    ventas.anadir(conn, fondo, date(2026, 2, 1), 4, 12, grupo_id=personal)
    assert grupos.mover_instrumento(conn, fondo, personal, pension) == 2
    assert posicion.calcular(conn, fondo, personal)["participaciones"] == 0
    assert posicion.calcular(conn, fondo, pension)["participaciones"] == 6
    assert grupos.borrar(conn, personal) is True  # ya no tiene operaciones


def test_mover_instrumento_rechaza_casos_invalidos(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 3, 1), 5, 10, grupo_id=pension)
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 10, grupo_id=personal)
    with pytest.raises(ValueError, match="mismo"):
        grupos.mover_instrumento(conn, fondo, personal, personal)
    with pytest.raises(ValueError, match="destino"):
        grupos.mover_instrumento(conn, fondo, personal, 999)
    vacio = grupos.anadir(conn, "Vacio")
    otro = grupos.anadir(conn, "Otro")
    with pytest.raises(ValueError, match="no tiene operaciones"):
        grupos.mover_instrumento(conn, fondo, vacio, otro)
    assert len(compras.listar(conn, grupo_id=personal)) == 1  # nada cambió


def test_mover_a_un_grupo_que_ya_lo_tiene_suma_las_operaciones(conn, fondo):
    personal = grupos.anadir(conn, "Personal")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, fondo, date(2026, 3, 1), 5, 10, grupo_id=pension)
    compras.anadir(conn, fondo, date(2026, 1, 5), 10, 20, grupo_id=personal)
    ventas.anadir(conn, fondo, date(2026, 2, 1), 4, 12, grupo_id=personal)
    assert grupos.mover_instrumento(conn, fondo, personal, pension) == 2
    p = posicion.calcular(conn, fondo, pension)
    assert p["participaciones"] == 11  # 5 + 10 - 4
    assert posicion.calcular(conn, fondo, personal)["participaciones"] == 0


def test_base_anterior_a_los_grupos_se_rechaza_con_un_mensaje_claro(tmp_path):
    import sqlite3

    ruta = tmp_path / "vieja.sqlite3"
    vieja = sqlite3.connect(ruta)
    vieja.execute(
        "CREATE TABLE compras (id INTEGER PRIMARY KEY, instrumento_id INTEGER, fecha TEXT, "
        "participaciones TEXT, precio TEXT)"
    )
    vieja.commit()
    vieja.close()
    with pytest.raises(ValueError, match="anterior a los grupos"):
        db.conectar(ruta)
