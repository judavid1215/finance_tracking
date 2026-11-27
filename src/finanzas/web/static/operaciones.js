"use strict";
// Pestaña Operaciones: navegación Grupos > Tipo de instrumento > Instrumentos > Operaciones con los datos reales
// (GET /api/operaciones). Añadir, editar y borrar operaciones guardan de verdad (POST/PUT/DELETE);
// importar CSV y mover un instrumento de grupo también guardan; crear instrumento sigue siendo maqueta: abre su diálogo pero no guarda nada.
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

  // Tipos de instrumento, en el orden en que se muestran (clave de la base de datos → nombre)
  const TIPOS = [
    ["Fondo", "Fondos"],
    ["ETF", "ETFs"],
    ["Accion", "Acciones"],
    ["Cripto", "Cripto"],
    ["Plan_pensiones", "Planes de pensiones"],
  ];
  const nombreTipo = (clave) => (TIPOS.find(([c]) => c === clave) || [clave, clave])[1];

  // De la respuesta del servidor a lo que pinta la lista: [tipo, fecha, participaciones, importe, id, detalle]
  function preparaDatos(r) {
    return r.grupos.map((g) => ({
      id: g.id,
      nombre: g.nombre,
      instrumentos: g.instrumentos.map((x) => ({
        id: x.id,
        nombre: x.nombre,
        divisa: x.divisa,
        tipo: x.tipo,
        ops: x.operaciones.map((o) => [
          o.tipo,
          fechaOp.format(new Date(o.fecha + "T00:00:00")).replace(/\./g, ""),
          numero.format(o.participaciones),
          dinero(o.importe, x.divisa),
          o.id,
          `${numero.format(o.participaciones)} part. a ${dinero(o.precio, x.divisa)}` +
            (o.comision ? ` · comisión ${dinero(o.comision, x.divisa)}` : ""),
          o, // datos tal cual, para rellenar el diálogo de editar
        ]),
      })),
    }));
  }

  async function enviar(url, opciones) {
    const r = await fetch(url, opciones);
    if (!r.ok) {
      // el servidor responde con una página HTML de error: se enseña solo el mensaje
      const html = new DOMParser().parseFromString(await r.text(), "text/html");
      throw new Error(html.querySelector("p")?.textContent.trim() || r.statusText);
    }
  }
  async function recargar() {
    DATOS = preparaDatos(await pedir("/api/operaciones"));
    if (nav.g !== null && !DATOS[nav.g]) nav.g = nav.t = nav.i = null;
    else if (nav.i !== null && !DATOS[nav.g].instrumentos[nav.i]) nav.i = null;
    if (nav.t !== null && nav.i === null && !tiposDelGrupo().some(([c]) => c === nav.t)) nav.t = null;
    pintar();
    if (typeof refrescarGrafico === "function") await refrescarGrafico();
  }
  function error(id, texto) {
    $(id).textContent = texto || "";
    $(id).hidden = !texto;
  }

  // Grupo (índice), tipo de instrumento (clave) e instrumento (índice en el grupo) abiertos;
  // null = ese nivel no está abierto
  const nav = { g: null, t: null, i: null };
  const grupo = () => DATOS[nav.g];
  const instrumento = () => DATOS[nav.g].instrumentos[nav.i];
  // Tipos que tiene el grupo abierto, [clave, nombre, nº de instrumentos], en el orden de TIPOS
  const tiposDelGrupo = () => {
    const claves = new Set(grupo().instrumentos.map((x) => x.tipo));
    const conocidos = TIPOS.map(([c]) => c);
    return [...conocidos, ...[...claves].filter((c) => !conocidos.includes(c))]
      .filter((c) => claves.has(c))
      .map((c) => [c, nombreTipo(c), grupo().instrumentos.filter((x) => x.tipo === c).length]);
  };
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

  function filaOperacion([tipo, fecha, part, importe, id, detalle, datos]) {
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
    const e = boton("", { editar: `${tipo}:${id}` }, "icono");
    e.setAttribute("aria-label", "Editar esta operación");
    e.title = "Editar";
    e.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
    li.append(e);
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
    const trozos = [["Grupos", () => { nav.g = nav.t = nav.i = null; pintar(); }]];
    if (nav.g !== null) trozos.push([grupo().nombre, () => { nav.t = nav.i = null; pintar(); }]);
    if (nav.t !== null) trozos.push([nombreTipo(nav.t), () => { nav.i = null; pintar(); }]);
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
      acciones.append(boton("+ Grupo", { abrir: "d-grupo" }, "primario"));
      if (!DATOS.length) lista.append(vacio("Todavía no hay grupos."));
      DATOS.forEach((g, k) => lista.append(fila(g.nombre, plural(g.instrumentos.length, "instrumento", "instrumentos"), () => { nav.g = k; pintar(); })));
    } else if (nav.t === null) {
      acciones.append(boton("+ Instrumento", { abrir: "d-instrumento" }, "primario"), boton("Importar CSV", { abrir: "d-csv" }), boton("Borrar grupo", { borrarGrupo: "1" }, "peligro"));
      if (!grupo().instrumentos.length) lista.append(vacio("Este grupo no tiene operaciones."));
      tiposDelGrupo().forEach(([clave, nombre, n]) => lista.append(fila(nombre, plural(n, "instrumento", "instrumentos"), () => { nav.t = clave; pintar(); })));
    } else if (nav.i === null) {
      acciones.append(boton("+ Instrumento", { abrir: "d-instrumento" }, "primario"), boton("Importar CSV", { abrir: "d-csv" }));
      grupo().instrumentos.forEach((x, k) => {
        if (x.tipo === nav.t) lista.append(fila(x.nombre, plural(x.ops.length, "operación", "operaciones"), () => { nav.i = k; pintar(); }));
      });
    } else {
      acciones.append(boton("+ Añadir", { abrir: "d-anadir" }, "primario"), boton("Mover a otro grupo", { abrir: "d-mover" }), boton("Borrar instrumento", { borrarInstrumento: "1" }, "peligro"));
      instrumento().ops.forEach((o) => lista.append(filaOperacion(o)));
    }
  }

  // Rellena el texto de contexto de cada diálogo según donde estés
  function preparar(id) {
    if (id === "d-anadir") {
      editando = null;
      $("titulo-anadir").textContent = "Añadir operación";
      for (const r of document.querySelectorAll("[name=tipo-op]")) r.disabled = false;
      $("ctx-anadir").textContent = `${instrumento().nombre} · ${grupo().nombre}`;
      error("error-anadir", "");
      $("op-fecha").value = new Date().toISOString().slice(0, 10);
      for (const c of ["op-part", "op-precio"]) $(c).value = "";
      $("op-comision").value = "0";
      mostrarTotal();
    } else if (id === "d-grupo") {
      $("grupo-nombre").value = "";
      error("error-grupo", "");
    } else if (id === "d-instrumento") {
      $("ctx-instrumento").textContent = `Grupo: ${grupo().nombre}`;
    } else if (id === "d-csv") {
      $("ctx-csv").textContent = `Grupo: ${grupo().nombre}`;
      csv = null;
      $("archivo-csv").value = "";
      error("error-csv", "");
      paso = 1; mostrarPaso();
    } else if (id === "d-mover") {
      $("ctx-mover").textContent = `${instrumento().nombre} · ahora en ${grupo().nombre}`;
      const otros = DATOS.filter((_, k) => k !== nav.g);
      $("destino-mover").replaceChildren(...otros.map((g) => new Option(g.nombre, g.id)));
      error("error-mover", "");
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

  // Editar: el mismo diálogo de añadir, con los datos de la operación. El instrumento y el tipo no se cambian.
  let editando = null; // {tipo, id} mientras el diálogo está en modo editar
  function abrirEditar(tipo, id) {
    const o = instrumento().ops.find((x) => x[0] === tipo && String(x[4]) === String(id))[6];
    preparar("d-anadir");
    editando = { tipo, id };
    $("titulo-anadir").textContent = "Editar operación";
    for (const r of document.querySelectorAll("[name=tipo-op]")) {
      r.checked = r.value === tipo;
      r.disabled = true;
    }
    $("op-fecha").value = o.fecha;
    $("op-part").value = String(o.participaciones);
    $("op-precio").value = String(o.precio);
    $("op-comision").value = String(o.comision || 0);
    mostrarTotal();
    $("d-anadir").showModal();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-editar]");
    if (b) abrirEditar(...b.dataset.editar.split(":"));
  });

  // Abrir diálogos (los botones de acciones se crean dinámicamente: delegación)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-abrir]");
    if (!b) return;
    preparar(b.dataset.abrir);
    $(b.dataset.abrir).showModal();
  });

  // Crear grupo; si el servidor lo rechaza (nombre vacío o repetido) el diálogo sigue abierto
  $("crear-grupo").addEventListener("click", async (e) => {
    e.preventDefault();
    if (!$("d-grupo").querySelector("form").reportValidity()) return;
    try {
      await enviar("/api/grupos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: $("grupo-nombre").value }),
      });
      $("d-grupo").close();
      await recargar();
    } catch (err) {
      error("error-grupo", err.message);
    }
  });

  // Mover el instrumento abierto a otro grupo; si el servidor lo rechaza el diálogo sigue abierto
  $("confirmar-mover").addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      await enviar(`/api/instrumentos/${instrumento().id}/mover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ origen: grupo().id, destino: Number($("destino-mover").value) }),
      });
      $("d-mover").close();
      nav.i = null; // ya no está en este grupo
      await recargar();
    } catch (err) {
      error("error-mover", err.message);
    }
  });

  // Borrar el grupo abierto (el servidor solo lo permite si está vacío)
  document.addEventListener("click", async (e) => {
    if (!e.target.closest("[data-borrar-grupo]")) return;
    const g = grupo();
    const n = g.instrumentos.reduce((t, x) => t + x.ops.length, 0);
    const aviso = n
      ? `¿Borrar el grupo «${g.nombre}» con sus ${plural(n, "operación", "operaciones")} (${plural(g.instrumentos.length, "instrumento", "instrumentos")})? Los instrumentos se conservan, pero las operaciones no se pueden recuperar.`
      : `¿Borrar el grupo «${g.nombre}»?`;
    if (!confirm(aviso)) return;
    try {
      await enviar(`/api/grupos/${g.id}?con_operaciones=1`, { method: "DELETE" });
      nav.g = nav.t = nav.i = null;
      await recargar();
    } catch (err) {
      alert(err.message);
    }
  });

  // Borrar el instrumento entero (todas sus operaciones, en todos los grupos, y sus precios)
  document.addEventListener("click", async (e) => {
    if (!e.target.closest("[data-borrar-instrumento]")) return;
    const x = instrumento();
    if (!confirm(`¿Borrar «${x.nombre}» con todas sus operaciones (en todos los grupos) y su histórico de precios? No se puede deshacer.`)) return;
    try {
      await enviar(`/api/instrumentos/${x.id}`, { method: "DELETE" });
      nav.i = null;
      await recargar();
    } catch (err) {
      alert(err.message);
    }
  });

  // Selección múltiple de operaciones
  $("lista-ops").addEventListener("change", () => {
    const n = document.querySelectorAll("#lista-ops input:checked").length;
    $("barra-seleccion").hidden = n === 0;
    $("n-seleccion").textContent = plural(n, "seleccionada", "seleccionadas");
  });

  // Importe de la operación mientras se escribe: participaciones × precio (± comisión), para que
  // el usuario compruebe de un vistazo que los datos están bien. Solo es visual; el servidor recalcula.
  const leer = (id) => {
    const t = $(id).value.trim().replace(",", ".");
    return t !== "" && Number.isFinite(Number(t)) ? Number(t) : null;
  };
  function mostrarTotal() {
    const n = leer("op-part"), precio = leer("op-precio"), com = leer("op-comision") || 0;
    const p = $("total-op");
    p.hidden = n === null || precio === null;
    if (p.hidden) return;
    const venta = document.querySelector("[name=tipo-op]:checked").value === "venta";
    const d = instrumento().divisa;
    const total = n * precio + (venta ? -com : com);
    p.textContent = `${numero.format(n)} × ${dinero(precio, d)} = ${dinero(n * precio, d)}` +
      (com ? ` ${venta ? "−" : "+"} comisión ${dinero(com, d)} = ${dinero(total, d)}` : "") +
      (venta ? " (cobrado)" : " (invertido)");
  }
  for (const id of ["op-part", "op-precio", "op-comision"]) $(id).addEventListener("input", mostrarTotal);
  for (const r of document.querySelectorAll("[name=tipo-op]")) r.addEventListener("change", mostrarTotal);

  // Guardar una operación nueva. Si el servidor la rechaza, el diálogo sigue abierto con el motivo.
  $("guardar-op").addEventListener("click", async (e) => {
    e.preventDefault();
    if (!$("d-anadir").querySelector("form").reportValidity()) return;
    const cuerpo = {
      ...(editando ? {} : {
        tipo: document.querySelector("[name=tipo-op]:checked").value,
        instrumento: instrumento().id,
        grupo: grupo().id,
      }),
      fecha: $("op-fecha").value,
      participaciones: $("op-part").value,
      precio: $("op-precio").value,
      comision: $("op-comision").value || "0",
    };
    try {
      await enviar(editando ? `/api/operaciones/${editando.tipo}/${editando.id}` : "/api/operaciones", {
        method: editando ? "PUT" : "POST",
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

  // Asistente CSV: 1) elegir fichero (el servidor lo lee sin guardar) 2) vista previa 3) confirmar
  let paso = 1;
  let csv = null; // {archivo, previa} del fichero elegido
  const esIbkr = () => csv && csv.previa.formato === "ibkr"; // Flex Query de Interactive Brokers (acciones)
  const nombreCsv = () => (esIbkr() ? "Interactive Brokers" : csv.previa.existente || $("csv-nombre").value).trim();
  function mostrarPaso() {
    for (const s of document.querySelectorAll("#asistente [data-paso]")) s.hidden = Number(s.dataset.paso) !== paso;
    document.querySelectorAll(".pasos li").forEach((li, i) => li.classList.toggle("activo", i + 1 === paso));
    $("csv-atras").hidden = paso === 1;
    $("csv-sig").textContent = paso === 3 ? "Importar" : "Siguiente";
    $("csv-sig").disabled = !csv || (paso === 2 && !nombreCsv());
  }
  // Los errores del servidor llegan como página HTML: se enseña solo el mensaje
  async function subirCsv(url, cuerpo) {
    const r = await fetch(url, { method: "POST", body: cuerpo });
    if (r.ok) return r.json();
    const html = new DOMParser().parseFromString(await r.text(), "text/html");
    throw new Error(html.querySelector("p")?.textContent.trim() || r.statusText);
  }
  const formCsv = (extra) => {
    const f = new FormData();
    f.append("archivo", csv.archivo);
    f.append("grupo", grupo().nombre);
    for (const [k, v] of Object.entries(extra || {})) f.append(k, v);
    return f;
  };

  async function elegirCsv(archivo) {
    csv = null;
    error("error-csv", "");
    mostrarPaso();
    try {
      csv = { archivo };
      csv.previa = await subirCsv("/api/importar/vista-previa", formCsv());
      if (esIbkr() && !csv.previa.operaciones.length) {
        const n = csv.previa.repetidas;
        csv = null;
        throw new Error(`Las ${plural(n, "operación", "operaciones")} del fichero ya están en el grupo ${grupo().nombre}.`);
      }
      if (csv.previa.ya_importado) {
        const nombre = csv.previa.existente;
        csv = null;
        throw new Error(`${nombre} ya tiene compras en el grupo ${grupo().nombre}; bórralas antes de reimportar.`);
      }
    } catch (err) {
      csv = null;
      error("error-csv", `${archivo.name}: ${err.message}`);
      return;
    }
    const p = csv.previa;
    if (esIbkr()) {
      $("csv-fondo").replaceChildren(
        Object.assign(document.createElement("strong"), { textContent: "Interactive Brokers" }),
        ` · ${plural(p.nuevos.length, "instrumento nuevo", "instrumentos nuevos")}`);
      $("csv-nombre-campo").hidden = $("csv-ticker-campo").hidden = true;
      $("csv-validas").textContent = plural(p.operaciones.length, "operación", "operaciones");
      $("csv-ignoradas").textContent = plural(p.ignoradas, "ignorada", "ignoradas") + (p.repetidas ? ` · ${plural(p.repetidas, "ya estaba", "ya estaban")}` : "");
      const filas = p.operaciones.slice(0, 4).map((o) => Object.assign(document.createElement("li"), {
        textContent: `${fechaOp.format(new Date(o.fecha + "T00:00:00")).replace(/\./g, "")} · ${o.lado === "BUY" ? "Compra" : "Venta"} ${o.simbolo} · ${numero.format(o.participaciones)} part. a ${dinero(o.precio, o.divisa)}`,
      }));
      if (p.operaciones.length > 4) filas.push(Object.assign(document.createElement("li"), { className: "nota", textContent: `… ${p.operaciones.length - 4} más` }));
      $("csv-lista").replaceChildren(...filas);
      paso = 2;
      return mostrarPaso();
    }
    $("csv-fondo").replaceChildren(
      Object.assign(document.createElement("strong"), { textContent: p.isin }),
      ` · ${p.existente ? p.existente + " (ya existe)" : "instrumento nuevo"} · ${p.divisa}`);
    $("csv-nombre-campo").hidden = $("csv-ticker-campo").hidden = !!p.existente;
    $("csv-nombre").value = $("csv-ticker").value = "";
    $("csv-validas").textContent = plural(p.compras.length, "válida", "válidas");
    $("csv-ignoradas").textContent = plural(p.ignoradas, "ignorada", "ignoradas");
    const lineas = p.compras.slice(0, 4).map((c) => Object.assign(document.createElement("li"), {
      textContent: `${fechaOp.format(new Date(c.fecha + "T00:00:00")).replace(/\./g, "")} · ${numero.format(c.participaciones)} part. a ${dinero(c.precio, p.divisa)}`,
    }));
    if (p.compras.length > 4) lineas.push(Object.assign(document.createElement("li"), { className: "nota", textContent: `… ${p.compras.length - 4} más` }));
    $("csv-lista").replaceChildren(...lineas);
    paso = 2;
    mostrarPaso();
  }

  $("elegir-csv").addEventListener("click", () => $("archivo-csv").click());
  $("archivo-csv").addEventListener("change", (e) => e.target.files[0] && elegirCsv(e.target.files[0]));
  $("zona-csv").addEventListener("dragover", (e) => e.preventDefault());
  $("zona-csv").addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) elegirCsv(e.dataTransfer.files[0]);
  });
  $("csv-nombre").addEventListener("input", mostrarPaso);

  $("csv-sig").addEventListener("click", async () => {
    error("error-csv", "");
    if (paso === 2) {
      const p = csv.previa;
      if (esIbkr()) {
        $("resumen-csv").replaceChildren(
          `Se añadirán ${plural(p.operaciones.length, "operación", "operaciones")} de acciones (${plural(p.nuevos.length, "instrumento nuevo", "instrumentos nuevos")}) al grupo `,
          Object.assign(document.createElement("strong"), { textContent: grupo().nombre }), ".");
        $("nota-csv").textContent = p.nota;
        paso = 3;
        return mostrarPaso();
      }
      $("resumen-csv").replaceChildren(
        `Se añadirán ${plural(p.compras.length, "compra", "compras")} de `,
        Object.assign(document.createElement("strong"), { textContent: nombreCsv() }),
        ` (${dinero(p.invertido, p.divisa)} invertidos) al grupo `,
        Object.assign(document.createElement("strong"), { textContent: grupo().nombre }), ".");
      $("nota-csv").textContent = p.ignoradas ? `Las ${plural(p.ignoradas, "orden", "órdenes")} “En curso” o “Rechazada” se ignoran.` : "";
      paso = 3;
      return mostrarPaso();
    }
    $("csv-sig").disabled = true;
    $("csv-sig").textContent = "Importando y bajando precios…";
    try {
      await subirCsv("/api/importar", formCsv({ nombre: nombreCsv(), ticker_yahoo: $("csv-ticker").value.trim() }));
      $("d-csv").close();
      await recargar();
    } catch (err) {
      error("error-csv", err.message);
      $("csv-sig").disabled = false;
      mostrarPaso();
    }
  });
  $("csv-atras").addEventListener("click", () => { paso--; error("error-csv", ""); mostrarPaso(); });

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
