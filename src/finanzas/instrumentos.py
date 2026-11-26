"""Añadir, borrar y consultar instrumentos (y su identificador) en SQLite."""

import sqlite3

TIPOS = ("Fondo", "ETF", "Accion", "Cripto", "Plan_pensiones")

# Qué identificador lleva cada tipo. En Cripto es opcional (ticker de Yahoo, ej. BTC-EUR).
IDENTIFICADOR_POR_TIPO = {
    "Cripto": "TICKER",
    "Fondo": "ISIN",
    "ETF": "ISIN",
    "Plan_pensiones": "DGS",
    "Accion": "TICKER",
}
OPCIONALES = ("Cripto",)

_SELECT = """
SELECT i.*, d.tipo AS id_tipo, d.valor AS identificador
FROM instrumentos i LEFT JOIN identificadores d ON d.instrumento_id = i.id
"""


def normalizar_tipo(tipo: str) -> str:
    """'fOnDo' -> 'Fondo'; 'etf' -> 'ETF' (siglas en mayúsculas)."""
    tipo = tipo.strip().lower()
    return "ETF" if tipo == "etf" else tipo.capitalize()


def anadir(
    conn: sqlite3.Connection,
    nombre: str,
    tipo: str,
    divisa: str,
    identificador: str | None = None,
    ticker_yahoo: str | None = None,
) -> int:
    """Inserta un instrumento con su identificador y devuelve su id.

    Fondo y ETF exigen ISIN, Plan_pensiones exige DGS y Accion exige TICKER; Cripto admite
    un TICKER opcional (para el precio automático). `ticker_yahoo` (opcional) es el símbolo con
    el que se buscan precios e histórico en Yahoo en lugar del identificador.
    Lanza ValueError si falta el identificador, o si el nombre o el identificador ya existen,
    y sqlite3.IntegrityError si el tipo o la divisa no son válidos.
    Todo se guarda junto o no se guarda nada.
    """
    nombre = nombre.strip()
    tipo = normalizar_tipo(tipo)
    tipo_id = IDENTIFICADOR_POR_TIPO.get(tipo)
    valor = (identificador or "").strip().upper()
    if tipo_id and not valor and tipo not in OPCIONALES:
        raise ValueError(f"Un instrumento de tipo {tipo} necesita {tipo_id}")
    try:
        cur = conn.execute(
            "INSERT INTO instrumentos (nombre, tipo, divisa, ticker_yahoo) VALUES (?, ?, ?, ?)",
            (nombre, tipo, divisa, (ticker_yahoo or "").strip().upper() or None),
        )
        if tipo_id and valor:
            conn.execute(
                "INSERT INTO identificadores (instrumento_id, tipo, valor) VALUES (?, ?, ?)",
                (cur.lastrowid, tipo_id, valor),
            )
    except sqlite3.IntegrityError as e:
        conn.rollback()  # que no quede el instrumento sin su identificador
        if "identificadores" in str(e) and "UNIQUE" in str(e):
            raise ValueError(f"Ya existe un instrumento con {tipo_id} {valor}") from None
        if "UNIQUE" in str(e):
            raise ValueError(f"Ya existe un instrumento llamado '{nombre}'") from None
        raise
    conn.commit()
    return cur.lastrowid


def asignar_identificador(conn: sqlite3.Connection, id: int, valor: str) -> None:
    """Pone o cambia el identificador de un instrumento existente (ej. BTC-EUR a un Bitcoin).

    Lanza ValueError si el instrumento no existe, no admite identificador o el valor ya
    lo tiene otro instrumento.
    """
    inst = obtener(conn, id)
    if inst is None:
        raise ValueError("No existe ese instrumento")
    tipo_id = IDENTIFICADOR_POR_TIPO.get(inst["tipo"])
    valor = valor.strip().upper()
    if not tipo_id or not valor:
        raise ValueError("Instrumento sin identificador o valor vacío")
    try:
        conn.execute("DELETE FROM identificadores WHERE instrumento_id = ?", (id,))
        conn.execute(
            "INSERT INTO identificadores (instrumento_id, tipo, valor) VALUES (?, ?, ?)",
            (id, tipo_id, valor),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"Ya existe un instrumento con {tipo_id} {valor}") from None
    conn.commit()


def asignar_ticker_yahoo(conn: sqlite3.Connection, id: int, ticker: str | None) -> None:
    """Pone o cambia el ticker de Yahoo de un instrumento (vacío o None lo quita).

    Lanza ValueError si el instrumento no existe.
    """
    if obtener(conn, id) is None:
        raise ValueError("No existe ese instrumento")
    conn.execute(
        "UPDATE instrumentos SET ticker_yahoo = ? WHERE id = ?",
        ((ticker or "").strip().upper() or None, id),
    )
    conn.commit()


def borrar(conn: sqlite3.Connection, id: int) -> bool:
    """Borra por id (y su identificador). Devuelve True si existía, False si no."""
    cur = conn.execute("DELETE FROM instrumentos WHERE id = ?", (id,))
    conn.commit()
    return cur.rowcount == 1


def borrar_con_operaciones(conn: sqlite3.Connection, id: int) -> bool:
    """Borra el instrumento con todas sus compras y ventas (de todos los grupos) y sus precios.

    Todo junto o nada. Devuelve True si existía. Es irreversible.
    """
    try:
        conn.execute("DELETE FROM ventas WHERE instrumento_id = ?", (id,))
        conn.execute("DELETE FROM compras WHERE instrumento_id = ?", (id,))
        cur = conn.execute("DELETE FROM instrumentos WHERE id = ?", (id,))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return cur.rowcount == 1


def obtener(conn: sqlite3.Connection, id: int) -> sqlite3.Row | None:
    """Devuelve un instrumento por id (con id_tipo e identificador), o None."""
    return conn.execute(_SELECT + " WHERE i.id = ?", (id,)).fetchone()


def listar(conn: sqlite3.Connection, tipo: str | None = None) -> list[sqlite3.Row]:
    """Devuelve todos los instrumentos (opcionalmente solo de un tipo), ordenados por id."""
    if tipo is None:
        return conn.execute(_SELECT + " ORDER BY i.id").fetchall()
    return conn.execute(
        _SELECT + " WHERE i.tipo = ? ORDER BY i.id", (normalizar_tipo(tipo),)
    ).fetchall()
