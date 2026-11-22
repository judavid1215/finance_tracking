from datetime import date
from decimal import Decimal

import pytest

from finanzas import db, instrumentos, precios, quefondos

HTML = (
    '<span>Valor liquidativo: </span><span class="floatright">19,607890 EUR</span>'
    '<span>Fecha: </span><span class="floatright">19/11/2026</span>'
)


def test_lee_valor_y_fecha():
    assert quefondos.leer_precio("N5396", html=HTML) == (date(2026, 11, 19), Decimal("19.607890"))


def test_pagina_sin_datos():
    with pytest.raises(ValueError):
        quefondos.leer_precio("N5396", html="<html></html>")


def test_actualizar_guarda_precio(tmp_path, monkeypatch):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    id_ = instrumentos.anadir(conn, "Plan", "plan_pensiones", "EUR", "N5396")
    monkeypatch.setattr(
        quefondos, "leer_precio", lambda codigo: (date(2026, 11, 19), Decimal("19.6"))
    )
    assert quefondos.actualizar(conn, id_) == (date(2026, 11, 19), Decimal("19.6"))
    assert precios.ultimo(conn, id_) == Decimal("19.6")
    conn.close()


def test_actualizar_rechaza_otros_tipos(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR")
    with pytest.raises(ValueError):
        quefondos.actualizar(conn, id_)
    conn.close()
