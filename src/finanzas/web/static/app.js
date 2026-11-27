"use strict";

const ETIQUETAS_PERIODO = { "1D": "Día", "1S": "1S", "1M": "1M", "1A": "1A", YTD: "YTD", MAX: "Máx" };

const estado = { periodo: "1M", vista: "valor", grupo: "todos", instrumento: "todos", tema: "auto", ocultas: [] };
const TEMAS = { auto: ["◐", "Tema: automático"], claro: ["☀", "Tema: claro"], oscuro: ["☾", "Tema: oscuro"] };
let grafico = null;
let ultimosDatos = null;
let sello = null; // última actualización de precios que conoce el servidor
const hora = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const $ = (id) => document.getElementById(id);
// Importes en la divisa de la serie: la del instrumento si todos los elegidos comparten una, si no EUR.
// (Los nombres "euros" son históricos: ahora dependen de fijarDivisa.)
let euros, eurosFino;
function fijarDivisa(divisa) {
  euros = new Intl.NumberFormat("es-ES", { style: "currency", currency: divisa, maximumFractionDigits: 0 });
  eurosFino = new Intl.NumberFormat("es-ES", { style: "currency", currency: divisa, maximumFractionDigits: 2 });
}
fijarDivisa("EUR");
const pct = new Intl.NumberFormat("es-ES", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero" });
const fechaCorta = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });
const fechaLarga = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric" });

const fechaHora = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const soloHora = new Intl.DateTimeFormat("es-ES", { hour: "2-digit", minute: "2-digit" });
const esDia = () => ultimosDatos && ultimosDatos.periodo === "1D"; // la serie trae instantes (UTC), no días

const aFecha = (iso) => new Date(iso + "T00:00:00");
const css = (nombre) => getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
const signo = (n) => (n > 0 ? "sube" : n < 0 ? "baja" : "");
const conSigno = (n) => (n > 0 ? "+" : "") + eurosFino.format(n);

// Recordar la última selección (si el navegador no deja guardar, no pasa nada).
function guardar() {
  try { localStorage.setItem("finanzas", JSON.stringify(estado)); } catch (e) { /* sin almacenamiento */ }
}
function recuperar() {
  try { Object.assign(estado, JSON.parse(localStorage.getItem("finanzas") || "{}")); } catch (e) { /* ignorar */ }
}

async function pedir(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.text()).replace(/<[^>]+>/g, " ").trim() || r.statusText);
  return r.json();
}

function rellenarSelect(select, opciones, textoTodos, actual) {
  select.replaceChildren(new Option(textoTodos, "todos"));
  for (const o of opciones) select.add(new Option(o.nombre, String(o.id)));
  select.value = opciones.some((o) => String(o.id) === actual) ? actual : "todos";
}

// El selector de instrumentos solo ofrece los del grupo elegido (todos si no hay grupo).
let todosInstrumentos = [];
function rellenarInstrumentos() {
  const g = Number(estado.grupo);
  const lista = estado.grupo === "todos" ? todosInstrumentos : todosInstrumentos.filter((i) => i.grupos.includes(g));
  rellenarSelect($("instrumento"), lista, "Todos los instrumentos", estado.instrumento);
  estado.instrumento = $("instrumento").value;
}

// El periodo Día solo tiene datos de los tipos con ticks (ETFs, acciones y cripto): los fondos
// y los planes solo tienen un precio al día. Con una selección sin ninguno, Día se desactiva.
const TIPOS_CON_TICKS = ["ETF", "Accion", "Cripto"];
function haySeriesDia() {
  const g = Number(estado.grupo);
  return todosInstrumentos.some(
    (i) =>
      TIPOS_CON_TICKS.includes(i.tipo) &&
      (estado.grupo === "todos" || i.grupos.includes(g)) &&
      (estado.instrumento === "todos" || String(i.id) === estado.instrumento),
  );
}

// Activa o desactiva el botón Día según la selección; si estaba elegido, pasa a 1M.
function actualizarDia() {
  const b = $("periodos").querySelector('[data-periodo="1D"]');
  if (!b) return;
  const hay = haySeriesDia();
  b.disabled = !hay;
  b.title = hay ? "" : "Solo hay precios durante el día para ETFs, acciones y cripto";
  if (!hay && estado.periodo === "1D") {
    estado.periodo = "1M";
    for (const x of $("periodos").children) x.setAttribute("aria-pressed", String(x.dataset.periodo === "1M"));
    guardar();
  }
}

function dibujarPeriodos(periodos) {
  const nav = $("periodos");
  nav.replaceChildren();
  for (const p of periodos) {
    const b = document.createElement("button");
    b.textContent = ETIQUETAS_PERIODO[p] || p;
    b.dataset.periodo = p;
    b.setAttribute("aria-pressed", String(p === estado.periodo));
    nav.append(b);
  }
}

function aplicarTema() {
  if (!TEMAS[estado.tema]) estado.tema = "auto";
  const raiz = document.documentElement;
  if (estado.tema === "auto") raiz.removeAttribute("data-theme");
  else raiz.dataset.theme = estado.tema === "claro" ? "light" : "dark";
  const [icono, texto] = TEMAS[estado.tema];
  $("tema").textContent = icono;
  $("tema").setAttribute("aria-label", texto + " (toca para cambiar)");
  $("tema").title = texto;
}

function mostrarMensaje(texto) {
  $("mensaje").textContent = texto || "";
  $("mensaje").hidden = !texto;
}

function pintarTarjetas(r) {
  const res = r && r.resumen;
  $("t-valor").textContent = res ? euros.format(res.valor) : "–";
  // Con un instrumento elegido: su último precio y de qué día es (para compararlo con el banco).
  const pr = $("precio"), pc = r && r.precio;
  pr.hidden = !pc;
  if (pc) {
    const div = new Intl.NumberFormat("es-ES", { style: "currency", currency: pc.divisa, maximumFractionDigits: 4 });
    const cuando = esDia()
      ? fechaHora.format(new Date(pc.fecha))
      : aFecha(pc.fecha).toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
    pr.textContent = `Participación: ${div.format(pc.valor)} (${cuando})`;
  }
  $("t-invertido").textContent = res ? `Invertido ${euros.format(res.invertido)}` : "";
  const g = $("t-ganancia"), p = $("t-rentab");
  g.textContent = res ? conSigno(res.ganancia) : "–";
  p.textContent = res && res.rentabilidad !== null ? pct.format(res.rentabilidad) : "–";
  g.className = res ? signo(res.ganancia) : "";
  p.className = res && res.rentabilidad !== null ? signo(res.rentabilidad) : "";
  $("rango").textContent = !r || !r.desde ? ""
    : esDia() ? `${fechaHora.format(new Date(r.desde))} – ${fechaHora.format(new Date(r.hasta))}`
    : `${fechaLarga.format(aFecha(r.desde))} – ${fechaLarga.format(aFecha(r.hasta))}`;
}

// Configuración de Chart.js para los datos actuales (null si no hay nada que dibujar).
function configuracion() {
  const r = ultimosDatos;
  if (!r || !r.puntos.length) return null;

  const etiquetas = r.puntos.map((p) => p.fecha);
  // Las series que el usuario ocultó (tocando la leyenda) siguen ocultas al repintar.
  const oculta = (label) => estado.ocultas.includes(label);
  const eje = { color: css("--suave"), font: { size: 11 } };
  let datasets, formatoY, formatoTooltip;

  // Círculo relleno sobre la línea en cada día con compras (en las dos vistas).
  const compras = new Map((r.aportaciones || []).map((a) => [a.fecha, a]));
  const marcas = (campo, color) => compras.size ? [{
    label: "Compras",
    hidden: oculta("Compras"),
    data: r.puntos.map((p) => (compras.has(p.fecha) ? p[campo] : null)),
    showLine: false,
    borderColor: css("--superficie"),
    backgroundColor: color,
    borderWidth: 1.5,
    pointStyle: "circle",
    pointRadius: 5,
    pointHoverRadius: 7,
  }] : [];
  const tooltipCompra = (c) => {
    const a = compras.get(r.puntos[c.dataIndex].fecha);
    return `Compra: ${eurosFino.format(a.importe)} (${a.instrumentos.join(", ")})`;
  };

  if (estado.vista === "valor") {
    datasets = [
      { label: "Valor", hidden: oculta("Valor"), data: r.puntos.map((p) => p.valor), borderColor: css("--acento"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15 },
      { label: "Invertido", hidden: oculta("Invertido"), data: r.puntos.map((p) => p.invertido), borderColor: css("--suave"), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0, stepped: true },
      ...marcas("valor", css("--acento")),
    ];
    formatoY = (v) => euros.format(v);
    formatoTooltip = (c) =>
      c.dataset.label === "Compras" ? tooltipCompra(c) : `${c.dataset.label}:${eurosFino.format(c.parsed.y)}`;
  } else {
    const sube = (r.resumen.rentabilidad || 0) >= 0;
    const color = css(sube ? "--sube" : "--baja");
    datasets = [
      { label: "Rentabilidad", hidden: oculta("Rentabilidad"), data: r.puntos.map((p) => (p.rentabilidad === null ? null : p.rentabilidad)), borderColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15, spanGaps: true },
      ...marcas("rentabilidad", color),
    ];
    formatoY = (v) => pct.format(v);
    formatoTooltip = (c) =>
      c.dataset.label === "Compras" ? tooltipCompra(c) : `Rentabilidad: ${pct.format(c.parsed.y)}`;
  }

  return {
    type: "line",
    data: { labels: etiquetas, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: css("--suave"), boxWidth: 14, usePointStyle: true },
          // Como el comportamiento normal (ocultar/mostrar la serie), pero recordando el estado.
          onClick: (e, item, legend) => {
            const ch = legend.chart, visible = ch.isDatasetVisible(item.datasetIndex);
            ch.setDatasetVisibility(item.datasetIndex, !visible);
            const resto = estado.ocultas.filter((l) => l !== item.text);
            estado.ocultas = visible ? [...resto, item.text] : resto;
            guardar();
            ch.update();
          },
        },
        tooltip: {
          callbacks: {
            title: (items) => (esDia() ? fechaHora.format(new Date(items[0].label)) : fechaLarga.format(aFecha(items[0].label))),
            label: formatoTooltip,
            afterBody: (items) => {
              const p = r.puntos[items[0].dataIndex];
              return estado.vista === "valor" ? [`Ganancia: ${conSigno(p.ganancia)}`] : [`Ganancia: ${conSigno(p.ganancia)}`, `Valor: ${eurosFino.format(p.valor)}`];
            },
          },
        },
      },
      scales: {
        x: { ticks: { ...eje, maxTicksLimit: 5, maxRotation: 0, callback: function (v) { const l = this.getLabelForValue(v); return esDia() ? soloHora.format(new Date(l)) : fechaCorta.format(aFecha(l)); } }, grid: { display: false } },
        y: { ticks: { ...eje, maxTicksLimit: 6, callback: formatoY }, grid: { color: css("--rejilla") } },
      },
    },
  };
}

function pintarGrafico() {
  if (grafico) { grafico.destroy(); grafico = null; }
  const c = configuracion();
  if (c) grafico = new Chart($("grafico"), c);
}

// Repinta con datos nuevos sin destruir el gráfico: no hay parpadeo ni animación.
function actualizarGrafico() {
  const c = configuracion();
  if (!c || !grafico) return pintarGrafico();
  grafico.data = c.data;
  grafico.options = c.options;
  grafico.update("none");
}

// Aviso sutil: la hora de la última actualización de precios.
function pintarAviso() {
  const a = $("aviso");
  a.hidden = !sello;
  if (sello) a.textContent = `Precios de las ${hora.format(new Date(sello))}`;
}

// Si el servidor avisa de precios nuevos, se vuelven a pedir los datos y se repinta en silencio.
async function consultarEstado() {
  const anterior = sello;
  try {
    sello = (await pedir("/api/estado")).actualizado;
  } catch (e) { return; /* sin aviso si no responde */ }
  pintarAviso();
  if (anterior && sello !== anterior) cargar(true);
}

let peticion = 0; // para ignorar respuestas que llegan tarde (se cambió de filtro mientras tanto)
async function cargar(enSilencio = false) {
  const esta = ++peticion;
  const q = new URLSearchParams({ periodo: estado.periodo, grupo: estado.grupo, instrumento: estado.instrumento });
  let datos = null, error = null;
  try {
    datos = await pedir("/api/evolucion?" + q);
  } catch (e) {
    error = e;
  }
  if (esta !== peticion) return;
  if (error && enSilencio) return; // en silencio, un fallo no borra lo que ya se ve
  if (enSilencio && JSON.stringify(datos) === JSON.stringify(ultimosDatos)) return; // nada nuevo: no se redibuja
  ultimosDatos = datos;
  fijarDivisa((datos && datos.divisa) || "EUR");
  mostrarMensaje(error ? "No se pudo cargar: " + error.message : datos.puntos.length ? "" : datos.periodo === "1D" ? "Sin precios de hoy (solo ETFs, acciones y cripto tienen precio durante el día)" : "Sin datos en este periodo");
  pintarTarjetas(ultimosDatos);
  if (enSilencio) actualizarGrafico(); else pintarGrafico();
}

// Tras añadir o borrar operaciones: vuelve a pedir las opciones (puede haber instrumentos nuevos)
// y redibuja la gráfica con los datos nuevos.
async function refrescarGrafico() {
  try {
    const o = await pedir("/api/opciones");
    todosInstrumentos = o.instrumentos;
    rellenarSelect($("grupo"), o.grupos, "Todos los grupos", estado.grupo);
    estado.grupo = $("grupo").value;
    rellenarInstrumentos();
    actualizarDia();
  } catch (e) { /* si falla, se redibuja con las opciones que ya había */ }
  await cargar();
}

function marcarVista() {
  for (const b of document.querySelectorAll(".vista button")) b.setAttribute("aria-selected", String(b.dataset.vista === estado.vista));
}

async function iniciar() {
  recuperar();
  aplicarTema();
  $("tema").addEventListener("click", () => {
    const orden = Object.keys(TEMAS);
    estado.tema = orden[(orden.indexOf(estado.tema) + 1) % orden.length];
    aplicarTema();
    guardar();
    pintarGrafico();
  });
  try {
    const o = await pedir("/api/opciones");
    if (!o.periodos.includes(estado.periodo)) estado.periodo = "1M";
    rellenarSelect($("grupo"), o.grupos, "Todos los grupos", estado.grupo);
    todosInstrumentos = o.instrumentos;
    estado.grupo = $("grupo").value;
    rellenarInstrumentos();
    dibujarPeriodos(o.periodos);
    actualizarDia();
  } catch (e) {
    mostrarMensaje("No se pudo cargar: " + e.message);
    return;
  }
  marcarVista();

  $("grupo").addEventListener("change", (e) => {
    estado.grupo = e.target.value;
    rellenarInstrumentos();
    actualizarDia();
    guardar();
    cargar();
  });
  $("instrumento").addEventListener("change", (e) => { estado.instrumento = e.target.value; actualizarDia(); guardar(); cargar(); });
  $("periodos").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    estado.periodo = b.dataset.periodo;
    for (const x of $("periodos").children) x.setAttribute("aria-pressed", String(x === b));
    guardar();
    cargar();
  });
  document.querySelector(".vista").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    estado.vista = b.dataset.vista;
    marcarVista();
    guardar();
    pintarGrafico();
  });
  // Cambiar entre tema claro y oscuro: repintar con los colores nuevos.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", pintarGrafico);

  await consultarEstado();
  cargar();
  setInterval(consultarEstado, 10000);
}

iniciar();
