import os
from datetime import date, datetime
from decimal import Decimal

import pytest

from finanzas import compras, db, grupos, importacion, instrumentos

ISIN = "IE00BYX5NX33"
NOMBRE = "Mi fondo"
EXPORT = date(2026, 11, 22)  # domingo; el último cierre anterior es el viernes 20
CABECERA = "Fecha fiscal;Inversión;Valor de mercado;Resultado fiscal"

LOTES = [
    (date(2026, 3, 2), Decimal("5.5")),
    (date(2026, 5, 6), Decimal("12")),
    (date(2026, 9, 1), Decimal("3.25")),
]


@pytest.fixture
def conn(tmp_path):
    conn = db.conectar(str(tmp_path / "t.sqlite3"))
    yield conn
    conn.close()


def precio(d: date) -> Decimal:
    """Precio de ejemplo que cambia mucho de un día a otro (para distinguir el NAV)."""
    return Decimal(10 + (d.toordinal() * 7) % 13)


def historico_falso(simbolo, desde, permitir_vacio=False):
    dias = [date.fromordinal(n) for n in range(desde.toordinal(), EXPORT.toordinal() + 1)]
    return [(d, precio(d)) for d in dias if d.weekday() < 5], "EUR"


def coma(x) -> str:
    return str(x).replace(".", ",")


def escribir(tmp_path, filas):
    ruta = tmp_path / "datos.csv"
    ruta.write_text("\n".join(filas) + "\n", encoding="utf-8")
    t = datetime.combine(EXPORT, datetime.min.time()).timestamp()
    os.utime(ruta, (t, t))
    return ruta


def csv_de(tmp_path, lotes, nav_dia=date(2026, 11, 19)):
    """Crea un CSV coherente: lotes = [(fecha, participaciones)], valorados al NAV de nav_dia."""
    filas = [CABECERA]
    for fecha, part in lotes:
        inversion = (part * precio(fecha)).quantize(Decimal("0.01"))
        valor = (part * precio(nav_dia)).quantize(Decimal("0.01"))
        filas.append(f"{fecha:%d/%m/%Y};{coma(inversion)};{coma(valor)};{coma(valor - inversion)}")
    return escribir(tmp_path, filas)


def importar(conn, ruta, isin=ISIN, nombre=NOMBRE, divisa="EUR", **kw):
    kw.setdefault("leer_historico", historico_falso)
    return importacion.importar(conn, ruta, isin, nombre, divisa, **kw)


def test_importa_con_el_nav_que_encaja_y_calcula_participaciones(conn, tmp_path):
    plan = importar(conn, csv_de(tmp_path, LOTES))
    assert plan["nav"][0] == date(2026, 11, 19)  # no el último cierre, que es el 20
    [inst] = instrumentos.listar(conn, "Fondo")
    assert (inst["nombre"], inst["divisa"], inst["identificador"]) == (NOMBRE, "EUR", ISIN)
    guardadas = compras.listar(conn, inst["id"])
    assert [c["participaciones"] for c in guardadas] == [Decimal(x) for x in ("5.5", "12", "3.25")]
    assert all(c["comision"] == 0 for c in guardadas)
    assert guardadas[0]["precio"] == precio(date(2026, 3, 2))


def test_normaliza_isin_nombre_y_divisa(conn, tmp_path):
    importar(conn, csv_de(tmp_path, LOTES), isin=" ie00byx5nx33 ", nombre="  X  ", divisa="eur")
    [inst] = instrumentos.listar(conn)
    assert (inst["nombre"], inst["divisa"], inst["identificador"]) == ("X", "EUR", ISIN)


def test_rechaza_si_ningun_nav_encaja(conn, tmp_path):
    filas = [CABECERA]
    for fecha, part in LOTES:  # el valor es el triple de lo que sale con cualquier precio real
        inversion = (part * precio(fecha)).quantize(Decimal("0.01"))
        filas.append(
            f"{fecha:%d/%m/%Y};{coma(inversion)};{coma(inversion * 3)};{coma(inversion * 2)}"
        )
    with pytest.raises(ValueError, match="ningún NAV"):
        importar(conn, escribir(tmp_path, filas))
    assert instrumentos.listar(conn) == []


def test_rechaza_fondo_que_ya_tiene_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Otro nombre", "Fondo", "EUR", ISIN)
    compras.anadir(conn, id_, date(2026, 1, 5), 1, 10)
    with pytest.raises(ValueError, match="ya tiene compras"):
        importar(conn, csv_de(tmp_path, LOTES))
    assert len(compras.listar(conn)) == 1


def test_reutiliza_instrumento_existente_sin_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Mi fondo", "Fondo", "EUR", ISIN)
    importar(conn, csv_de(tmp_path, LOTES))
    assert len(instrumentos.listar(conn)) == 1
    assert len(compras.listar(conn, id_)) == 3


def test_fila_mala_no_escribe_nada(conn, tmp_path):
    ruta = csv_de(tmp_path, LOTES)
    ruta.write_text(ruta.read_text(encoding="utf-8") + "99/99/2026;1;2;1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="línea 5"):
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
        importar(conn, csv_de(tmp_path, LOTES))
    assert instrumentos.listar(conn) == [] and compras.listar(conn) == []


@pytest.mark.parametrize(
    "isin, nombre, divisa, error",
    [
        ("IE00BYX5NX3", NOMBRE, "EUR", "ISIN no válido"),
        (ISIN, "  ", "EUR", "falta el nombre"),
        (ISIN, NOMBRE, "EU", "divisa no válida"),
        (ISIN, NOMBRE, "USD", "USD"),  # Yahoo da el fondo en EUR
    ],
)
def test_datos_de_entrada_invalidos(conn, tmp_path, isin, nombre, divisa, error):
    with pytest.raises(ValueError, match=error):
        importar(conn, csv_de(tmp_path, LOTES), isin, nombre, divisa)
    assert instrumentos.listar(conn) == []


def test_fichero_inexistente(conn, tmp_path):
    with pytest.raises(ValueError, match="no se puede leer"):
        importar(conn, tmp_path / "no_existe.csv")


def test_otra_divisa_si_coincide_con_yahoo(conn, tmp_path):
    def en_usd(simbolo, desde, permitir_vacio=False):
        return historico_falso(simbolo, desde)[0], "USD"

    importar(conn, csv_de(tmp_path, LOTES), divisa="USD", leer_historico=en_usd)
    assert instrumentos.listar(conn)[0]["divisa"] == "USD"


def test_sin_historico_en_yahoo_usa_el_ultimo_cierre_y_marca_sin_validar(conn, tmp_path):
    ruta = csv_de(tmp_path, LOTES, nav_dia=date(2026, 11, 20))
    ultimo = date(2026, 11, 20)

    def solo_el_ultimo(simbolo, desde, permitir_vacio=False):
        return [(ultimo, precio(ultimo))], "EUR"

    plan = importar(conn, ruta, leer_historico=solo_el_ultimo)
    assert plan["nav"] == (ultimo, precio(ultimo), None)


@pytest.mark.parametrize(
    "filas, error",
    [
        (["Fecha;Inversión"], "cabecera"),
        ([CABECERA, "01/01/2026;1.000,5;2;1"], "punto"),
        ([CABECERA, "01/01/2026;10;12;5"], "resultado"),
        ([CABECERA, "01/01/2026;0;12;12"], "mayores"),
        ([CABECERA], "ningún lote"),
    ],
)
def test_csv_mal_formado(tmp_path, filas, error):
    with pytest.raises(ValueError, match=error):
        importacion.leer_csv(escribir(tmp_path, filas))


def test_lote_que_no_encaja_usa_el_precio_de_yahoo(conn, tmp_path):
    # el último lote (traspaso) declara un valor el triple del que le corresponde
    normales = csv_de(tmp_path, LOTES).read_text(encoding="utf-8").splitlines()
    fecha = date(2026, 4, 1)
    inversion = (Decimal(4) * precio(fecha)).quantize(Decimal("0.01"))
    valor = (Decimal(4) * precio(date(2026, 11, 19)) * Decimal(3)).quantize(Decimal("0.01"))
    filas = [
        *normales,
        f"{fecha:%d/%m/%Y};{coma(inversion)};{coma(valor)};{coma(valor - inversion)}",
    ]
    plan = importar(conn, escribir(tmp_path, filas))
    assert plan["con_precio_yahoo"] == 1
    guardadas = {c["fecha"]: c for c in compras.listar(conn)}
    assert guardadas[fecha]["precio"] == precio(fecha)
    assert guardadas[fecha]["participaciones"] == Decimal(4)  # inversión / precio de Yahoo
    assert guardadas[LOTES[0][0]]["participaciones"] == Decimal("5.5")  # el resto, como siempre


def test_importar_csv_abre_la_base_escribe_y_devuelve_el_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(importacion.yahoo, "leer_historico", historico_falso)
    ruta_db = tmp_path / "otra.sqlite3"
    plan = importacion.importar_csv(NOMBRE, ISIN, "EUR", csv_de(tmp_path, LOTES), ruta_db=ruta_db)
    assert len(plan["compras"]) == 3 and "Hecho." in capsys.readouterr().out
    conn = db.conectar(ruta_db)
    assert len(compras.listar(conn)) == 3
    conn.close()


def test_importar_csv_con_error_no_escribe(tmp_path, monkeypatch):
    monkeypatch.setattr(importacion.yahoo, "leer_historico", historico_falso)
    ruta_db = tmp_path / "otra.sqlite3"
    ruta = csv_de(tmp_path, LOTES)
    with pytest.raises(ValueError, match="ISIN no válido"):
        importacion.importar_csv(NOMBRE, "XX", "EUR", ruta, ruta_db=ruta_db)
    conn = db.conectar(ruta_db)
    assert instrumentos.listar(conn) == []
    conn.close()


def test_importar_csv_con_fondo_ya_importado_avisa_y_sigue(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(importacion.yahoo, "leer_historico", historico_falso)
    ruta_db = tmp_path / "otra.sqlite3"
    ruta = csv_de(tmp_path, LOTES)
    importacion.importar_csv(NOMBRE, ISIN, "EUR", ruta, ruta_db=ruta_db)
    assert importacion.importar_csv(NOMBRE, ISIN, "EUR", ruta, ruta_db=ruta_db) is None
    assert "AVISO" in capsys.readouterr().out
    conn = db.conectar(ruta_db)
    assert len(compras.listar(conn)) == 3  # no se duplicó
    conn.close()


def test_ticker_yahoo_se_usa_para_el_historico_y_se_guarda_el_isin(conn, tmp_path):
    pedidos = []

    def espia(simbolo, desde, permitir_vacio=False):
        pedidos.append(simbolo)
        return historico_falso(simbolo, desde)

    importar(conn, csv_de(tmp_path, LOTES), ticker_yahoo="0P00009PQ4.F", leer_historico=espia)
    assert pedidos == ["0P00009PQ4.F"]
    assert instrumentos.listar(conn)[0]["identificador"] == ISIN


def test_ticker_yahoo_se_guarda_en_el_instrumento_nuevo_y_en_el_existente(conn, tmp_path):
    importar(conn, csv_de(tmp_path, LOTES), ticker_yahoo="0p00009pq4.f")
    assert instrumentos.listar(conn)[0]["ticker_yahoo"] == "0P00009PQ4.F"


def test_ticker_yahoo_en_instrumento_existente_sin_compras(conn, tmp_path):
    id_ = instrumentos.anadir(conn, "Mi fondo", "Fondo", "EUR", ISIN)
    importar(conn, csv_de(tmp_path, LOTES), ticker_yahoo="X.F")
    assert instrumentos.obtener(conn, id_)["ticker_yahoo"] == "X.F"


def test_usa_el_ticker_ya_guardado_si_no_se_da_otro(conn, tmp_path):
    instrumentos.anadir(conn, "Mi fondo", "Fondo", "EUR", ISIN, "GUARDADO.F")
    pedidos = []

    def espia(simbolo, desde, permitir_vacio=False):
        pedidos.append(simbolo)
        return historico_falso(simbolo, desde)

    importar(conn, csv_de(tmp_path, LOTES), leer_historico=espia)
    assert pedidos == ["GUARDADO.F"]


def test_grupo_por_defecto_y_grupo_indicado_se_crea_si_no_existe(conn, tmp_path):
    importar(conn, csv_de(tmp_path, LOTES))
    assert {c["grupo"] for c in compras.listar(conn)} == {"Personal"}
    # el mismo fondo en otro grupo no es un duplicado
    plan = importar(conn, csv_de(tmp_path, LOTES), grupo="Pension")
    assert plan["grupo"] == "Pension" and plan["grupo_creado"] is True
    por_grupo = {}
    for c in compras.listar(conn):
        por_grupo[c["grupo"]] = por_grupo.get(c["grupo"], 0) + 1
    assert por_grupo == {"Personal": 3, "Pension": 3}
    assert len(instrumentos.listar(conn)) == 1  # un solo instrumento para los dos grupos


def test_reimportar_en_el_mismo_grupo_se_rechaza_pero_no_en_otro(conn, tmp_path):
    ruta = csv_de(tmp_path, LOTES)
    importar(conn, ruta, grupo="Pension")
    with pytest.raises(importacion.FondoYaImportado, match="grupo Pension"):
        importar(conn, ruta, grupo="pension")  # sin distinguir mayúsculas
    importar(conn, ruta, grupo="Personal")
    assert len(compras.listar(conn)) == 6


def test_grupo_vacio(conn, tmp_path):
    with pytest.raises(ValueError, match="falta el grupo"):
        importar(conn, csv_de(tmp_path, LOTES), grupo="  ")


def test_si_falla_al_escribir_no_deja_ni_el_grupo_nuevo(conn, tmp_path, monkeypatch):
    importar(conn, csv_de(tmp_path, LOTES), grupo="Personal")
    reales = compras.anadir
    llamadas = []

    def falla_a_la_segunda(*args, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 2:
            raise RuntimeError("disco lleno")
        return reales(*args, **kwargs)

    monkeypatch.setattr(compras, "anadir", falla_a_la_segunda)
    with pytest.raises(RuntimeError):
        importar(conn, csv_de(tmp_path, LOTES), grupo="Pension")
    assert grupos.obtener_por_nombre(conn, "Pension") is None
    assert len(compras.listar(conn)) == 3  # lo del otro grupo sigue intacto


def test_importar_csv_con_grupo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(importacion.yahoo, "leer_historico", historico_falso)
    ruta_db = tmp_path / "otra.sqlite3"
    importacion.importar_csv(
        NOMBRE, ISIN, "EUR", csv_de(tmp_path, LOTES), grupo="Pension", ruta_db=ruta_db
    )
    salida = capsys.readouterr().out
    assert "[Pension]" in salida and "Se ha creado el grupo 'Pension'" in salida
