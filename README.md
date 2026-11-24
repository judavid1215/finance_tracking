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
- `actualizacion.py`: consulta de una vez el precio de ahora de todo lo que tienes (opción 14, y
  también al arrancar). Solo toca instrumentos con participaciones, sigue si uno falla, marca los
  precios con más de 5 días como antiguos, consulta el tipo de cambio de las divisas que uses y
  termina con un resumen. También baja el histórico diario de Yahoo (opción 17): precios y tipos
  de cambio a euros. La primera vez desde la primera compra; después solo los días que faltan.
  El día de hoy no se guarda (su cierre puede estar a medias); entra completo en la siguiente.

Para probar a mano: `python main.py` (menú de consola).

## Grupos

Cada compra y venta pertenece a un grupo (`grupos.py`: Personal, Pension...), para poder tener el
mismo fondo con objetivos distintos. Un instrumento sigue siendo uno solo (un histórico de
precios) y su posición se calcula por grupo: no se puede vender de un grupo lo que solo tiene
otro. Sin indicar grupo se usa "Personal". La cartera da una fila por instrumento y grupo, el
reparto puede agruparse por grupo y los grupos se gestionan con la opción 19 del menú.
Las bases anteriores a los grupos no se migran: hay que borrarlas y volver a importar.

## Importar desde CSV (MyInvestor)

`finanzas.importacion.importar_csv(nombre, isin, divisa, ruta, grupo="Personal", ruta_db=..., ticker_yahoo=None)`
importa un CSV de **órdenes** de MyInvestor (`Fecha de la orden;ISIN;Importe estimado;Nº de participaciones;Estado`)
como un fondo (uno por llamada). Lanza `ValueError` si algo falla.

- Cada orden `Finalizada` es una compra: fecha, participaciones y precio = importe / participaciones
  (comisión 0).
- Las órdenes `En curso` y `Rechazada` se ignoran (aún no tienen participaciones) y se cuentan en el resumen.
- El ISIN y la divisa del CSV deben coincidir con los indicados.

Todo o nada: un error en cualquier fila cancela la importación y se listan todos. Un
fondo que ya tiene compras en el grupo se rechaza.


## De dónde salen los precios

Cada instrumento puede tener un **ticker de Yahoo** (opción 18 del menú, o `ticker_yahoo` al
importar) que se usa en lugar del ISIN o ticker para buscar el precio actual y el histórico
(opciones 14 y 17). Sirve cuando Yahoo no tiene datos con el ISIN, p. ej. `0P00009PQ4.F` para un
fondo. El identificador (ISIN) no cambia.

Ninguna fuente es una API oficial; el precio se puede poner a mano (opción 9) o descargar
(opciones 13, 14 y 17 del menú).

Hay dos tipos de precio:

- **Histórico** (tabla `precios`): un cierre por instrumento y día. Lo rellena la opción 17
  (Yahoo, desde la primera compra), la opción 9 (a mano) y los planes de pensiones (13 y 14, su
  valor liquidativo es oficial y diario). Es lo que se usará para ver la evolución en el tiempo.
- **En vivo**: el precio de Yahoo y el tipo de cambio del momento de la consulta (al arrancar y
  con la opción 14). Se usan para calcular la cartera (opciones 8 y 16), pero solo viven en
  memoria mientras la aplicación está abierta: no se guardan en el histórico. Si no hay valor en
  vivo, se usa el último guardado.

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

La opción 8 acaba con el total de la cartera en euros. Convierte con el tipo de cambio del
momento (se consulta al arrancar y con la opción 14; si no hay, el último guardado), tanto el
valor como lo invertido: lo invertido en
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

Para rellenar la base con compras y ventas de ejemplo: `python scripts/rellenar_datos.py`.
Las fechas, cantidades y comisiones son inventadas, pero los precios son reales (cierre de
Yahoo del día de cada operación); solo el plan de pensiones, sin histórico, lleva precios
inventados. Necesita conexión. Si un instrumento ya existe se salta; para empezar de cero,
borra antes `data/finanzas.sqlite3`. Después, la opción 17 baja el histórico.

## Probar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install pytest ruff yfinance
.\.venv\Scripts\python -m pytest -v
```

## Web para el móvil

Interfaz de solo lectura para ver la evolución desde el móvil: `python servir.py [puerto]` y abrir
`http://<ip-de-la-raspberry>:8000` (puerto 8000 por defecto). Necesita `flask` (`pip install flask`).

- `periodos.py`: recorta la serie diaria a 1S, 1M, 1A, YTD o Máx. La ganancia y la rentabilidad
  son *del periodo* (se descuenta la ganancia que ya había al empezar, así que aportar dinero no
  cuenta como ganancia). La rentabilidad es una aproximación sencilla; la ponderada por tiempo
  (TWR) queda pendiente.
- `evolucion.serie()` y `evolucion.aportaciones()` (las compras en euros) admiten `grupo_id` y/o
  `instrumento_id`. En las vistas de valor y de rentabilidad, cada día con compras lleva un círculo relleno sobre la línea
  (una compra en festivo se marca en el siguiente día con precio).
- El botón de la esquina cambia el tema: automático (el del sistema), claro u oscuro.
- `web/app.py`: API (`/api/opciones`, `/api/evolucion`) y página en `web/static/`
  (Chart.js se carga desde un CDN: el móvil necesita internet para dibujar el gráfico).
- Escucha en toda la red local y no tiene contraseña: no la expongas a internet (fuera de casa,
  usa algo como Tailscale).
