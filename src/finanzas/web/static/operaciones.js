"use strict";
// Maqueta de la pestaña Operaciones: navegación Grupos > Instrumentos > Operaciones.
// Datos de ejemplo en memoria; nada se guarda ni se lee del servidor. El 5º valor de cada compra
// es un id de ejemplo para el botón de evolución (pide /api/aportacion/<id>: usa ids reales).
(() => {
  const $ = (id) => document.getElementById(id);

  const DATOS = [
    { nombre: "Cartera principal", instrumentos: [
      { nombre: "Fidelity MSCI World Index", ops: [
        ["compra", "14 oct 2026", "8,12", "153,94 €", 1], ["compra", "14 sep 2026", "8,30", "150,60 €", 2], ["venta", "02 ago 2026", "2,00", "149,10 €"]] },
      { nombre: "iShares Developed World Index", ops: [["compra", "01 sep 2026", "3,47", "30,26 €", 3]] },
      { nombre: "DNB Fund - Technology A", ops: [["compra", "02 oct 2026", "1,05", "285,71 €", 4]] },
      { nombre: "Amundi Core MSCI Emerging Markets", ops: [["compra", "10 jul 2026", "4,80", "208,33 €", 5], ["venta", "21 sep 2026", "2,40", "210,00 €"]] },
    ] },
    { nombre: "Inversiones Laura", instrumentos: [
      { nombre: "Fidelity MSCI World Index", ops: [["compra", "05 sep 2026", "1,31", "152,67 €", 6]] },
    ] },
  ];

  const nav = { g: null, i: null }; // índices del grupo e instrumento abiertos (null = ese nivel no está abierto)
  const grupo = () => DATOS[nav.g];
  const instrumento = () => DATOS[nav.g].instrumentos[nav.i];
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

  function boton(texto, extra = {}, clase = "") {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = texto;
    if (clase) b.className = clase;
    Object.assign(b.dataset, extra);
    return b;
  }

  // Fila navegable (grupo o instrumento): título, subtítulo y flecha
  function fila(titulo, detalle, alPulsar) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tarjeta-nav";
    const t = document.createElement("strong");
    t.textContent = titulo;
    const d = document.createElement("span");
    d.className = "op-detalle";
    d.textContent = detalle;
    const flecha = document.createElement("span");
    flecha.className = "flecha";
    flecha.textContent = "›";
    const cuerpo = document.createElement("span");
    cuerpo.className = "op-cuerpo";
    cuerpo.append(t, d);
    b.append(cuerpo, flecha);
    b.addEventListener("click", alPulsar);
    li.append(b);
    return li;
  }

  function filaOperacion([tipo, fecha, part, precio, id]) {
    const li = document.createElement("li");
    li.className = "op";
    li.innerHTML =
      '<label class="check"><input type="checkbox" aria-label="Seleccionar"></label>' +
      '<div class="op-cuerpo"><div class="op-linea"><strong></strong><span class="op-importe"></span></div>' +
      '<div class="op-detalle"></div></div>';
    li.querySelector("strong").textContent = `${tipo === "compra" ? "Compra" : "Venta"} · ${fecha}`;
    li.querySelector(".op-importe").textContent = precio;
    li.querySelector(".op-detalle").textContent = `${part} participaciones`;
    if (tipo === "compra" && id) {
      const g = boton("", { aportacion: id }, "icono");
      g.setAttribute("aria-label", "Ver evolución de esta aportación");
      g.title = "Ver evolución";
      g.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>';
      li.append(g);
    }
    li.dataset.resumen = `${tipo === "compra" ? "Compra" : "Venta"} ${fecha} · ${part} part. a ${precio}`;
    return li;
  }

  function migas() {
    const m = $("migas");
    m.replaceChildren();
    const trozos = [["Grupos", () => { nav.g = nav.i = null; pintar(); }]];
    if (nav.g !== null) trozos.push([grupo().nombre, () => { nav.i = null; pintar(); }]);
    if (nav.i !== null) trozos.push([instrumento().nombre, null]);
    trozos[trozos.length - 1][1] = null; // el último es donde estás: título, no enlace
    trozos.forEach(([texto, alPulsar], k) => {
      if (k) m.append(Object.assign(document.createElement("span"), { textContent: "›", className: "sep" }));
      const e = alPulsar ? boton(texto) : Object.assign(document.createElement("span"), { textContent: texto, className: "actual" });
      if (alPulsar) e.addEventListener("click", alPulsar);
      m.append(e);
    });
  }

  function pintar() {
    migas();
    const acciones = $("acciones-ops");
    const lista = $("lista-ops");
    acciones.replaceChildren();
    lista.replaceChildren();
    $("barra-seleccion").hidden = true;

    if (nav.g === null) {
      DATOS.forEach((g, k) => lista.append(fila(g.nombre, plural(g.instrumentos.length, "instrumento", "instrumentos"), () => { nav.g = k; pintar(); })));
    } else if (nav.i === null) {
      acciones.append(boton("+ Instrumento", { abrir: "d-instrumento" }, "primario"), boton("Importar CSV", { abrir: "d-csv" }));
      grupo().instrumentos.forEach((x, k) => lista.append(fila(x.nombre, plural(x.ops.length, "operación", "operaciones"), () => { nav.i = k; pintar(); })));
    } else {
      acciones.append(boton("+ Añadir", { abrir: "d-anadir" }, "primario"), boton("Mover a otro grupo", { abrir: "d-mover" }));
      instrumento().ops.forEach((o) => lista.append(filaOperacion(o)));
    }
  }

  // Rellena el texto de contexto de cada diálogo según donde estés
  function preparar(id) {
    if (id === "d-anadir") {
      $("ctx-anadir").textContent = `${instrumento().nombre} · ${grupo().nombre}`;
      $("nota-venta").textContent = "Tienes 8,12 participaciones en este grupo.";
    } else if (id === "d-instrumento") {
      $("ctx-instrumento").textContent = `Grupo: ${grupo().nombre}`;
    } else if (id === "d-csv") {
      $("ctx-csv").textContent = `Grupo: ${grupo().nombre}`;
      $("resumen-csv").innerHTML = "Se añadirán <strong>14 compras</strong> al grupo <strong></strong>.";
      $("resumen-csv").lastElementChild.textContent = grupo().nombre;
      paso = 1; mostrarPaso();
    } else if (id === "d-mover") {
      $("ctx-mover").textContent = `${instrumento().nombre} · ahora en ${grupo().nombre}`;
      const otros = DATOS.filter((_, k) => k !== nav.g);
      $("destino-mover").replaceChildren(...otros.map((g) => new Option(g.nombre)));
      $("nota-mover").textContent = `Se moverán sus ${instrumento().ops.length} operaciones. Si el grupo destino ya tiene este instrumento, se sumarán a las suyas.`;
    } else if (id === "d-borrar") {
      const filas = [...document.querySelectorAll("#lista-ops input:checked")].map((c) => c.closest(".op").dataset.resumen);
      $("lista-borrar").replaceChildren(...filas.map((t) => Object.assign(document.createElement("li"), { textContent: t })));
    }
  }

  // Pestañas de sección
  for (const b of document.querySelectorAll(".pestanas button")) {
    b.addEventListener("click", () => {
      const op = b.dataset.seccion === "operaciones";
      for (const t of document.querySelectorAll(".pestanas button")) t.setAttribute("aria-selected", String(t === b));
      $("s-evolucion").hidden = op;
      $("periodos").hidden = op;
      $("s-operaciones").hidden = !op;
      window.dispatchEvent(new Event("resize")); // el gráfico se reajusta al volver
    });
  }

  // Abrir diálogos (los botones de acciones se crean dinámicamente: delegación)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-abrir]");
    if (!b) return;
    preparar(b.dataset.abrir);
    $(b.dataset.abrir).showModal();
  });

  // Selección múltiple de operaciones
  $("lista-ops").addEventListener("change", () => {
    const n = document.querySelectorAll("#lista-ops input:checked").length;
    $("barra-seleccion").hidden = n === 0;
    $("n-seleccion").textContent = plural(n, "seleccionada", "seleccionadas");
  });

  // Compra/venta: la nota de participaciones solo en ventas
  for (const r of document.querySelectorAll("[name=tipo-op]")) {
    r.addEventListener("change", () => { $("nota-venta").hidden = r.parentElement.textContent.trim() !== "Venta"; });
  }

  // Asistente CSV de tres pasos
  let paso = 1;
  function mostrarPaso() {
    for (const s of document.querySelectorAll("#asistente [data-paso]")) s.hidden = Number(s.dataset.paso) !== paso;
    document.querySelectorAll(".pasos li").forEach((li, i) => li.classList.toggle("activo", i + 1 === paso));
    $("csv-atras").hidden = paso === 1;
    $("csv-sig").textContent = paso === 3 ? "Importar" : "Siguiente";
  }
  $("csv-sig").addEventListener("click", () => { if (paso < 3) { paso++; mostrarPaso(); } else $("d-csv").close(); });
  $("csv-atras").addEventListener("click", () => { paso--; mostrarPaso(); });

  pintar();
})();
