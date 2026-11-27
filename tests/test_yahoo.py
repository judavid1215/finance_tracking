from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from finanzas import compras, db, instrumentos, precios, yahoo


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


class FakeHistorico(FakeTicker):
    """Tres días de mercado (con un viernes y un lunes) y un hueco sin dato."""

    def __init__(self, simbolo, divisa="EUR", vacio=False):
        super().__init__(simbolo, divisa)
        indice = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
        self._h = pd.DataFrame({"Close": [10.0, 11.5, float("nan"), 12.12345]}, index=indice)
        if vacio:
            self._h = self._h.iloc[0:0]

    def history(self, start=None, auto_adjust=True, period=None):
        self.llamada = (start, auto_adjust)
        return self._h


def comprado(conn, desde="2026-01-02", divisa="EUR"):
    id_ = instrumentos.anadir(conn, "ETF", "etf", divisa, "IE00BYX5NX33")
    compras.anadir(conn, id_, date.fromisoformat(desde), "1", "10")
    return id_


def test_leer_historico_salta_huecos_y_no_ajusta(monkeypatch):
    ticker = FakeHistorico("X")
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: ticker)
    filas, divisa = yahoo.leer_historico("X", date(2026, 1, 2))
    assert filas == [
        (date(2026, 1, 2), Decimal("10.0")),
        (date(2026, 1, 5), Decimal("11.5")),
        (date(2026, 1, 7), Decimal("12.1235")),
    ]
    assert divisa == "EUR"
    assert ticker.llamada == ("2026-01-02", False)


def test_historico_vacio(monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: FakeHistorico(s, vacio=True))
    with pytest.raises(ValueError):
        yahoo.leer_historico("X", date(2026, 1, 2))


def test_descargar_historico_desde_primera_compra(conn, monkeypatch):
    ticker = FakeHistorico("X")
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: ticker)
    id_ = comprado(conn, "2026-01-02")
    compras.anadir(conn, id_, date(2026, 3, 1), "1", "10")  # una compra posterior no cambia nada
    assert yahoo.descargar_historico(conn, id_) == (date(2026, 1, 2), date(2026, 1, 7), 3)
    assert ticker.llamada[0] == "2026-01-02"
    assert precios.ultimo(conn, id_) == Decimal("12.1235")
    n = conn.execute("SELECT COUNT(*) FROM precios WHERE instrumento_id=?", (id_,)).fetchone()[0]
    assert n == 3


def test_descargar_historico_completa_con_morningstar(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeHistorico)  # Yahoo llega hasta el 7
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 1, 8), Decimal("13"), "EUR")
    )
    id_ = comprado(conn, "2026-01-02")
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 9)) == (
        date(2026, 1, 2),
        date(2026, 1, 8),
        4,
    )
    assert precios.ultimo(conn, id_) == Decimal("13")


def test_descargar_historico_morningstar_no_pisa_a_yahoo(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeHistorico)
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 1, 7), Decimal("1"), "EUR")
    )
    id_ = comprado(conn, "2026-01-02")
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 9))[2] == 3
    assert precios.ultimo(conn, id_) == Decimal("12.1235")


def test_descargar_historico_dos_veces_no_duplica(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeHistorico)
    id_ = comprado(conn)
    yahoo.descargar_historico(conn, id_)
    yahoo.descargar_historico(conn, id_)
    n = conn.execute("SELECT COUNT(*) FROM precios WHERE instrumento_id=?", (id_,)).fetchone()[0]
    assert n == 3


def test_historico_sin_compras(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeHistorico)
    id_ = instrumentos.anadir(conn, "ETF", "etf", "EUR", "IE00BYX5NX33")
    with pytest.raises(ValueError, match="compras"):
        yahoo.descargar_historico(conn, id_)


def test_historico_divisa_distinta_no_guarda(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: FakeHistorico(s, divisa="USD"))
    id_ = comprado(conn)
    with pytest.raises(ValueError):
        yahoo.descargar_historico(conn, id_)
    assert precios.ultimo(conn, id_) is None


def test_historico_rechaza_planes(conn):
    plan = instrumentos.anadir(conn, "Plan", "plan_pensiones", "EUR", "N5396")
    with pytest.raises(ValueError):
        yahoo.descargar_historico(conn, plan)


class FakeFiltrado(FakeHistorico):
    """Como FakeHistorico, pero solo devuelve lo posterior o igual a `start`, y cuenta llamadas."""

    llamadas: list = []

    def history(self, start=None, auto_adjust=True, period=None):
        FakeFiltrado.llamadas.append(start)
        return self._h[self._h.index >= pd.Timestamp(start)]


def test_segunda_descarga_solo_baja_lo_que_falta(conn, monkeypatch):
    FakeFiltrado.llamadas = []
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeFiltrado)
    id_ = comprado(conn, "2026-01-02")
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 6)) == (
        date(2026, 1, 2),
        date(2026, 1, 5),
        2,
    )  # el 6 (hoy) no se guarda; el hueco del 6 de la fake no cuenta
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 6)) == (None, None, 0)
    # al día siguiente solo llega lo nuevo (el 7); se pide desde el último día guardado (el 5)
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 8)) == (
        date(2026, 1, 7),
        date(2026, 1, 7),
        1,
    )
    assert FakeFiltrado.llamadas == ["2026-01-02", "2026-01-05", "2026-01-05"]
    n = conn.execute("SELECT COUNT(*) FROM precios WHERE instrumento_id=?", (id_,)).fetchone()[0]
    assert n == 3


def test_si_ya_esta_al_dia_no_llama_a_yahoo(conn, monkeypatch):
    FakeFiltrado.llamadas = []
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeFiltrado)
    id_ = comprado(conn, "2026-01-02")
    precios.anadir(conn, id_, date(2026, 1, 2), "10")
    precios.anadir(conn, id_, date(2026, 1, 7), "10")
    assert yahoo.descargar_historico(conn, id_, date(2026, 1, 7)) == (None, None, 0)
    assert FakeFiltrado.llamadas == []


def test_hoy_no_se_guarda(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeFiltrado)
    id_ = comprado(conn, "2026-01-02")
    yahoo.descargar_historico(conn, id_, date(2026, 1, 5))  # solo el día 2 es anterior a hoy
    assert precios.rango(conn, id_) == (date(2026, 1, 2), date(2026, 1, 2))


def test_compra_antigua_nueva_vuelve_a_bajar_todo(conn, monkeypatch):
    FakeFiltrado.llamadas = []
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeFiltrado)
    id_ = comprado(conn, "2026-01-02")
    precios.anadir(conn, id_, date(2026, 3, 1), "10")  # lo guardado empieza mucho después
    yahoo.descargar_historico(conn, id_, date(2026, 12, 1))
    assert FakeFiltrado.llamadas == ["2026-01-02"]


def test_con_ticker_yahoo_se_busca_por_el_ticker_y_no_por_el_isin(conn, monkeypatch):
    pedidos = []

    def ticker(simbolo):
        pedidos.append(simbolo)
        return FakeHistorico(simbolo)

    monkeypatch.setattr(yahoo.yf, "Ticker", ticker)
    id_ = instrumentos.anadir(conn, "DNB", "Fondo", "EUR", "LU0302296495", "0P00009PQ4.F")
    compras.anadir(conn, id_, date(2026, 1, 2), "1", "10")
    yahoo.descargar_historico(conn, id_)
    yahoo.consultar(conn, id_)
    assert pedidos and set(pedidos) == {"0P00009PQ4.F"}


def test_sin_ticker_yahoo_se_busca_por_el_identificador(conn, monkeypatch):
    pedidos = []
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: pedidos.append(s) or FakeTicker(s))
    id_ = instrumentos.anadir(conn, "DNB", "Fondo", "EUR", "LU0302296495")
    yahoo.consultar(conn, id_)
    assert pedidos == ["LU0302296495"]


XML_MS = '<Security><LastPrice date="21-11-2026 00:00:00" currency="EUR" marketTimeZone="GMT">14.2<'


def test_morningstar_leer_precio():
    from finanzas import morningstar

    assert morningstar.leer_precio("X", xml=XML_MS) == (date(2026, 11, 21), Decimal("14.2"), "EUR")
    with pytest.raises(ValueError):
        morningstar.leer_precio("X", xml="<Response/>")


def test_gana_morningstar_si_es_mas_reciente(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)  # Yahoo: 20-11
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 11, 21), Decimal("14.2"), "EUR")
    )
    id_ = instrumentos.anadir(conn, "Fondo", "fondo", "EUR", "LU0996175948")
    assert yahoo.actualizar(conn, id_) == (date(2026, 11, 21), Decimal("14.2"))
    assert precios.ultimo(conn, id_) == Decimal("14.2")


def test_gana_yahoo_si_morningstar_no_es_mas_reciente(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 11, 20), Decimal("1"), "EUR")
    )
    id_ = instrumentos.anadir(conn, "Fondo", "fondo", "EUR", "LU0996175948")
    assert yahoo.consultar(conn, id_) == (date(2026, 11, 20), Decimal("13.9519"))


def test_morningstar_en_otra_divisa_se_ignora(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 11, 25), Decimal("9"), "USD")
    )
    id_ = instrumentos.anadir(conn, "Fondo", "fondo", "EUR", "LU0996175948")
    assert yahoo.consultar(conn, id_)[0] == date(2026, 11, 20)


def test_si_yahoo_falla_sirve_morningstar(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", lambda s: FakeTicker(s, vacio=True))
    monkeypatch.setattr(
        yahoo.morningstar, "leer_precio", lambda isin: (date(2026, 11, 21), Decimal("14.2"), "EUR")
    )
    id_ = instrumentos.anadir(conn, "Fondo", "fondo", "EUR", "LU0996175948")
    assert yahoo.consultar(conn, id_) == (date(2026, 11, 21), Decimal("14.2"))


def test_cripto_no_consulta_morningstar(conn, monkeypatch):
    monkeypatch.setattr(yahoo.yf, "Ticker", FakeTicker)

    def no_debe_llamarse(isin):
        raise AssertionError("Morningstar solo para ISIN")

    monkeypatch.setattr(yahoo.morningstar, "leer_precio", no_debe_llamarse)
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "btc-eur")
    assert yahoo.consultar(conn, id_)[0] == date(2026, 11, 20)
