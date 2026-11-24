"use strict";

const ETIQUETAS_PERIODO = { "1S": "1S", "1M": "1M", "1A": "1A", YTD: "YTD", MAX: "Máx" };

const estado = { periodo: "1M", vista: "valor", grupo: "todos", instrumento: "todos", tema: "auto" };
const TEMAS = { auto: ["◐", "Tema: automático"], claro: ["☀", "Tema: claro"], oscuro: ["☾", "Tema: oscuro"] };
let grafico = null;
let ultimosDatos = null;

const $ = (id) => document.getElementById(id);
const euros = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eurosFino = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 2 });
const pct = new Intl.NumberFormat("es-ES", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero" });
const fechaCorta = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });
const fechaLarga = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", year: "numeric" });

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
  const g = $("t-ganancia"), p = $("t-rentab");
  g.textContent = res ? conSigno(res.ganancia) : "–";
  p.textContent = res && res.rentabilidad !== null ? pct.format(res.rentabilidad) : "–";
  g.className = res ? signo(res.ganancia) : "";
  p.className = res && res.rentabilidad !== null ? signo(res.rentabilidad) : "";
  $("rango").textContent = r && r.desde ? `${fechaLarga.format(aFecha(r.desde))} – ${fechaLarga.format(aFecha(r.hasta))}` : "";
}

function pintarGrafico() {
  const r = ultimosDatos;
  if (grafico) { grafico.destroy(); grafico = null; }
  if (!r || !r.puntos.length) return;

  const etiquetas = r.puntos.map((p) => p.fecha);
  const eje = { color: css("--suave"), font: { size: 11 } };
  let datasets, formatoY, formatoTooltip;

  // Círculo relleno sobre la línea en cada día con compras (en las dos vistas).
  const compras = new Map((r.aportaciones || []).map((a) => [a.fecha, a]));
  const marcas = (campo, color) => compras.size ? [{
    label: "Compras",
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
      { label: "Valor", data: r.puntos.map((p) => p.valor), borderColor: css("--acento"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15 },
      { label: "Invertido", data: r.puntos.map((p) => p.invertido), borderColor: css("--suave"), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0, stepped: true },
      ...marcas("valor", css("--acento")),
    ];
    formatoY = (v) => euros.format(v);
    formatoTooltip = (c) =>
      c.dataset.label === "Compras" ? tooltipCompra(c) : `${c.dataset.label}: ${eurosFino.format(c.parsed.y)}`;
  } else {
    const sube = (r.resumen.rentabilidad || 0) >= 0;
    const color = css(sube ? "--sube" : "--baja");
    datasets = [
      { label: "Rentabilidad", data: r.puntos.map((p) => (p.rentabilidad === null ? null : p.rentabilidad)), borderColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15, spanGaps: true },
      ...marcas("rentabilidad", color),
    ];
    formatoY = (v) => pct.format(v);
    formatoTooltip = (c) =>
      c.dataset.label === "Compras" ? tooltipCompra(c) : `Rentabilidad: ${pct.format(c.parsed.y)}`;
  }

  grafico = new Chart($("grafico"), {
    type: "line",
    data: { labels: etiquetas, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, labels: { color: css("--suave"), boxWidth: 14, usePointStyle: true } },
        tooltip: {
          callbacks: {
            title: (items) => fechaLarga.format(aFecha(items[0].label)),
            label: formatoTooltip,
            afterBody: (items) => {
              const p = r.puntos[items[0].dataIndex];
              return estado.vista === "valor" ? [`Ganancia: ${conSigno(p.ganancia)}`] : [`Ganancia: ${conSigno(p.ganancia)}`, `Valor: ${eurosFino.format(p.valor)}`];
            },
          },
        },
      },
      scales: {
        x: { ticks: { ...eje, maxTicksLimit: 5, maxRotation: 0, callback: function (v) { return fechaCorta.format(aFecha(this.getLabelForValue(v))); } }, grid: { display: false } },
        y: { ticks: { ...eje, maxTicksLimit: 6, callback: formatoY }, grid: { color: css("--rejilla") } },
      },
    },
  });
}

async function cargar() {
  const q = new URLSearchParams({ periodo: estado.periodo, grupo: estado.grupo, instrumento: estado.instrumento });
  try {
    ultimosDatos = await pedir("/api/evolucion?" + q);
    mostrarMensaje(ultimosDatos.puntos.length ? "" : "Sin datos en este periodo");
  } catch (e) {
    ultimosDatos = null;
    mostrarMensaje("No se pudo cargar: " + e.message);
  }
  pintarTarjetas(ultimosDatos);
  pintarGrafico();
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
  } catch (e) {
    mostrarMensaje("No se pudo cargar: " + e.message);
    return;
  }
  marcarVista();

  $("grupo").addEventListener("change", (e) => {
    estado.grupo = e.target.value;
    rellenarInstrumentos();
    guardar();
    cargar();
  });
  $("instrumento").addEventListener("change", (e) => { estado.instrumento = e.target.value; guardar(); cargar(); });
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

  cargar();
}

iniciar();
