# Finanzas

Seguimiento personal de inversiones. Python 3.12 + SQLite (módulo estándar `sqlite3`).

Qué hay (en `src/finanzas/`):

- `instrumentos.py`: añadir, borrar y consultar instrumentos.
- `compras.py` y `ventas.py`: operaciones de compra y venta, cada una con su comisión
  opcional (0 por defecto). La comisión va en la divisa del instrumento, igual que el precio.
- `posicion.py`: participaciones e invertido de un instrumento con coste medio ponderado
  (una venta quita participaciones al precio medio que había). No deja vender de más.
  La comisión de una compra encarece el coste (sube lo invertido y el precio medio); la de
  una venta no cambia la posición, solo se guarda.
- `precios.py`: precio actual puesto a mano.
- `cartera.py`: resumen de lo que hay en cartera.

Para probar a mano: `python main.py` (menú de consola).

No incluido todavía: cálculo de impuestos (en España las ventas se imputan por FIFO, se hará
cuando se aborde; ahí se restará la comisión de venta al ingreso), traspasos entre fondos ni
cambio de divisa.

Las bases creadas antes de existir las comisiones se actualizan solas al conectar (la columna
`comision` se añade y las filas antiguas quedan a 0).

Para rellenar la base con datos inventados (compras, ventas y comisiones):
`python scripts/rellenar_datos.py`. Si un instrumento ya existe se salta; para empezar de
cero, borra antes `data/finanzas.sqlite3`.

## Probar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install pytest ruff
.\.venv\Scripts\python -m pytest -v
```
