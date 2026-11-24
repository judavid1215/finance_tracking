from datetime import date
from decimal import Decimal

import pytest

from finanzas import compras, db, evolucion, grupos, instrumentos, periodos, precios

D = Decimal


def _fila(dia, invertido, valor):
    return {
        "fecha": dia,
        "invertido": D(invertido),
        "valor": D(valor),
        "ganancia": D(valor) - D(invertido),
        "rentabilidad": None,
    }


def test_inicio_de_cada_periodo():
    hoy = date(2026, 3, 31)
    assert periodos.inicio("1S", hoy) == date(2026, 3, 24)
    assert periodos.inicio("1M", hoy) == date(2026, 2, 28)  # febrero es más corto
    assert periodos.inicio("1A", date(2028, 2, 29)) == date(2027, 2, 28)
    assert periodos.inicio("ytd", hoy) == date(2025, 12, 31)
    assert periodos.inicio("MAX", hoy) is None
    with pytest.raises(ValueError):
        periodos.inicio("2D", hoy)


def test_ganancia_del_periodo_descuenta_lo_anterior():
    filas = [
        _fila(date(2026, 1, 1), 100, 100),
        _fila(date(2026, 1, 10), 100, 110),  # base de 1S (corte 10 ene si hoy=17)
        _fila(date(2026, 1, 12), 100, 121),
        _fila(date(2026, 1, 17), 100, 132),
    ]
    r = periodos.recortar(filas, "1S", hoy=date(2026, 1, 17))
    assert r["desde"] == date(2026, 1, 12)
    assert [p["ganancia"] for p in r["puntos"]] == [D(11), D(22)]  # 21-10 y 32-10
    assert r["resumen"]["ganancia"] == D(22)
    assert r["resumen"]["rentabilidad"] == D("0.2")  # 22 / valor base 110


def test_aportar_no_cuenta_como_ganancia():
    filas = [
        _fila(date(2026, 1, 1), 100, 100),
        _fila(date(2026, 1, 12), 200, 200),  # aporta 100 sin ganar nada
    ]
    r = periodos.recortar(filas, "1S", hoy=date(2026, 1, 12))
    assert r["resumen"]["ganancia"] == D(0)
    assert r["resumen"]["valor"] == D(200)


def test_max_y_cartera_nueva_parten_de_cero():
    filas = [_fila(date(2026, 1, 1), 100, 100), _fila(date(2026, 1, 2), 100, 110)]
    r = periodos.recortar(filas, "max", hoy=date(2026, 1, 2))
    assert [p["ganancia"] for p in r["puntos"]] == [D(0), D(10)]
    assert r["resumen"]["rentabilidad"] == D("0.1")  # 10 / 100 invertido
    # 1A con cartera de 1 día de vida: sin base, igual que el máximo
    assert periodos.recortar(filas, "1A", hoy=date(2026, 1, 2))["puntos"] == r["puntos"]


def test_ignora_dias_futuros_y_sin_datos():
    filas = [_fila(date(2026, 1, 1), 100, 100), _fila(date(2026, 2, 1), 100, 200)]
    r = periodos.recortar(filas, "max", hoy=date(2026, 1, 15))
    assert len(r["puntos"]) == 1
    vacio = periodos.recortar(filas, "1S", hoy=date(2026, 3, 1))
    assert vacio["puntos"] == [] and vacio["resumen"] is None and vacio["desde"] is None
    assert periodos.recortar([], "max")["resumen"] is None


def test_serie_por_instrumento(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    a = instrumentos.anadir(conn, "A", "cripto", "EUR")
    b = instrumentos.anadir(conn, "B", "cripto", "EUR")
    for id_, precio in ((a, "10"), (b, "100")):
        compras.anadir(conn, id_, date(2026, 1, 1), "1", precio)
        precios.anadir(conn, id_, date(2026, 1, 1), precio)
    assert evolucion.serie(conn)[0]["valor"] == D(110)
    assert evolucion.serie(conn, instrumento_id=a)[0]["valor"] == D(10)
    assert evolucion.serie(conn, instrumento_id=b)[0]["valor"] == D(100)
    g = grupos.por_defecto(conn)
    assert evolucion.serie(conn, grupo_id=g, instrumento_id=a)[0]["valor"] == D(10)
    conn.close()


def test_aportaciones_se_situan_en_el_dia_del_grafico():
    filas = [
        _fila(date(2026, 1, 1), 100, 100),
        _fila(date(2026, 1, 12), 100, 110),
        _fila(date(2026, 1, 14), 200, 220),
        _fila(date(2026, 1, 15), 200, 225),
    ]
    compras = [
        {"fecha": date(2026, 1, 1), "importe": D(100), "instrumento": "A"},  # antes del corte
        {"fecha": date(2026, 1, 13), "importe": D(60), "instrumento": "A"},  # sin precio ese día
        {"fecha": date(2026, 1, 14), "importe": D(40), "instrumento": "B"},  # mismo día que ↑
        {"fecha": date(2026, 1, 16), "importe": D(5), "instrumento": "A"},  # sin precio todavía
    ]
    r = periodos.recortar(filas, "1S", hoy=date(2026, 1, 17), aportaciones=compras)
    assert r["aportaciones"] == [
        {"fecha": date(2026, 1, 14), "importe": D(100), "instrumentos": ["A", "B"]}
    ]
    # En el máximo entra también la primera compra
    r = periodos.recortar(filas, "max", hoy=date(2026, 1, 17), aportaciones=compras)
    assert [a["fecha"].day for a in r["aportaciones"]] == [1, 14]
    assert periodos.recortar(filas, "max", hoy=date(2026, 1, 17))["aportaciones"] == []


def test_aportaciones_en_euros_y_con_filtros(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    a = instrumentos.anadir(conn, "A", "cripto", "EUR")
    b = instrumentos.anadir(conn, "B", "cripto", "USD")
    pension = grupos.anadir(conn, "Pension")
    compras.anadir(conn, a, date(2026, 1, 1), "2", "10", comision="1")
    compras.anadir(conn, b, date(2026, 1, 2), "1", "100", grupo_id=pension)
    with pytest.raises(ValueError):  # USD sin tipo de cambio guardado
        evolucion.aportaciones(conn)
    conn.execute("INSERT INTO tipos_cambio VALUES ('USD', '2026-01-02', '0.5')")
    todo = evolucion.aportaciones(conn)
    assert [(x["instrumento"], x["importe"]) for x in todo] == [("A", D(21)), ("B", D(50))]
    assert [x["instrumento"] for x in evolucion.aportaciones(conn, instrumento_id=b)] == ["B"]
    assert [x["instrumento"] for x in evolucion.aportaciones(conn, grupo_id=pension)] == ["B"]
    conn.close()
