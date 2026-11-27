"""Evolución diaria de la cartera: cuánto tenías invertido y cuánto valía cada día.

La divisa de la serie la decide `moneda()`: la de los instrumentos si todos los elegidos están en
la misma (un instrumento en dólares se ve en dólares, sin convertir) y el euro en cualquier otro
caso (mezcla de divisas o nada elegido).

Cada día lleva, por instrumento y grupo, la posición de ese día (coste medio, ver posicion.py)
y el último precio guardado hasta ese día (si un día no cotiza, vale el precio anterior). Los
días de la serie son los días con precio de algún instrumento y los días de operación, desde la
primera operación.

- Si un instrumento todavía no tiene precio en esa fecha (p. ej. se compró en festivo y su
  primer precio llega unos días después), vale lo que costó: ni gana ni pierde.
- Cuando la serie va en euros y un instrumento está en otra divisa, como en cartera.total() cada
  día se convierte con el tipo de cambio de ese día (el último guardado hasta entonces; antes del
  primero se usa el primero). Con una divisa sin ningún tipo de cambio guardado se lanza
  ValueError. Si la serie va en la divisa del instrumento no hace falta ningún tipo de cambio.
- Todo en Decimal.
"""

import sqlite3
from bisect import bisect_right
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from finanzas import divisas, posicion


def _carga(conn, sql, params):
    fechas, valores = [], []
    for f in conn.execute(sql, params):
        fechas.append(date.fromisoformat(f[0]))
        valores.append(Decimal(f[1]))
    return fechas, valores


def _hasta(fechas, valores, dia):
    """Último valor con fecha <= dia, o None si todavía no hay ninguno."""
    i = bisect_right(fechas, dia)
    return valores[i - 1] if i else None


def _tasas(conn, divisa):
    if divisa == divisas.BASE:
        return None
    fechas, valores = _carga(
        conn, "SELECT fecha, tasa FROM tipos_cambio WHERE divisa = ? ORDER BY fecha", (divisa,)
    )
    if not fechas:
        raise ValueError(f"Falta el tipo de cambio {divisa}/{divisas.BASE}: descarga el histórico")
    return fechas, valores


def _pares(conn, grupo_id, instrumento_id):
    """Los pares (instrumento, grupo) con operaciones que encajan con los filtros."""
    return [
        (inst_id, g)
        for inst_id, g in conn.execute(
            "SELECT instrumento_id, grupo_id FROM compras UNION SELECT instrumento_id, grupo_id "
            "FROM ventas ORDER BY 1, 2"
        )
        if (grupo_id is None or g == grupo_id)
        and (instrumento_id is None or inst_id == instrumento_id)
    ]


def moneda(
    conn: sqlite3.Connection, grupo_id: int | None = None, instrumento_id: int | None = None
) -> str:
    """Divisa en la que se muestra lo elegido (mismos filtros que serie()): la de los
    instrumentos si todos comparten la misma, y el euro si hay mezcla o no hay ninguno."""
    ids = {inst_id for inst_id, _ in _pares(conn, grupo_id, instrumento_id)}
    usadas = {
        conn.execute("SELECT divisa FROM instrumentos WHERE id = ?", (i,)).fetchone()[0]
        for i in ids
    }
    return usadas.pop() if len(usadas) == 1 else divisas.BASE


def _posiciones(conn, grupo_id, instrumento_id):
    """Las posiciones (instrumento, grupo) a contar: (posiciones, inicio, dias), donde cada
    posición es (instrumento_id, divisa, fechas de operación, pasos, fechas de precio, precios,
    tasas), inicio la fecha de la primera operación (None si no hay) y dias las fechas con precio
    o con operación. `tasas` es None si la divisa del instrumento es la de la serie (ver
    moneda()): no hay que convertir."""
    destino = moneda(conn, grupo_id, instrumento_id)
    posiciones = []
    inicio = None
    dias = set()
    for inst_id, g in _pares(conn, grupo_id, instrumento_id):
        pasos = posicion.historial(conn, inst_id, g)
        pasos = [(date.fromisoformat(f), n, inv) for f, n, inv in pasos]
        divisa = conn.execute(
            "SELECT divisa FROM instrumentos WHERE id = ?", (inst_id,)
        ).fetchone()[0]
        pf, pv = _carga(
            conn,
            "SELECT fecha, precio FROM precios WHERE instrumento_id = ? ORDER BY fecha",
            (inst_id,),
        )
        posiciones.append(
            (
                inst_id,
                divisa,
                [p[0] for p in pasos],
                pasos,
                pf,
                pv,
                None if divisa == destino else _tasas(conn, divisa),
            )
        )
        dias.update(pf)
        if pf:  # el día de cada operación sale aunque ese día aún no haya precio
            dias.update(p[0] for p in pasos)
        if inicio is None or pasos[0][0] < inicio:
            inicio = pasos[0][0]
    return posiciones, inicio, dias


def serie(
    conn: sqlite3.Connection, grupo_id: int | None = None, instrumento_id: int | None = None
) -> list[dict]:
    """Una fila por día: {"fecha", "invertido", "valor", "ganancia", "rentabilidad"} en la divisa
    de moneda() (rentabilidad en tanto por uno, None si no había nada invertido). Con grupo_id
    solo cuenta ese grupo y con instrumento_id solo ese instrumento (se pueden combinar). Sin
    operaciones o sin precios, devuelve una lista vacía."""
    posiciones, inicio, dias = _posiciones(conn, grupo_id, instrumento_id)
    if inicio is None:
        return []
    dias = sorted(d for d in dias if d >= inicio)
    resultado = []
    for dia in dias:
        invertido = valor = Decimal(0)
        for _, _, fechas_op, pasos, pf, pv, tasas in posiciones:
            i = bisect_right(fechas_op, dia)
            if not i:
                continue
            _, participaciones, coste = pasos[i - 1]
            if participaciones == 0:
                continue
            precio = _hasta(pf, pv, dia)
            valor_pos = coste if precio is None else participaciones * precio
            if tasas is None:
                tasa = Decimal(1)
            else:
                tasa = _hasta(tasas[0], tasas[1], dia) or tasas[1][0]
            invertido += coste * tasa
            valor += valor_pos * tasa
        resultado.append(
            {
                "fecha": dia,
                "invertido": invertido,
                "valor": valor,
                "ganancia": valor - invertido,
                "rentabilidad": (valor - invertido) / invertido if invertido else None,
            }
        )
    return resultado


def serie_intradia(
    conn: sqlite3.Connection,
    grupo_id: int | None = None,
    instrumento_id: int | None = None,
    horas: int = 24,
) -> list[dict]:
    """El último día de la cartera con los ticks de ETFs, acciones y cripto (`precios_mercado`).

    La ventana son las `horas` anteriores al último tick (no al reloj: con la bolsa cerrada se
    ve la última sesión). Devuelve la primera fila con el estado al empezar la ventana y después
    una por cada instante con algún tick: {"fecha" (datetime UTC), "invertido", "valor",
    "ganancia", "rentabilidad"}, como `serie` (misma divisa, ver moneda(); si es euros, al cambio
    del día). En cada instante
    cada instrumento vale su último tick; lo que no tiene ticks (fondos, planes) vale su último
    precio diario. Sin ticks de lo elegido, devuelve una lista vacía.
    """
    posiciones, _, _ = _posiciones(conn, grupo_id, instrumento_id)
    ticks = {}  # instrumento_id -> (momentos ISO, precios)
    for pos in posiciones:
        inst_id = pos[0]
        if inst_id in ticks:
            continue
        filas = conn.execute(
            "SELECT momento, precio FROM precios_mercado WHERE instrumento_id = ? ORDER BY momento",
            (inst_id,),
        ).fetchall()
        if filas:
            ticks[inst_id] = ([f[0] for f in filas], [Decimal(f[1]) for f in filas])
    if not ticks:
        return []
    fin = max(m[-1] for m, _ in ticks.values())
    fecha_fin = datetime.strptime(fin, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    inicio = (fecha_fin - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
    instantes = sorted({m for ms, _ in ticks.values() for m in ms if inicio < m <= fin})
    resultado = []
    for momento in [inicio, *instantes]:
        dt = datetime.strptime(momento, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        dia = dt.date()
        invertido = valor = Decimal(0)
        for inst_id, _, fechas_op, pasos, pf, pv, tasas in posiciones:
            i = bisect_right(fechas_op, dia)
            if not i:
                continue
            _, participaciones, coste = pasos[i - 1]
            if participaciones == 0:
                continue
            precio = None
            if inst_id in ticks:
                momentos, precios = ticks[inst_id]
                j = bisect_right(momentos, momento)
                precio = precios[j - 1] if j else None
            if precio is None:
                precio = _hasta(pf, pv, dia)
            valor_pos = coste if precio is None else participaciones * precio
            tasa = Decimal(1) if tasas is None else _hasta(tasas[0], tasas[1], dia) or tasas[1][0]
            invertido += coste * tasa
            valor += valor_pos * tasa
        resultado.append(
            {
                "fecha": dt,
                "invertido": invertido,
                "valor": valor,
                "ganancia": valor - invertido,
                "rentabilidad": (valor - invertido) / invertido if invertido else None,
            }
        )
    return resultado


def aportaciones(
    conn: sqlite3.Connection, grupo_id: int | None = None, instrumento_id: int | None = None
) -> list[dict]:
    """Las compras (con su comisión) por fecha, en la divisa de moneda() (si es euros, al cambio
    de su día): {"fecha", "importe", "instrumento"}. Mismos filtros que serie()."""
    destino = moneda(conn, grupo_id, instrumento_id)
    sql = (
        "SELECT c.fecha, c.participaciones, c.precio, c.comision, i.nombre, i.divisa "
        "FROM compras c JOIN instrumentos i ON i.id = c.instrumento_id WHERE 1 = 1"
    )
    params = []
    if grupo_id is not None:
        sql += " AND c.grupo_id = ?"
        params.append(grupo_id)
    if instrumento_id is not None:
        sql += " AND c.instrumento_id = ?"
        params.append(instrumento_id)
    tasas: dict = {}
    resultado = []
    filas = conn.execute(sql + " ORDER BY c.fecha", params)
    for fecha, n, precio, comision, nombre, divisa in filas:
        if divisa not in tasas:
            tasas[divisa] = None if divisa == destino else _tasas(conn, divisa)
        dia = date.fromisoformat(fecha)
        if tasas[divisa] is None:
            tasa = Decimal(1)
        else:
            tasa = _hasta(tasas[divisa][0], tasas[divisa][1], dia) or tasas[divisa][1][0]
        resultado.append(
            {
                "fecha": dia,
                "importe": (Decimal(n) * Decimal(precio) + Decimal(comision)) * tasa,
                "instrumento": nombre,
            }
        )
    return resultado


def mensual(filas: list[dict]) -> list[dict]:
    """Resumen de una serie diaria: el último día de cada mes con datos (el último mes puede
    estar a medias, y entonces es el último día disponible)."""
    ultimos: dict[tuple[int, int], dict] = {}
    for f in filas:
        ultimos[(f["fecha"].year, f["fecha"].month)] = f
    return list(ultimos.values())
