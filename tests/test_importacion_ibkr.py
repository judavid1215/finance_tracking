from datetime import date
from decimal import Decimal

import pytest

from finanzas import compras, db, grupos, importacion_ibkr, instrumentos, ventas

CABECERA = (
    '"CurrencyPrimary","FXRateToBase","AssetClass","Symbol","Description","Conid","ISIN",'
    '"TradeID","DateTime","TradeDate","Quantity","TradeMoney","IBCommission",'
    '"IBCommissionCurrency","NetCash","OrigTradePrice","Buy/Sell","IBOrderID","TransactionID"'
)


def fila(
    divisa, clase, simbolo, trade_id, fecha, cant, dinero, comision, lado, orden, desc=None, isin=""
):
    return (
        f'"{divisa}","1","{clase}","{simbolo}","{desc or simbolo + " INC"}","1","{isin}",'
        f'"{trade_id}","{fecha};093000","{fecha}","{cant}","{dinero}","{comision}",'
        f'"{divisa}","0","0","{lado}","{orden}","9"'
    )


ISIN_IBE = "ES0144580Y14"
FILAS = [
    # una orden en tres ejecuciones, con una devolución de comisión (IBKR la netea)
    fila(
        "EUR", "STK", "IBE", "1", "20260226", 1, "20.09", -3, "BUY", 10, "IBERDROLA SA.", ISIN_IBE
    ),
    fila(
        "EUR", "STK", "IBE", "2", "20260226", 3, "60.27", 1.75, "BUY", 10, "IBERDROLA SA.", ISIN_IBE
    ),
    fila(
        "EUR", "STK", "IBE", "3", "20260226", "0.5", "10", 0, "BUY", 10, "IBERDROLA SA.", ISIN_IBE
    ),
    fila("USD", "STK", "NVDA", "4", "20260416", "0.5", "100", "-0.35", "BUY", 11, "NVIDIA"),
    fila("USD", "STK", "NVDA", "5", "20260501", "-0.25", "-60", "-0.35", "SELL", 12, "NVIDIA"),
    fila("USD", "CASH", "EUR.USD", "6", "20260416", "-0.3", "-0.35", 0, "SELL", 13),
    fila("EUR", "STK", "IBE.D", "", "20260703", "-0.9", "-0.4", 0, "SELL", 14, "IBE RTS"),
]


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def escribir(tmp_path, filas=FILAS, envoltorio=True):
    lineas = [CABECERA, *filas]
    if envoltorio:
        lineas = ['"BOF","U1"', '"BOS","TRNT","Trades"', *lineas, '"EOS","TRNT","7"', '"EOF"']
    ruta = tmp_path / "ibkr.csv"
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def importar(conn, ruta, grupo="IBKR", **kw):
    plan = importacion_ibkr.preparar(conn, ruta, grupo, **kw)
    importacion_ibkr.aplicar(conn, plan)
    return plan


def test_junta_las_ejecuciones_de_una_orden_y_netea_la_comision(conn, tmp_path):
    plan = importar(conn, escribir(tmp_path), tickers_yahoo={"ibe": "ibe.xx"})
    assert plan["ignoradas"] == {"cambios_divisa": 1, "sin_tradeid": 1, "otras": 0}
    ibe = next(i for i in instrumentos.listar(conn) if i["identificador"] == "IBE")
    assert (ibe["tipo"], ibe["divisa"], ibe["ticker_yahoo"]) == ("Accion", "EUR", "IBE.XX")
    [c] = compras.listar(conn, ibe["id"])
    assert c["fecha"] == date(2026, 2, 26) and c["participaciones"] == Decimal("4.5")
    assert c["precio"] * c["participaciones"] == Decimal("90.36") and c["comision"] == Decimal(
        "1.25"
    )
    assert c["grupo"] == "IBKR"


def test_las_ventas_se_importan_y_las_filas_sin_tradeid_y_el_cambio_de_divisa_no(conn, tmp_path):
    importar(conn, escribir(tmp_path))
    assert {i["identificador"] for i in instrumentos.listar(conn)} == {"IBE", "NVDA"}
    nvda = next(i for i in instrumentos.listar(conn) if i["identificador"] == "NVDA")
    [v] = ventas.listar(conn, nvda["id"])
    assert (v["participaciones"], v["precio"], v["comision"]) == (
        Decimal("0.25"),
        Decimal("240"),
        Decimal("0.35"),
    )


def test_funciona_sin_las_lineas_bof_eos(conn, tmp_path):
    plan = importar(conn, escribir(tmp_path, envoltorio=False))
    assert len(plan["operaciones"]) == 3


def test_reimportar_no_duplica(conn, tmp_path):
    ruta = escribir(tmp_path)
    importar(conn, ruta)
    plan = importacion_ibkr.preparar(conn, ruta, "ibkr")
    assert plan["operaciones"] == [] and plan["repetidas"] == 3
    assert len(compras.listar(conn)) == 2 and len(ventas.listar(conn)) == 1


def test_reutiliza_el_instrumento_existente(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Nvidia a mano", "Accion", "USD", "NVDA")
    plan = importar(conn, escribir(tmp_path))
    assert "NVDA" not in plan["nuevos"] and len(compras.listar(conn, id_)) == 1


def test_una_venta_sin_compras_cancela_todo(conn, tmp_path):
    filas = [FILAS[0], fila("USD", "STK", "AMZN", "7", "20260301", "-1", "-100", 0, "SELL", 15)]
    plan = importacion_ibkr.preparar(conn, escribir(tmp_path, filas), "IBKR")
    with pytest.raises(ValueError, match="AMZN"):
        importacion_ibkr.aplicar(conn, plan)
    assert instrumentos.listar(conn) == [] and compras.listar(conn) == []
    assert grupos.obtener_por_nombre(conn, "IBKR") is None


def test_errores_de_formato_se_listan_todos(conn, tmp_path):
    filas = [
        fila("EUR", "STK", "IBE", "1", "20260226", "x", "20", 0, "BUY", 1),
        fila("EUR", "STK", "IBE", "2", "20260226", 1, "20", 0, "HOLD", 2),
    ]
    with pytest.raises(ValueError) as e:
        importacion_ibkr.preparar(conn, escribir(tmp_path, filas), "IBKR")
    assert "Quantity" in str(e.value) and "Buy/Sell" in str(e.value)
    assert instrumentos.listar(conn) == []


def test_falta_una_columna(conn, tmp_path):
    ruta = tmp_path / "mal.csv"
    ruta.write_text('"CurrencyPrimary","Symbol"\n"EUR","IBE"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="faltan columnas"):
        importacion_ibkr.preparar(conn, ruta, "IBKR")


def test_el_ticker_de_yahoo_sale_del_pais_del_isin_si_no_se_indica(conn, tmp_path):
    importar(conn, escribir(tmp_path))
    por_ticker = {i["identificador"]: i["ticker_yahoo"] for i in instrumentos.listar(conn)}
    assert por_ticker == {"IBE": "IBE.MC", "NVDA": None}  # las de EE. UU. no llevan sufijo


def test_reconoce_el_csv_de_ibkr_y_no_el_de_myinvestor(tmp_path):
    assert importacion_ibkr.es_flex_query(escribir(tmp_path))
    otro = tmp_path / "ordenes.csv"
    otro.write_text("Fecha de la orden;ISIN;Importe estimado\n", encoding="utf-8")
    assert not importacion_ibkr.es_flex_query(otro)
    assert not importacion_ibkr.es_flex_query(tmp_path / "no_existe.csv")
