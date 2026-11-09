// Lo que hace que el libro se sienta físico y rápido de manejar:
//   · transiciones de hoja (pasar de pestaña, arrancar la hoja del taco)
//   · la tapa que se abre al entrar
//   · el índice rápido (Ctrl+K o /): pacientes, fechas dichas en español, secciones y acciones
//   · atajos de teclado y su chuleta (?)
import { api, esc, icono, dialogo, fechaLarga, fechaCorta, sumarDias, iso, deIso, DIAS, MESES } from "./util.js";

export const sinMovimiento = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- transiciones de hoja ----------
let enCurso = null;
/** Ejecuta pintar() dentro de una transición de vista con el tipo dado (CSS: html[data-transicion=…]). */
export async function transicion(tipo, pintar) {
  if (enCurso) {
    // Navegando deprisa: la animación que estaba en marcha se corta y esta hoja se pinta sin animación.
    // (Encadenar transiciones de vista a veces deja la segunda sin terminar en Chromium.)
    enCurso.skipTransition();
    enCurso = null;
    return pintar();
  }
  if (!tipo || !document.startViewTransition || sinMovimiento()) return pintar();
  const html = document.documentElement;
  html.dataset.transicion = tipo;
  const t = document.startViewTransition(pintar);
  enCurso = t;
  t.ready.catch(() => {});
  t.finished.catch(() => {}).finally(() => {
    if (enCurso === t) enCurso = null;
    if (html.dataset.transicion === tipo) delete html.dataset.transicion;
  });
  try { await t.updateCallbackDone; } catch { /* la vista se pintó igual */ }
}

// ---------- la tapa que se abre ----------
/** Copia la portada en una tapa por encima, deja que debajo se pinte el libro y la abre. */
export async function abrirTapa(pintarDebajo) {
  const portada = document.querySelector(".portada");
  if (!portada || sinMovimiento()) return pintarDebajo();
  const tapa = portada.cloneNode(true);
  tapa.classList.add("tapa-abriendose");
  tapa.setAttribute("aria-hidden", "true");
  tapa.inert = true;     // es solo un dibujo: ni foco, ni campos con nombre que un gestor de contraseñas confunda
  tapa.querySelectorAll("[name], [id]").forEach((x) => { x.removeAttribute("name"); x.removeAttribute("id"); });
  tapa.querySelectorAll("form").forEach((f) => f.replaceWith(Object.assign(document.createElement("div"), { className: f.className, innerHTML: f.innerHTML })));
  document.body.append(tapa);
  await pintarDebajo();
  tapa.classList.add("tapa-abriendose--ya");
  setTimeout(() => tapa.remove(), 1100);
}

// ---------- fechas dichas como se dicen ----------
const SIN_TILDE = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const DIAS_SIN = DIAS.map(SIN_TILDE);
const MESES_SIN = MESES.map(SIN_TILDE);

/** «mañana», «pasado mañana», «lunes», «15», «15/11», «15 nov», «3 de diciembre», «+3», «-2» → AAAA-MM-DD (o null). */
export function leerFecha(texto, hoy) {
  const t = SIN_TILDE(texto).replace(/^el\s+/, "").replace(/^(ir a|ve a)\s+/, "");
  if (!t) return null;
  if (t === "hoy") return hoy;
  if (t === "manana") return sumarDias(hoy, 1);
  if (t === "pasado manana" || t === "pasado") return sumarDias(hoy, 2);
  if (t === "ayer") return sumarDias(hoy, -1);
  let m = t.match(/^([+-])\s*(\d{1,3})(\s*d(ias?)?)?$/);
  if (m) return sumarDias(hoy, Number(m[2]) * (m[1] === "-" ? -1 : 1));
  m = t.match(/^(en|dentro de)\s+(\d{1,2})\s+(dias?|semanas?)$/);
  if (m) return sumarDias(hoy, Number(m[2]) * (m[3].startsWith("semana") ? 7 : 1));
  const nombreDia = t.replace(/^(el |proximo |este )/, "");
  const dia = nombreDia.length >= 2 ? DIAS_SIN.findIndex((d) => d.startsWith(nombreDia)) : -1;
  if (dia >= 0) {
    const hoyN = (deIso(hoy).getDay() + 6) % 7;
    return sumarDias(hoy, ((dia - hoyN + 7) % 7) || 7);
  }
  const base = deIso(hoy);
  m = t.match(/^(\d{1,2})(?:\s*(?:\/|-|\.|de)?\s*(\d{1,2}|[a-z]+))?(?:\s*(?:\/|-|\.|de)?\s*(\d{2,4}))?$/);
  if (m) {
    const d = Number(m[1]);
    let mes = base.getMonth();
    let año = base.getFullYear();
    if (m[2]) {
      if (/^\d+$/.test(m[2])) mes = Number(m[2]) - 1;
      else {
        mes = MESES_SIN.findIndex((x) => x.startsWith(m[2].slice(0, 3)));
        if (mes < 0) return null;
      }
    }
    if (m[3]) año = Number(m[3]) < 100 ? 2000 + Number(m[3]) : Number(m[3]);
    const f = new Date(año, mes, d, 12);
    if (f.getDate() !== d || mes > 11) return null;
    // «15» o «15/11» sin año: el próximo que venga (si ya pasó este mes o este año, el siguiente)
    if (!m[3] && iso(f) < hoy) {
      if (m[2]) f.setFullYear(año + 1); else f.setMonth(mes + 1);
    }
    return iso(f);
  }
  return null;
}

// ---------- índice rápido ----------
let abierto = false;

/** opciones: { hoy, irA(hash), acciones: [{ id, nombre, pista, hacer }], secciones: [{ id, nombre, hash }] } */
export function indiceRapido(opciones) {
  if (abierto) return;
  abierto = true;
  let elegido = 0, resultados = [], pacientes = [], pedido = 0, temporizador;
  const pista = matchMedia("(hover: hover)").matches;
  return dialogo(`
    <div class="indice" role="combobox" aria-expanded="true" aria-haspopup="listbox">
      <label class="indice__buscar">${icono("buscar", 20)}
        <span class="sr">Buscar en el libro</span>
        <input type="text" autocomplete="off" spellcheck="false" placeholder="Paciente, fecha («mañana», «lunes», «15/11») o qué quieres hacer" aria-controls="indice-lista">
      </label>
      <ul class="indice__lista" id="indice-lista" role="listbox"></ul>
      ${pista ? `<p class="indice__pie"><kbd>↑</kbd><kbd>↓</kbd> elegir · <kbd>⏎</kbd> abrir · <kbd>Esc</kbd> cerrar · <kbd>?</kbd> atajos</p>` : ""}
    </div>`, (d, cerrar) => {
    d.classList.add("impreso--indice");
    const entrada = d.querySelector("input");
    const lista = d.querySelector("ul");
    const calcular = () => {
      const q = entrada.value.trim();
      const qs = SIN_TILDE(q);
      const filas = [];
      const fecha = leerFecha(q, opciones.hoy);
      if (fecha) {
        filas.push({ grupo: "Ir al día", nombre: fechaLarga(fecha, { año: true }).replace(/^./, (c) => c.toUpperCase()), pista: fechaCorta(fecha), icono: "reloj", hacer: () => opciones.irA(`#/libro/${fecha}`) });
      }
      for (const a of opciones.acciones) {
        if (!qs || SIN_TILDE(a.nombre).includes(qs)) filas.push({ grupo: "Hacer", ...a, icono: a.icono || "mas" });
      }
      for (const s of opciones.secciones) {
        if (qs && SIN_TILDE(s.nombre).startsWith(qs)) filas.push({ grupo: "Abrir", nombre: s.nombre, pista: s.tecla ? `tecla ${s.tecla}` : "", icono: "derecha", hacer: () => opciones.irA(s.hash) });
      }
      for (const p of pacientes) {
        filas.push({ grupo: "Pacientes", nombre: `${p.apellidos}, ${p.nombre}`, pista: p.proxima ? `próxima ${fechaCorta(p.proxima)} ${p.proxima.slice(11, 16)}` : (p.telefono || ""),
          icono: "lapiz", hacer: () => opciones.irA(`#/fichero/${p.id}`) });
      }
      if (!q) for (const s of opciones.secciones) filas.push({ grupo: "Abrir", nombre: s.nombre, pista: s.tecla ? `tecla ${s.tecla}` : "", icono: "derecha", hacer: () => opciones.irA(s.hash) });
      resultados = filas;
      elegido = Math.min(elegido, Math.max(0, filas.length - 1));
      pintar();
    };
    const pintar = () => {
      let grupo = null;
      lista.innerHTML = resultados.length ? resultados.map((r, i) => {
        const cab = r.grupo !== grupo ? `<li class="indice__grupo" role="presentation">${esc(r.grupo)}</li>` : "";
        grupo = r.grupo;
        return `${cab}<li role="option" id="indice-${i}" aria-selected="${i === elegido}" data-i="${i}" class="indice__fila">
          <span class="indice__icono">${icono(r.icono, 16)}</span><span class="indice__nombre">${esc(r.nombre)}</span><span class="indice__pista">${esc(r.pista || "")}</span></li>`;
      }).join("") : `<li class="indice__vacio">Nada con «${esc(entrada.value)}». Prueba con un apellido, un teléfono o una fecha.</li>`;
      entrada.setAttribute("aria-activedescendant", resultados.length ? `indice-${elegido}` : "");
      lista.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    };
    const elegir = (i) => { const r = resultados[i]; if (!r) return; cerrar(); r.hacer(); };
    entrada.addEventListener("input", () => {
      elegido = 0;
      clearTimeout(temporizador);
      const q = entrada.value.trim();
      if (q.length < 2 || leerFecha(q, opciones.hoy)) { pacientes = []; calcular(); return; }
      calcular();
      temporizador = setTimeout(async () => {
        const n = ++pedido;
        try {
          const r = await api(`/api/pacientes?q=${encodeURIComponent(q)}`);
          if (n !== pedido) return;
          pacientes = r.pacientes.slice(0, 6);
          calcular();
        } catch { /* sin pacientes */ }
      }, 140);
    });
    entrada.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!resultados.length) return;
        elegido = (elegido + (e.key === "ArrowDown" ? 1 : -1) + resultados.length) % resultados.length;
        pintar();
      } else if (e.key === "Enter") {
        e.preventDefault();
        elegir(elegido);
      }
    });
    lista.addEventListener("click", (e) => { const f = e.target.closest("[data-i]"); if (f) elegir(Number(f.dataset.i)); });
    lista.addEventListener("pointermove", (e) => {
      const f = e.target.closest("[data-i]");
      if (f && Number(f.dataset.i) !== elegido) { elegido = Number(f.dataset.i); pintar(); }
    });
    d.addEventListener("close", () => { abierto = false; });
    calcular();
    entrada.focus();
  });
}

// ---------- atajos ----------
export const ATAJOS = [
  ["Ctrl K  o  /", "Índice rápido: buscar paciente, ir a un día o hacer algo"],
  ["N", "Apuntar una cita"],
  ["← →", "Día (o semana) anterior y siguiente"],
  ["H", "Volver a hoy"],
  ["L · S · E · F · A", "Libro · Semana · Espera · Fichero · Avisos"],
  ["Esc", "Cerrar la tarjeta o el impreso"],
  ["?", "Esta chuleta"],
];

export function chuleta() {
  return dialogo(`
    <div class="impreso__cabeza"><h2>Atajos del libro</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
    <div class="impreso__cuerpo">
      <dl class="chuleta">${ATAJOS.map(([k, t]) => `<div><dt>${k.split(" ").filter(Boolean).map((x) => x === "o" || x === "·" ? `<span>${x}</span>` : `<kbd>${esc(x)}</kbd>`).join(" ")}</dt><dd>${esc(t)}</dd></div>`).join("")}</dl>
      <p style="font-size:var(--t-s);color:var(--tinta-2)">En el móvil, desliza la hoja del libro a izquierda o derecha para cambiar de día.</p>
    </div>`);
}

/** manejadores: { indice, apuntar, paso(n), hoy, ir(id), chuleta } */
export function atajos(manejadores) {
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    // Una caja de un diálogo que se acaba de cerrar no cuenta: el foco tarda un instante en salir de ella
    const escribiendo = t.closest?.("input, textarea, select, [contenteditable]") && !t.closest("dialog:not([open])") && t.isConnected;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (!document.querySelector("dialog[open]")) manejadores.indice();
      return;
    }
    if (escribiendo || e.ctrlKey || e.metaKey || e.altKey || document.querySelector("dialog[open]")) return;
    const k = e.key;
    const accion = {
      "/": manejadores.indice, "?": manejadores.chuleta, n: manejadores.apuntar, N: manejadores.apuntar,
      ArrowLeft: () => manejadores.paso(-1), ArrowRight: () => manejadores.paso(1),
      h: manejadores.hoy, l: () => manejadores.ir("libro"), s: () => manejadores.ir("semana"),
      e: () => manejadores.ir("espera"), f: () => manejadores.ir("fichero"), a: () => manejadores.ir("avisos"),
    }[k];
    if (!accion) return;
    // Las flechas solo mueven la hoja si no hay una tarjeta abierta (ahí se usan para leerla)
    if ((k === "ArrowLeft" || k === "ArrowRight") && document.querySelector(".tarjeta-cita")) return;
    e.preventDefault();
    accion();
  });
}

// ---------- cifras que cuentan ----------
export function contar(raiz) {
  if (sinMovimiento()) return;
  raiz.querySelectorAll("[data-cuenta]").forEach((el) => {
    const final = Number(el.dataset.cuenta);
    if (!Number.isFinite(final) || final === 0) return;
    const sufijo = el.dataset.sufijo || "";
    const t0 = performance.now();
    const paso = (t) => {
      const p = Math.min(1, (t - t0) / 700);
      el.textContent = Math.round(final * (1 - (1 - p) ** 3)).toLocaleString("es-ES") + sufijo;
      if (p < 1) requestAnimationFrame(paso);
    };
    requestAnimationFrame(paso);
  });
}
