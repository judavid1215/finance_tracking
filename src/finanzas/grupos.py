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


def mover_instrumento(
    conn: sqlite3.Connection, instrumento_id: int, origen_id: int, destino_id: int
) -> int:
    """Pasa todas las compras y ventas de un instrumento del grupo `origen` al grupo `destino`.

    Devuelve cuántas operaciones se movieron. ValueError (y no cambia nada) si el destino no
    existe, si es el mismo grupo, si no hay operaciones que mover o si el destino ya tiene
    operaciones de ese instrumento.
    """
    if origen_id == destino_id:
        raise ValueError("El grupo de origen y el de destino son el mismo")
    if conn.execute("SELECT 1 FROM grupos WHERE id = ?", (destino_id,)).fetchone() is None:
        raise ValueError("No existe el grupo de destino")
    en_grupo = (
        "SELECT COUNT(*) FROM {t} WHERE instrumento_id = :i AND grupo_id = :g"
    )
    cuenta = lambda g: sum(  # noqa: E731
        conn.execute(en_grupo.format(t=t), {"i": instrumento_id, "g": g}).fetchone()[0]
        for t in ("compras", "ventas")
    )
    if cuenta(destino_id):
        raise ValueError("El grupo de destino ya tiene operaciones de este instrumento")
    movidas = cuenta(origen_id)
    if not movidas:
        raise ValueError("El instrumento no tiene operaciones en el grupo de origen")
    for tabla in ("compras", "ventas"):
        conn.execute(
            f"UPDATE {tabla} SET grupo_id = ? WHERE instrumento_id = ? AND grupo_id = ?",
            (destino_id, instrumento_id, origen_id),
        )
    conn.commit()
    return movidas


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


def borrar_con_operaciones(conn: sqlite3.Connection, id: int) -> bool:
    """Borra un grupo y todas sus compras y ventas (los instrumentos se conservan).

    Todo junto o nada. Devuelve True si existía. Es irreversible.
    """
    try:
        conn.execute("DELETE FROM ventas WHERE grupo_id = ?", (id,))
        conn.execute("DELETE FROM compras WHERE grupo_id = ?", (id,))
        cur = conn.execute("DELETE FROM grupos WHERE id = ?", (id,))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return cur.rowcount == 1
