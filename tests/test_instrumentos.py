import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3
import pytest

from src.finanzas import instrumentos


@pytest.fixture
def conn(tmp_path):
    conn = instrumentos.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def test_anadir_y_obtener(conn):
    id_ = instrumentos.anadir(conn, "MSCI World", "etf", "EUR")
    fila = instrumentos.obtener(conn, id_)
    assert (fila["nombre"], fila["tipo"], fila["divisa"]) == ("MSCI World", "etf", "EUR")


def test_listar_todos_y_por_tipo(conn):
    instrumentos.anadir(conn, "A", "etf", "EUR")
    instrumentos.anadir(conn, "B", "cripto", "USD")
    assert [f["nombre"] for f in instrumentos.listar(conn)] == ["A", "B"]
    assert [f["nombre"] for f in instrumentos.listar(conn, "cripto")] == ["B"]
    assert instrumentos.listar(conn, "fondo") == []


def test_borrar(conn):
    id_ = instrumentos.anadir(conn, "A", "etf", "EUR")
    assert instrumentos.borrar(conn, id_) is True
    assert instrumentos.obtener(conn, id_) is None
    assert instrumentos.borrar(conn, id_) is False  # ya no existe


def test_obtener_inexistente(conn):
    assert instrumentos.obtener(conn, 999) is None


@pytest.mark.parametrize(("tipo", "divisa"), [("bono", "EUR"), ("etf", "EURO"), ("etf", "")])
def test_rechaza_datos_invalidos(conn, tipo, divisa):
    with pytest.raises(sqlite3.IntegrityError):
        instrumentos.anadir(conn, "X", tipo, divisa)
    assert instrumentos.listar(conn) == []


def test_persiste_entre_conexiones(tmp_path):
    ruta = str(tmp_path / "t.sqlite3")
    c1 = instrumentos.conectar(ruta)
    instrumentos.anadir(c1, "A", "fondo", "EUR")
    c1.close()
    c2 = instrumentos.conectar(ruta)
    assert len(instrumentos.listar(c2)) == 1
    c2.close()
