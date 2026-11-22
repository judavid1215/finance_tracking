from finanzas import db


def test_crea_la_carpeta_si_no_existe(tmp_path):
    ruta = tmp_path / "data" / "sub" / "t.sqlite3"
    db.conectar(ruta).close()
    assert ruta.exists()


def test_base_antigua_sin_ticker_yahoo_se_actualiza(tmp_path):
    import sqlite3

    ruta = tmp_path / "vieja.sqlite3"
    viejo = sqlite3.connect(ruta)
    viejo.execute(
        "CREATE TABLE instrumentos (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, "
        "tipo TEXT NOT NULL, divisa TEXT NOT NULL)"
    )
    viejo.execute("INSERT INTO instrumentos (nombre, tipo, divisa) VALUES ('A', 'Fondo', 'EUR')")
    viejo.commit()
    viejo.close()
    conn = db.conectar(ruta)
    assert conn.execute("SELECT ticker_yahoo FROM instrumentos").fetchone()[0] is None
    conn.close()
