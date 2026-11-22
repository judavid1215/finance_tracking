from finanzas import db


def test_crea_la_carpeta_si_no_existe(tmp_path):
    ruta = tmp_path / "data" / "sub" / "t.sqlite3"
    db.conectar(ruta).close()
    assert ruta.exists()
