from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from finanzas import actualizacion, cartera, compras, db, divisas, instrumentos, precios, yahoo


class FakeTicker:
    def __init__(self, simbolo, vacio=False):
        self.simbolo = simbolo
        indice = pd.to_datetime(["2026-11-19", "2026-11-20"])
        self._h = pd.DataFrame({"Close": [0.9, 0.9234567891]}, index=indice)
        if vacio:
            self._h = self._h.iloc[0:0]

    def history(self, period):
        return self._h


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def comprar(conn, nombre, divisa, ident, precio="10", n="2"):
    id_ = instrumentos.anadir(conn, nombre, "accion", divisa, ident)
    compras.anadir(conn, id_, date(2026, 1, 1), n, precio)
    return id_


def test_leer_tasa(monkeypatch):
    visto = []

    def falso(simbolo):
        visto.append(simbolo)
        return FakeTicker(simbolo)

    monkeypatch.setattr(divisas.yf, "Ticker", falso)
    assert divisas.leer_tasa("usd") == (date(2026, 11, 20), Decimal("0.923457"))
    assert visto == ["USDEUR=X"]


def test_sin_datos(monkeypatch):
    monkeypatch.setattr(divisas.yf, "Ticker", lambda s: FakeTicker(s, vacio=True))
    with pytest.raises(ValueError):
        divisas.leer_tasa("USD")


def test_actualizar_guarda_y_ultima(conn, monkeypatch):
    monkeypatch.setattr(divisas.yf, "Ticker", FakeTicker)
    assert divisas.ultima(conn, "USD") is None
    divisas.actualizar(conn, "USD")
    assert divisas.ultima(conn, "USD") == Decimal("0.923457")


def test_eur_es_uno_y_no_se_actualiza(conn):
    assert divisas.ultima(conn, "EUR") == 1
    with pytest.raises(ValueError):
        divisas.actualizar(conn, "EUR")


def test_ultima_es_la_mas_reciente(conn):
    divisas.guardar(conn, "USD", date(2026, 11, 20), "0.9")
    divisas.guardar(conn, "USD", date(2026, 11, 10), "0.8")
    assert divisas.ultima(conn, "USD") == Decimal("0.9")


def test_total_convierte_a_euros(conn):
    eur = comprar(conn, "Europea", "EUR", "SAN.MC", precio="10", n="2")  # invierte 20
    usd = comprar(conn, "Apple", "USD", "AAPL", precio="100", n="1")  # invierte 100 USD
    precios.anadir(conn, eur, date(2026, 11, 20), "15")  # valor 30 EUR
    precios.anadir(conn, usd, date(2026, 11, 20), "150")  # valor 150 USD
    divisas.guardar(conn, "USD", date(2026, 11, 20), "0.9")
    t = cartera.total(conn)
    assert t["invertido"] == Decimal("110.0")  # 20 + 100*0.9
    assert t["valor"] == Decimal("165.0")  # 30 + 150*0.9
    assert t["ganancia"] == Decimal("55.0")
    assert t["rentabilidad"] == Decimal("0.5")
    assert t["excluidos"] == []


def test_total_excluye_sin_precio_y_sin_tasa(conn):
    ok = comprar(conn, "Ok", "EUR", "SAN.MC")
    sin_tasa = comprar(conn, "SinTasa", "USD", "AAPL")
    comprar(conn, "SinPrecio", "EUR", "BBVA.MC")
    precios.anadir(conn, ok, date(2026, 11, 20), "11")
    precios.anadir(conn, sin_tasa, date(2026, 11, 20), "11")
    t = cartera.total(conn)
    assert t["valor"] == Decimal("22")
    assert t["invertido"] == Decimal("20")  # solo lo valorado: no mezcla
    assert sorted(t["excluidos"]) == [
        ("SinPrecio", "sin precio"),
        ("SinTasa", "sin tipo de cambio USD/EUR"),
    ]


def test_total_vacio(conn):
    assert cartera.total(conn) == {
        "invertido": None,
        "valor": None,
        "ganancia": None,
        "rentabilidad": None,
        "excluidos": [],
    }


def test_resumen_incluye_divisa(conn):
    comprar(conn, "Apple", "USD", "AAPL")
    assert cartera.resumen(conn)[0]["divisa"] == "USD"


def test_actualizar_todos_incluye_divisas(conn, monkeypatch):
    comprar(conn, "Apple", "USD", "AAPL")
    comprar(conn, "Europea", "EUR", "SAN.MC")
    monkeypatch.setattr(yahoo, "actualizar", lambda c, i: (date(2026, 11, 20), Decimal("1")))
    monkeypatch.setattr(divisas.yf, "Ticker", FakeTicker)
    res = actualizacion.actualizar_todos(conn, date(2026, 11, 22))
    assert [d["divisa"] for d in res["divisas"]] == ["USD"]  # EUR no se pide
    assert res["divisas"][0]["estado"] == "ok"
    assert divisas.ultima(conn, "USD") == Decimal("0.923457")


def test_error_de_divisa_no_corta(conn, monkeypatch):
    comprar(conn, "Apple", "USD", "AAPL")
    monkeypatch.setattr(yahoo, "actualizar", lambda c, i: (date(2026, 11, 20), Decimal("1")))
    monkeypatch.setattr(divisas.yf, "Ticker", lambda s: FakeTicker(s, vacio=True))
    res = actualizacion.actualizar_todos(conn, date(2026, 11, 22))
    assert res["filas"][0]["estado"] == "ok"
    assert res["divisas"][0]["estado"] == "error"
