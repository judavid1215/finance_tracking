"use strict";
// Diálogo con la evolución de una aportación (una compra): pide /api/aportacion/<id> y la dibuja.
// Todo en la divisa del instrumento; las ventas no cuentan.
(() => {
  const $ = (id) => document.getElementById(id);
  let grafico = null;
  let datos = null;
  let vista = "valor";
  let peticion = 0; // ignora respuestas que llegan tarde (se abrió otra aportación mientras tanto)

  function formato(divisa, decimales) {
    try {
      return new Intl.NumberFormat("es-ES", { style: "currency", currency: divisa, maximumFractionDigits: decimales });
    } catch (e) {
      return new Intl.NumberFormat("es-ES", { maximumFractionDigits: decimales }); // divisa que Intl no conoce
    }
  }

  function pintarResumen(r, dinero) {
    const sube = r.resumen.ganancia >= 0;
    $("ap-resumen").replaceChildren(
      ...[
        ["Aportado", dinero.format(r.aportado), ""],
        ["Valor hoy", dinero.format(r.resumen.valor), ""],
        ["Ganancia", (r.resumen.ganancia > 0 ? "+" : "") + dinero.format(r.resumen.ganancia), sube ? "sube" : "baja"],
        ["Rentabilidad", pct.format(r.resumen.rentabilidad), sube ? "sube" : "baja"],
      ].map(([titulo, valor, clase]) => {
        const d = document.createElement("div");
        const t = Object.assign(document.createElement("span"), { textContent: titulo });
        const v = Object.assign(document.createElement("strong"), { textContent: valor, className: clase });
        d.append(t, v);
        return d;
      })
    );
  }

  function pintarGrafico() {
    if (grafico) { grafico.destroy(); grafico = null; }
    if (!datos) return;
    const r = datos;
    const dinero = formato(r.divisa, 2);
    const eje = { color: css("--suave"), font: { size: 11 } };
    const etiquetas = r.puntos.map((p) => p.fecha);
    let datasets, formatoY, formatoTooltip;
    if (vista === "valor") {
      datasets = [
        { label: "Valor", data: r.puntos.map((p) => p.valor), borderColor: css("--acento"), borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15 },
        { label: "Aportado", data: r.puntos.map(() => r.aportado), borderColor: css("--suave"), borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0, pointHoverRadius: 0 },
      ];
      const entero = formato(r.divisa, 0);
      formatoY = (v) => entero.format(v);
      formatoTooltip = (c) => `${c.dataset.label}: ${dinero.format(c.parsed.y)}`;
    } else {
      const color = css(r.resumen.rentabilidad >= 0 ? "--sube" : "--baja");
      datasets = [{ label: "Rentabilidad", data: r.puntos.map((p) => p.rentabilidad), borderColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.15 }];
      formatoY = (v) => pct.format(v);
      formatoTooltip = (c) => `Rentabilidad: ${pct.format(c.parsed.y)}`;
    }
    grafico = new Chart($("ap-grafico"), {
      type: "line",
      data: { labels: etiquetas, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: vista === "valor", labels: { color: css("--suave"), boxWidth: 14, usePointStyle: true } },
          tooltip: {
            callbacks: {
              title: (items) => fechaLarga.format(aFecha(items[0].label)),
              label: formatoTooltip,
              afterBody: (items) => {
                const p = r.puntos[items[0].dataIndex];
                return [`Ganancia: ${(p.ganancia > 0 ? "+" : "") + dinero.format(p.ganancia)}`];
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

  function marcarVista() {
    for (const b of document.querySelectorAll("#ap-vista button")) b.setAttribute("aria-selected", String(b.dataset.vista === vista));
  }

  async function abrir(id) {
    const esta = ++peticion;
    datos = null;
    $("ap-titulo").textContent = "Evolución de la aportación";
    $("ap-contexto").textContent = "";
    $("ap-resumen").replaceChildren();
    $("ap-mensaje").textContent = "Cargando…";
    $("ap-mensaje").hidden = false;
    pintarGrafico();
    $("d-aportacion").showModal();
    let r;
    try {
      r = await pedir("/api/aportacion/" + id);
    } catch (e) {
      if (esta === peticion) $("ap-mensaje").textContent = "No se pudo cargar: " + e.message;
      return;
    }
    if (esta !== peticion) return;
    datos = r;
    const dinero = formato(r.divisa, 2);
    $("ap-titulo").textContent = r.instrumento;
    $("ap-contexto").textContent =
      `${r.grupo} · compra del ${fechaLarga.format(aFecha(r.fecha))} · ${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 6 }).format(r.participaciones)} part. a ${dinero.format(r.precio)}` +
      (r.comision ? ` (+${dinero.format(r.comision)} de comisión)` : "");
    $("ap-mensaje").hidden = true;
    pintarResumen(r, dinero);
    marcarVista();
    pintarGrafico();
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-aportacion]");
    if (b) abrir(b.dataset.aportacion);
  });
  $("ap-vista").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    vista = b.dataset.vista;
    marcarVista();
    pintarGrafico();
  });
  $("d-aportacion").addEventListener("close", () => { if (grafico) { grafico.destroy(); grafico = null; } });
})();
