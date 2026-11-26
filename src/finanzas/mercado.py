"""Precios durante el día (ticks) de ETFs, acciones y cripto, y su compactación a una hora.

Cada tick guarda la última barra de 1 minuto de Yahoo con SU hora (UTC), no la del reloj: con el
mercado cerrado Yahoo devuelve la misma barra, ya existe y no se guarda nada. Así no hace falta
conocer horarios ni festivos de cada bolsa.
Los ticks de más de RETENCION_HORAS se compactan: de cada hora queda solo el último, con la
hora en punto como `momento` (el precio es el de cierre de esa hora).
"""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import yfinance as yf

from finanzas import cartera, instrumentos, yahoo

TIPOS = ("ETF", "Accion", "Cripto")
RETENCION_HORAS = 48
FORMATO = "%Y-%m-%dT%H:%M:%SZ"

# Yahoo da barras de 1 hora hasta unos 730 días atrás (se queda un día de margen).
DIAS_HISTORICO_HORARIO = 729
# Si lo guardado empieza más tarde que el inicio + estos días, se vuelve a bajar todo.
MARGEN_INICIO = 7
# Con ticks recientes no hace falta preguntar por horas; y tras preguntar por un instrumento no
# se vuelve a preguntar hasta pasado este tiempo (con la bolsa cerrada no habría nada nuevo).
HUECO_MINIMO = timedelta(hours=2)
REINTENTO = timedelta(hours=1)

_divisas_ok: dict[str, bool] = {}  # símbolo -> si Yahoo lo da en la divisa del instrumento


def formatear(momento: datetime) -> str:
    """datetime con zona -> 'AAAA-MM-DDTHH:MM:SSZ' en UTC."""
    return momento.astimezone(UTC).strftime(FORMATO)


def leer_ultimas_barras(simbolos: list[str]) -> dict[str, tuple[datetime, Decimal]]:
    """Última barra de 1 minuto de cada símbolo, con una sola petición a Yahoo.

    Devuelve {símbolo: (momento con zona, cierre)}; los símbolos sin datos no aparecen.
    Los fallos de red llegan como error.
    """
    if not simbolos:
        return {}
    datos = yf.download(
        simbolos,
        period="1d",
        interval="1m",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    barras = {}
    for simbolo in simbolos:
        try:
            cierres = datos[simbolo]["Close"].dropna()
        except KeyError:
            continue
        if len(cierres) == 0:
            continue
        indice = cierres.index[-1]
        barras[simbolo] = (
            indice.to_pydatetime(),
            Decimal(str(round(float(cierres.iloc[-1]), 4))),
        )
    return barras


def _divisa_correcta(simbolo: str, divisa: str) -> bool:
    """Comprueba (una vez por símbolo y proceso) que Yahoo da el precio en la divisa esperada."""
    clave = f"{simbolo}|{divisa}"
    if clave not in _divisas_ok:
        actual = str(yf.Ticker(simbolo).fast_info["currency"]).upper()
        _divisas_ok[clave] = actual == divisa
    return _divisas_ok[clave]


def _candidatos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """ETFs, acciones y cripto con participaciones en cartera y con símbolo para Yahoo."""
    en_cartera = {f["instrumento_id"] for f in cartera.resumen(conn)}
    return [
        i
        for i in instrumentos.listar(conn)
        if i["id"] in en_cartera and i["tipo"] in TIPOS and i["id_tipo"] in yahoo.TIPOS_ID
    ]


def registrar_ticks(conn: sqlite3.Connection) -> list[dict]:
    """Guarda el tick de ahora de cada ETF, acción y cripto con participaciones en cartera.

    Devuelve una fila por instrumento: "nombre" y "estado": "nuevo" (se guardó un tick),
    "repetido" (Yahoo no tiene barra nueva: mercado cerrado) o "error" (con "mensaje").
    Los errores de red no se lanzan: se devuelven en cada fila.
    """
    candidatos = _candidatos(conn)
    if not candidatos:
        return []
    filas = [{"nombre": i["nombre"]} for i in candidatos]
    simbolos = list(dict.fromkeys(yahoo.simbolo(i) for i in candidatos))
    try:
        barras = leer_ultimas_barras(simbolos)
    except (ValueError, OSError, KeyError) as e:
        for fila in filas:
            fila.update(estado="error", mensaje=str(e))
        return filas
    for inst, fila in zip(candidatos, filas, strict=True):
        simbolo = yahoo.simbolo(inst)
        if simbolo not in barras:
            fila.update(estado="error", mensaje=f"Yahoo no tiene precio para {simbolo}")
            continue
        try:
            if not _divisa_correcta(simbolo, inst["divisa"]):
                fila.update(estado="error", mensaje=f"{simbolo} no cotiza en {inst['divisa']}")
                continue
        except (ValueError, OSError, KeyError) as e:
            fila.update(estado="error", mensaje=str(e))
            continue
        momento, precio = barras[simbolo]
        cur = conn.execute(
            "INSERT OR IGNORE INTO precios_mercado (instrumento_id, momento, precio) "
            "VALUES (?,?,?)",
            (inst["id"], formatear(momento), str(precio)),
        )
        conn.commit()
        fila.update(estado="nuevo" if cur.rowcount else "repetido")
    return filas


def leer_historico_horario(
    simbolo: str, desde: datetime
) -> tuple[list[tuple[datetime, Decimal]], str | None]:
    """Barras de 1 hora desde `desde` hasta ahora: ([(inicio de la barra con zona, cierre)],
    divisa). Sin datos devuelve ([], None). Los fallos de red llegan como error."""
    ticker = yf.Ticker(simbolo)
    historico = ticker.history(start=desde.date().isoformat(), interval="1h", auto_adjust=False)
    cierres = historico["Close"].dropna() if not historico.empty else historico
    if len(cierres) == 0:
        return [], None
    filas = [
        (indice.to_pydatetime(), Decimal(str(round(float(c), 4)))) for indice, c in cierres.items()
    ]
    return filas, str(ticker.fast_info["currency"]).upper()


def _momento(texto: str) -> datetime:
    return datetime.strptime(texto, FORMATO).replace(tzinfo=UTC)


def _desde(inicio: datetime, primero: str | None, ultimo: str | None) -> datetime:
    """Desde cuándo hay que pedir horas: todo si no hay nada guardado o lo guardado empieza
    tarde (p. ej. se añadió después una compra más antigua); si no, desde el último momento."""
    if primero is None or ultimo is None:
        return inicio
    if _momento(primero) > inicio + timedelta(days=MARGEN_INICIO):
        return inicio
    return _momento(ultimo)


_ultimo_intento: dict[int, datetime] = {}  # instrumento_id -> cuándo se preguntó por horas


def rellenar_horas(conn: sqlite3.Connection, ahora: datetime | None = None) -> list[dict]:
    """Rellena con las barras de 1 hora de Yahoo las horas que faltan de cada ETF, acción y
    cripto en cartera (p. ej. mientras la app estuvo apagada).

    La primera vez baja desde la primera compra (con el límite de ~730 días de Yahoo); después,
    desde el último momento guardado. Solo entran horas completas y solo en horas sin ningún dato
    del instrumento (los ticks, más finos, mandan). Cada barra se guarda con la hora en punto como
    `momento` y su cierre como precio, igual que al compactar. Con ticks de las últimas 2 horas, o
    si ya se preguntó hace menos de 1 hora, no se consulta nada ("al_dia").

    Devuelve una fila por instrumento: "nombre" y "estado": "ok" (con "nuevas"), "al_dia" o
    "error" (con "mensaje"). Los errores no se lanzan: se devuelven en cada fila.
    """
    ahora = ahora or datetime.now(UTC)
    filas = []
    for inst in _candidatos(conn):
        fila = {"nombre": inst["nombre"]}
        filas.append(fila)
        primero, ultimo = conn.execute(
            "SELECT MIN(momento), MAX(momento) FROM precios_mercado WHERE instrumento_id = ?",
            (inst["id"],),
        ).fetchone()
        compra = conn.execute(
            "SELECT MIN(fecha) FROM compras WHERE instrumento_id = ?", (inst["id"],)
        ).fetchone()[0]
        inicio = max(
            datetime.combine(date.fromisoformat(compra), datetime.min.time(), tzinfo=UTC),
            ahora - timedelta(days=DIAS_HISTORICO_HORARIO),
        )
        desde = _desde(inicio, primero, ultimo)
        intento = _ultimo_intento.get(inst["id"])
        reciente = ultimo and ahora - _momento(ultimo) < HUECO_MINIMO
        # Con ticks de hace poco no hace falta preguntar, salvo que falte el histórico anterior.
        if (reciente and desde != inicio) or (intento and ahora - intento < REINTENTO):
            fila.update(estado="al_dia", nuevas=0)
            continue
        simbolo = yahoo.simbolo(inst)
        _ultimo_intento[inst["id"]] = ahora
        try:
            barras, divisa = leer_historico_horario(simbolo, desde)
            if barras and divisa != inst["divisa"]:
                raise ValueError(f"{simbolo} no cotiza en {inst['divisa']}")
        except (ValueError, OSError, KeyError) as e:
            fila.update(estado="error", mensaje=str(e))
            continue
        nuevas = 0
        for inicio_barra, precio in barras:
            if inicio_barra + timedelta(hours=1) > ahora:
                continue  # hora sin terminar
            momento = formatear(inicio_barra.replace(minute=0, second=0, microsecond=0))
            cur = conn.execute(
                "INSERT INTO precios_mercado (instrumento_id, momento, precio) "
                "SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM precios_mercado "
                "WHERE instrumento_id = ? AND substr(momento, 1, 13) = substr(?, 1, 13))",
                (inst["id"], momento, str(precio), inst["id"], momento),
            )
            nuevas += cur.rowcount
        conn.commit()
        fila.update(estado="ok", nuevas=nuevas)
    return filas


def compactar(conn: sqlite3.Connection, ahora: datetime | None = None) -> int:
    """Deja un solo tick por hora (el último, con la hora en punto) en lo anterior a
    RETENCION_HORAS. Se puede repetir sin problema. Devuelve cuántas filas desaparecieron."""
    ahora = ahora or datetime.now(UTC)
    corte = formatear(
        (ahora - timedelta(hours=RETENCION_HORAS)).replace(minute=0, second=0, microsecond=0)
    )
    antes = conn.execute("SELECT COUNT(*) FROM precios_mercado").fetchone()[0]
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO precios_mercado (instrumento_id, momento, precio)
            SELECT p.instrumento_id, substr(p.momento, 1, 13) || ':00:00Z', p.precio
            FROM precios_mercado p
            JOIN (
                SELECT instrumento_id, MAX(momento) AS ultimo
                FROM precios_mercado
                WHERE momento < ?
                GROUP BY instrumento_id, substr(momento, 1, 13)
                HAVING MAX(momento) NOT LIKE '%:00:00Z'
            ) u ON u.instrumento_id = p.instrumento_id AND u.ultimo = p.momento
            """,
            (corte,),
        )
        conn.execute(
            "DELETE FROM precios_mercado WHERE momento < ? AND momento NOT LIKE '%:00:00Z'",
            (corte,),
        )
    despues = conn.execute("SELECT COUNT(*) FROM precios_mercado").fetchone()[0]
    return antes - despues
