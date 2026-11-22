# Finanzas

Seguimiento personal de inversiones. Python 3.12 + SQLite (módulo estándar `sqlite3`).

Por ahora solo hay operaciones sobre la tabla `instrumentos`: añadir, borrar y consultar
(`src/finanzas/instrumentos.py`).

## Probar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install pytest ruff
.\.venv\Scripts\python -m pytest -v
```
