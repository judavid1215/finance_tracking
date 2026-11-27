"""Importa las operaciones de acciones de Interactive Brokers desde una Flex Query en CSV.

Uso:
    from finanzas.importacion_ibkr import importar_csv
    importar_csv(r"C:\\ruta\\IBKR_trade.csv", grupo="Interactive Brokers",
                 tickers_yahoo={"IBE": "IBE.MC"})

El CSV es el de la Flex Query "Trades" (con o sin las líneas BOF/BOA/BOS/EOS/EOA/EOF). Columnas
usadas: CurrencyPrimary, AssetClass, Symbol, Description, TradeID, TradeDate, Quantity,
TradeMoney, IBCommission, IBCommissionCurrency, Buy/Sell, IBOrderID.

- Solo cuenta `AssetClass = STK` (acciones y ETF; todos entran como tipo Accion, IBKR no los
  distingue). Las filas CASH (cambios de divisa) y las que no tienen TradeID (derechos y otras
  operaciones corporativas) se ignoran y se cuentan en el resumen.
- IBKR parte una orden en varias ejecuciones (fills): se juntan por orden, fecha y lado. La
  cantidad y el importe se suman, el precio es importe / cantidad y la comisión es la suma de
  las comisiones de las ejecuciones (IBKR a veces devuelve una parte: se netea). El precio y la
  comisión van en la divisa del instrumento, sin convertir: el euro se calcula al valorar.
- Un instrumento se identifica por su ticker (Symbol). Si ya existe, se reutiliza.
- Se puede reimportar un CSV que se solape con otro: las operaciones que ya están (mismo
  instrumento, grupo, fecha, cantidad y precio) se saltan.
- Todo o nada: un error en cualquier fila (o una venta sin compras que la cubran) no escribe nada.
"""

import csv
import re
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from finanzas import compras, db, grupos, instrumentos, ventas

RUTA_DB = Path(__file__).resolve().parents[2] / "data" / "finanzas.sqlite3"
GRUPO_IBKR = "Interactive Brokers"
DECIMALES = Decimal("0.00000001")  # el máximo que admiten participaciones y precio

COLUMNAS = [
    "CurrencyPrimary",
    "AssetClass",
    "Symbol",
    "Description",
    "TradeID",
    "TradeDate",
    "Quantity",
    "TradeMoney",
    "IBCommission",
    "IBCommissionCurrency",
    "Buy/Sell",
    "IBOrderID",
]


# Sufijo de Yahoo según el país del ISIN, para las acciones en euros (IBE -> IBE.MC). Las que
# cotizan en EE. UU. no llevan sufijo.
SUFIJOS_YAHOO = {"ES": "MC", "DE": "DE", "FR": "PA", "NL": "AS", "IT": "MI", "BE": "BR", "PT": "LS"}


def es_flex_query(ruta: Path) -> bool:
    """¿Es un CSV de Flex Query de IBKR? (tiene la cabecera con CurrencyPrimary y TradeID)."""
    try:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            for _, fila in zip(range(10), csv.reader(f), strict=False):
                if fila and fila[0] == "CurrencyPrimary":
                    return "TradeID" in fila
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return False


def _ticker_yahoo(simbolo: str, isin: str, divisa: str) -> str | None:
    sufijo = SUFIJOS_YAHOO.get(isin[:2].upper()) if divisa == "EUR" else None
    return f"{simbolo}.{sufijo}" if sufijo and re.fullmatch(r"[A-Z0-9]+", simbolo) else None


def _numero(texto: str, campo: str) -> Decimal:
    try:
        d = Decimal(texto.strip())
    except InvalidOperation:
        raise ValueError(f"{campo}: número no válido: {texto!r}") from None
    if not d.is_finite():
        raise ValueError(f"{campo}: número no válido: {texto!r}")
    return d


def leer_csv(ruta: Path) -> tuple[list[dict], dict]:
    """Lee las ejecuciones de acciones del CSV.

    Devuelve (ejecuciones, ignoradas), con ignoradas = {"cambios_divisa": n, "sin_tradeid": n,
    "otras": n}. Lanza ValueError con todos los problemas encontrados, uno por línea.
    """
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        filas = [fila for fila in csv.reader(f) if fila]
    inicio = next((n for n, fila in enumerate(filas) if fila[0] == "CurrencyPrimary"), None)
    if inicio is None:
        raise ValueError("no encuentro la cabecera de la Flex Query (columna CurrencyPrimary)")
    cabecera = [c.strip() for c in filas[inicio]]
    faltan = [c for c in COLUMNAS if c not in cabecera]
    if faltan:
        raise ValueError(f"faltan columnas en la Flex Query: {', '.join(faltan)}")
    pos = {c: cabecera.index(c) for c in COLUMNAS}
    if "ISIN" in cabecera:
        pos["ISIN"] = cabecera.index("ISIN")

    ejecuciones, errores = [], []
    ignoradas = {"cambios_divisa": 0, "sin_tradeid": 0, "otras": 0}
    for n, fila in enumerate(filas[inicio + 1 :], start=inicio + 2):
        if fila[0] in ("EOS", "EOA", "EOF"):  # fin de sección: no hay más operaciones
            break
        try:
            if len(fila) != len(cabecera):
                raise ValueError(f"debe tener {len(cabecera)} columnas")
            v = {c: fila[i].strip() for c, i in pos.items()}
            if v["AssetClass"] == "CASH":
                ignoradas["cambios_divisa"] += 1
                continue
            if v["AssetClass"] != "STK":
                ignoradas["otras"] += 1
                continue
            if not v["TradeID"]:
                ignoradas["sin_tradeid"] += 1
                continue
            lado = v["Buy/Sell"].upper()
            if lado not in ("BUY", "SELL"):
                raise ValueError(f"Buy/Sell desconocido: {v['Buy/Sell']!r}")
            if not v["Symbol"]:
                raise ValueError("falta el Symbol")
            if not re.fullmatch(r"[A-Z]{3}", v["CurrencyPrimary"]):
                raise ValueError(f"divisa no válida: {v['CurrencyPrimary']!r}")
            if v["IBCommissionCurrency"] != v["CurrencyPrimary"]:
                raise ValueError(
                    f"la comisión está en {v['IBCommissionCurrency']} y el instrumento en "
                    f"{v['CurrencyPrimary']}"
                )
            cantidad = abs(_numero(v["Quantity"], "Quantity"))
            dinero = abs(_numero(v["TradeMoney"], "TradeMoney"))
            if cantidad == 0 or dinero == 0:
                raise ValueError("cantidad e importe deben ser distintos de 0")
            ejecuciones.append(
                {
                    "linea": n,
                    "simbolo": v["Symbol"].upper(),
                    "nombre": v["Description"] or v["Symbol"],
                    "isin": v.get("ISIN", "").upper(),
                    "divisa": v["CurrencyPrimary"],
                    "fecha": datetime.strptime(v["TradeDate"], "%Y%m%d").date(),
                    "lado": lado,
                    "cantidad": cantidad,
                    "dinero": dinero,
                    "comision": -_numero(v["IBCommission"], "IBCommission"),
                    "orden": v["IBOrderID"] or v["TradeID"],
                }
            )
        except ValueError as e:
            errores.append(f"línea {n}: {e}")
    if errores:
        raise ValueError("\n".join(errores))
    return ejecuciones, ignoradas


def agrupar(ejecuciones: list[dict]) -> list[dict]:
    """Junta las ejecuciones de una misma orden (símbolo, orden, fecha y lado) en una operación."""
    juntas: dict[tuple, dict] = {}
    for e in ejecuciones:
        clave = (e["simbolo"], e["orden"], e["fecha"], e["lado"])
        if clave not in juntas:
            juntas[clave] = dict(e)
        else:
            j = juntas[clave]
            j["cantidad"] += e["cantidad"]
            j["dinero"] += e["dinero"]
            j["comision"] += e["comision"]
    operaciones = []
    for j in juntas.values():
        if j["comision"] < 0:
            raise ValueError(
                f"{j['simbolo']} {j['fecha']}: la comisión de la orden {j['orden']} sale "
                f"negativa ({-j['comision']}); revisa el CSV"
            )
        j["cantidad"] = j["cantidad"].quantize(DECIMALES, ROUND_HALF_UP)
        j["precio"] = (j["dinero"] / j["cantidad"]).quantize(DECIMALES, ROUND_HALF_UP)
        j["comision"] = j["comision"].quantize(DECIMALES, ROUND_HALF_UP)
        operaciones.append(j)
    return sorted(operaciones, key=lambda o: (o["fecha"], o["simbolo"], o["orden"]))


def preparar(conn, ruta: Path, grupo: str, tickers_yahoo: dict[str, str] | None = None) -> dict:
    """Lee el CSV y calcula qué se importaría, sin escribir nada. Lanza ValueError si algo falla."""
    grupo = grupo.strip()
    if not grupo:
        raise ValueError("falta el grupo")
    try:
        ejecuciones, ignoradas = leer_csv(Path(ruta))
    except OSError as e:
        raise ValueError(f"no se puede leer {ruta}: {e.strerror}") from None
    operaciones = agrupar(ejecuciones)
    if not operaciones:
        raise ValueError("el CSV no tiene ninguna operación de acciones")

    divisas = defaultdict(set)
    for o in operaciones:
        divisas[o["simbolo"]].add(o["divisa"])
    mezcladas = [s for s, d in divisas.items() if len(d) > 1]
    if mezcladas:
        raise ValueError(f"mismo símbolo en varias divisas: {', '.join(sorted(mezcladas))}")

    tickers_yahoo = {k.upper(): v.upper() for k, v in (tickers_yahoo or {}).items()}
    existentes = {
        i["identificador"]: i for i in instrumentos.listar(conn) if i["id_tipo"] == "TICKER"
    }
    g = grupos.obtener_por_nombre(conn, grupo)
    nuevos, repetidas, a_importar = {}, 0, []
    for o in operaciones:
        inst = existentes.get(o["simbolo"])
        if inst is None:
            nuevos.setdefault(o["simbolo"], o)
        elif inst["divisa"] != o["divisa"]:
            raise ValueError(
                f"{o['simbolo']} ya existe en {inst['divisa']} y el CSV lo trae en {o['divisa']}"
            )
        if inst and g and _ya_existe(conn, inst["id"], g["id"], o):
            repetidas += 1
        else:
            a_importar.append(o)
    nombres = {i["nombre"].lower() for i in existentes.values()}
    for s, o in nuevos.items():
        if o["nombre"].lower() in nombres:
            raise ValueError(f"ya existe un instrumento llamado '{o['nombre']}' ({s})")
    return {
        "grupo": g["nombre"] if g else grupo,
        "operaciones": a_importar,
        "repetidas": repetidas,
        "nuevos": {
            s: {
                "nombre": o["nombre"],
                "divisa": o["divisa"],
                "ticker_yahoo": tickers_yahoo.get(s) or _ticker_yahoo(s, o["isin"], o["divisa"]),
            }
            for s, o in nuevos.items()
        },
        "ignoradas": ignoradas,
    }


def _ya_existe(conn, instrumento_id: int, grupo_id: int, op: dict) -> bool:
    tabla = compras if op["lado"] == "BUY" else ventas
    return any(
        x["fecha"] == op["fecha"]
        and x["participaciones"] == op["cantidad"]
        and x["precio"] == op["precio"]
        for x in tabla.listar(conn, instrumento_id, grupo_id)
    )


def aplicar(conn, plan: dict) -> None:
    """Escribe el plan; si algo falla deshace todo lo escrito y relanza el error."""
    ids = {
        i["identificador"]: i["id"] for i in instrumentos.listar(conn) if i["id_tipo"] == "TICKER"
    }
    creados, compras_ids, ventas_ids = [], [], []
    grupo_id, grupo_creado = None, False
    try:
        grupo_id, grupo_creado = grupos.obtener_o_crear(conn, plan["grupo"])
        for simbolo, n in plan["nuevos"].items():
            ids[simbolo] = instrumentos.anadir(
                conn, n["nombre"], "Accion", n["divisa"], simbolo, n["ticker_yahoo"]
            )
            creados.append(ids[simbolo])
        # Primero todas las compras y después las ventas: la posición se comprueba en cada venta.
        for o in plan["operaciones"]:
            if o["lado"] == "BUY":
                compras_ids.append(
                    compras.anadir(
                        conn,
                        ids[o["simbolo"]],
                        o["fecha"],
                        o["cantidad"],
                        o["precio"],
                        o["comision"],
                        grupo_id,
                    )
                )
        for o in plan["operaciones"]:
            if o["lado"] == "SELL":
                try:
                    ventas_ids.append(
                        ventas.anadir(
                            conn,
                            ids[o["simbolo"]],
                            o["fecha"],
                            o["cantidad"],
                            o["precio"],
                            o["comision"],
                            grupo_id,
                        )
                    )
                except ValueError as e:
                    raise ValueError(
                        f"venta de {o['simbolo']} del {o['fecha']}: {e}. Si compraste antes del "
                        "periodo del CSV, descarga también el histórico anterior"
                    ) from None
    except Exception:
        for id_ in ventas_ids:
            ventas.borrar(conn, id_)
        for id_ in compras_ids:
            conn.execute("DELETE FROM compras WHERE id = ?", (id_,))
        conn.commit()
        for id_ in creados:
            instrumentos.borrar(conn, id_)
        if grupo_creado:
            grupos.borrar(conn, grupo_id)
        raise
    plan["grupo_creado"] = grupo_creado


def resumen(plan: dict) -> str:
    """Texto con lo que se importa (o se ha importado)."""
    ops = plan["operaciones"]
    n_compras = sum(o["lado"] == "BUY" for o in ops)
    lineas = [
        f"[{plan['grupo']}] {n_compras} compras y {len(ops) - n_compras} ventas "
        f"({len(plan['nuevos'])} instrumentos nuevos)"
    ]
    if plan["repetidas"]:
        lineas.append(f"  {plan['repetidas']} operaciones ya estaban y se saltan")
    ig = plan["ignoradas"]
    partes = []
    if ig["cambios_divisa"]:
        partes.append(f"{ig['cambios_divisa']} cambios de divisa")
    if ig["sin_tradeid"]:
        partes.append(f"{ig['sin_tradeid']} sin TradeID (derechos u operaciones corporativas)")
    if ig["otras"]:
        partes.append(f"{ig['otras']} de otro tipo de activo")
    if partes:
        lineas.append("  ignoradas: " + ", ".join(partes))
    sin_yahoo = [
        s for s, n in plan["nuevos"].items() if n["divisa"] != "USD" and not n["ticker_yahoo"]
    ]
    if sin_yahoo:
        lineas.append(
            f"  AVISO: {', '.join(sin_yahoo)} no cotiza en dólares y no tiene ticker de Yahoo: "
            "Yahoo puede no encontrarlo (ej. IBE.MC para Iberdrola)"
        )
    return "\n".join(lineas)


def a_json(plan: dict) -> dict:
    """Lo que enseña la vista previa de la web: operaciones (con fecha ISO y números normales),
    cuántas ya estaban, instrumentos nuevos y un texto con lo ignorado."""
    ig = plan["ignoradas"]
    partes = []
    if ig["cambios_divisa"]:
        partes.append(f"{ig['cambios_divisa']} cambios de divisa")
    if ig["sin_tradeid"]:
        partes.append(f"{ig['sin_tradeid']} sin TradeID (derechos u operaciones corporativas)")
    if ig["otras"]:
        partes.append(f"{ig['otras']} de otro tipo de activo")
    return {
        "formato": "ibkr",
        "operaciones": [
            {
                "fecha": o["fecha"].isoformat(),
                "simbolo": o["simbolo"],
                "lado": o["lado"],
                "participaciones": float(o["cantidad"]),
                "precio": float(o["precio"]),
                "divisa": o["divisa"],
            }
            for o in plan["operaciones"]
        ],
        "repetidas": plan["repetidas"],
        "nuevos": [n["nombre"] for n in plan["nuevos"].values()],
        "ignoradas": sum(ig.values()),
        "nota": ("Se ignoran: " + ", ".join(partes) + ".") if partes else "",
    }


def importar_csv(
    ruta: str | Path,
    grupo: str = GRUPO_IBKR,
    ruta_db: str | Path = RUTA_DB,
    tickers_yahoo: dict[str, str] | None = None,
    solo_ver: bool = False,
) -> dict:
    """Importa el CSV de la Flex Query, imprime un resumen y devuelve el plan.

    `grupo` es el grupo al que van las operaciones (se crea si no existe). `tickers_yahoo`
    ({"IBE": "IBE.MC"}) fija el símbolo de Yahoo de los instrumentos nuevos. Con `solo_ver` no
    se escribe nada. Lanza ValueError sin escribir nada si el CSV tiene algún problema.
    """
    conn = db.conectar(ruta_db)
    try:
        plan = preparar(conn, Path(ruta), grupo, tickers_yahoo)
        if not solo_ver:
            aplicar(conn, plan)
    finally:
        conn.close()
    print(resumen(plan))
    print("Hecho." if not solo_ver else "Solo revisado: no se ha escrito nada.")
    return plan
