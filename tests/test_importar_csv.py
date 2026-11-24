from datetime import date
from decimal import Decimal

import pytest

from finanzas import compras, db, grupos, importacion, instrumentos

ISIN = "IE00BYX5NX33"
NOMBRE = "Mi fondo"
CABECERA = "Fecha de la orden;ISIN;Importe estimado;Nº de participaciones;Estado"

# (fecha dd/mm/aaaa, importe, participaciones, estado), como las exporta MyInvestor
ORDENES = [
    ("23/11/2026", "890 EUR", "", "En curso"),
    ("05/08/2026", "320 EUR", "20", "Finalizada"),
    ("26/03/2026", "180 EUR", "", "Rechazada"),
    ("04/06/2026", "4826.56 EUR", "413,956", "Finalizada"),
    ("29/04/2026", "525 EUR", "40,025", "Finalizada"),
]


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def escribir(tmp_path, ordenes=ORDENES, isin=ISIN, cabecera=CABECERA):
    filas = [cabecera] + [f"{f};{isin};{imp};{part};{est}" for f, imp, part, est in ordenes]
    ruta = tmp_path / "ordenes.csv"
    ruta.write_text("\n".join(filas) + "\n", encoding="utf-8")
    return ruta


def importar(conn, ruta, isin=ISIN, nombre=NOMBRE, divisa="EUR", **kw):
    return importacion.importar(conn, ruta, isin, nombre, divisa, **kw)


def test_importa_solo_las_finalizadas_con_precio_importe_sobre_participaciones(conn, tmp_path):
    plan = importar(conn, escribir(tmp_path))
    assert plan["ignoradas"] == 2 and plan["invertido"] == Decimal("5671.56")
    [inst] = instrumentos.listar(conn, "Fondo")
    assert (inst["nombre"], inst["divisa"], inst["identificador"]) == (NOMBRE, "EUR", ISIN)
    guardadas = {c["fecha"]: c for c in compras.listar(conn, inst["id"])}
    assert len(guardadas) == 3
    agosto = guardadas[date(2026, 8, 5)]
    assert (agosto["participaciones"], agosto["precio"], agosto["comision"]) == (
        Decimal(20),
        Decimal(16),
        0,
    )
    assert guardadas[date(2026, 6, 4)]["participaciones"] == Decimal("413.956")
    assert guardadas[date(2026, 6, 4)]["precio"] == Decimal("11.659597")  # 4826.56 / 413.956


def test_normaliza_isin_nombre_y_divisa(conn, tmp_path):
    importar(conn, escribir(tmp_path), isin=" ie00byx5nx33 ", nombre="  X  ", divisa="eur")
    [inst] = instrumentos.listar(conn)
    assert (inst["nombre"], inst["divisa"], inst["identificador"]) == ("X", "EUR", ISIN)


def test_rechaza_si_el_isin_o_la_divisa_no_son_los_del_csv(conn, tmp_path):
    with pytest.raises(ValueError, match="ISIN IE00BYX5NX33 y has indicado LU0996175948"):
        importar(conn, escribir(tmp_path), isin="LU0996175948")
    with pytest.raises(ValueError, match="está en EUR y has indicado USD"):
        importar(conn, escribir(tmp_path), divisa="USD")
    assert instrumentos.listar(conn) == []


def test_rechaza_fondo_que_ya_tiene_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Otro nombre", "Fondo", "EUR", ISIN)
    compras.anadir(conn, id_, date(2026, 1, 5), 1, 10)
    with pytest.raises(ValueError, match="ya tiene compras"):
        importar(conn, escribir(tmp_path))
    assert len(compras.listar(conn)) == 1


def test_reutiliza_instrumento_existente_sin_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Mi fondo", "Fondo", "EUR", ISIN)
    importar(conn, escribir(tmp_path))
    assert len(instrumentos.listar(conn)) == 1
    assert len(compras.listar(conn, id_)) == 3


def test_fila_mala_no_escribe_nada(conn, tmp_path):
    ruta = escribir(tmp_path)
    ruta.write_text(
        ruta.read_text(encoding="utf-8") + f"99/99/2026;{ISIN};1 EUR;1;Finalizada\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="línea 7"):
        importar(conn, ruta)
    assert instrumentos.listar(conn) == [] and compras.listar(conn) == []


def test_si_falla_al_escribir_se_deshace_todo(conn, tmp_path, monkeypatch):
    reales = compras.anadir
    llamadas = []

    def falla_a_la_tercera(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 3:
            raise RuntimeError("disco lleno")
        return reales(*args, **kwargs)

    monkeypatch.setattr(compras, "anadir", falla_a_la_tercera)
    with pytest.raises(RuntimeError):
        importar(conn, escribir(tmp_path))
    assert instrumentos.listar(conn) == [] and compras.listar(conn) == []


@pytest.mark.parametrize(
    "isin, nombre, divisa, error",
    [
        ("IE00BYX5NX3", NOMBRE, "EUR", "ISIN no válido"),
        (ISIN, "  ", "EUR", "falta el nombre"),
        (ISIN, NOMBRE, "EU", "divisa no válida"),
    ],
)
def test_datos_de_entrada_invalidos(conn, tmp_path, isin, nombre, divisa, error):
    with pytest.raises(ValueError, match=error):
        importar(conn, escribir(tmp_path), isin, nombre, divisa)
    assert instrumentos.listar(conn) == []


def test_fichero_inexistente(conn, tmp_path):
    with pytest.raises(ValueError, match="no se puede leer"):
        importar(conn, tmp_path / "no_existe.csv")


def test_otra_divisa_si_coincide_con_el_csv(conn, tmp_path):
    ordenes = [("05/08/2026", "320 USD", "20", "Finalizada")]
    importar(conn, escribir(tmp_path, ordenes), divisa="USD")
    assert instrumentos.listar(conn)[0]["divisa"] == "USD"


@pytest.mark.parametrize(
    "orden, error",
    [
        (("01/01/2026", "10 EUR", "1.000,5", "Finalizada"), "número no válido"),
        (("01/01/2026", "10", "1", "Finalizada"), "importe no válido"),
        (("01/01/2026", "0 EUR", "1", "Finalizada"), "mayores"),
        (("01/01/2026", "10 EUR", "", "Finalizada"), "número no válido"),
        (("01/01/2026", "10 EUR", "1", "Pendiente"), "estado desconocido"),
    ],
)
def test_csv_mal_formado(tmp_path, orden, error):
    with pytest.raises(ValueError, match=error):
        importacion.leer_csv(escribir(tmp_path, [orden]))


def test_cabecera_incorrecta_o_sin_ordenes_finalizadas(tmp_path):
    with pytest.raises(ValueError, match="cabecera"):
        importacion.leer_csv(escribir(tmp_path, cabecera="Fecha fiscal;Inversión"))
    with pytest.raises(ValueError, match="ninguna orden finalizada"):
        importacion.leer_csv(escribir(tmp_path, [ORDENES[0], ORDENES[2]]))


def test_importar_csv_abre_la_base_escribe_y_devuelve_el_plan(tmp_path, capsys):
    ruta_db = tmp_path / "otra.sqlite3"
    plan = importacion.importar_csv(NOMBRE, ISIN, "EUR", escribir(tmp_path), ruta_db=ruta_db)
    salida = capsys.readouterr().out
    assert len(plan["compras"]) == 3 and "Hecho." in salida
    assert "2 orden(es) en curso o rechazadas ignoradas" in salida
    conn = db.conectar(ruta_db)
    assert len(compras.listar(conn)) == 3
    conn.close()


def test_importar_csv_con_error_no_escribe(tmp_path):
    ruta_db = tmp_path / "otra.sqlite3"
    with pytest.raises(ValueError, match="ISIN no válido"):
        importacion.importar_csv(NOMBRE, "XX", "EUR", escribir(tmp_path), ruta_db=ruta_db)
    conn = db.conectar(ruta_db)
    assert instrumentos.listar(conn) == []
    conn.close()


def test_importar_csv_con_fondo_ya_importado_avisa_y_sigue(tmp_path, capsys):
    ruta_db = tmp_path / "otra.sqlite3"
    ruta = escribir(tmp_path)
    importacion.importar_csv(NOMBRE, ISIN, "EUR", ruta, ruta_db=ruta_db)
    assert importacion.importar_csv(NOMBRE, ISIN, "EUR", ruta, ruta_db=ruta_db) is None
    assert "AVISO" in capsys.readouterr().out
    conn = db.conectar(ruta_db)
    assert len(compras.listar(conn)) == 3  # no se duplicó
    conn.close()


def test_ticker_yahoo_se_guarda_en_el_instrumento_nuevo_y_en_el_existente(conn, tmp_path):
    importar(conn, escribir(tmp_path), ticker_yahoo="0p00009pq4.f")
    assert instrumentos.listar(conn)[0]["ticker_yahoo"] == "0P00009PQ4.F"
    assert instrumentos.listar(conn)[0]["identificador"] == ISIN


def test_ticker_yahoo_en_instrumento_existente_sin_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Mi fondo", "Fondo", "EUR", ISIN)
    importar(conn, escribir(tmp_path), ticker_yahoo="X.F")
    assert instrumentos.obtener(conn, id_)["ticker_yahoo"] == "X.F"


def test_grupo_por_defecto_y_grupo_indicado_se_crea_si_no_existe(conn, tmp_path):
    ruta = escribir(tmp_path)
    importar(conn, ruta)
    assert {c["grupo"] for c in compras.listar(conn)} == {"Personal"}
    # el mismo fondo en otro grupo no es un duplicado
    plan = importar(conn, ruta, grupo="Pension")
    assert plan["grupo"] == "Pension" and plan["grupo_creado"] is True
    por_grupo = {}
    for c in compras.listar(conn):
        por_grupo[c["grupo"]] = por_grupo.get(c["grupo"], 0) + 1
    assert por_grupo == {"Personal": 3, "Pension": 3}
    assert len(instrumentos.listar(conn)) == 1  # un solo instrumento para los dos grupos


def test_reimportar_en_el_mismo_grupo_se_rechaza_pero_no_en_otro(conn, tmp_path):
    ruta = escribir(tmp_path)
    importar(conn, ruta, grupo="Pension")
    with pytest.raises(importacion.FondoYaImportado, match="grupo Pension"):
        importar(conn, ruta, grupo="pension")  # sin distinguir mayúsculas
    importar(conn, ruta, grupo="Personal")
    assert len(compras.listar(conn)) == 6


def test_grupo_vacio(conn, tmp_path):
    with pytest.raises(ValueError, match="falta el grupo"):
        importar(conn, escribir(tmp_path), grupo="  ")


def test_si_falla_al_escribir_no_deja_ni_el_grupo_nuevo(conn, tmp_path, monkeypatch):
    ruta = escribir(tmp_path)
    importar(conn, ruta, grupo="Personal")
    reales = compras.anadir
    llamadas = []

    def falla_a_la_segunda(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 2:
            raise RuntimeError("disco lleno")
        return reales(*args, **kwargs)

    monkeypatch.setattr(compras, "anadir", falla_a_la_segunda)
    with pytest.raises(RuntimeError):
        importar(conn, ruta, grupo="Pension")
    assert grupos.obtener_por_nombre(conn, "Pension") is None
    assert len(compras.listar(conn)) == 3  # lo del otro grupo sigue intacto


def test_importar_csv_con_grupo(tmp_path, capsys):
    ruta_db = tmp_path / "otra.sqlite3"
    importacion.importar_csv(
        NOMBRE, ISIN, "EUR", escribir(tmp_path), grupo="Pension", ruta_db=ruta_db
    )
    salida = capsys.readouterr().out
    assert "[Pension]" in salida and "Se ha creado el grupo 'Pension'" in salida
