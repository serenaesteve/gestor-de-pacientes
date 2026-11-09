// Volante · armazón: sesión, membrete, uñero y rutas.
import { api, esc, icono, avatar, nota, ROLES, MESES_CORTOS, deIso, sumarDias, iso } from "./util.js";
import * as libro from "./libro.js";
import * as fichero from "./fichero.js";
import * as medicos from "./medicos.js";
import * as avisos from "./avisos.js";
import * as ajustes from "./ajustes.js";
import * as espera from "./espera.js";
import * as informe from "./informe.js";
import { transicion, abrirTapa, indiceRapido, atajos, chuleta } from "./vivo.js";
import { apuntar } from "./cita-form.js";

export const estado = { yo: null, permisos: [], ajustes: {}, medicos: [], hoy: iso(new Date()), bandeja: 0 };
export const puede = (p) => estado.permisos.includes(p);

const raiz = document.getElementById("app");

// «secundaria»: en el móvil va dentro de «Más» para que la barra de abajo no tenga ocho pestañas.
const VISTAS = [
  { id: "libro", nombre: "Libro", modulo: libro },
  { id: "semana", nombre: "Semana", modulo: libro },
  { id: "espera", nombre: "Espera", modulo: espera },
  { id: "fichero", nombre: "Fichero", modulo: fichero },
  { id: "avisos", nombre: "Avisos", modulo: avisos },
  { id: "medicos", nombre: "Médicos", modulo: medicos, secundaria: true },
  { id: "informe", nombre: "Informe", modulo: informe, secundaria: true, permiso: "informe" },
  { id: "ajustes", nombre: "Ajustes", modulo: ajustes, secundaria: true },
];
const visibles = () => VISTAS.filter((v) => !v.permiso || puede(v.permiso));

// ---------- tema ----------
function aplicarTema() {
  let t = null;
  try { t = localStorage.getItem("volante:tema"); } catch { /* sin almacenamiento */ }
  if (t) document.documentElement.dataset.tema = t; else delete document.documentElement.dataset.tema;
}
function alternarTema() {
  const oscuro = document.documentElement.dataset.tema
    ? document.documentElement.dataset.tema === "oscuro"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  try { localStorage.setItem("volante:tema", oscuro ? "claro" : "oscuro"); } catch { /* nada */ }
  aplicarTema();
}

// ---------- portada: entrar o poner en marcha ----------
// «Lucía Pérez» → «lucia.perez», igual que hace el servidor: se puede escribir el usuario como salga.
const normalizarUsuario = (t) => (t || "").trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, ".");

// modo: «entrar», «registro» (cuenta nueva = centro nuevo) o «primera» (puesta en marcha de un servidor vacío)
function portada(modo, hayRegistro) {
  const titulos = { entrar: "Entrar", registro: "Crear cuenta nueva", primera: "Puesta en marcha" };
  document.title = `${titulos[modo]} · Volante`;
  const nueva = modo !== "entrar";
  raiz.innerHTML = `
    <main class="portada">
      <div class="portada__libro">
        <div class="portada__lomo">
          <h1>Volante</h1>
          <p>Libro de citas de la consulta</p>
        </div>
        <form class="portada__etiqueta" novalidate>
          ${modo === "primera" ? `
            <h2>Abrir el libro por primera vez</h2>
            <p>Crea la cuenta de dirección. Con ella darás de alta a médicos, recepción y horarios.</p>` : ""}
          ${modo === "registro" ? `
            <h2>Estrenar un libro nuevo</h2>
            <p>Tu cuenta abre un centro propio: sus médicos, pacientes y citas solo los ves tú y el equipo al que des cuenta.</p>` : ""}
          ${modo === "entrar" ? `<h2>Entrar</h2>` : ""}
          ${nueva ? `
            <label class="campo"><span>Nombre del centro o consulta</span><input name="centro" required maxlength="80" autocomplete="organization" placeholder="Centro Médico…"></label>
            <label class="campo"><span>Tu nombre</span><input name="nombre" required maxlength="80" autocomplete="name"></label>` : ""}
          <label class="campo"><span>Usuario</span><input name="usuario" required autocomplete="username" autocapitalize="none" spellcheck="false" maxlength="30">
            ${nueva ? "<small>De 3 a 30 caracteres. Si pones tildes o espacios, se guarda sin tildes y con puntos: «Lucía Pérez» → lucia.perez.</small>" : ""}</label>
          <label class="campo"><span>Contraseña</span><input name="contrasena" type="password" required autocomplete="${nueva ? "new-password" : "current-password"}" minlength="${nueva ? 10 : 1}">
            ${nueva ? "<small>10 caracteres como mínimo: aquí habrá datos de salud.</small>" : ""}</label>
          ${modo === "registro" ? `
            <label class="casilla"><input type="checkbox" name="ejemplo"> Empezar con médicos, pacientes y citas de ejemplo (inventados) para probarlo</label>
            <p class="portada__aviso">No hay correo para recuperar la contraseña: apúntala. Puedes borrar el centro entero cuando quieras desde Ajustes.
              <a href="/privacidad.html">Qué se guarda y dónde</a>.</p>` : ""}
          <p class="mensaje-error" role="alert"></p>
          <button class="boton boton--tinta" type="submit">${{ entrar: "Abrir el libro", registro: "Crear la cuenta y estrenar el libro", primera: "Crear la cuenta y abrir el libro" }[modo]}</button>
          ${modo === "entrar" && hayRegistro ? `<p class="portada__otra">¿Primera vez? <button type="button" class="boton boton--plano" data-modo="registro">Crear cuenta nueva</button></p>` : ""}
          ${modo === "registro" ? `<p class="portada__otra">¿Ya tienes cuenta? <button type="button" class="boton boton--plano" data-modo="entrar">Entrar</button></p>` : ""}
        </form>
        <p class="portada__pie">${modo === "primera" ? "Si trabajas con más gente, cada persona tendrá su propia cuenta."
          : modo === "registro" ? "Recepción y médicos no se registran aquí: dirección les crea su cuenta desde Ajustes → Equipo."
          : "¿Trabajas en un centro que ya usa Volante? Tu cuenta te la da dirección, y también una contraseña nueva si la olvidas."}</p>
      </div>
    </main>`;
  const form = raiz.querySelector("form");
  form.querySelector("input").focus();
  form.querySelectorAll("[data-modo]").forEach((b) => b.addEventListener("click", () => {
    history.replaceState(null, "", b.dataset.modo === "registro" ? "#/registro" : location.pathname);
    portada(b.dataset.modo, hayRegistro);
  }));
  const marcar = (campo, mensaje) => {
    const error = form.querySelector(".mensaje-error");
    form.querySelectorAll(".campo--error").forEach((c) => c.classList.remove("campo--error"));
    error.textContent = mensaje || "";
    const entrada = campo && form.elements[campo];
    if (entrada) {
      entrada.closest(".campo")?.classList.add("campo--error");
      entrada.setAttribute("aria-invalid", "true");
      entrada.focus();
    }
  };
  form.addEventListener("input", (e) => {
    e.target.closest(".campo")?.classList.remove("campo--error");
    e.target.removeAttribute("aria-invalid");
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = form.querySelector("button[type=submit]");
    const datos = Object.fromEntries(new FormData(form));
    datos.ejemplo = Boolean(form.ejemplo?.checked);
    // Lo mismo que comprueba el servidor, dicho antes de enviar y señalando el campo
    if (nueva) {
      const usuario = normalizarUsuario(datos.usuario);
      if (!datos.centro?.trim()) return marcar("centro", "Pon el nombre del centro o de la consulta.");
      if (!datos.nombre?.trim()) return marcar("nombre", "Pon tu nombre.");
      if (usuario.length < 3 || usuario.length > 30) return marcar("usuario", "El usuario lleva de 3 a 30 caracteres.");
      if (!/^[a-z0-9._@+-]+$/.test(usuario)) return marcar("usuario", "En el usuario solo valen letras, números, punto, guion, guion bajo y @.");
      if ((datos.contrasena || "").length < 10) return marcar("contrasena", `La contraseña necesita 10 caracteres como mínimo (llevas ${(datos.contrasena || "").length}).`);
    } else if (!datos.usuario?.trim() || !datos.contrasena) {
      return marcar(!datos.usuario?.trim() ? "usuario" : "contrasena", "Escribe tu usuario y tu contraseña.");
    }
    marcar(null, "");
    boton.disabled = true;
    if (modo === "registro") boton.textContent = datos.ejemplo ? "Preparando tu centro con datos de ejemplo…" : "Preparando tu centro…";
    try {
      await api({ entrar: "/api/entrar", registro: "/api/registro", primera: "/api/alta" }[modo], { metodo: "POST", datos });
      if (modo === "registro") history.replaceState(null, "", location.pathname);
      await abrirTapa(arrancar);       // la tapa se abre y debajo ya está el libro
    } catch (err) {
      marcar(["usuario", "contrasena"].includes(err.codigo) ? err.codigo : null, err.message);
      boton.disabled = false;
      boton.textContent = { entrar: "Abrir el libro", registro: "Crear la cuenta y estrenar el libro", primera: "Crear la cuenta y abrir el libro" }[modo];
    }
  });
}

// ---------- mesa de trabajo ----------
function mesa() {
  raiz.innerHTML = `
    <a class="saltar" href="#contenido">Saltar al contenido</a>
    <div class="mesa">
      <div class="hoja">
        <header class="membrete" id="membrete"></header>
        <main class="contenido" id="contenido" tabindex="-1"></main>
      </div>
      <nav class="unero" aria-label="Secciones del libro" id="unero"></nav>
    </div>`;
  pintarUnero();
}

export function pintarUnero(actual) {
  const nav = document.getElementById("unero");
  if (!nav) return;
  const secundariaActiva = visibles().some((v) => v.secundaria && v.id === actual);
  const sube = estado.bandeja > (pintarUnero.antes ?? estado.bandeja);
  pintarUnero.antes = estado.bandeja;
  nav.innerHTML = visibles().map((v) => `
      <a href="${enlaceVista(v.id)}" ${v.id === actual ? 'aria-current="page"' : ""} ${v.secundaria ? "data-secundaria" : ""}>
        ${icono(v.id, 18)}<span class="unero__texto">${esc(v.nombre)}</span>${v.id === "avisos" && estado.bandeja ? `<span class="contador${sube ? " contador--sube" : ""}" aria-label="${estado.bandeja} por mandar">${estado.bandeja > 99 ? "99+" : estado.bandeja}</span>` : ""}
      </a>`).join("") + `
    <button type="button" class="unero__mas" data-mas aria-expanded="false" ${secundariaActiva ? 'aria-current="page"' : ""}>Más</button>
    <div class="unero__menu" data-menu hidden>
      ${visibles().filter((v) => v.secundaria).map((v) => `<a href="${enlaceVista(v.id)}" ${v.id === actual ? 'aria-current="page"' : ""}>${esc(v.nombre)}</a>`).join("")}
      <button type="button" data-tema>Papel claro u oscuro</button>
      <button type="button" data-salir>Salir</button>
    </div>
    <div class="unero__pie">
      <button type="button" data-tema title="Cambiar a papel claro u oscuro" aria-label="Cambiar tema">${icono("luna")}</button>
      <button type="button" data-salir title="Cerrar el libro (salir)" aria-label="Salir">${icono("salir")}</button>
    </div>`;
  moverGota(nav);
  nav.querySelectorAll("[data-tema]").forEach((b) => { b.onclick = alternarTema; });
  nav.querySelectorAll("[data-salir]").forEach((b) => { b.onclick = salir; });
  const mas = nav.querySelector("[data-mas]"), menu = nav.querySelector("[data-menu]");
  mas.onclick = () => { menu.hidden = !menu.hidden; mas.setAttribute("aria-expanded", String(!menu.hidden)); };
  menu.addEventListener("click", (e) => { if (e.target.closest("a")) menu.hidden = true; });
}

// La pestaña activa es una gota que se desliza desde donde estaba, se estira por el camino y recupera la forma.
let gotaAntes = null;
function moverGota(nav) {
  const activa = [...nav.querySelectorAll('a[aria-current="page"], .unero__mas[aria-current="page"]')].find((x) => x.offsetParent !== null);
  const gota = document.createElement("span");
  gota.className = "unero__gota";
  gota.setAttribute("aria-hidden", "true");
  nav.prepend(gota);
  if (!activa) { gota.hidden = true; return; }
  const sitio = { top: activa.offsetTop, left: activa.offsetLeft, width: activa.offsetWidth, height: activa.offsetHeight };
  const poner = (p) => Object.assign(gota.style, { top: `${p.top}px`, left: `${p.left}px`, width: `${p.width}px`, height: `${p.height}px` });
  const misma = gotaAntes && gotaAntes.top === sitio.top && gotaAntes.left === sitio.left;
  if (gotaAntes && !misma && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    gota.style.transition = "none";
    poner(gotaAntes);
    void gota.offsetWidth;
    gota.style.transition = "";
    gota.classList.add("unero__gota--estira");
    requestAnimationFrame(() => { poner(sitio); setTimeout(() => gota.classList.remove("unero__gota--estira"), 260); });
  } else {
    poner(sitio);
  }
  gotaAntes = sitio;
}
// Si cambia el tamaño o terminan de llegar las fuentes, la gota se recoloca sin animación
function recolocarGota() {
  const nav = document.getElementById("unero");
  if (!nav) return;
  gotaAntes = null;
  nav.querySelector(".unero__gota")?.remove();
  moverGota(nav);
}
addEventListener("resize", recolocarGota);
document.fonts?.ready.then(recolocarGota);

function enlaceVista(id) {
  if (id === "libro") return `#/libro/${ultimoDia}`;
  if (id === "semana") return `#/semana/${ultimoMedico || estado.medicos[0]?.id || 0}/${ultimoDia}`;
  if (id === "avisos") return "#/avisos/bandeja";
  if (id === "informe") return `#/informe/${ultimoDia.slice(0, 7)}`;
  return `#/${id}`;
}
let ultimoDia = estado.hoy;
let ultimoMedico = null;
export function recordarDia(dia, medico) {
  ultimoDia = dia;
  if (medico) ultimoMedico = medico;
}

async function salir() {
  await api("/api/salir", { metodo: "POST" }).catch(() => {});
  location.hash = "";
  arrancar();
}

// El membrete cambia con la vista: en el libro lleva el taco con la fecha; en el resto, el título.
export function membrete({ titulo, subtitulo = "", taco = null, casillas = "" }, contenido = null) {
  if (contenido && !contenido.isConnected) return;      // una vista que llega tarde no cambia el membrete
  const el = document.getElementById("membrete");
  const yo = estado.yo;
  let tacoHtml = "";
  if (taco) {
    const d = deIso(taco.fecha);
    tacoHtml = `
      <div class="taco" id="taco">
        <div class="taco__hoja" aria-hidden="true"><span class="taco__mes">${MESES_CORTOS[d.getMonth()]} ${d.getFullYear() !== deIso(estado.hoy).getFullYear() ? d.getFullYear() : ""}</span><span class="taco__dia">${String(d.getDate()).padStart(2, "0")}</span></div>
        <div class="taco__flechas">
          <button type="button" data-paso="-1" aria-label="${esc(taco.anterior)}" title="${esc(taco.anterior)}">${icono("izquierda", 16)}</button>
          <button type="button" data-paso="1" aria-label="${esc(taco.siguiente)}" title="${esc(taco.siguiente)}">${icono("derecha", 16)}</button>
        </div>
      </div>`;
  }
  el.innerHTML = `
    <div class="membrete__marca"><b>Volante</b><span>${esc(estado.ajustes.centro || "")}</span></div>
    <div class="membrete__centro">
      ${tacoHtml}
      <div class="membrete__titulo"><span class="rotulo">${esc(subtitulo)}</span><h1>${esc(titulo)}</h1></div>
      ${casillas}
    </div>
    <div class="membrete__yo">
      <button type="button" class="buscador-rapido" data-indice title="Índice rápido (Ctrl K)">${icono("buscar", 16)}<span>Buscar o ir a…</span><kbd>Ctrl K</kbd></button>
      <span class="membrete__cuenta">${avatar(yo.nombre, "violeta")}<span><b>${esc(yo.nombre)}</b><small>${esc(ROLES[yo.rol])}</small></span></span>
    </div>
    <button type="button" class="buscador-rapido buscador-rapido--movil" data-indice aria-label="Buscar o ir a…">${icono("buscar", 20)}</button>`;
  el.querySelectorAll("[data-indice]").forEach((b) => b.addEventListener("click", abrirIndice));
  if (taco) {
    el.querySelectorAll("[data-paso]").forEach((b) => b.addEventListener("click", () => {
      document.getElementById("taco").classList.remove("taco--arrancar");
      taco.alPasar(Number(b.dataset.paso));
    }));
  }
  requestAnimationFrame(() => document.documentElement.style.setProperty("--alto-membrete", `${el.offsetHeight}px`));
}

export function arrancarTaco() {
  const t = document.getElementById("taco");
  if (t) { void t.offsetWidth; t.classList.add("taco--arrancar"); }
}

// ---------- rutas ----------
let vistaActual = null;
// Las navegaciones van en fila: si llega otra mientras se pinta una (teclas pulsadas muy deprisa),
// al acabar se pinta la última dirección y las intermedias se saltan. Así dos animaciones nunca se cruzan.
let navegando = false, otraVez = false;
async function enrutar() {
  if (navegando) { otraVez = true; return; }
  navegando = true;
  try {
    do { otraVez = false; await enrutarUna(); } while (otraVez);
  } finally {
    navegando = false;
  }
}

async function enrutarUna() {
  if (!estado.yo) return;
  const [, id = "libro", ...resto] = (location.hash || "#/libro").replace(/^#/, "").split("/");
  const vista = VISTAS.find((v) => v.id === id) || VISTAS[0];
  if (vista.id === "libro" && !resto[0]) resto[0] = estado.hoy;
  const tipo = tipoTransicion(vistaActual, rutaActual, vista.id, resto);
  if (vistaActual !== vista.id) scrollTo({ top: 0, behavior: "instant" });
  vistaActual = vista.id;
  rutaActual = resto;
  document.querySelector(".tarjeta-cita")?.remove();
  document.querySelector(".vistazo")?.remove();
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
  await transicion(tipo, async () => {
    pintarUnero(vista.id);
    // Cada navegación pinta en un contenedor nuevo: si la vista anterior termina de cargar tarde,
    // escribe en uno que ya no está en la página y no pisa a la nueva.
    const viejo = document.getElementById("contenido");
    const contenido = viejo.cloneNode(false);
    viejo.replaceWith(contenido);
    try {
      await vista.modulo.mostrar(contenido, { vista: vista.id, params: resto });
    } catch (err) {
      if (contenido.isConnected) contenido.innerHTML = `<p class="vacio"><b>No se ha podido abrir esta hoja.</b>${esc(err.message)}</p>`;
    }
  });
}

// Pasar de pestaña (adelante o atrás según el uñero) o arrancar la hoja del taco (día siguiente o anterior).
let rutaActual = [];
function tipoTransicion(antes, rutaAntes, ahora, ruta) {
  if (!antes) return null;
  if (antes === ahora) {
    const f0 = (rutaAntes || []).find((x) => /^\d{4}-\d{2}-\d{2}$/.test(x)), f1 = ruta.find((x) => /^\d{4}-\d{2}-\d{2}$/.test(x));
    if ((ahora === "libro" || ahora === "semana") && f0 && f1 && f0 !== f1) return f1 > f0 ? "dia-siguiente" : "dia-anterior";
    return null;
  }
  const orden = VISTAS.map((v) => v.id);
  return orden.indexOf(ahora) > orden.indexOf(antes) ? "pasa-adelante" : "pasa-atras";
}

// ---------- índice rápido y atajos ----------
function abrirIndice() {
  if (!estado.yo) return;
  const irA = (hash) => { location.hash = hash; };
  const acciones = [];
  if (puede("citas")) {
    acciones.push({ nombre: "Apuntar una cita", pista: "tecla N", icono: "mas", hacer: () => apuntar({ fecha: ultimoDia }).then((r) => r && recargar()) });
    acciones.push({ nombre: "Apuntar en la lista de espera", icono: "reloj", hacer: () => import("./espera.js").then((m) => m.formularioEspera()) });
  }
  if (puede("pacientes")) acciones.push({ nombre: "Paciente nuevo", icono: "lapiz", hacer: () => import("./fichero.js").then((m) => m.formularioPaciente()).then((r) => r?.id && irA(`#/fichero/${r.id}`)) });
  acciones.push({ nombre: "Ir a hoy", pista: "tecla H", icono: "reloj", hacer: () => irA(`#/libro/${estado.hoy}`) });
  const teclas = { libro: "L", semana: "S", espera: "E", fichero: "F", avisos: "A" };
  indiceRapido({
    hoy: estado.hoy, irA, acciones,
    secciones: visibles().map((v) => ({ id: v.id, nombre: v.nombre, tecla: teclas[v.id], hash: enlaceVista(v.id) })),
  });
}

let atajosPuestos = false;
function ponerAtajos() {
  if (atajosPuestos) return;
  atajosPuestos = true;
  atajos({
    indice: abrirIndice,
    chuleta,
    apuntar: () => {
      if (!estado.yo || !puede("citas")) return;
      const boton = document.querySelector("[data-apuntar]");
      if (boton) boton.click(); else apuntar({ fecha: ultimoDia }).then((r) => r && recargar());
    },
    // El día sale de la dirección, no de la hoja pintada: aunque la hoja aún se esté cambiando, el paso es el bueno
    paso: (n) => {
      const [, id, ...resto] = location.hash.replace(/^#/, "").split("/");
      if (id === "libro" || !id) location.hash = `#/libro/${sumarDias(resto[0] || estado.hoy, n)}`;
      else if (id === "semana") location.hash = `#/semana/${resto[0]}/${sumarDias(resto[1] || estado.hoy, 7 * n)}`;
    },
    hoy: () => estado.yo && (location.hash = `#/libro/${estado.hoy}`),
    ir: (id) => {
      if (!estado.yo) return;
      const v = visibles().find((x) => x.id === id);
      if (v) location.hash = enlaceVista(v.id);
    },
  });
}
export const recargar = () => enrutar();
export const vista = () => vistaActual;

export async function refrescarBandeja() {
  try {
    const r = await api("/api/avisos?vista=bandeja");
    estado.bandeja = (r.cuentas.en_bandeja || 0) + (r.cuentas.fallido || 0);
    pintarUnero(vistaActual);
  } catch { /* no es grave */ }
}

export async function cargarMedicos() {
  estado.medicos = await api("/api/medicos");
  return estado.medicos;
}

async function arrancar() {
  aplicarTema();
  let yo;
  try {
    yo = await api("/api/yo");
  } catch (err) {
    raiz.innerHTML = `<main class="portada"><div class="portada__libro"><div class="portada__etiqueta"><h2>Sin conexión</h2><p>${esc(err.message)}</p><button class="boton boton--tinta" type="button" data-reintentar>Reintentar</button></div></div></main>`;
    raiz.querySelector("[data-reintentar]").addEventListener("click", () => location.reload());
    return;
  }
  if (yo.ahora) { estado.hoy = yo.ahora.slice(0, 10); ultimoDia = estado.hoy; }
  if (!yo.yo) {
    const { puesta_en_marcha, registro } = await api("/api/estado");
    estado.yo = null;
    // #/registro abre directamente el alta (sirve para enlazarlo desde el portafolio)
    return portada(puesta_en_marcha ? "primera" : registro && location.hash === "#/registro" ? "registro" : "entrar", registro);
  }
  estado.yo = yo.yo;
  estado.permisos = yo.permisos;
  const [aj] = await Promise.all([api("/api/ajustes"), cargarMedicos()]);
  estado.ajustes = aj;
  mesa();
  ponerAtajos();
  await enrutar();
  refrescarBandeja();
}

window.addEventListener("hashchange", enrutar);
document.addEventListener("volante:sesion", () => {
  if (!estado.yo) return;
  estado.yo = null;
  nota("Tu sesión ha terminado. Vuelve a entrar.", { error: true });
  arrancar();
});
// Cada minuto se repinta el libro para que el hilo de «ahora» y los huecos pasados se muevan solos.
setInterval(() => {
  if (!estado.yo || document.hidden || document.querySelector("dialog[open], .tarjeta-cita")) return;
  if (vistaActual === "libro" || vistaActual === "semana") libro.refrescar?.();
  refrescarBandeja();
}, 60_000);

export const hoyMasDias = (n) => sumarDias(estado.hoy, n);
arrancar();
