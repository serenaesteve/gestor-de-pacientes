// El libro de citas: hoja del día (una columna por médico) y hoja de la semana (un médico, siete días),
// con la sala de espera, mover arrastrando y la tarjeta de cada cita.
import { estado, membrete, arrancarTaco, recordarDia, puede, refrescarBandeja } from "./app.js";
import {
  api, esc, icono, nota, confirmar, ESTADOS, CANALES, hora, minutosDe, aHHMM, fechaLarga, fechaCorta, sumarDias,
  lunesDe, deIso, DIAS_CORTOS, edad, tipoAviso, cuandoRelativo, plural, avatar,
} from "./util.js";
import { apuntar, mover, manejarConflicto } from "./cita-form.js";
import { hojaDelDia, justificante } from "./imprimir.js";

let actual = null;         // { vista, fecha, medico, datos, columnas }
let recienSellada = null;  // id de la cita a la que acaba de caer un sello
let recienEscritas = new Set();   // citas recién apuntadas o movidas: se escriben a tinta delante de ti
let desfase = 0;                  // hora de la consulta menos la del navegador, para que lo vivo vaya en hora
let columnaMovil = null;

export async function mostrar(contenido, { vista, params }) {
  if (vista === "semana") {
    const medico = Number(params[0]) || estado.medicos[0]?.id;
    const fecha = params[1] || estado.hoy;
    if (!medico) return sinMedicos(contenido);
    actual = { vista, fecha: lunesDe(fecha), medico };
  } else {
    actual = { vista: "libro", fecha: params[0] || estado.hoy };
  }
  if (estado.yo.rol === "medico" && vista !== "semana" && !columnaMovil) columnaMovil = `m${estado.yo.medico_id}`;
  recordarDia(actual.vista === "semana" ? params[1] || estado.hoy : actual.fecha, actual.medico);
  actual.contenido = contenido;
  contenido.innerHTML = `<p class="cargando">Abriendo la hoja…</p>`;
  await refrescar();
}

function sinMedicos(contenido) {
  membrete({ titulo: "El libro está en blanco", subtitulo: "Libro de citas" });
  contenido.innerHTML = `<div class="vacio"><b>Todavía no hay médicos.</b>Da de alta al primero y ponle horario: entonces aparecerán sus huecos en el libro.
    ${puede("medicos") ? `<p style="margin-top:16px"><a class="boton boton--tinta" href="#/medicos">Dar de alta un médico</a></p>` : ""}</div>`;
}

export async function refrescar() {
  if (!actual) return;
  const contenido = actual.contenido;
  if (!contenido?.isConnected) return;
  const ruta = actual.vista === "semana"
    ? `/api/semana?medico=${actual.medico}&desde=${actual.fecha}`
    : `/api/libro?fecha=${actual.fecha}`;
  const datos = await api(ruta);
  if (!contenido.isConnected) return;
  estado.hoy = datos.ahora.slice(0, 10);
  desfase = momento(datos.ahora) - Date.now();
  actual.datos = datos;
  if (actual.vista === "semana") pintarSemana(contenido, datos);
  else pintarDia(contenido, datos);
}

const momento = (t) => { const [f, h] = t.split(" "); const [a, m, d] = f.split("-").map(Number); const [hh, mm, ss = 0] = h.split(":").map(Number); return new Date(a, m - 1, d, hh, mm, ss).getTime(); };
const ahoraConsulta = () => new Date(Date.now() + desfase);
const activa = (c) => c.estado === "pendiente" || c.estado === "confirmada";
const enSala = (c) => activa(c) && c.llegada && !c.entra;
const enConsulta = (c) => activa(c) && c.entra;

// ---------- hoja del día ----------
function pintarDia(contenido, datos) {
  if (!datos.columnas.length) return sinMedicos(contenido);
  const { fecha } = datos;
  const r = datos.resumen.por_estado;
  const total = Object.entries(r).filter(([k]) => k !== "anulada").reduce((s, [, n]) => s + n, 0);
  const porConfirmar = r.pendiente || 0;
  const esHoy = fecha === estado.hoy;
  membrete({
    titulo: fechaLarga(fecha, { año: deIso(fecha).getFullYear() !== deIso(estado.hoy).getFullYear() }),
    subtitulo: esHoy ? "Hoja de hoy" : fecha < estado.hoy ? "Hoja pasada" : "Hoja del libro",
    taco: { fecha, anterior: "Día anterior", siguiente: "Día siguiente", alPasar: (n) => irA(sumarDias(fecha, n)) },
    casillas: `<div class="casillas">
      <div><b>${total}</b><span class="rotulo">Citas</span></div>
      <div class="${porConfirmar ? "alerta" : ""}"><b>${porConfirmar}</b><span class="rotulo">Sin confirmar</span></div>
      ${esHoy ? `<div><b>${datos.resumen.en_sala}</b><span class="rotulo">En sala</span></div>` : ""}
      <div><b>${r.atendida || 0}</b><span class="rotulo">Atendidas</span></div>
    </div>`,
  });
  arrancarTaco();
  document.title = `${fechaCorta(fecha)} · Libro · Volante`;

  const columnas = datos.columnas.map((c) => ({
    clave: `m${c.medico.id}`, color: c.medico.color, medico_id: c.medico.id, fecha,
    titulo: c.medico.nombre, subtitulo: [c.medico.especialidad, c.medico.consulta].filter(Boolean).join(" · "),
    cabeza: `${avatar(c.medico.nombre, c.medico.color)}
      <a href="#/semana/${c.medico.id}/${fecha}" title="Ver la semana de ${esc(c.medico.nombre)}"><h2>${esc(c.medico.nombre)}</h2></a>
      <p>${esc([c.medico.especialidad, c.medico.consulta].filter(Boolean).join(" · "))}</p>`,
    franjas: c.franjas, ausencia: c.ausencia, citas: c.citas, huecos: c.huecos,
  }));
  actual.columnas = columnas;
  if (!columnas.some((c) => c.clave === columnaMovil)) {
    columnaMovil = (columnas.find((c) => c.citas.length) || columnas[0]).clave;
  }
  contenido.innerHTML = `
    ${barra(`<label class="campo" style="width:auto"><span class="sr">Ir a un día</span><input type="date" value="${fecha}" data-ir></label>
      ${!esHoy ? `<button class="boton" type="button" data-hoy>Volver a hoy</button>` : ""}`)}
    ${esHoy ? sala(datos.columnas) : ""}
    <div class="tampones" role="group" aria-label="Médico que se ve">
      ${columnas.map((c) => `<button type="button" data-ver="${c.clave}" aria-pressed="${c.clave === columnaMovil}">
        <span class="tampon" style="--c:var(--t-${esc(c.color)})"></span>${esc(c.titulo.replace(/^Dra?\.\s*/, ""))}
        <span class="mono" style="color:var(--tinta-3)">${c.citas.filter((x) => x.estado !== "anulada").length}</span></button>`).join("")}
    </div>
    ${rejilla(columnas, datos.ahora)}`;
  conectar(contenido);
  desplazarAAhora(contenido, fecha);
}

// La sala de espera: quién ha llegado, desde cuándo, y quién está dentro.
function sala(columnas) {
  const ahora = minutosDe(hora(actual.datos.ahora));
  const yo = estado.yo;
  const filas = [];
  for (const col of columnas) {
    if (yo.rol === "medico" && col.medico.id !== yo.medico_id) continue;
    for (const c of col.citas) {
      if (enSala(c) || enConsulta(c)) filas.push({ c, m: col.medico });
    }
  }
  if (!filas.length) return "";
  filas.sort((a, b) => (a.c.entra ? 1 : 0) - (b.c.entra ? 1 : 0) || a.c.llegada.localeCompare(b.c.llegada));
  return `<section class="sala" aria-label="Sala de espera">
    <h2 class="rotulo">Sala de espera</h2>
    <ol>${filas.map(({ c, m }) => {
      const espera = Math.max(0, ahora - minutosDe(hora(c.llegada)));
      const tarde = !c.entra && espera >= 20;
      return `<li class="${c.entra ? "dentro" : ""}">
        <span class="tampon" style="--c:var(--t-${esc(m.color)})"></span>
        <button type="button" class="sala__quien" data-cita="${c.id}"><b>${esc(c.apellidos)}, ${esc(c.nombre)}</b>
          <small>${hora(c.empieza)} · ${esc(m.nombre)}</small></button>
        <span class="mono sala__tiempo ${tarde ? "sala__tiempo--tarde" : ""}" ${c.entra ? "" : `data-llegada="${esc(c.llegada)}"`}>${c.entra ? `dentro desde ${hora(c.entra)}` : `llegó ${hora(c.llegada)} · <b>${espera}′</b>`}</span>
        ${c.entra ? `<button class="boton boton--chico" type="button" data-rapido="atendida" data-id="${c.id}">Atendido</button>`
          : `<button class="boton boton--tinta boton--chico" type="button" data-rapido="pasa" data-id="${c.id}">Pasar</button>`}
      </li>`;
    }).join("")}</ol>
  </section>`;
}

// ---------- hoja de la semana ----------
function pintarSemana(contenido, datos) {
  const m = datos.medico;
  const lunes = datos.lunes;
  const domingo = sumarDias(lunes, 6);
  const total = datos.dias.reduce((s, d) => s + d.citas.filter((c) => c.estado !== "anulada").length, 0);
  const libres = datos.dias.reduce((s, d) => s + d.huecos.length, 0);
  membrete({
    titulo: m.nombre,
    subtitulo: `Semana del ${deIso(lunes).getDate()} al ${fechaCorta(domingo).replace(/^\S+ /, "")}`,
    taco: { fecha: lunes, anterior: "Semana anterior", siguiente: "Semana siguiente", alPasar: (n) => irA(sumarDias(lunes, 7 * n)) },
    casillas: `<div class="casillas"><div><b>${total}</b><span class="rotulo">Citas</span></div><div><b>${libres}</b><span class="rotulo">Huecos libres</span></div></div>`,
  });
  arrancarTaco();
  document.title = `${m.nombre} · Semana · Volante`;
  const columnas = datos.dias
    .filter((d, i) => i < 5 || d.franjas.length || d.citas.length)   // sábado y domingo solo si se trabaja
    .map((d) => ({
      clave: d.fecha, color: m.color, medico_id: m.id, fecha: d.fecha,
      titulo: fechaLarga(d.fecha), subtitulo: m.nombre,
      cabeza: `<span class="tampon" style="--c:${d.fecha === estado.hoy ? "var(--margen)" : "transparent"}"></span>
        <a href="#/libro/${d.fecha}" title="Abrir la hoja de este día"><h2>${esc(DIAS_CORTOS[(deIso(d.fecha).getDay() + 6) % 7])} ${deIso(d.fecha).getDate()}</h2></a>
        <p>${d.ausencia ? esc(d.ausencia.motivo || "No pasa consulta") : d.franjas.length ? `${plural(d.citas.filter((c) => c.estado !== "anulada").length, "cita", "citas")} · ${d.huecos.length} libres` : "Sin consulta"}</p>`,
      franjas: d.franjas, ausencia: d.ausencia, citas: d.citas, huecos: d.huecos,
    }));
  actual.columnas = columnas;
  if (!columnas.some((c) => c.clave === columnaMovil)) {
    columnaMovil = (columnas.find((c) => c.fecha === estado.hoy) || columnas.find((c) => c.citas.length) || columnas[0]).clave;
  }
  contenido.innerHTML = `
    ${barra(`<label class="campo" style="width:auto"><span class="sr">Médico</span>
      <select data-medico>${estado.medicos.map((x) => `<option value="${x.id}" ${x.id === m.id ? "selected" : ""}>${esc(x.nombre)}</option>`).join("")}</select></label>
      ${lunes !== lunesDe(estado.hoy) ? `<button class="boton" type="button" data-hoy>Esta semana</button>` : ""}`)}
    <div class="tampones" role="group" aria-label="Día que se ve">
      ${columnas.map((c) => `<button type="button" data-ver="${c.clave}" aria-pressed="${c.clave === columnaMovil}">${esc(fechaCorta(c.fecha))}
        <span class="mono" style="color:var(--tinta-3)">${c.citas.filter((x) => x.estado !== "anulada").length}</span></button>`).join("")}
    </div>
    ${rejilla(columnas, datos.ahora)}`;
  conectar(contenido);
  contenido.querySelector("[data-medico]").addEventListener("change", (e) => { location.hash = `#/semana/${e.target.value}/${lunes}`; });
  desplazarAAhora(contenido, estado.hoy);
}

function irA(fecha) {
  location.hash = actual.vista === "semana" ? `#/semana/${actual.medico}/${fecha}` : `#/libro/${fecha}`;
}

function barra(extra) {
  return `<div class="barra">
    ${puede("citas") ? `<button class="boton boton--tinta" type="button" data-apuntar>${icono("mas", 16)} Apuntar cita</button>` : ""}
    ${extra}
    <span class="barra__hueco"></span>
    ${puede("citas") ? `<span class="barra__pista">Arrastra una cita a un hueco para moverla</span>` : ""}
    <button class="boton boton--plano" type="button" data-imprimir>${icono("imprimir", 16)} Imprimir la hoja</button>
  </div>`;
}

// ---------- la rejilla pautada ----------
function rango(columnas) {
  let ini = Infinity, fin = -Infinity;
  for (const c of columnas) {
    for (const f of c.franjas) { ini = Math.min(ini, minutosDe(f.desde)); fin = Math.max(fin, minutosDe(f.hasta)); }
    for (const x of c.citas) { ini = Math.min(ini, minutosDe(hora(x.empieza))); fin = Math.max(fin, minutosDe(hora(x.termina))); }
  }
  if (ini === Infinity) { ini = 9 * 60; fin = 14 * 60; }
  return [Math.floor(ini / 60) * 60, Math.ceil(fin / 60) * 60];
}

function rejilla(columnas, ahora) {
  const [ini, fin] = rango(columnas);
  const AIRE = 12;   // minutos de papel en blanco arriba y abajo, para que la primera hora no quede bajo la cabecera
  const alto = `calc(var(--px-min) * ${fin - ini + 2 * AIRE})`;
  const y = (min) => `calc(var(--px-min) * ${min - ini + AIRE})`;
  const marcas = [];
  for (let t = ini; t <= fin; t += 30) {
    marcas.push(`<span class="${t % 60 ? "cuarto" : ""}" style="top:${y(t)}">${aHHMM(t)}</span>`);
  }
  const ahoraMin = minutosDe(hora(ahora));
  const cols = columnas.map((c) => {
    const franjas = c.franjas.map((f) => {
      const a = minutosDe(f.desde), b = minutosDe(f.hasta);
      return `<div class="franja" style="top:${y(a)};height:calc(var(--px-min) * ${b - a});--fase:calc(var(--px-min) * ${(60 - (a % 60)) % 60})"></div>`;
    }).join("");
    const ausencia = c.ausencia ? `<div class="ausente"><span class="sello sello--grande sello--anulada" style="--giro:-8deg">${esc(c.ausencia.motivo || "No pasa consulta")}</span></div>` : "";
    const huecos = c.ausencia || !puede("citas") ? "" : c.huecos.map((h) => {
      const a = minutosDe(h.hora);
      return `<button type="button" class="hueco" style="top:${y(a)};height:calc(var(--px-min) * ${h.minutos})"
        data-hueco="${h.hora}" data-minutos="${h.minutos}" data-medico="${c.medico_id}" data-fecha="${c.fecha}"
        aria-label="Apuntar cita a las ${h.hora}">${h.hora}</button>`;
    }).join("");
    const citas = c.citas
      .slice().sort((a, b) => (a.estado === "anulada") - (b.estado === "anulada"))
      .map((x) => anotacion(x, c.color, y, ahora)).join("");
    const linea = c.fecha === ahora.slice(0, 10) && ahoraMin >= ini && ahoraMin <= fin ? `<div class="ahora" style="top:${y(ahoraMin)}" aria-hidden="true"></div>` : "";
    return `<div class="columna" data-col="${c.clave}" ${c.clave === columnaMovil ? "data-visible" : ""} style="height:${alto}">${franjas}${ausencia}${huecos}${citas}${linea}</div>`;
  }).join("");
  const cabezas = columnas.map((c) => `<div class="libro__cabeza" data-col="${c.clave}" ${c.clave === columnaMovil ? "data-visible" : ""}>${c.cabeza}</div>`).join("");
  return `
    <div class="libro" data-movil data-ini="${ini}" data-fin="${fin}" data-aire="${AIRE}" style="--columnas:${columnas.length}">
      <div class="libro__rejilla">
        <div class="libro__cabeza libro__cabeza--margen" aria-hidden="true"></div>${cabezas}
        <div class="libro__margen" style="height:${alto}" aria-hidden="true">${marcas.join("")}</div>${cols}
      </div>
    </div>`;
}

const CORTOS = { confirmada: "Conf.", atendida: "Atend.", no_acudio: "Faltó", en_sala: "Sala", en_consulta: "Dentro" };
const LARGOS = { ...ESTADOS, en_sala: "En sala", en_consulta: "En consulta" };

function anotacion(c, color, y, ahora) {
  const a = minutosDe(hora(c.empieza));
  const largo = Math.max(c.minutos, 12);
  const marca = enConsulta(c) ? "en_consulta" : enSala(c) ? "en_sala" : c.estado !== "pendiente" && c.estado !== "anulada" ? c.estado : null;
  const sello = marca ? `<span class="sello sello--${marca}${c.id === recienSellada ? " sello--cae" : ""}" style="--giro:${giro(c.id)}deg"><span class="sello__largo">${esc(LARGOS[marca])}</span><span class="sello__corto" aria-hidden="true">${CORTOS[marca]}</span></span>` : "";
  const enBandeja = c.avisos.some((r) => r.estado === "en_bandeja" || r.estado === "fallido");
  const pendientes = c.avisos.some((r) => r.estado === "pendiente");
  const iconoAviso = activa(c)
    ? enBandeja ? `<span class="icono-aviso icono-aviso--bandeja" title="Tiene un aviso por mandar a mano">${icono("bandeja", 14)}</span>`
      : pendientes ? `<span class="icono-aviso" title="Recordatorio programado">${icono("campana", 14)}</span>` : ""
    : "";
  // Se arrastra lo que aún se puede mover: en pie, por llegar y sin paciente en la sala.
  const movible = puede("citas") && activa(c) && !c.llegada && c.empieza > ahora;
  return `<button type="button" class="anotacion anotacion--${c.estado}${sello ? " anotacion--sellada" : ""}${movible ? " anotacion--movible" : ""}${recienEscritas.has(c.id) ? " anotacion--escrita" : ""}" data-cita="${c.id}"
      ${movible ? 'draggable="true"' : ""}
      style="top:${y(a)};height:calc(var(--px-min) * ${largo} - 2px);--c:var(--t-${esc(color)})"
      aria-label="${esc(`${hora(c.empieza)}, ${c.apellidos}, ${c.nombre}. ${marca ? LARGOS[marca] : "Sin confirmar"}`)}">
    <span class="anotacion__linea"><span class="hora">${hora(c.empieza)}</span><b>${esc(c.apellidos)}, ${esc(c.nombre)}</b>${c.serie_total ? `<span class="anotacion__serie" title="Cita ${c.serie_n} de ${c.serie_total} de una serie">${c.serie_n}/${c.serie_total}</span>` : ""}${sello ? "" : iconoAviso}${c.estado === "anulada" ? '<span class="sr">(anulada)</span>' : ""}</span>
    ${c.minutos >= 25 && c.motivo ? `<span class="anotacion__motivo">${esc(c.motivo)}</span>` : ""}
    ${sello}
  </button>`;
}

// Cada sello cae con su propio ángulo, siempre el mismo para la misma cita.
const giro = (id) => ((id * 37) % 9) - 7;

let desplazado = false;
function desplazarAAhora(contenido, fecha) {
  // Si hay gente en la sala de espera, la hoja se queda arriba: lo primero es verla.
  if (fecha !== estado.hoy || desplazado || contenido.querySelector(".sala")) return;
  const linea = contenido.querySelector(".columna[data-visible] .ahora") || contenido.querySelector(".ahora");
  if (linea) {
    desplazado = true;
    const top = linea.getBoundingClientRect().top + scrollY - innerHeight / 3;
    if (top > 200) scrollTo({ top, behavior: "instant" });
  }
}

function conectar(contenido) {
  contenido.querySelector("[data-apuntar]")?.addEventListener("click", () => apuntar({
    medico_id: actual.medico || (columnaMovil?.startsWith("m") ? Number(columnaMovil.slice(1)) : undefined),
    fecha: actual.vista === "semana" ? (columnaMovil && /^\d{4}/.test(columnaMovil) ? columnaMovil : estado.hoy) : actual.fecha,
  }).then(tras));
  contenido.querySelector("[data-hoy]")?.addEventListener("click", () => irA(estado.hoy));
  contenido.querySelector("[data-ir]")?.addEventListener("change", (e) => e.target.value && irA(e.target.value));
  contenido.querySelector("[data-imprimir]")?.addEventListener("click", () => {
    const titulo = actual.vista === "semana"
      ? `${actual.datos.medico.nombre}, semana del ${fechaCorta(actual.datos.lunes)}`
      : fechaLarga(actual.fecha, { año: true });
    hojaDelDia(actual.columnas, titulo);
  });
  contenido.querySelectorAll("[data-ver]").forEach((b) => b.addEventListener("click", () => {
    columnaMovil = b.dataset.ver;
    contenido.querySelectorAll("[data-ver]").forEach((x) => x.setAttribute("aria-pressed", x === b));
    contenido.querySelectorAll("[data-col]").forEach((col) => col.toggleAttribute("data-visible", col.dataset.col === columnaMovil));
  }));
  contenido.querySelector(".sala")?.addEventListener("click", async (e) => {
    const quien = e.target.closest("[data-cita]");
    if (quien) return abrirTarjeta(Number(quien.dataset.cita), document.querySelector(`.anotacion[data-cita="${quien.dataset.cita}"]`));
    const b = e.target.closest("[data-rapido]");
    if (!b) return;
    b.disabled = true;
    try {
      if (b.dataset.rapido === "pasa") await api(`/api/citas/${b.dataset.id}/sala`, { metodo: "POST", datos: { accion: "pasa" } });
      else await api(`/api/citas/${b.dataset.id}/estado`, { metodo: "POST", datos: { estado: "atendida" } });
      recienSellada = Number(b.dataset.id);
      await refrescar();
      recienSellada = null;
    } catch (err) { nota(err.message, { error: true }); b.disabled = false; }
  });
  const libro = contenido.querySelector(".libro");
  deslizar(libro);
  vistazo(libro);
  vivo(contenido);
  libro.addEventListener("click", (e) => {
    const hueco = e.target.closest("[data-hueco]");
    if (hueco) {
      apuntar({ medico_id: Number(hueco.dataset.medico), fecha: hueco.dataset.fecha, hora: hueco.dataset.hueco, minutos: Number(hueco.dataset.minutos) }).then(tras);
      return;
    }
    const a = e.target.closest("[data-cita]");
    if (a) abrirTarjeta(Number(a.dataset.cita), a);
  });
  arrastrar(libro);
}

// ---------- mover arrastrando ----------
// Se coge la anotación y se suelta en un hueco libre, de cualquier columna: en la hoja del día cambia
// también de médico; en la semana, de día. Los huecos se iluminan mientras se arrastra.
function arrastrar(libro) {
  let cogida = null;
  libro.addEventListener("dragstart", (e) => {
    const a = e.target.closest(".anotacion--movible");
    if (!a) return;
    cogida = buscarCita(Number(a.dataset.cita));
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", a.dataset.cita);
    // Lo que se arrastra es el renglón recortado, levantado y algo torcido, como un papel cogido con dos dedos
    const papel = a.cloneNode(true);
    papel.classList.add("anotacion--papel");
    papel.style.width = `${a.offsetWidth}px`;
    papel.style.height = `${a.offsetHeight}px`;
    papel.style.setProperty("--c", a.style.getPropertyValue("--c"));
    document.body.append(papel);
    const caja = a.getBoundingClientRect();
    e.dataTransfer.setDragImage(papel, e.clientX - caja.left, e.clientY - caja.top);
    setTimeout(() => papel.remove(), 0);
    document.querySelector(".vistazo")?.remove();
    document.querySelector(".tarjeta-cita")?.remove();
    requestAnimationFrame(() => { libro.classList.add("libro--arrastrando"); a.classList.add("anotacion--cogida"); });
  });
  libro.addEventListener("dragend", () => {
    libro.classList.remove("libro--arrastrando");
    libro.querySelectorAll(".anotacion--cogida, .hueco--encima").forEach((x) => x.classList.remove("anotacion--cogida", "hueco--encima"));
    cogida = null;
  });
  libro.addEventListener("dragover", (e) => {
    const h = e.target.closest(".hueco");
    if (!cogida || !h) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    libro.querySelectorAll(".hueco--encima").forEach((x) => x !== h && x.classList.remove("hueco--encima"));
    h.classList.add("hueco--encima");
  });
  libro.addEventListener("dragleave", (e) => e.target.closest?.(".hueco")?.classList.remove("hueco--encima"));
  libro.addEventListener("drop", async (e) => {
    const h = e.target.closest(".hueco");
    if (!cogida || !h) return;
    e.preventDefault();
    const c = cogida;
    const datos = { fecha: h.dataset.fecha, hora: h.dataset.hueco, medico_id: Number(h.dataset.medico) };
    const otroMedico = datos.medico_id !== c.medico_id;
    try {
      await manejarConflicto((forzar) => api(`/api/citas/${c.id}`, { metodo: "PUT", datos: { ...datos, forzar } }));
    } catch (err) {
      if (err) nota(err.message, { error: true });
      return;
    }
    const m = estado.medicos.find((x) => x.id === datos.medico_id);
    nota(`${c.nombre} ${c.apellidos}: ${hora(c.empieza)} → ${datos.hora}${otroMedico ? ` con ${m?.nombre}` : ""}${datos.fecha !== c.empieza.slice(0, 10) ? `, ${fechaCorta(datos.fecha)}` : ""}. Se le avisará.`, {
      accion: "Deshacer", segundos: 8,
      alPulsar: async () => {
        try { await api(`/api/citas/${c.id}`, { metodo: "PUT", datos: { fecha: c.empieza.slice(0, 10), hora: hora(c.empieza), medico_id: c.medico_id, forzar: true } }); }
        catch (err) { return nota(err.message, { error: true }); }
        refrescar();
      },
    });
    recienEscritas = new Set([c.id]);
    await refrescar();
    recienEscritas = new Set();
    refrescarBandeja();
  });
}

async function tras(resultado) {
  if (!resultado) return;
  recienEscritas = new Set(resultado.ids || [resultado.id]);
  await refrescar();
  recienEscritas = new Set();
  refrescarBandeja();
  if (resultado.id) {
    const el = document.querySelector(`[data-cita="${resultado.id}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

// ---------- la tarjeta de cita ----------
function buscarCita(id) {
  const d = actual.datos;
  const listas = actual.vista === "semana" ? d.dias.map((x) => x.citas) : d.columnas.map((x) => x.citas);
  for (const l of listas) { const c = l.find((x) => x.id === id); if (c) return c; }
  return null;
}
function medicoDe(id) { return estado.medicos.find((m) => m.id === id) || {}; }

function abrirTarjeta(id, origen) {
  document.querySelector(".tarjeta-cita")?.remove();
  document.querySelectorAll('.anotacion[aria-pressed="true"]').forEach((x) => x.setAttribute("aria-pressed", "false"));
  const c = buscarCita(id);
  if (!c) return;
  origen?.setAttribute("aria-pressed", "true");
  const m = medicoDe(c.medico_id);
  const ahora = actual.datos.ahora;
  const empezada = c.empieza <= ahora;
  const vive = activa(c);
  const deHoy = c.empieza.slice(0, 10) === ahora.slice(0, 10);
  const yo = estado.yo;
  const suya = yo.rol === "medico" && yo.medico_id === c.medico_id;
  const ajena = yo.rol === "medico" && !suya;
  const anos = edad(c.nacimiento, estado.hoy);
  const avisos = c.avisos.length
    ? `<ul class="linea-avisos">${c.avisos.map((r) => `<li class="${r.estado}"><span>${esc(tipoAviso(r.tipo))} · ${esc(CANALES[r.canal])}</span>
        <span class="mono">${r.estado === "pendiente" ? esc(cuandoRelativo(r.programado, ahora)) : esc(etiquetaAviso(r.estado))}</span></li>`).join("")}</ul>`
    : `<p class="vacio" style="padding:8px 0">${c.canal === "ninguno" ? "Ha pedido no recibir avisos." : vive && !empezada ? `Sin recordatorios: falta el ${c.canal === "correo" ? "correo" : "teléfono"} en su ficha.` : "No se le mandó ningún aviso."}</p>`;
  const marca = enConsulta(c) ? "en_consulta" : enSala(c) ? "en_sala" : c.estado !== "pendiente" ? c.estado : null;

  // Lo que toca hacer ahora va primero y en tinta: llegar → pasar → atendido.
  const acciones = [];
  if (vive && deHoy && !c.llegada && puede("citas")) acciones.push(`<button class="boton boton--tinta" data-sala="llega">Ha llegado</button>`);
  if (enSala(c)) acciones.push(`<button class="boton boton--tinta" data-sala="pasa" ${ajena ? "disabled" : ""}>Pasar a consulta</button>`);
  if (vive && (empezada || c.llegada)) {
    acciones.push(`<button class="boton ${enConsulta(c) ? "boton--tinta" : ""}" data-estado="atendida" ${ajena ? "disabled" : ""}>Atendido</button>`);
    if (!c.entra) acciones.push(`<button class="boton" data-estado="no_acudio" ${ajena ? "disabled" : ""}>No acudió</button>`);
  }
  if (vive && !empezada && !c.llegada && c.estado === "pendiente") acciones.push(`<button class="boton" data-estado="confirmada">Confirmar</button>`);
  if (vive && !empezada && !c.llegada) acciones.push(`<button class="boton" data-mover>Mover</button>`);
  if (c.estado === "atendida" || c.llegada) acciones.push(`<button class="boton boton--chico" data-justificante>${icono("imprimir", 14)} Justificante</button>`);
  const menores = [];
  if (c.llegada && vive) menores.push(`<button class="boton boton--plano boton--chico" data-sala="deshacer">Quitar la llegada</button>`);
  if (c.estado === "atendida" || c.estado === "no_acudio") menores.push(`<button class="boton boton--plano boton--chico" data-estado="pendiente">Quitar el sello</button>`);
  if (c.estado === "anulada" && !empezada) menores.push(`<button class="boton boton--plano boton--chico" data-estado="pendiente">Volver a darla</button>`);

  const t = document.createElement("aside");
  t.className = "tarjeta-cita";
  t.setAttribute("aria-label", "Cita");
  t.innerHTML = `
    <button class="tarjeta-cita__cerrar" type="button" aria-label="Cerrar la tarjeta">${icono("cerrar")}</button>
    <span class="rotulo">Tarjeta de cita · nº ${c.id}${c.serie_total ? ` · serie ${c.serie_n} de ${c.serie_total}` : ""}</span>
    <h2><a href="#/fichero/${c.paciente_id}">${esc(c.apellidos)}, ${esc(c.nombre)}</a></h2>
    ${marca ? `<span class="tarjeta-cita__sello sello sello--grande sello--${marca}">${esc(LARGOS[marca])}</span>` : ""}
    <div class="tarjeta-cita__cuando"><span class="hora">${hora(c.empieza)}–${hora(c.termina)}</span><span>${esc(fechaLarga(c.empieza))}</span></div>
    <dl class="tarjeta-cita__datos">
      <dt>Médico</dt><dd>${esc(m.nombre || "")}${m.consulta ? ` · ${esc(m.consulta)}` : ""}</dd>
      <dt>Motivo</dt><dd>${esc(c.motivo || "—")}</dd>
      <dt>Teléfono</dt><dd>${c.telefono ? `<a href="tel:${esc(c.telefono.replace(/\s/g, ""))}">${esc(c.telefono)}</a>` : "—"}</dd>
      ${anos !== null ? `<dt>Edad</dt><dd>${anos} años</dd>` : ""}
      <dt>Avisos por</dt><dd>${esc(CANALES[c.canal])}</dd>
      ${c.llegada ? `<dt>Sala</dt><dd>llegó a las ${hora(c.llegada)}${c.entra ? `, pasó a las ${hora(c.entra)}` : ""}</dd>` : ""}
      ${c.estado === "anulada" ? `<dt>Anulada</dt><dd>${c.anulada_por === "paciente" ? "por el paciente, desde su enlace" : "en recepción"}</dd>` : ""}
      ${c.estado === "confirmada" && c.confirmada_en && !c.llegada ? `<dt>Confirmó</dt><dd>${esc(cuandoRelativo(c.confirmada_en, ahora))}</dd>` : ""}
      ${c.origen === "paciente" ? `<dt>La pidió</dt><dd>el paciente, desde su enlace</dd>` : c.origen === "espera" ? `<dt>Vino de</dt><dd>la lista de espera</dd>` : ""}
    </dl>
    ${c.notas_paciente ? `<p class="nota-paciente">${esc(c.notas_paciente)}</p>` : ""}
    <div class="acciones">${acciones.join("")}</div>
    ${menores.length ? `<div class="acciones" style="margin-top:4px">${menores.join("")}</div>` : ""}
    ${suya && (c.estado === "atendida" || empezada || c.entra) ? `
      <form class="campo" data-nota style="margin-top:16px"><span>Nota clínica (solo la ven médicos y dirección)</span>
        <textarea name="nota" maxlength="4000" rows="3">${esc(c.nota || "")}</textarea>
        <div class="acciones" style="margin-top:8px"><button class="boton boton--chico" type="submit">Guardar la nota</button></div></form>` :
      c.nota ? `<p style="margin-top:12px;font-size:var(--t-s)"><span class="rotulo">Nota clínica</span><br>${esc(c.nota)}</p>` : ""}
    <div class="seccion" style="margin-top:20px"><h3>Recordatorios
      ${vive && !empezada && c.canal !== "ninguno" && !c.llegada ? `<button class="boton boton--plano boton--chico" data-recordar>${icono("campana", 14)} Avisar ahora</button>` : ""}</h3>${avisos}</div>
    ${vive && !empezada && !c.llegada ? `<div class="acciones acciones--pie"><button class="boton boton--plano boton--chico" data-anular style="color:var(--peligro)">Anular la cita</button></div>` : ""}`;
  document.body.append(t);
  const cerrar = () => {
    t.remove();
    origen?.setAttribute("aria-pressed", "false");
    document.removeEventListener("keydown", tecla);
    origen?.focus({ preventScroll: true });
  };
  const tecla = (e) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) cerrar(); };
  document.addEventListener("keydown", tecla);
  t.querySelector(".tarjeta-cita__cerrar").addEventListener("click", cerrar);
  t.querySelector(".tarjeta-cita__cerrar").focus();

  const despues = async (sellada) => {
    recienSellada = sellada ? c.id : null;
    cerrar();
    await refrescar();
    refrescarBandeja();
    recienSellada = null;
  };
  const cambiar = async (nuevo, extra = {}) => {
    const antes = c.estado;
    let r;
    try {
      r = await api(`/api/citas/${c.id}/estado`, { metodo: "POST", datos: { estado: nuevo, ...extra } });
    } catch (err) { nota(err.message, { error: true }); return; }
    await despues(["confirmada", "atendida", "no_acudio", "anulada"].includes(nuevo));
    if (nuevo === "anulada") {
      const ofrecida = r.ofertas?.[0];
      nota(r.anuladas > 1 ? `${r.anuladas} citas de la serie anuladas.`
        : ofrecida ? `Cita anulada. El hueco se ha ofrecido a ${ofrecida.paciente}, de la lista de espera, hasta las ${hora(ofrecida.caduca_en)}.`
          : `Cita de las ${hora(c.empieza)} anulada. El hueco vuelve a estar libre.`, {
        accion: r.anuladas > 1 ? undefined : "Deshacer", segundos: 9,
        alPulsar: async () => {
          try { await api(`/api/citas/${c.id}/estado`, { metodo: "POST", datos: { estado: antes, deshacer: true } }); } catch (err) { return nota(err.message, { error: true }); }
          refrescar();
        },
      });
    }
  };
  t.querySelectorAll("[data-estado]").forEach((b) => b.addEventListener("click", () => cambiar(b.dataset.estado)));
  t.querySelectorAll("[data-sala]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try { await api(`/api/citas/${c.id}/sala`, { metodo: "POST", datos: { accion: b.dataset.sala } }); }
    catch (err) { nota(err.message, { error: true }); b.disabled = false; return; }
    if (b.dataset.sala === "llega") nota(`${c.nombre} ${c.apellidos} está en la sala de espera.`);
    despues(b.dataset.sala !== "deshacer");
  }));
  t.querySelector("[data-justificante]")?.addEventListener("click", async () => {
    try { justificante(await api(`/api/citas/${c.id}/justificante`)); } catch (err) { nota(err.message, { error: true }); }
  });
  t.querySelector("[data-anular]")?.addEventListener("click", async () => {
    const siguientes = c.serie_total ? c.serie_total - c.serie_n : 0;
    const r = await confirmar("¿Anular la cita?",
      `${c.nombre} ${c.apellidos}, ${fechaLarga(c.empieza)} a las ${hora(c.empieza)}. Los recordatorios que faltaban ya no saldrán y el hueco se ofrecerá a la lista de espera.`,
      { boton: "Anular esta cita", peligro: true, extra: siguientes ? { valor: "serie", texto: `Anular esta y las ${siguientes} siguientes de la serie` } : null });
    if (r === "serie") cambiar("anulada", { serie: true });
    else if (r) cambiar("anulada");
  });
  t.querySelector("[data-mover]")?.addEventListener("click", () => { cerrar(); mover(c).then(tras); });
  t.querySelector("[data-recordar]")?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      await api(`/api/citas/${c.id}/recordar`, { metodo: "POST" });
      nota(estado.ajustes.correo_configurado && c.canal === "correo" ? "Recordatorio enviado." : "Recordatorio preparado: está en la bandeja de Avisos para mandarlo.");
      await despues(false);
    } catch (err) { nota(err.message, { error: true }); e.currentTarget.disabled = false; }
  });
  t.querySelector("[data-nota]")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/api/citas/${c.id}/estado`, { metodo: "POST", datos: { estado: c.estado, nota: e.target.nota.value } });
      nota("Nota guardada.");
      c.nota = e.target.nota.value;
    } catch (err) { nota(err.message, { error: true }); }
  });
}

export function etiquetaAviso(e) {
  return { enviado: "enviado", en_bandeja: "por mandar a mano", fallido: "falló", anulado: "anulado", omitido: "no tocaba", pendiente: "programado" }[e] || e;
}

// ---------- en el móvil, deslizar la hoja cambia de día (o de semana) ----------
function deslizar(libro) {
  let x0 = null, y0 = 0, t0 = 0;
  libro.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "touch") return;
    x0 = e.clientX; y0 = e.clientY; t0 = performance.now();
  });
  libro.addEventListener("pointerup", (e) => {
    if (x0 === null || e.pointerType !== "touch") return;
    const dx = e.clientX - x0, dy = e.clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 70 && Math.abs(dy) < 45 && performance.now() - t0 < 600) {
      const paso = dx < 0 ? 1 : -1;
      irA(sumarDias(actual.fecha, paso * (actual.vista === "semana" ? 7 : 1)));
    }
  });
  libro.addEventListener("pointercancel", () => { x0 = null; });
}

// ---------- vistazo: al dejar el ratón sobre una cita, sus datos sin abrirla ----------
function vistazo(libro) {
  if (!matchMedia("(hover: hover)").matches) return;
  let temporizador = null, sobre = null;
  const quitar = () => { clearTimeout(temporizador); document.querySelector(".vistazo")?.remove(); sobre = null; };
  libro.addEventListener("pointerover", (e) => {
    const a = e.target.closest(".anotacion");
    if (!a || a === sobre) return;
    quitar();
    sobre = a;
    temporizador = setTimeout(() => {
      if (!a.isConnected || document.querySelector(".tarjeta-cita, dialog[open], .libro--arrastrando")) return;
      const c = buscarCita(Number(a.dataset.cita));
      if (!c) return;
      const anos = edad(c.nacimiento, estado.hoy);
      const proximo = c.avisos.find((r) => r.estado === "pendiente");
      const porMandar = c.avisos.filter((r) => r.estado === "en_bandeja" || r.estado === "fallido").length;
      const v = document.createElement("div");
      v.className = "vistazo";
      v.setAttribute("role", "tooltip");
      v.innerHTML = `
        <b>${esc(c.nombre)} ${esc(c.apellidos)}</b>
        <span class="mono">${hora(c.empieza)}–${hora(c.termina)}${anos !== null ? ` · ${anos} años` : ""}</span>
        ${c.motivo ? `<span>${esc(c.motivo)}</span>` : ""}
        ${c.telefono ? `<span class="mono">${esc(c.telefono)}</span>` : ""}
        ${c.notas_paciente ? `<span class="vistazo__nota">${esc(c.notas_paciente)}</span>` : ""}
        <span class="vistazo__avisos">${porMandar ? `${porMandar} aviso por mandar a mano` : proximo ? `Próximo aviso: ${esc(cuandoRelativo(proximo.programado, actual.datos.ahora))}` : c.estado === "anulada" ? "Anulada" : "Sin avisos pendientes"}</span>
        <small>Pulsa para abrir la tarjeta${a.classList.contains("anotacion--movible") ? " · arrástrala para moverla" : ""}</small>`;
      document.body.append(v);
      const r = a.getBoundingClientRect();
      const ancho = v.offsetWidth, alto = v.offsetHeight;
      const derecha = r.right + 10 + ancho < innerWidth;
      v.style.left = `${derecha ? r.right + 10 : Math.max(8, r.left - ancho - 10)}px`;
      v.style.top = `${Math.min(innerHeight - alto - 8, Math.max(8, r.top))}px`;
    }, 380);
  });
  libro.addEventListener("pointerout", (e) => {
    if (sobre && !sobre.contains(e.relatedTarget)) quitar();
  });
  libro.addEventListener("pointerdown", quitar);
  addEventListener("scroll", quitar, { passive: true, once: true });
}

// ---------- lo vivo: el hilo de «ahora» baja y los minutos de la sala corren, sin recargar ----------
let latido = null;
function vivo(contenido) {
  clearInterval(latido);
  const tic = () => {
    if (!contenido.isConnected) { clearInterval(latido); return; }
    const ahora = ahoraConsulta();
    const minutos = ahora.getHours() * 60 + ahora.getMinutes() + ahora.getSeconds() / 60;
    const libro = contenido.querySelector(".libro");
    if (libro) {
      const ini = Number(libro.dataset.ini), fin = Number(libro.dataset.fin), aire = Number(libro.dataset.aire);
      contenido.querySelectorAll(".ahora").forEach((l) => {
        l.hidden = minutos < ini || minutos > fin;
        l.style.top = `calc(var(--px-min) * ${(minutos - ini + aire).toFixed(2)})`;
      });
    }
    contenido.querySelectorAll("[data-llegada]").forEach((el) => {
      const espera = Math.max(0, Math.floor((ahora.getTime() - momento(el.dataset.llegada)) / 60000));
      el.innerHTML = `llegó ${el.dataset.llegada.slice(11, 16)} · <b>${espera}′</b>`;
      el.classList.toggle("sala__tiempo--tarde", espera >= 20);
    });
  };
  latido = setInterval(tic, 15000);
}
