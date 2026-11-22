"""Conexión a SQLite y definición de las tablas."""

import sqlite3
from pathlib import Path

_TABLAS = """
CREATE TABLE IF NOT EXISTS instrumentos (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- sin repetidos (ignora mayúsculas)
    tipo    TEXT NOT NULL CHECK (tipo IN ('Fondo','ETF','Accion','Cripto','Plan_pensiones')),
    divisa  TEXT NOT NULL CHECK (length(divisa) = 3)
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

-- participaciones y precio van como TEXT (decimal exacto): REAL perdería precisión.
CREATE TABLE IF NOT EXISTS compras (
    id              INTEGER PRIMARY KEY,
    instrumento_id  INTEGER NOT NULL REFERENCES instrumentos(id),
    fecha           TEXT NOT NULL CHECK (date(fecha) = fecha),  -- AAAA-MM-DD
    participaciones TEXT NOT NULL CHECK (CAST(participaciones AS REAL) > 0),
    precio          TEXT NOT NULL CHECK (CAST(precio AS REAL) > 0)
);
CREATE INDEX IF NOT EXISTS ix_compras_instrumento ON compras(instrumento_id);

-- Vistas para consultar en DB Browser. Se recrean en cada conexión para que los cambios
-- de definición se apliquen también a bases ya existentes.
DROP VIEW IF EXISTS compras_detalle;
CREATE VIEW compras_detalle AS
SELECT c.id,
       i.nombre AS instrumento,
       d.valor AS isin,
       strftime('%d-%m-%Y', c.fecha) AS fecha,
       c.participaciones,
       c.precio
FROM compras c
JOIN instrumentos i ON i.id = c.instrumento_id
LEFT JOIN identificadores d ON d.instrumento_id = i.id AND d.tipo = 'ISIN'
ORDER BY c.fecha, c.id;

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
    return conn
