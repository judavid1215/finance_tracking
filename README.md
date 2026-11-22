# Finanzas

Seguimiento personal de inversiones. Python 3.12 + SQLite (módulo estándar `sqlite3`) + yfinance para los precios.

Qué hay (en `src/finanzas/`):

- `instrumentos.py`: añadir, borrar y consultar instrumentos.
- `compras.py` y `ventas.py`: operaciones de compra y venta, cada una con su comisión
  opcional (0 por defecto). La comisión va en la divisa del instrumento, igual que el precio.
- `posicion.py`: participaciones e invertido de un instrumento con coste medio ponderado
  (una venta quita participaciones al precio medio que había). No deja vender de más.
  La comisión de una compra encarece el coste (sube lo invertido y el precio medio); la de
  una venta no cambia la posición, solo se guarda.
- `precios.py`: guarda el precio de un instrumento por fecha (a mano o automático).
- `yahoo.py` y `quefondos.py`: descargan el precio actual (ver "De dónde salen los precios").
- `cartera.py`: resumen de lo que hay en cartera y su total en euros (`total`).
- `divisas.py`: tipos de cambio a euros desde Yahoo (`USDEUR=X`).
- `actualizacion.py`: actualiza de una vez el precio de todo lo que tienes (opción 14). Solo toca
  instrumentos con participaciones, sigue si uno falla, marca los precios con más de 5 días
  como antiguos, baja el tipo de cambio de las divisas que uses y termina con un resumen.

Para probar a mano: `python main.py` (menú de consola).

## De dónde salen los precios

Ninguna fuente es una API oficial; el precio se puede poner a mano (opción 9) o descargar
(opciones 13 y 14 del menú). El precio se guarda con la fecha que da la fuente, que puede ser
de unos días antes.

| Tipo | Fuente | Se busca por |
|---|---|---|
| Fondo, ETF | [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance) | ISIN |
| Acción | yfinance | ticker (ej. `NVDA`) |
| Cripto | yfinance | ticker de Yahoo (ej. `BTC-EUR`), opcional |
| Plan de pensiones | [Quefondos](https://www.quefondos.com) (lee su web) | código DGS (ej. `N5396`) |

- **yfinance** es gratis y no oficial; Yahoo puede cambiar o limitar el acceso. Si Yahoo da el
  precio en otra divisa que la del instrumento (un ETF que cotiza en USD en esa bolsa), no se
  guarda y se avisa.
- **Quefondos** no tiene API: se lee el valor liquidativo de su página con una expresión
  regular. Si cambian la web, saldrá un error claro y habrá que ajustar `quefondos.py`.
- **Morningstar** se descartó: su API es de pago (institucional) y las librerías no oficiales
  necesitan Chrome con ventana. Finect no tiene API documentada.
- Una cripto sin ticker no se actualiza sola: usa la opción 15 para ponérselo.

No incluido todavía: cálculo de impuestos (en España las ventas se imputan por FIFO, se hará
cuando se aborde; ahí se restará la comisión de venta al ingreso), traspasos entre fondos ni
operaciones de cambio de divisa.

## Total en euros

La opción 8 acaba con el total de la cartera en euros. Convierte con el último tipo de cambio
guardado (opción 14 lo descarga de Yahoo), tanto el valor como lo invertido: lo invertido en
dólares se ve a lo que vale hoy el dólar, no a lo que valía al comprar, así que la ganancia
incluye el efecto de la divisa solo desde hoy. Lo que no tenga precio, o tipo de cambio si no
está en euros, no cuenta en el total y se lista aparte.

## Reparto en porcentaje

La opción 16 muestra qué porcentaje del valor en euros pesa cada grupo, agrupado por instrumento,
tipo (fondo, ETF, acción...) o divisa del instrumento. Usa los mismos criterios que el total: lo
que no tenga precio o tipo de cambio no cuenta (se lista aparte) y los porcentajes suman 100
sobre lo valorado. En código: `cartera.reparto(conn, por)`.

Las bases creadas antes de existir las comisiones se actualizan solas al conectar (la columna
`comision` se añade y las filas antiguas quedan a 0).

Para rellenar la base con datos inventados (compras, ventas y comisiones):
`python scripts/rellenar_datos.py`. Si un instrumento ya existe se salta; para empezar de
cero, borra antes `data/finanzas.sqlite3`.

## Probar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install pytest ruff yfinance
.\.venv\Scripts\python -m pytest -v
```
