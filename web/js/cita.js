// Páginas del paciente, sin cuenta y con enlace firmado:
//   /c/…  su cita: confirmar, anular, calendario y pedir otra
//   /o/…  un hueco de la lista de espera: quedárselo o dejarlo pasar
//   /v/…  comprobar un justificante de asistencia
import { esc, fechaLarga, fechaCorta, hora, DIAS_CORTOS, deIso, iso } from "./util.js";

const raiz = document.getElementById("cita");
// /c/123/firma (centro 1) o /c/2/123/firma (otro centro): la ruta se reenvía tal cual a la API.
const ruta = location.pathname.replace(/\/+$/, "");
const tipo = ruta.split("/")[1];
const base = `/api${ruta}`;
const SELLOS = { confirmada: "Confirmada", anulada: "Anulada", atendida: "Atendido", no_acudio: "No acudió" };

async function pedir(ruta, metodo = "GET", datos) {
  const r = await fetch(ruta, { method: metodo, headers: { "X-Volante": "1", "Content-Type": "application/json" }, body: datos ? JSON.stringify(datos) : undefined });
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(cuerpo.error || "No se ha podido completar. Llame a la consulta.");
  return cuerpo;
}

const telefono = (c) => (c.telefono_centro ? `llame al ${esc(c.telefono_centro)}` : "llame a la consulta");
const membrete = (c) => `<p class="carton__centro">${esc(c.centro || "Consulta")}</p>${c.direccion ? `<p class="carton__dir">${esc(c.direccion)}</p>` : ""}`;
const renglones = (c) => `<dl class="carton__renglones">
  <div><dt>Con</dt><dd>${esc(c.medico)}</dd></div>
  <div><dt>Especialidad</dt><dd>${esc(c.especialidad)}</dd></div>
  ${c.consulta ? `<div><dt>Dónde</dt><dd>${esc(c.consulta)}</dd></div>` : ""}</dl>`;

// ---------------------------------------------------------------- su cita
function pintarCita(c, { recien = false, error = "" } = {}) {
  document.title = `Su cita · ${c.centro || "Consulta"}`;
  const activa = (c.estado === "pendiente" || c.estado === "confirmada") && !c.pasada;
  const sello = SELLOS[c.estado];
  raiz.innerHTML = `
    <article class="carton">
      ${membrete(c)}
      <h1>${c.pasada ? "Su cita fue el" : c.estado === "anulada" ? "Cita anulada" : `Hola, ${esc(c.nombre)}: su cita es el`}</h1>
      <p class="carton__dia">${esc(fechaLarga(c.empieza, { año: true }))}</p>
      <div class="carton__fila"><p class="carton__hora">${hora(c.empieza)}</p>
        ${sello ? `<span class="carton__sello sello sello--grande sello--${c.estado}${recien ? " sello--cae" : ""}">${esc(sello)}</span>` : ""}</div>
      ${renglones(c)}
      ${error ? `<p class="mensaje-error" role="alert" style="margin-top:16px">${esc(error)}</p>` : ""}
      ${activa ? `<div class="carton__acciones">
          ${c.estado === "pendiente" ? `<button class="boton boton--tinta" type="button" data-accion="confirmar">Confirmo que iré</button>` : ""}
          <a class="boton" href="${ruta}/cita.ics" download="cita.ics">Añadir a mi calendario</a>
          <button class="boton boton--peligro" type="button" data-accion="anular">No puedo ir: anular la cita</button>
        </div>` : ""}
      ${c.puede_pedir ? `<div class="carton__otra"><button class="boton ${activa ? "boton--plano" : "boton--tinta"}" type="button" data-otra>
          ${c.estado === "anulada" ? "Pedir otra cita" : `Pedir otra cita con ${esc(c.medico)}`}</button></div>` : ""}
      <div data-huecos></div>
      <p class="carton__pie">${c.estado === "anulada"
        ? `El hueco ya está libre para otra persona.${c.puede_pedir ? "" : ` Si quiere otra cita, ${telefono(c)}.`}`
        : activa ? `Para cambiarla de hora, ${telefono(c)}. Este enlace es personal: no lo comparta.` : ""}</p>
    </article>`;
  raiz.querySelectorAll("[data-accion]").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.accion === "anular" && !b.dataset.seguro) {
      b.dataset.seguro = "1";
      b.textContent = "Pulse otra vez para anularla";
      return;
    }
    raiz.querySelectorAll("button").forEach((x) => { x.disabled = true; });
    try { pintarCita(await pedir(base, "POST", { accion: b.dataset.accion }), { recien: true }); }
    catch (err) { pintarCita(c, { error: err.message }); }
  }));
  raiz.querySelector("[data-otra]")?.addEventListener("click", (e) => { e.currentTarget.hidden = true; elegirHueco(c, estadoCalendario()); });
}

const estadoCalendario = () => ({ desde: iso(new Date()), dia: null, hora: null, dias: [] });

// Pedir otra cita: dos semanas de huecos del mismo médico, día y luego hora.
async function elegirHueco(c, sel) {
  const zona = raiz.querySelector("[data-huecos]");
  zona.innerHTML = `<p class="cargando">Buscando huecos libres…</p>`;
  let r;
  try { r = await pedir(`${base}/huecos?desde=${sel.desde}`); } catch (err) { zona.innerHTML = `<p class="mensaje-error">${esc(err.message)}</p>`; return; }
  sel.dias = r.dias;
  if (!sel.dia || !r.dias.some((d) => d.fecha === sel.dia)) sel.dia = r.dias[0]?.fecha || null;
  const dia = r.dias.find((d) => d.fecha === sel.dia);
  zona.innerHTML = `
    <section class="carton__pedir" aria-label="Pedir otra cita">
      <h2>Elija día y hora con ${esc(c.medico)}</h2>
      ${r.dias.length ? `
        <div class="carton__dias" role="group" aria-label="Día">${r.dias.map((d) => {
          const f = deIso(d.fecha);
          return `<button type="button" data-dia="${d.fecha}" aria-pressed="${d.fecha === sel.dia}"><small>${DIAS_CORTOS[(f.getDay() + 6) % 7]}</small><b>${f.getDate()}</b></button>`;
        }).join("")}</div>
        <div class="horas-libres" role="group" aria-label="Hora">${dia.huecos.map((h) => `<button type="button" data-hora="${h.hora}" aria-pressed="${h.hora === sel.hora}">${h.hora}</button>`).join("")}</div>`
        : `<p>No quedan huecos libres en estas dos semanas.</p>`}
      <div class="carton__mas">
        ${sel.desde > iso(new Date()) ? `<button class="boton boton--plano boton--chico" type="button" data-semanas="-14">Antes</button>` : "<span></span>"}
        ${r.fin ? "" : `<button class="boton boton--plano boton--chico" type="button" data-semanas="14">Dos semanas más tarde</button>`}
      </div>
      <p class="mensaje-error" role="alert"></p>
      <button class="boton boton--tinta" type="button" data-reservar ${sel.hora ? "" : "disabled"} style="width:100%;min-height:48px">
        ${sel.hora ? `Reservar el ${esc(fechaCorta(sel.dia))} a las ${sel.hora}` : "Elija una hora"}</button>
    </section>`;
  zona.querySelectorAll("[data-dia]").forEach((b) => b.addEventListener("click", () => { sel.dia = b.dataset.dia; sel.hora = null; pintarSeleccion(c, sel, r); }));
  zona.querySelectorAll("[data-hora]").forEach((b) => b.addEventListener("click", () => { sel.hora = b.dataset.hora; pintarSeleccion(c, sel, r); }));
  zona.querySelectorAll("[data-semanas]").forEach((b) => b.addEventListener("click", () => {
    const d = new Date(`${sel.desde}T12:00`); d.setDate(d.getDate() + Number(b.dataset.semanas));
    sel.desde = iso(d); sel.dia = null; sel.hora = null;
    elegirHueco(c, sel);
  }));
  zona.querySelector("[data-reservar]")?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try {
      const n = await pedir(`${base}/pedir`, "POST", { fecha: sel.dia, hora: sel.hora });
      location.href = n.enlace;     // su cita nueva, con su propio enlace
    } catch (err) {
      zona.querySelector(".mensaje-error").textContent = err.message;
      sel.hora = null;
      setTimeout(() => elegirHueco(c, sel), 1500);
    }
  });
  zona.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
// Cambiar de día o de hora no vuelve a pedir nada al servidor.
function pintarSeleccion(c, sel, r) {
  const zona = raiz.querySelector("[data-huecos]");
  const dia = r.dias.find((d) => d.fecha === sel.dia);
  zona.querySelectorAll("[data-dia]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.dia === sel.dia)));
  zona.querySelector(".horas-libres").innerHTML = dia.huecos.map((h) => `<button type="button" data-hora="${h.hora}" aria-pressed="${h.hora === sel.hora}">${h.hora}</button>`).join("");
  zona.querySelectorAll("[data-hora]").forEach((b) => b.addEventListener("click", () => { sel.hora = b.dataset.hora; pintarSeleccion(c, sel, r); }));
  const boton = zona.querySelector("[data-reservar]");
  boton.disabled = !sel.hora;
  boton.textContent = sel.hora ? `Reservar el ${fechaCorta(sel.dia)} a las ${sel.hora}` : "Elija una hora";
}

// ---------------------------------------------------------------- oferta de la lista de espera
const TEXTO_OFERTA = {
  aceptada: "Es suyo: tiene la cita.", rechazada: "Entendido: sigue en la lista de espera.",
  caducada: "Esta oferta ha caducado y el hueco ha pasado a otra persona. Sigue en la lista de espera.",
  ocupada: "Lo sentimos: este hueco ya lo ha cogido otra persona. Sigue en la lista de espera.",
};
function pintarOferta(o, { recien = false, error = "" } = {}) {
  document.title = `Hueco libre · ${o.centro || "Consulta"}`;
  const abierta = o.estado === "abierta";
  raiz.innerHTML = `
    <article class="carton">
      ${membrete(o)}
      <h1>${abierta ? `Hola, ${esc(o.nombre)}: se ha quedado libre un hueco el` : "Hueco del"}</h1>
      <p class="carton__dia">${esc(fechaLarga(o.empieza, { año: true }))}</p>
      <div class="carton__fila"><p class="carton__hora">${hora(o.empieza)}</p>
        ${o.estado === "aceptada" ? `<span class="carton__sello sello sello--grande sello--confirmada${recien ? " sello--cae" : ""}">Reservada</span>` : ""}</div>
      ${renglones(o)}
      ${error ? `<p class="mensaje-error" role="alert" style="margin-top:16px">${esc(error)}</p>` : ""}
      ${abierta ? `<p class="carton__plazo">Puede quedárselo hasta ${o.caduca_en.slice(0, 10) === iso(new Date()) ? "hoy" : `el ${esc(fechaCorta(o.caduca_en))}`} a las <b>${hora(o.caduca_en)}</b>. Después pasa a la siguiente persona.</p>
        <div class="carton__acciones">
          <button class="boton boton--tinta" type="button" data-accion="aceptar">Me lo quedo</button>
          <button class="boton" type="button" data-accion="rechazar">No me viene bien</button>
        </div>` : `<p class="carton__plazo">${esc(TEXTO_OFERTA[o.estado] || "")}</p>`}
      ${o.enlace_cita ? `<div class="carton__acciones"><a class="boton boton--tinta" href="${esc(o.enlace_cita)}">Ver mi cita</a></div>` : ""}
      <p class="carton__pie">Este enlace es personal: no lo comparta. Para cualquier duda, ${telefono(o)}.</p>
    </article>`;
  raiz.querySelectorAll("[data-accion]").forEach((b) => b.addEventListener("click", async () => {
    raiz.querySelectorAll("button").forEach((x) => { x.disabled = true; });
    try { pintarOferta(await pedir(base, "POST", { accion: b.dataset.accion }), { recien: true }); }
    catch (err) { pedir(base).then((o2) => pintarOferta(o2, { error: err.message })).catch(() => pintarOferta(o, { error: err.message })); }
  }));
}

// ---------------------------------------------------------------- verificar un justificante
function pintarVerificacion(v) {
  document.title = "Justificante válido";
  raiz.innerHTML = `
    <article class="carton">
      <p class="carton__centro">${esc(v.centro || "Consulta")}</p>
      <h1>Comprobación de justificante · código ${esc(v.codigo)}</h1>
      <div class="carton__fila"><p class="carton__dia">Justificante válido</p><span class="carton__sello sello sello--grande sello--atendida">Auténtico</span></div>
      <dl class="carton__renglones">
        <div><dt>Paciente</dt><dd>${esc(v.iniciales)}</dd></div>
        <div><dt>Fecha</dt><dd>${esc(fechaLarga(v.fecha, { año: true }))}</dd></div>
        <div><dt>Horario</dt><dd>de ${hora(v.desde)} a ${hora(v.hasta)}</dd></div>
        <div><dt>Consulta de</dt><dd>${esc(v.especialidad)}</dd></div>
      </dl>
      <p class="carton__pie">Solo se muestran las iniciales del paciente. Este justificante acredita la asistencia y la hora, sin información clínica.</p>
    </article>`;
}

const pintores = { c: pintarCita, o: pintarOferta, v: pintarVerificacion };
pedir(base).then((d) => pintores[tipo](d)).catch((err) => {
  raiz.innerHTML = `<article class="carton"><p class="carton__centro">${tipo === "v" ? "Justificante" : "Su cita"}</p><p style="margin-top:24px">${esc(err.message)}</p></article>`;
});
