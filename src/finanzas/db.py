"""Conexión a SQLite y definición de las tablas."""

import sqlite3
from pathlib import Path

_TABLAS = """
CREATE TABLE IF NOT EXISTS instrumentos (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- sin repetidos (ignora mayúsculas)
    tipo    TEXT NOT NULL CHECK (tipo IN ('Fondo','ETF','Accion','Cripto','Plan_pensiones')),
    divisa  TEXT NOT NULL CHECK (length(divisa) = 3),
    -- Símbolo de Yahoo para precios e histórico, si no es el identificador (ej. 0P00009PQ4.F).
    ticker_yahoo TEXT CHECK (ticker_yahoo IS NULL OR length(ticker_yahoo) > 0)
    -- Más adelante: grupo_id INTEGER (nullable) para agrupar instrumentos.
);

-- Un identificador (ISIN, DGS o TICKER) identifica a un único instrumento: PK (tipo, valor).
CREATE TABLE IF NOT EXISTS identificadores (
    instrumento_id  INTEGER NOT NULL REFERENCES instrumentos(id) ON DELETE CASCADE,
    tipo            TEXT NOT NULL CHECK (tipo IN ('ISIN','DGS','TICKER')),
    valor           TEXT NOT NULL CHECK (length(valor) > 0),
    PRIMARY KEY (tipo, valor)
);
CREATE INDEX IF NOT EXISTS ix_identificadores_instrumento ON identificadores(instrumento_id);

-- participaciones, precio y comision van como TEXT (decimal exacto): REAL perdería precisión.
-- La comision está en la divisa del instrumento (la misma en que se compró). 0 = sin comisión.
CREATE TABLE IF NOT EXISTS compras (
    id              INTEGER PRIMARY KEY,
    instrumento_id  INTEGER NOT NULL REFERENCES instrumentos(id),
    fecha           TEXT NOT NULL CHECK (date(fecha) = fecha),  -- AAAA-MM-DD
    participaciones TEXT NOT NULL CHECK (CAST(participaciones AS REAL) > 0),
    precio          TEXT NOT NULL CHECK (CAST(precio AS REAL) > 0),
    comision        TEXT NOT NULL DEFAULT '0' CHECK (CAST(comision AS REAL) >= 0)
);
CREATE INDEX IF NOT EXISTS ix_compras_instrumento ON compras(instrumento_id);

-- Mismas columnas que compras.
CREATE TABLE IF NOT EXISTS ventas (
    id              INTEGER PRIMARY KEY,
    instrumento_id  INTEGER NOT NULL REFERENCES instrumentos(id),
    fecha           TEXT NOT NULL CHECK (date(fecha) = fecha),  -- AAAA-MM-DD
    participaciones TEXT NOT NULL CHECK (CAST(participaciones AS REAL) > 0),
    precio          TEXT NOT NULL CHECK (CAST(precio AS REAL) > 0),
    comision        TEXT NOT NULL DEFAULT '0' CHECK (CAST(comision AS REAL) >= 0)
);
CREATE INDEX IF NOT EXISTS ix_ventas_instrumento ON ventas(instrumento_id);

-- Precio de mercado de un instrumento en una fecha (a mano). Uno por instrumento y día.
CREATE TABLE IF NOT EXISTS precios (
    id              INTEGER PRIMARY KEY,
    instrumento_id  INTEGER NOT NULL REFERENCES instrumentos(id) ON DELETE CASCADE,
    fecha           TEXT NOT NULL CHECK (date(fecha) = fecha),  -- AAAA-MM-DD
    precio          TEXT NOT NULL CHECK (CAST(precio AS REAL) > 0),
    UNIQUE (instrumento_id, fecha)
);

-- Tipo de cambio a euros: cuántos EUR vale 1 unidad de la divisa en esa fecha (ej. USD 0.92).
CREATE TABLE IF NOT EXISTS tipos_cambio (
    divisa  TEXT NOT NULL CHECK (length(divisa) = 3 AND divisa != 'EUR'),
    fecha   TEXT NOT NULL CHECK (date(fecha) = fecha),  -- AAAA-MM-DD
    tasa    TEXT NOT NULL CHECK (CAST(tasa AS REAL) > 0),
    PRIMARY KEY (divisa, fecha)
);
"""

_VISTAS = """
-- Vistas para consultar en DB Browser. Se recrean en cada conexión para que los cambios
-- de definición se apliquen también a bases ya existentes.
DROP VIEW IF EXISTS compras_detalle;
CREATE VIEW compras_detalle AS
SELECT c.id,
       i.nombre AS instrumento,
       d.valor AS isin,
       strftime('%d-%m-%Y', c.fecha) AS fecha,
       c.participaciones,
       c.precio,
       c.comision
FROM compras c
JOIN instrumentos i ON i.id = c.instrumento_id
LEFT JOIN identificadores d ON d.instrumento_id = i.id AND d.tipo = 'ISIN'
ORDER BY c.fecha, c.id;

DROP VIEW IF EXISTS ventas_detalle;
CREATE VIEW ventas_detalle AS
SELECT v.id,
       i.nombre AS instrumento,
       d.valor AS isin,
       strftime('%d-%m-%Y', v.fecha) AS fecha,
       v.participaciones,
       v.precio,
       v.comision
FROM ventas v
JOIN instrumentos i ON i.id = v.instrumento_id
LEFT JOIN identificadores d ON d.instrumento_id = i.id AND d.tipo = 'ISIN'
ORDER BY v.fecha, v.id;

DROP VIEW IF EXISTS identificadores_detalle;
CREATE VIEW identificadores_detalle AS
SELECT i.nombre AS instrumento, d.tipo, d.valor
FROM identificadores d JOIN instrumentos i ON i.id = d.instrumento_id
ORDER BY i.nombre;
"""


def conectar(ruta: str | Path) -> sqlite3.Connection:
    """Abre la base (la crea si no existe) y asegura que las tablas existen."""
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)  # crea la carpeta si no existe
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row  # las filas se leen por nombre: fila["nombre"]
    # SQLite no aplica las claves foráneas salvo que se pida en cada conexión.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_TABLAS)
    _anadir_comision_si_falta(conn)
    _anadir_ticker_yahoo_si_falta(conn)
    conn.executescript(_VISTAS)
    return conn


def _anadir_ticker_yahoo_si_falta(conn: sqlite3.Connection) -> None:
    """Bases creadas antes de existir ticker_yahoo: añade la columna (las filas viejas, sin él)."""
    columnas = [c["name"] for c in conn.execute("PRAGMA table_info(instrumentos)")]
    if "ticker_yahoo" not in columnas:
        conn.execute(
            "ALTER TABLE instrumentos ADD COLUMN ticker_yahoo TEXT "
            "CHECK (ticker_yahoo IS NULL OR length(ticker_yahoo) > 0)"
        )
        conn.commit()


def _anadir_comision_si_falta(conn: sqlite3.Connection) -> None:
    """Bases creadas antes de existir las comisiones: añade la columna (las filas viejas, a 0)."""
    for tabla in ("compras", "ventas"):
        columnas = [c["name"] for c in conn.execute(f"PRAGMA table_info({tabla})")]
        if "comision" not in columnas:
            conn.execute(
                f"ALTER TABLE {tabla} ADD COLUMN comision "
                "TEXT NOT NULL DEFAULT '0' CHECK (CAST(comision AS REAL) >= 0)"
            )
    conn.commit()
