import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3

import pytest

from finanzas import db, instrumentos


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def test_anadir_y_obtener(conn):
    id_ = instrumentos.anadir(conn, "MSCI World", "etf", "EUR", "IE00B4L5Y983")
    fila = instrumentos.obtener(conn, id_)
    assert (fila["nombre"], fila["tipo"], fila["divisa"]) == ("MSCI World", "ETF", "EUR")


def test_listar_todos_y_por_tipo(conn):
    instrumentos.anadir(conn, "A", "etf", "EUR", "IE0000000001")
    instrumentos.anadir(conn, "B", "cripto", "USD")
    assert [f["nombre"] for f in instrumentos.listar(conn)] == ["A", "B"]
    assert [f["nombre"] for f in instrumentos.listar(conn, "CRIPTO")] == ["B"]
    assert instrumentos.listar(conn, "fondo") == []
    assert [f["nombre"] for f in instrumentos.listar(conn, "etf")] == ["A"]


def test_borrar(conn):
    id_ = instrumentos.anadir(conn, "A", "etf", "EUR", "IE0000000001")
    assert instrumentos.borrar(conn, id_) is True
    assert instrumentos.obtener(conn, id_) is None
    assert instrumentos.borrar(conn, id_) is False  # ya no existe


def test_obtener_inexistente(conn):
    assert instrumentos.obtener(conn, 999) is None


@pytest.mark.parametrize(("tipo", "divisa"), [("bono", "EUR"), ("etf", "EURO"), ("etf", "")])
def test_rechaza_datos_invalidos(conn, tipo, divisa):
    with pytest.raises(sqlite3.IntegrityError):
        instrumentos.anadir(conn, "X", tipo, divisa, "ES0000000003")
    assert instrumentos.listar(conn) == []


def test_persiste_entre_conexiones(tmp_path):
    ruta = str(tmp_path / "t.sqlite3")
    c1 = db.conectar(ruta)
    instrumentos.anadir(c1, "A", "fondo", "EUR", "ES0000000001")
    c1.close()
    c2 = db.conectar(ruta)
    assert len(instrumentos.listar(c2)) == 1
    c2.close()


@pytest.mark.parametrize(
    ("escrito", "guardado"),
    [
        ("fondo", "Fondo"),
        ("FONDO", "Fondo"),
        ("etf", "ETF"),
        ("Etf", "ETF"),
        ("  accion ", "Accion"),
        ("cRiPtO", "Cripto"),
        ("PLAN_PENSIONES", "Plan_pensiones"),
    ],
)
def test_normaliza_tipo(conn, escrito, guardado):
    id_ = instrumentos.anadir(conn, "X", escrito, "EUR", "ABC123")
    assert instrumentos.obtener(conn, id_)["tipo"] == guardado


def test_rechaza_instrumento_repetido(conn):
    instrumentos.anadir(conn, "MSCI World", "etf", "EUR", "IE00B4L5Y983")
    for repetido in ("MSCI World", "msci world", "  MSCI WORLD "):
        with pytest.raises(ValueError, match="Ya existe"):
            instrumentos.anadir(conn, repetido, "fondo", "USD", "ES0000000002")
    assert len(instrumentos.listar(conn)) == 1


@pytest.mark.parametrize(
    ("tipo", "id_tipo"),
    [("fondo", "ISIN"), ("etf", "ISIN"), ("plan_pensiones", "DGS"), ("accion", "TICKER")],
)
def test_guarda_el_identificador_que_exige_cada_tipo(conn, tipo, id_tipo):
    id_ = instrumentos.anadir(conn, "X", tipo, "EUR", " n5396 ")
    fila = instrumentos.obtener(conn, id_)
    assert (fila["id_tipo"], fila["identificador"]) == (id_tipo, "N5396")  # sin espacios, mayúsc.


@pytest.mark.parametrize("tipo", ["fondo", "etf", "plan_pensiones", "accion"])
@pytest.mark.parametrize("vacio", [None, "", "   "])
def test_exige_identificador(conn, tipo, vacio):
    with pytest.raises(ValueError, match="necesita"):
        instrumentos.anadir(conn, "X", tipo, "EUR", vacio)
    assert instrumentos.listar(conn) == []


def test_cripto_no_pide_identificador(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    fila = instrumentos.obtener(conn, id_)
    assert fila["identificador"] is None


def test_rechaza_identificador_repetido_y_no_deja_instrumento_a_medias(conn):
    instrumentos.anadir(conn, "A", "etf", "EUR", "IE00B4L5Y983")
    with pytest.raises(ValueError, match="ISIN IE00B4L5Y983"):
        instrumentos.anadir(conn, "B", "fondo", "EUR", "ie00b4l5y983")
    assert [f["nombre"] for f in instrumentos.listar(conn)] == ["A"]


def test_borrar_instrumento_borra_su_identificador(conn):
    id_ = instrumentos.anadir(conn, "A", "etf", "EUR", "IE00B4L5Y983")
    instrumentos.borrar(conn, id_)
    assert conn.execute("SELECT count(*) FROM identificadores").fetchone()[0] == 0
