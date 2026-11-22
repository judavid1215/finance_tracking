from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from finanzas import db, instrumentos, precios, yahoo


class FakeTicker:
    def __init__(self, simbolo, divisa="EUR", vacio=False):
        self.fast_info = {"currency": divisa}
        indice = pd.to_datetime(["2026-11-19", "2026-11-20"])
        self._h = pd.DataFrame({"Close": [13.5, 13.9519]}, index=indice)
        if vacio:
            self._h = self._h.iloc[0:0]

    def history(self, period):
        return self._h


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def test_leer_precio(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    assert yahoo.leer_precio("X") == (date(2026, 11, 20), Decimal("13.9519"), "EUR")


def test_sin_datos(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: FakeTicker(s, vacio=True))
    with pytest.raises(ValueError):
        yahoo.leer_precio("X")


def test_actualizar_guarda(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    id_ = instrumentos.anadir(conn, "ETF", "etf", "EUR", "IE00BYX5NX33")
    assert yahoo.actualizar(conn, id_) == (date(2026, 11, 20), Decimal("13.9519"))
    assert precios.ultimo(conn, id_) == Decimal("13.9519")


def test_divisa_distinta_no_guarda(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: FakeTicker(s, divisa="USD"))
    id_ = instrumentos.anadir(conn, "ETF", "etf", "EUR", "IE00BYX5NX33")
    with pytest.raises(ValueError):
        yahoo.actualizar(conn, id_)
    assert precios.ultimo(conn, id_) is None


def test_cripto_con_ticker(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "btc-eur")
    assert yahoo.actualizar(conn, id_)[1] == Decimal("13.9519")


def test_asignar_identificador_a_cripto_existente(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    with pytest.raises(ValueError):
        yahoo.actualizar(conn, id_)  # sin ticker todavía
    instrumentos.asignar_identificador(conn, id_, "btc-eur")
    assert instrumentos.obtener(conn, id_)["identificador"] == "BTC-EUR"
    yahoo.actualizar(conn, id_)


def test_rechaza_planes(conn):
    plan = instrumentos.anadir(conn, "Plan", "plan_pensiones", "EUR", "N5396")
    with pytest.raises(ValueError):
        yahoo.actualizar(conn, plan)
