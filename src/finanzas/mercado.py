"""Precios durante el día (ticks) de ETFs, acciones y cripto, y su compactación a una hora.

Cada tick guarda la última barra de 1 minuto de Yahoo con SU hora (UTC), no la del reloj: con el
mercado cerrado Yahoo devuelve la misma barra, ya existe y no se guarda nada. Así no hace falta
conocer horarios ni festivos de cada bolsa.
Los ticks de más de RETENCION_HORAS se compactan: de cada hora queda solo el último, con la
hora en punto como `momento` (el precio es el de cierre de esa hora).
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import yfinance as yf

from finanzas import cartera, instrumentos, yahoo

TIPOS = ("ETF", "Accion", "Cripto")
RETENCION_HORAS = 48
FORMATO = "%Y-%m-%dT%H:%M:%SZ"

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


def registrar_ticks(conn: sqlite3.Connection) -> list[dict]:
    """Guarda el tick de ahora de cada ETF, acción y cripto con participaciones en cartera.

    Devuelve una fila por instrumento: "nombre" y "estado": "nuevo" (se guardó un tick),
    "repetido" (Yahoo no tiene barra nueva: mercado cerrado) o "error" (con "mensaje").
    Los errores de red no se lanzan: se devuelven en cada fila.
    """
    en_cartera = {f["instrumento_id"] for f in cartera.resumen(conn)}
    candidatos = [
        i
        for i in instrumentos.listar(conn)
        if i["id"] in en_cartera and i["tipo"] in TIPOS and i["id_tipo"] in yahoo.TIPOS_ID
    ]
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
