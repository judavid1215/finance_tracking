from datetime import UTC, date, datetime, timezone
from decimal import Decimal

import pytest

from finanzas import compras, db, instrumentos, mercado


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def sin_cache_divisas():
    mercado._divisas_ok.clear()
    mercado._ultimo_intento.clear()
    yield
    mercado._divisas_ok.clear()
    mercado._ultimo_intento.clear()


def utc(texto):
    return datetime.fromisoformat(texto).replace(tzinfo=UTC)


def comprar(conn, nombre, tipo, ident, divisa="EUR"):
    id_ = instrumentos.anadir(conn, nombre, tipo, divisa, ident)
    compras.anadir(conn, id_, date(2026, 1, 1), "1", "10")
    return id_


def filas(conn, id_):
    return [
        (f["momento"], f["precio"])
        for f in conn.execute(
            "SELECT momento, precio FROM precios_mercado WHERE instrumento_id=? ORDER BY momento",
            (id_,),
        )
    ]


def falso_yahoo(monkeypatch, barras, divisa="EUR"):
    monkeypatch.setattr(mercado, "leer_ultimas_barras", lambda simbolos: barras(simbolos))

    class T:
        fast_info = {"currency": divisa}

    monkeypatch.setattr(mercado.yf, "Ticker", lambda s: T())


def test_tick_guarda_con_la_hora_de_yahoo(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    falso_yahoo(
        monkeypatch, lambda s: {"BTC-EUR": (utc("2026-11-26T10:03:00"), Decimal("80000.5"))}
    )
    [fila] = mercado.registrar_ticks(conn)
    assert fila["estado"] == "nuevo"
    assert filas(conn, id_) == [("2026-11-26T10:03:00Z", "80000.5")]


def test_hora_se_pasa_a_utc(conn, monkeypatch):
    from datetime import timedelta

    id_ = comprar(conn, "Apple", "accion", "AAPL", "EUR")
    zona = timezone(timedelta(hours=-5))
    momento = datetime(2026, 11, 26, 10, 0, tzinfo=zona)
    falso_yahoo(monkeypatch, lambda s: {"AAPL": (momento, Decimal("200"))})
    mercado.registrar_ticks(conn)
    assert filas(conn, id_) == [("2026-11-26T15:00:00Z", "200")]


def test_mercado_cerrado_no_duplica(conn, monkeypatch):
    id_ = comprar(conn, "Apple", "accion", "AAPL")
    falso_yahoo(monkeypatch, lambda s: {"AAPL": (utc("2026-11-26T20:59:00"), Decimal("200"))})
    assert mercado.registrar_ticks(conn)[0]["estado"] == "nuevo"
    assert mercado.registrar_ticks(conn)[0]["estado"] == "repetido"
    assert len(filas(conn, id_)) == 1


def test_fondos_y_planes_no_hacen_tick(conn, monkeypatch):
    comprar(conn, "Fondo", "fondo", "LU0996175948")
    comprar(conn, "Plan", "plan_pensiones", "N5396")
    pedidos = []
    falso_yahoo(monkeypatch, lambda s: pedidos.append(s) or {})
    assert mercado.registrar_ticks(conn) == []
    assert pedidos == []


def test_sin_posicion_no_hace_tick(conn, monkeypatch):
    instrumentos.anadir(conn, "Apple", "accion", "EUR", "AAPL")  # sin compras
    pedidos = []
    falso_yahoo(monkeypatch, lambda s: pedidos.append(s) or {})
    assert mercado.registrar_ticks(conn) == []
    assert pedidos == []


def test_una_sola_peticion_para_todos(conn, monkeypatch):
    comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    comprar(conn, "Apple", "accion", "AAPL")
    comprar(conn, "ETF", "etf", "IE00BYX5NX33")
    llamadas = []
    falso_yahoo(monkeypatch, lambda s: llamadas.append(list(s)) or {})
    mercado.registrar_ticks(conn)
    assert llamadas == [["BTC-EUR", "AAPL", "IE00BYX5NX33"]]


def test_sin_barra_es_error_pero_los_demas_siguen(conn, monkeypatch):
    comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    apple = comprar(conn, "Apple", "accion", "AAPL")
    falso_yahoo(monkeypatch, lambda s: {"AAPL": (utc("2026-11-26T15:00:00"), Decimal("200"))})
    res = {f["nombre"]: f for f in mercado.registrar_ticks(conn)}
    assert res["Bitcoin"]["estado"] == "error"
    assert res["Apple"]["estado"] == "nuevo"
    assert len(filas(conn, apple)) == 1


def test_fallo_de_red_no_lanza(conn, monkeypatch):
    comprar(conn, "Bitcoin", "cripto", "BTC-EUR")

    def falla(simbolos):
        raise OSError("sin red")

    falso_yahoo(monkeypatch, falla)
    [fila] = mercado.registrar_ticks(conn)
    assert fila["estado"] == "error" and "sin red" in fila["mensaje"]


def test_divisa_distinta_no_guarda(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR", "EUR")
    falso_yahoo(
        monkeypatch,
        lambda s: {"BTC-EUR": (utc("2026-11-26T10:00:00"), Decimal("1"))},
        divisa="USD",
    )
    assert mercado.registrar_ticks(conn)[0]["estado"] == "error"
    assert filas(conn, id_) == []


def guardar(conn, id_, momento, precio):
    conn.execute(
        "INSERT INTO precios_mercado (instrumento_id, momento, precio) VALUES (?,?,?)",
        (id_, momento, precio),
    )
    conn.commit()


def test_compactar_deja_el_ultimo_de_cada_hora_con_la_hora_en_punto(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    for m, p in [
        ("2026-11-20T10:02:00Z", "1"),
        ("2026-11-20T10:30:00Z", "2"),
        ("2026-11-20T10:58:00Z", "3"),
        ("2026-11-20T11:01:00Z", "4"),
    ]:
        guardar(conn, id_, m, p)
    quitadas = mercado.compactar(conn, utc("2026-11-26T12:00:00"))
    assert quitadas == 2
    assert filas(conn, id_) == [("2026-11-20T10:00:00Z", "3"), ("2026-11-20T11:00:00Z", "4")]


def test_compactar_no_toca_lo_reciente(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    for m in ["2026-11-26T10:02:00Z", "2026-11-26T10:04:00Z", "2026-11-24T12:30:00Z"]:
        guardar(conn, id_, m, "1")
    # corte: 24-11 12:00 (48 h antes, hora en punto); todo es posterior o igual
    assert mercado.compactar(conn, utc("2026-11-26T12:30:00")) == 0
    assert len(filas(conn, id_)) == 3


def test_compactar_es_idempotente_y_respeta_la_hora_ya_guardada(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    guardar(conn, id_, "2026-11-20T10:00:00Z", "9")  # p. ej. rellenada desde Yahoo
    guardar(conn, id_, "2026-11-20T10:30:00Z", "5")  # un tick posterior de esa hora
    ahora = utc("2026-11-26T12:00:00")
    mercado.compactar(conn, ahora)
    assert filas(conn, id_) == [("2026-11-20T10:00:00Z", "5")]
    assert mercado.compactar(conn, ahora) == 0
    assert filas(conn, id_) == [("2026-11-20T10:00:00Z", "5")]


def test_compactar_separa_instrumentos(conn):
    a = instrumentos.anadir(conn, "A", "cripto", "EUR", "A-EUR")
    b = instrumentos.anadir(conn, "B", "cripto", "EUR", "B-EUR")
    guardar(conn, a, "2026-11-20T10:10:00Z", "1")
    guardar(conn, b, "2026-11-20T10:20:00Z", "2")
    mercado.compactar(conn, utc("2026-11-26T12:00:00"))
    assert filas(conn, a) == [("2026-11-20T10:00:00Z", "1")]
    assert filas(conn, b) == [("2026-11-20T10:00:00Z", "2")]


def test_borrar_instrumento_borra_sus_ticks(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    guardar(conn, id_, "2026-11-26T10:00:00Z", "1")
    instrumentos.borrar(conn, id_)
    assert conn.execute("SELECT COUNT(*) FROM precios_mercado").fetchone()[0] == 0


def test_vista_precios_mercado_detalle(conn):
    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    guardar(conn, id_, "2026-11-26T10:03:00Z", "80000.5")
    guardar(conn, id_, "2026-11-26T10:05:00Z", "80010")
    filas = conn.execute("SELECT * FROM precios_mercado_detalle").fetchall()
    assert [f["momento_utc"] for f in filas] == ["26-11-2026 10:05:00", "26-11-2026 10:03:00"]
    f = filas[0]
    assert (f["instrumento"], f["identificador"], f["tipo"], f["divisa"], f["precio"]) == (
        "Bitcoin", "BTC-EUR", "Cripto", "EUR", "80010",
    )
    assert f["hora_local"] is not None


AHORA = utc("2026-11-26T12:30:00")


def falso_horario(monkeypatch, barras, divisa="EUR"):
    pedidos = []

    def leer(simbolo, desde):
        pedidos.append((simbolo, desde))
        return barras, divisa

    monkeypatch.setattr(mercado, "leer_historico_horario", leer)
    return pedidos


def test_horas_primera_vez_baja_desde_la_primera_compra(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")  # compra el 2026-01-01
    pedidos = falso_horario(
        monkeypatch,
        [
            (utc("2026-11-26T09:00:00"), Decimal("1")),
            (utc("2026-11-26T10:00:00"), Decimal("2")),
            (utc("2026-11-26T12:00:00"), Decimal("3")),  # hora sin terminar: no entra
        ],
    )
    [fila] = mercado.rellenar_horas(conn, AHORA)
    assert fila == {"nombre": "Bitcoin", "estado": "ok", "nuevas": 2}
    assert pedidos == [("BTC-EUR", utc("2026-01-01T00:00:00"))]
    assert filas(conn, id_) == [("2026-11-26T09:00:00Z", "1"), ("2026-11-26T10:00:00Z", "2")]


def test_horas_us_con_barras_a_y_media_se_guardan_a_la_hora_en_punto(conn, monkeypatch):
    id_ = comprar(conn, "Apple", "accion", "AAPL")
    falso_horario(
        monkeypatch,
        [(utc("2026-11-25T14:30:00"), Decimal("7")), (utc("2026-11-25T15:30:00"), Decimal("8"))],
    )
    mercado.rellenar_horas(conn, AHORA)
    assert filas(conn, id_) == [("2026-11-25T14:00:00Z", "7"), ("2026-11-25T15:00:00Z", "8")]


def test_horas_no_pisa_una_hora_que_ya_tiene_ticks(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    guardar(conn, id_, "2026-11-26T09:20:00Z", "5")
    falso_horario(
        monkeypatch,
        [(utc("2026-11-26T09:00:00"), Decimal("1")), (utc("2026-11-26T10:00:00"), Decimal("2"))],
    )
    [fila] = mercado.rellenar_horas(conn, AHORA)
    assert fila["nuevas"] == 1
    assert filas(conn, id_) == [("2026-11-26T09:20:00Z", "5"), ("2026-11-26T10:00:00Z", "2")]


def test_horas_despues_pide_desde_lo_ultimo_guardado(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    guardar(conn, id_, "2026-01-02T00:00:00Z", "1")
    guardar(conn, id_, "2026-11-26T05:00:00Z", "1")
    pedidos = falso_horario(monkeypatch, [])
    mercado.rellenar_horas(conn, AHORA)
    assert pedidos == [("BTC-EUR", utc("2026-11-26T05:00:00"))]


def test_horas_si_lo_guardado_empieza_tarde_baja_todo_otra_vez(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    guardar(conn, id_, "2026-06-01T00:00:00Z", "1")  # mucho después de la compra
    guardar(conn, id_, "2026-11-26T05:00:00Z", "1")
    pedidos = falso_horario(monkeypatch, [])
    mercado.rellenar_horas(conn, AHORA)
    assert pedidos == [("BTC-EUR", utc("2026-01-01T00:00:00"))]


def test_horas_limite_de_yahoo(conn, monkeypatch):
    from datetime import timedelta

    id_ = instrumentos.anadir(conn, "Bitcoin", "cripto", "EUR", "BTC-EUR")
    compras.anadir(conn, id_, date(2020, 1, 1), "1", "10")
    pedidos = falso_horario(monkeypatch, [])
    mercado.rellenar_horas(conn, AHORA)
    assert pedidos[0][1] == AHORA - timedelta(days=mercado.DIAS_HISTORICO_HORARIO)


def test_horas_con_ticks_recientes_no_consulta(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    guardar(conn, id_, "2026-01-02T00:00:00Z", "1")  # el histórico ya está
    guardar(conn, id_, "2026-11-26T11:00:00Z", "1")  # hace 1 h 30
    pedidos = falso_horario(monkeypatch, [])
    assert mercado.rellenar_horas(conn, AHORA)[0]["estado"] == "al_dia"
    assert pedidos == []


def test_horas_con_ticks_recientes_pero_sin_historico_lo_baja(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    guardar(conn, id_, "2026-11-26T12:00:00Z", "1")  # solo ticks de hoy
    pedidos = falso_horario(monkeypatch, [(utc("2026-11-20T09:00:00"), Decimal("4"))])
    assert mercado.rellenar_horas(conn, AHORA)[0]["nuevas"] == 1
    assert pedidos == [("BTC-EUR", utc("2026-01-01T00:00:00"))]


def test_horas_no_repite_la_consulta_en_una_hora(conn, monkeypatch):
    comprar(conn, "Apple", "accion", "AAPL")
    pedidos = falso_horario(monkeypatch, [])
    mercado.rellenar_horas(conn, AHORA)
    from datetime import timedelta

    assert mercado.rellenar_horas(conn, AHORA + timedelta(minutes=2))[0]["estado"] == "al_dia"
    mercado.rellenar_horas(conn, AHORA + timedelta(hours=1, minutes=1))
    assert len(pedidos) == 2


def test_horas_divisa_distinta_o_fallo_de_red_no_guardan(conn, monkeypatch):
    id_ = comprar(conn, "Bitcoin", "cripto", "BTC-EUR")
    falso_horario(monkeypatch, [(utc("2026-11-26T09:00:00"), Decimal("1"))], divisa="USD")
    assert mercado.rellenar_horas(conn, AHORA)[0]["estado"] == "error"
    mercado._ultimo_intento.clear()

    def falla(simbolo, desde):
        raise OSError("sin red")

    monkeypatch.setattr(mercado, "leer_historico_horario", falla)
    [fila] = mercado.rellenar_horas(conn, AHORA)
    assert fila["estado"] == "error" and "sin red" in fila["mensaje"]
    assert filas(conn, id_) == []


def test_horas_ignora_fondos(conn, monkeypatch):
    comprar(conn, "Fondo", "fondo", "LU0996175948")
    pedidos = falso_horario(monkeypatch, [])
    assert mercado.rellenar_horas(conn, AHORA) == []
    assert pedidos == []
