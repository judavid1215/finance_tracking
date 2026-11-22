import sqlite3

import pytest

from finanzas import db, instrumentos

ISIN = "IE00B4L5Y983"


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def test_anadir_y_obtener(conn):
    id_ = instrumentos.anadir(conn, "MSCI World", "etf", "EUR", ISIN)
    fila = instrumentos.obtener(conn, id_)
    assert (fila["nombre"], fila["tipo"], fila["divisa"]) == ("MSCI World", "ETF", "EUR")
    assert (fila["id_tipo"], fila["identificador"]) == ("ISIN", ISIN)


def test_listar_todos_y_por_tipo(conn):
    instrumentos.anadir(conn, "A", "etf", "EUR", ISIN)
    instrumentos.anadir(conn, "B", "cripto", "USD")
    assert [f["nombre"] for f in instrumentos.listar(conn)] == ["A", "B"]
    assert [f["nombre"] for f in instrumentos.listar(conn, "cripto")] == ["B"]
    assert instrumentos.listar(conn, "fondo") == []


def test_borrar(conn):
    id_ = instrumentos.anadir(conn, "A", "etf", "EUR", ISIN)
    assert instrumentos.borrar(conn, id_) is True
    assert instrumentos.obtener(conn, id_) is None
    assert instrumentos.borrar(conn, id_) is False  # ya no existe


def test_obtener_inexistente(conn):
    assert instrumentos.obtener(conn, 999) is None


@pytest.mark.parametrize(("tipo", "divisa"), [("bono", "EUR"), ("cripto", "EURO"), ("cripto", "")])
def test_rechaza_datos_invalidos(conn, tipo, divisa):
    with pytest.raises(sqlite3.IntegrityError):
        instrumentos.anadir(conn, "X", tipo, divisa)
    assert instrumentos.listar(conn) == []


def test_exige_identificador_segun_tipo(conn):
    with pytest.raises(ValueError):
        instrumentos.anadir(conn, "X", "etf", "EUR")
    assert instrumentos.listar(conn) == []


def test_rechaza_nombre_repetido(conn):
    instrumentos.anadir(conn, "A", "cripto", "EUR")
    with pytest.raises(ValueError):
        instrumentos.anadir(conn, "a", "cripto", "EUR")


def test_persiste_entre_conexiones(tmp_path):
    ruta = str(tmp_path / "t.sqlite3")
    c1 = db.conectar(ruta)
    instrumentos.anadir(c1, "A", "fondo", "EUR", ISIN)
    c1.close()
    c2 = db.conectar(ruta)
    assert len(instrumentos.listar(c2)) == 1
    c2.close()


def test_ticker_yahoo_al_anadir_y_al_cambiarlo(conn):
    id_ = instrumentos.anadir(conn, "DNB", "Fondo", "EUR", "LU0302296495", " 0p00009pq4.f ")
    assert instrumentos.obtener(conn, id_)["ticker_yahoo"] == "0P00009PQ4.F"
    instrumentos.asignar_ticker_yahoo(conn, id_, "OTRO.F")
    assert instrumentos.obtener(conn, id_)["ticker_yahoo"] == "OTRO.F"
    instrumentos.asignar_ticker_yahoo(conn, id_, "  ")  # vacío = quitarlo
    assert instrumentos.obtener(conn, id_)["ticker_yahoo"] is None
    assert instrumentos.obtener(conn, id_)["identificador"] == "LU0302296495"
    with pytest.raises(ValueError):
        instrumentos.asignar_ticker_yahoo(conn, 999, "X")
