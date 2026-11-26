"use strict";
// Pestaña Operaciones: navegación Grupos > Instrumentos > Operaciones con los datos reales
// (GET /api/operaciones). Añadir y borrar operaciones guardan de verdad (POST/DELETE);
// crear instrumento, mover e importar siguen siendo maqueta: abren su diálogo pero no guardan nada.
(() => {
  const $ = (id) => document.getElementById(id);

  let DATOS = []; // grupos > instrumentos > ops, ya con los textos listos para pintar
  const fechaOp = new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "short", year: "numeric" });
  const numero = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 6 });
  const dinero = (n, divisa) => {
    try {
      return new Intl.NumberFormat("es-ES", { style: "currency", currency: divisa, maximumFractionDigits: 2 }).format(n);
    } catch (e) {
      return `${numero.format(n)} ${divisa}`;
    }
  };

  // De la respuesta del servidor a lo que pinta la lista: [tipo, fecha, participaciones, importe, id, detalle]
  function preparaDatos(r) {
    return r.grupos.map((g) => ({
      id: g.id,
      nombre: g.nombre,
      instrumentos: g.instrumentos.map((x) => ({
        id: x.id,
        nombre: x.nombre,
        ops: x.operaciones.map((o) => [
          o.tipo,
          fechaOp.format(new Date(o.fecha + "T00:00:00")).replace(/\./g, ""),
          numero.format(o.participaciones),
          dinero(o.importe, x.divisa),
          o.id,
          `${numero.format(o.participaciones)} part. a ${dinero(o.precio, x.divisa)}` +
            (o.comision ? ` · comisión ${dinero(o.comision, x.divisa)}` : ""),
        ]),
      })),
    }));
  }

  async function enviar(url, opciones) {
    const r = await fetch(url, opciones);
    if (!r.ok) throw new Error((await r.text()).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() || r.statusText);
  }
  async function recargar() {
    DATOS = preparaDatos(await pedir("/api/operaciones"));
    if (nav.g !== null && !DATOS[nav.g]) nav.g = nav.i = null;
    else if (nav.i !== null && !DATOS[nav.g].instrumentos[nav.i]) nav.i = null;
    pintar();
    if (typeof refrescarGrafico === "function") await refrescarGrafico();
  }
  function error(id, texto) {
    $(id).textContent = texto || "";
    $(id).hidden = !texto;
  }

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

  function filaOperacion([tipo, fecha, part, importe, id, detalle]) {
    const li = document.createElement("li");
    li.className = "op";
    li.dataset.tipo = tipo;
    li.dataset.id = id;
    li.innerHTML =
      '<label class="check"><input type="checkbox" aria-label="Seleccionar"></label>' +
      '<div class="op-cuerpo"><div class="op-linea"><strong></strong><span class="op-importe"></span></div>' +
      '<div class="op-detalle"></div></div>';
    li.querySelector("strong").textContent = `${tipo === "compra" ? "Compra" : "Venta"} · ${fecha}`;
    li.querySelector(".op-importe").textContent = importe;
    li.querySelector(".op-detalle").textContent = detalle;
    if (tipo === "compra" && id) {
      const g = boton("", { aportacion: id }, "icono");
      g.setAttribute("aria-label", "Ver evolución de esta aportación");
      g.title = "Ver evolución";
      g.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>';
      li.append(g);
    }
    li.dataset.resumen = `${tipo === "compra" ? "Compra" : "Venta"} ${fecha} · ${importe}`;
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

  function vacio(texto) {
    return Object.assign(document.createElement("li"), { className: "nota", textContent: texto });
  }

  function pintar() {
    migas();
    const acciones = $("acciones-ops");
    const lista = $("lista-ops");
    acciones.replaceChildren();
    lista.replaceChildren();
    $("barra-seleccion").hidden = true;

    if (nav.g === null) {
      if (!DATOS.length) lista.append(vacio("Todavía no hay grupos."));
      DATOS.forEach((g, k) => lista.append(fila(g.nombre, plural(g.instrumentos.length, "instrumento", "instrumentos"), () => { nav.g = k; pintar(); })));
    } else if (nav.i === null) {
      acciones.append(boton("+ Instrumento", { abrir: "d-instrumento" }, "primario"), boton("Importar CSV", { abrir: "d-csv" }));
      if (!grupo().instrumentos.length) lista.append(vacio("Este grupo no tiene operaciones."));
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
      error("error-anadir", "");
      $("op-fecha").value = new Date().toISOString().slice(0, 10);
      for (const c of ["op-part", "op-precio"]) $(c).value = "";
      $("op-comision").value = "0";
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
      error("error-borrar", "");
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

  // Guardar una operación nueva. Si el servidor la rechaza, el diálogo sigue abierto con el motivo.
  $("guardar-op").addEventListener("click", async (e) => {
    e.preventDefault();
    if (!$("d-anadir").querySelector("form").reportValidity()) return;
    const cuerpo = {
      tipo: document.querySelector("[name=tipo-op]:checked").value,
      instrumento: instrumento().id,
      grupo: grupo().id,
      fecha: $("op-fecha").value,
      participaciones: $("op-part").value,
      precio: $("op-precio").value,
      comision: $("op-comision").value || "0",
    };
    try {
      await enviar("/api/operaciones", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo),
      });
      $("d-anadir").close();
      await recargar();
    } catch (err) {
      error("error-anadir", err.message);
    }
  });

  // Borrar las operaciones marcadas, una a una; las que fallen se quedan y se avisa del motivo
  $("confirmar-borrar").addEventListener("click", async (e) => {
    e.preventDefault();
    const marcadas = [...document.querySelectorAll("#lista-ops input:checked")].map((c) => c.closest(".op"));
    const fallos = [];
    for (const li of marcadas) {
      try {
        await enviar(`/api/operaciones/${li.dataset.tipo}/${li.dataset.id}`, { method: "DELETE" });
      } catch (err) {
        fallos.push(`${li.dataset.resumen}: ${err.message}`);
      }
    }
    await recargar();
    if (fallos.length) error("error-borrar", fallos.join(" · "));
    else $("d-borrar").close();
  });

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

  // Carga inicial: si el servidor no responde se avisa en la propia lista
  (async () => {
    try {
      DATOS = preparaDatos(await pedir("/api/operaciones"));
      pintar();
    } catch (e) {
      $("lista-ops").replaceChildren(vacio("No se pudo cargar: " + e.message));
    }
  })();
})();
