import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from finanzas import compras, db, instrumentos


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


@pytest.fixture
def inst(conn):
    return instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")


def test_anadir_y_listar(conn, inst):
    id_ = compras.anadir(conn, inst, date(2026, 3, 15), "0.00012345", "61234.56", "1,25")
    assert compras.listar(conn) == [
        {
            "id": id_,
            "instrumento_id": inst,
            "instrumento": "Bitcoin",
            "grupo_id": 1,
            "grupo": "Personal",
            "fecha": date(2026, 3, 15),
            "participaciones": Decimal("0.00012345"),
            "precio": Decimal("61234.56"),
            "comision": Decimal("1.25"),
        }
    ]


def test_comision_por_defecto_es_cero(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    assert compras.listar(conn)[0]["comision"] == Decimal("0")


@pytest.mark.parametrize("malo", ["-1", "abc", "NaN", "0.123456789"])
def test_rechaza_comision_invalida(conn, inst, malo):
    with pytest.raises(ValueError):
        compras.anadir(conn, inst, date(2026, 1, 1), 1, 10, malo)
    assert compras.listar(conn) == []


@pytest.mark.parametrize("malo", [0.5, True, None])
def test_rechaza_comision_float_bool_none(conn, inst, malo):
    with pytest.raises(TypeError):
        compras.anadir(conn, inst, date(2026, 1, 1), 1, 10, malo)


def test_base_antigua_sin_comision_se_migra(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    antigua = db.conectar(ruta)
    antigua.executescript(
        """
        DROP VIEW compras_detalle; DROP VIEW ventas_detalle;
        DROP TABLE compras; DROP TABLE ventas;
        INSERT INTO grupos VALUES (1, 'Personal');
        CREATE TABLE compras (id INTEGER PRIMARY KEY, instrumento_id INTEGER NOT NULL,
            grupo_id INTEGER NOT NULL, fecha TEXT NOT NULL, participaciones TEXT NOT NULL,
            precio TEXT NOT NULL);
        CREATE TABLE ventas (id INTEGER PRIMARY KEY, instrumento_id INTEGER NOT NULL,
            grupo_id INTEGER NOT NULL, fecha TEXT NOT NULL, participaciones TEXT NOT NULL,
            precio TEXT NOT NULL);
        INSERT INTO instrumentos (nombre, tipo, divisa) VALUES ('Bitcoin', 'Cripto', 'EUR');
        INSERT INTO compras VALUES (1, 1, 1, '2026-01-01', '2', '100');
        """
    )
    antigua.close()
    nueva = db.conectar(ruta)
    assert compras.listar(nueva)[0]["comision"] == Decimal("0")  # la fila vieja queda a 0
    compras.anadir(nueva, 1, date(2026, 2, 1), 1, 10, "0.5")  # y ya se pueden guardar comisiones
    assert nueva.execute("SELECT comision FROM compras_detalle").fetchone()[0] == "0"


def test_decimales_exactos(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), Decimal("0.1"), Decimal("0.2"))
    c = compras.listar(conn)[0]
    assert c["participaciones"] + c["precio"] == Decimal("0.3")  # con float: 0.30000000000000004


def test_listar_por_instrumento_y_orden_por_fecha(conn, inst):
    otro = instrumentos.anadir(conn, "MSCI World", "etf", "EUR", "IE00B4L5Y983")
    compras.anadir(conn, inst, date(2026, 5, 1), 1, 10)
    compras.anadir(conn, inst, date(2026, 2, 1), 1, 10)
    compras.anadir(conn, otro, date(2026, 3, 1), 1, 10)
    assert [c["fecha"].month for c in compras.listar(conn, inst)] == [2, 5]
    assert len(compras.listar(conn, otro)) == 1
    assert len(compras.listar(conn)) == 3


def test_borrar(conn, inst):
    id_ = compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    assert compras.borrar(conn, id_) is True
    assert compras.borrar(conn, id_) is False
    assert compras.listar(conn) == []


@pytest.mark.parametrize("malo", [0.5, True, None])
def test_rechaza_float_bool_none(conn, inst, malo):
    with pytest.raises(TypeError):
        compras.anadir(conn, inst, date(2026, 1, 1), malo, 10)
    with pytest.raises(TypeError):
        compras.anadir(conn, inst, date(2026, 1, 1), 1, malo)


@pytest.mark.parametrize("malo", ["abc", "0", "-1", "NaN", "0.123456789"])
def test_rechaza_numeros_invalidos(conn, inst, malo):
    with pytest.raises(ValueError):
        compras.anadir(conn, inst, date(2026, 1, 1), malo, 10)
    assert compras.listar(conn) == []


def test_rechaza_fecha_que_no_es_date(conn, inst):
    with pytest.raises(TypeError):
        compras.anadir(conn, inst, "2026-01-01", 1, 10)


def test_instrumento_inexistente(conn):
    with pytest.raises(sqlite3.IntegrityError):
        compras.anadir(conn, 999, date(2026, 1, 1), 1, 10)


def test_no_se_borra_instrumento_con_compras(conn, inst):
    compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    with pytest.raises(sqlite3.IntegrityError):
        instrumentos.borrar(conn, inst)
    assert instrumentos.obtener(conn, inst) is not None


def test_se_borra_instrumento_tras_borrar_sus_compras(conn, inst):
    id_ = compras.anadir(conn, inst, date(2026, 1, 1), 1, 10)
    compras.borrar(conn, id_)
    assert instrumentos.borrar(conn, inst) is True


@pytest.mark.parametrize("escrito", ["1,5", "1.5", " 1,50 "])
def test_acepta_coma_o_punto(conn, inst, escrito):
    compras.anadir(conn, inst, date(2026, 1, 1), escrito, escrito)
    c = compras.listar(conn)[0]
    assert c["participaciones"] == c["precio"] == Decimal("1.5")


@pytest.mark.parametrize("malo", ["1.234,56", "1,2,3"])
def test_rechaza_separadores_ambiguos(conn, inst, malo):
    with pytest.raises(ValueError):
        compras.anadir(conn, inst, date(2026, 1, 1), malo, 10)


def test_vista_compras_detalle(conn, inst):
    compras.anadir(conn, inst, date(2026, 3, 5), "2", "10")
    fila = conn.execute("SELECT * FROM compras_detalle").fetchone()
    assert (fila["instrumento"], fila["fecha"]) == ("Bitcoin", "05-03-2026")


def test_vista_compras_detalle_con_isin(conn):
    etf = instrumentos.anadir(conn, "MSCI World", "etf", "EUR", "ie00b4l5y983")
    accion = instrumentos.anadir(conn, "Apple", "accion", "USD", "AAPL")
    compras.anadir(conn, etf, date(2026, 3, 5), "2", "10")
    compras.anadir(conn, accion, date(2026, 3, 6), "1", "200")
    filas = conn.execute("SELECT * FROM compras_detalle").fetchall()
    assert [(f["instrumento"], f["isin"]) for f in filas] == [
        ("MSCI World", "IE00B4L5Y983"),
        ("Apple", None),  # las acciones tienen ticker, no ISIN
    ]


def test_vista_identificadores_detalle(conn):
    instrumentos.anadir(conn, "Apple", "accion", "USD", "aapl")
    fila = conn.execute("SELECT * FROM identificadores_detalle").fetchone()
    assert tuple(fila) == ("Apple", "TICKER", "AAPL")


def test_vistas_se_actualizan_en_una_base_antigua(tmp_path):
    ruta = tmp_path / "t.sqlite3"
    antigua = db.conectar(ruta)
    antigua.executescript(
        "DROP VIEW compras_detalle; CREATE VIEW compras_detalle AS SELECT 1 AS x;"
    )
    antigua.close()
    nueva = db.conectar(ruta)
    columnas = [c[1] for c in nueva.execute("PRAGMA table_info(compras_detalle)")]
    assert "isin" in columnas


def test_editar_compra(conn):
    id_ = instrumentos.anadir(conn, "X", "cripto", "EUR")
    c = compras.anadir(conn, id_, date(2026, 1, 1), "2", "10")
    assert compras.editar(conn, c, date(2026, 1, 3), "2,5", "11", "0.5")
    (o,) = compras.listar(conn)
    assert (o["fecha"], o["participaciones"], o["precio"], o["comision"]) == (
        date(2026, 1, 3), Decimal("2.5"), Decimal("11"), Decimal("0.5"))
    assert compras.editar(conn, 999, date(2026, 1, 3), "1", "1") is False
    with pytest.raises(ValueError):
        compras.editar(conn, c, date(2026, 1, 3), "0", "1")
