"""Grupos de operaciones (Personal, Pension...): cada compra y venta pertenece a uno.

Un mismo instrumento puede tener operaciones en varios grupos (p. ej. el mismo fondo en
"Personal" y en "Pension"); su posición se calcula por grupo.
"""

import sqlite3

GRUPO_POR_DEFECTO = "Personal"


def anadir(conn: sqlite3.Connection, nombre: str) -> int:
    """Crea un grupo y devuelve su id. ValueError si el nombre está vacío o ya existe."""
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El grupo necesita un nombre")
    try:
        cur = conn.execute("INSERT INTO grupos (nombre) VALUES (?)", (nombre,))
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"Ya existe el grupo '{nombre}'") from None
    conn.commit()
    return cur.lastrowid


def listar(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Todos los grupos, ordenados por nombre."""
    return conn.execute("SELECT * FROM grupos ORDER BY nombre COLLATE NOCASE").fetchall()


def obtener_por_nombre(conn: sqlite3.Connection, nombre: str) -> sqlite3.Row | None:
    """El grupo con ese nombre (sin distinguir mayúsculas), o None."""
    return conn.execute("SELECT * FROM grupos WHERE nombre = ?", (nombre.strip(),)).fetchone()


def obtener_o_crear(conn: sqlite3.Connection, nombre: str) -> tuple[int, bool]:
    """Devuelve (id, creado) del grupo con ese nombre, creándolo si no existe."""
    existente = obtener_por_nombre(conn, nombre)
    if existente:
        return existente["id"], False
    return anadir(conn, nombre), True


def por_defecto(conn: sqlite3.Connection) -> int:
    """Id del grupo por defecto ("Personal"); se crea si no existe."""
    return obtener_o_crear(conn, GRUPO_POR_DEFECTO)[0]


def borrar(conn: sqlite3.Connection, id: int) -> bool:
    """Borra un grupo por id. Devuelve True si existía.

    ValueError (y no borra) si tiene compras o ventas.
    """
    usado = conn.execute(
        "SELECT (SELECT COUNT(*) FROM compras WHERE grupo_id = :id)"
        " + (SELECT COUNT(*) FROM ventas WHERE grupo_id = :id)",
        {"id": id},
    ).fetchone()[0]
    if usado:
        raise ValueError("El grupo tiene compras o ventas: no se puede borrar")
    cur = conn.execute("DELETE FROM grupos WHERE id = ?", (id,))
    conn.commit()
    return cur.rowcount == 1
