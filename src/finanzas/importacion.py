"""Importa a la base las posiciones abiertas de los CSV "Plusvalías y minusvalías" de MyInvestor.

Uso:
    from finanzas.importacion import importar_csv
    importar_csv("Fidelity MSCI World", "IE00BYX5NX33", "EUR", r"C:
utaichero.csv")
Un fondo por llamada.

Cada fila del CSV es un lote que sigue en cartera: Fecha fiscal (la compra), Inversión, Valor de
mercado y Resultado fiscal. El CSV no trae participaciones ni precios, así que se calculan:

- participaciones = valor de mercado / valor liquidativo (NAV) con el que MyInvestor valoró.
  Ese NAV es de un día cercano a la fecha de modificación del fichero; se prueban los últimos
  cierres de Yahoo y se elige el que hace que el precio de compra implícito encaje mejor con el
  histórico de Yahoo en la fecha de cada lote.
- precio de compra = inversión / participaciones (comisión 0: la inversión ya la incluye).
- excepción: un lote cuyo precio de compra implícito difiere más de un 10 % del de Yahoo (p. ej.
  un traspaso entre fondos) se calcula con el cierre de Yahoo de su fecha fiscal:
  participaciones = inversión / precio.

Todo o nada: si falla cualquier fila no se escribe nada y se listan todos los errores.
Si el fondo ya tiene compras, se rechaza (para reimportarlo hay que borrarlas antes). Si ya
existe el instrumento con ese ISIN y sin compras, se reutiliza.
"""

import csv
import re
import statistics
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from finanzas import compras, db, instrumentos, yahoo

RUTA_DB = Path(__file__).resolve().parents[2] / "data" / "finanzas.sqlite3"

CABECERA = ["Fecha fiscal", "Inversión", "Valor de mercado", "Resultado fiscal"]

CANDIDATOS = 5  # cuántos de los últimos cierres se prueban como NAV de la exportación
VENTANA = 4  # días a cada lado de la fecha fiscal en los que se busca el precio de compra
TOL_YAHOO = Decimal("0.10")  # un lote con más error se calcula con el precio de Yahoo (traspasos)
TOL_MEDIANA = Decimal("0.015")  # error mediano máximo entre precio implícito y el de Yahoo
DECIMALES = Decimal("0.000001")  # participaciones y precio: 6 decimales (el máximo es 8)


class FondoYaImportado(ValueError):
    """El fondo ya tiene compras en la base."""


def normalizar_isin(isin: str) -> str:
    isin = isin.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        raise ValueError(f"ISIN no válido: {isin!r}")
    return isin


def _numero(texto: str) -> Decimal:
    if "." in texto:
        raise ValueError(f"número con punto: {texto!r} (se espera coma decimal)")
    try:
        return Decimal(texto.strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"número no válido: {texto!r}") from None


def leer_csv(ruta: Path) -> list[dict]:
    """Lee los lotes del CSV (separador ';', coma decimal, fechas dd/mm/aaaa).

    Lanza ValueError con todos los problemas encontrados, uno por línea.
    """
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = [fila for fila in csv.reader(f, delimiter=";") if fila]
    if not filas or [c.strip() for c in filas[0]] != CABECERA:
        raise ValueError(f"la cabecera debe ser: {';'.join(CABECERA)}")
    lotes, errores = [], []
    for n, fila in enumerate(filas[1:], start=2):
        try:
            if len(fila) != 4:
                raise ValueError("debe tener 4 columnas")
            fecha = datetime.strptime(fila[0].strip(), "%d/%m/%Y").date()
            inversion, valor, resultado = (_numero(c) for c in fila[1:])
            if inversion <= 0 or valor <= 0:
                raise ValueError("inversión y valor de mercado deben ser mayores que 0")
            if abs(valor - inversion - resultado) > Decimal("0.01"):
                raise ValueError("valor - inversión no coincide con el resultado fiscal")
            lotes.append(
                {"fecha": fecha, "inversion": inversion, "valor": valor, "resultado": resultado}
            )
        except ValueError as e:
            errores.append(f"línea {n}: {e}")
    if errores:
        raise ValueError("\n".join(errores))
    if not lotes:
        raise ValueError("no tiene ningún lote")
    return lotes


def _error_lote(lote: dict, nav: Decimal, historico: list) -> Decimal | None:
    """Diferencia relativa entre el precio de compra implícito y el más cercano de Yahoo.

    None si Yahoo no tiene ningún precio cerca de la fecha del lote (no se puede comprobar).
    """
    implicito = lote["inversion"] * nav / lote["valor"]
    cercanos = [p for f, p in historico if abs((f - lote["fecha"]).days) <= VENTANA]
    return min(abs(implicito / p - 1) for p in cercanos) if cercanos else None


def elegir_nav(
    lotes: list[dict], historico: list, fecha_export: date
) -> tuple[date, Decimal, Decimal | None]:
    """Devuelve (fecha, NAV, error mediano) del cierre que mejor explica los lotes.

    Se prueban los últimos cierres anteriores a la exportación (el de ese mismo día aún no
    está publicado). Con empate gana el más reciente. Lanza ValueError si ninguno encaja.
    Si Yahoo no tiene histórico cerca de ningún lote no se puede validar: se usa el último
    cierre y el error mediano sale None (el script lo avisa).
    """
    cierres = [(f, p) for f, p in historico if f < fecha_export][-CANDIDATOS:]
    if not cierres:
        raise ValueError("Yahoo no tiene cierres anteriores a la fecha de exportación")
    mejor = None
    for fecha, nav in reversed(cierres):
        errores = [
            e for e in (_error_lote(lote, nav, historico) for lote in lotes) if e is not None
        ]
        if not errores:
            return cierres[-1][0], cierres[-1][1], None
        mediana = statistics.median(errores)
        if mejor is None or mediana < mejor[2]:
            mejor = (fecha, nav, mediana)
    fecha, nav, mediana = mejor
    if mediana > TOL_MEDIANA:
        raise ValueError(
            f"ningún NAV reciente encaja con el histórico de Yahoo (mejor: {fecha:%d/%m/%Y}, "
            f"error mediano {mediana:.2%})"
        )
    return fecha, nav, mediana


def preparar(
    ruta: Path, isin: str, nombre: str, divisa: str, conn, leer_historico=None, ticker_yahoo=None
) -> dict:
    """Valida un CSV y calcula sus compras, sin escribir nada. Lanza ValueError si algo falla."""
    leer_historico = leer_historico or yahoo.leer_historico
    isin = normalizar_isin(isin)
    nombre = nombre.strip()
    divisa = divisa.strip().upper()
    if not nombre:
        raise ValueError("falta el nombre del fondo")
    if not re.fullmatch(r"[A-Z]{3}", divisa):
        raise ValueError(f"divisa no válida: {divisa!r} (se espera un código como EUR)")
    try:
        lotes = leer_csv(ruta)
    except OSError as e:
        raise ValueError(f"no se puede leer {ruta}: {e.strerror}") from None
    fecha_export = datetime.fromtimestamp(ruta.stat().st_mtime).date()
    if max(lote["fecha"] for lote in lotes) > fecha_export:
        raise ValueError("hay lotes con fecha posterior a la del fichero")
    existente = next((i for i in instrumentos.listar(conn) if i["identificador"] == isin), None)
    if existente and compras.listar(conn, existente["id"]):
        raise FondoYaImportado(
            f"{existente['nombre']} ya tiene compras; bórralas antes de reimportar"
        )
    ticker_yahoo = (ticker_yahoo or "").strip().upper() or None
    simbolo = ticker_yahoo or (existente["ticker_yahoo"] if existente else None) or isin
    historico, divisa_yahoo = leer_historico(
        simbolo,
        min(lote["fecha"] for lote in lotes) - timedelta(days=10),
    )
    if divisa_yahoo != divisa:
        raise ValueError(f"Yahoo da {isin} en {divisa_yahoo} y has indicado {divisa}")
    fecha_nav, nav, error = elegir_nav(lotes, historico, fecha_export)
    operaciones, con_precio_yahoo = [], 0
    for lote in lotes:
        error_lote = _error_lote(lote, nav, historico)
        if error_lote is not None and error_lote > TOL_YAHOO:
            # Lote que no encaja (p. ej. un traspaso entre fondos): se usa el cierre de Yahoo del
            # día de la fecha fiscal (o el siguiente): participaciones = inversión / precio.
            precio = next(p for f, p in historico if f >= lote["fecha"])
            participaciones = (lote["inversion"] / precio).quantize(DECIMALES, ROUND_HALF_UP)
            con_precio_yahoo += 1
        else:
            participaciones = (lote["valor"] / nav).quantize(DECIMALES, rounding=ROUND_HALF_UP)
            precio = (lote["inversion"] / participaciones).quantize(DECIMALES, ROUND_HALF_UP)
        operaciones.append((lote["fecha"], participaciones, precio))
    return {
        "isin": isin,
        "nombre": nombre,
        "divisa": divisa,
        "ticker_yahoo": ticker_yahoo,
        "id": existente["id"] if existente else None,
        "compras": sorted(operaciones),
        "nav": (fecha_nav, nav, error),
        "con_precio_yahoo": con_precio_yahoo,
        "invertido": sum(lote["inversion"] for lote in lotes),
        "valor": sum(lote["valor"] for lote in lotes),
    }


def aplicar(conn, plan: dict) -> None:
    """Escribe el plan; si algo falla deshace todo lo escrito y relanza el error."""
    id_ = plan["id"]
    creado = id_ is None
    try:
        if creado:
            id_ = instrumentos.anadir(
                conn, plan["nombre"], "Fondo", plan["divisa"], plan["isin"], plan["ticker_yahoo"]
            )
        elif plan["ticker_yahoo"]:
            instrumentos.asignar_ticker_yahoo(conn, id_, plan["ticker_yahoo"])
        for fecha, participaciones, precio in plan["compras"]:
            compras.anadir(conn, id_, fecha, participaciones, precio)
    except Exception:
        if id_ is not None:
            conn.execute("DELETE FROM compras WHERE instrumento_id = ?", (id_,))
            conn.commit()
            if creado:
                instrumentos.borrar(conn, id_)
        raise


def importar(
    conn,
    ruta: Path,
    isin: str,
    nombre: str,
    divisa: str,
    leer_historico=None,
    ticker_yahoo: str | None = None,
) -> dict:
    """Valida el CSV y, si no hay ningún error, lo escribe.

    Devuelve el plan (compras calculadas, NAV elegido...). Lanza ValueError si algo falla.
    """
    plan = preparar(Path(ruta), isin, nombre, divisa, conn, leer_historico, ticker_yahoo)
    aplicar(conn, plan)
    return plan


def resumen(plan: dict) -> str:
    """Texto de una línea con lo calculado para un fondo."""
    fecha, nav, error = plan["nav"]
    validacion = (
        f"error mediano {error:.2%}"
        if error is not None
        else "SIN VALIDAR: Yahoo no tiene histórico"
    )
    texto = (
        f"{plan['nombre']}: {len(plan['compras'])} compras, "
        f"{sum(c[1] for c in plan['compras'])} participaciones, invertido {plan['invertido']} "
        f"{plan['divisa']}, valor {plan['valor']} {plan['divisa']} "
        f"(NAV {nav} del {fecha:%d/%m/%Y}, {validacion})"
    )
    if plan["con_precio_yahoo"]:
        texto += f", {plan['con_precio_yahoo']} lote(s) con precio de Yahoo"
    return texto


def importar_csv(
    nombre: str,
    isin: str,
    divisa: str,
    ruta: str | Path,
    ruta_db: str | Path = RUTA_DB,
    ticker_yahoo: str | None = None,
) -> dict | None:
    """Importa un CSV de MyInvestor como un fondo nuevo, imprime un resumen y devuelve el plan.

    Si el fondo ya tiene compras, avisa, no hace nada y devuelve None (así se puede repetir una
    serie de llamadas sin que se pare). Con cualquier otro problema lanza ValueError sin escribir
    nada: ISIN, nombre o divisa no válidos, CSV mal formado, divisa distinta de la de Yahoo, NAV
    que no encaja...
    `ruta_db` es la base de datos a usar. `ticker_yahoo`
    (opcional, ej. "0P00009PQ4.F") es el símbolo con el que se busca el histórico en Yahoo cuando
    el ISIN no da datos. Se guarda en el instrumento y se usa también para los precios y el
    histórico posteriores; el fondo se guarda siempre con su ISIN como identificador.
    """
    conn = db.conectar(ruta_db)
    try:
        plan = importar(conn, Path(ruta), isin, nombre, divisa, ticker_yahoo=ticker_yahoo)
    except FondoYaImportado as e:
        print(f"AVISO: {e}. No se importa de nuevo.")
        return None
    finally:
        conn.close()
    print(resumen(plan))
    print("Hecho.")
    return plan


if __name__ == "__main__":
    path_msci = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo IE00BYX5NX33.csv"
    importar_csv(
        nombre="Fidelity MSCI World Index Fund P-ACC-EUR",
        isin="IE00BYX5NX33",
        divisa="EUR",
        ruta=path_msci,
    )

    path_axa = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo FR0000447823.csv"
    importar_csv(
        nombre="AXA Trésor Court Terme C", isin="FR0000447823", divisa="EUR", ruta=path_axa
    )

    path_ishares = (
        r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo IE000ZYRH0Q7.csv"
    )
    importar_csv(
        nombre="iShares Developed World Index Fund (IE) Class S",
        isin="IE000ZYRH0Q7",
        divisa="EUR",
        ruta=path_ishares,
    )

    path_dnb = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo LU0302296495.csv"
    importar_csv(
        nombre="DNB Fund - Technology A EUR (Acc)",
        ticker_yahoo="0P00009PQ4.F",
        isin="LU0302296495",
        divisa="EUR",
        ruta=path_dnb,
    )

    path_amundi = r"C:\finance_tracking\import_data\Plusvalías y minusvalías fondo LU0996175948.csv"
    importar_csv(
        nombre="Amundi Core MSCI Emerging Markets",
        isin="LU0996175948",
        divisa="EUR",
        ruta=path_amundi,
    )