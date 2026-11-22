import importlib.util
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzas import compras, db, instrumentos, posicion, precios, ventas, yahoo

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "rellenar_datos.py"
_spec = importlib.util.spec_from_file_location("rellenar_datos", _RUTA)
rellenar_datos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rellenar_datos)

HOY = date(2026, 11, 22)


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def historico_falso(simbolo, desde, permitir_vacio=False):
    """Un día de mercado cada 3 días (precio = nº del día), en EUR salvo NVDA y AAPL."""
    filas = [
        (date.fromordinal(n), Decimal(n % 1000 + 10))
        for n in range(desde.toordinal(), HOY.toordinal() + 1)
        if n % 3 == 0
    ]
    return filas, "USD" if simbolo in ("NVDA", "AAPL") else "EUR"


def test_precios_reales_fechas_de_mercado_y_sin_precio_actual(conn, monkeypatch):
    monkeypatch.setattr(yahoo, "leer_historico", historico_falso)
    rellenar_datos.rellenar(conn, random.Random(1), HOY)
    assert len(instrumentos.listar(conn)) == 6
    assert conn.execute("SELECT COUNT(*) FROM precios").fetchone()[0] == 0
    # cada compra y venta de un instrumento de Yahoo usa un precio y un día del histórico falso
    for inst in instrumentos.listar(conn):
        if inst["id_tipo"] == "DGS":
            continue
        reales = dict(historico_falso(inst["identificador"], date(2025, 12, 1))[0])
        operaciones = compras.listar(conn, inst["id"]) + ventas.listar(conn, inst["id"])
        assert operaciones
        for o in operaciones:
            assert o["fecha"] < HOY
            assert o["precio"] == reales[o["fecha"]]
        assert len(compras.listar(conn, inst["id"])) == 12
        assert len(ventas.listar(conn, inst["id"])) == 2
        assert posicion.calcular(conn, inst["id"])["participaciones"] > 0


def test_plan_de_pensiones_con_precios_inventados(conn, monkeypatch):
    monkeypatch.setattr(yahoo, "leer_historico", historico_falso)
    rellenar_datos.rellenar(conn, random.Random(1), HOY)
    [plan] = instrumentos.listar(conn, "Plan_pensiones")
    assert len(compras.listar(conn, plan["id"])) == 12


def test_si_yahoo_falla_se_omite_sin_crear(conn, monkeypatch):
    def falla(simbolo, desde, permitir_vacio=False):
        if simbolo == "NVDA":
            raise OSError("sin conexión")
        return historico_falso(simbolo, desde)

    monkeypatch.setattr(yahoo, "leer_historico", falla)
    rellenar_datos.rellenar(conn, random.Random(1), HOY)
    nombres = {i["nombre"] for i in instrumentos.listar(conn)}
    assert "NVIDIA" not in nombres and len(nombres) == 5
    assert precios.ultimo(conn, instrumentos.listar(conn)[0]["id"]) is None


def test_mes_sin_dia_de_mercado_cerrado_se_salta(conn, monkeypatch):
    monkeypatch.setattr(yahoo, "leer_historico", historico_falso)
    rellenar_datos.rellenar(conn, random.Random(1), date(2026, 11, 3))  # el día 5 aún no llegó
    [msci] = [i for i in instrumentos.listar(conn) if i["nombre"] == "MSCI World"]
    assert len(compras.listar(conn, msci["id"])) == 11
