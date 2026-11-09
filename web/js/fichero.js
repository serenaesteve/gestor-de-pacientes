// Fichero de pacientes: el cajón de fichas y la ficha de cada uno.
import { estado, membrete, puede } from "./app.js";
import {
  api, esc, icono, nota, confirmar, dialogo, datosFormulario, opciones, ESTADOS, CANALES, fechaNum, fechaCorta, hora, edad,
  tipoAviso, cuandoRelativo, plural,
} from "./util.js";
import { apuntar } from "./cita-form.js";
import { etiquetaAviso } from "./libro.js";
import { formularioEspera } from "./espera.js";

const LETRAS = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ".split("");
let filtro = { q: "", letra: "" };

export async function mostrar(contenido, { params }) {
  const id = Number(params[0]) || null;
  document.title = "Fichero · Volante";
  membrete({ titulo: "Fichero de pacientes", subtitulo: "Historias y datos de contacto" });
  contenido.innerHTML = `
    <div class="fichero" ${id ? "data-detalle" : ""}>
      <section class="fichero__lista" aria-label="Pacientes">
        <div class="barra">
          ${puede("pacientes") ? `<button class="boton boton--tinta" type="button" data-alta>${icono("mas", 16)} Paciente nuevo</button>` : ""}
        </div>
        <label class="campo"><span>Buscar</span><input type="search" data-q value="${esc(filtro.q)}" placeholder="Apellidos, nombre, DNI o teléfono" autocomplete="off"></label>
        <div class="abecedario" role="group" aria-label="Por la inicial del primer apellido">
          ${LETRAS.map((l) => `<button type="button" data-letra="${l}" aria-pressed="${filtro.letra === l}">${l}</button>`).join("")}
        </div>
        <div class="cajon" data-cajon><p class="cargando">Abriendo el cajón…</p></div>
      </section>
      <section class="fichero__detalle" data-zona-ficha aria-live="polite">
        ${id ? `<p class="cargando">Sacando la ficha…</p>` : `<div class="vacio"><b>Elige una ficha del cajón.</b>Ahí verás sus datos, sus citas pasadas y futuras y los avisos que se le han mandado.</div>`}
      </section>
    </div>`;
  const q = contenido.querySelector("[data-q]");
  let temporizador;
  q.addEventListener("input", () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { filtro = { q: q.value, letra: "" }; pintarLetras(contenido); cargarCajon(contenido, id); }, 180);
  });
  contenido.querySelectorAll("[data-letra]").forEach((b) => b.addEventListener("click", () => {
    filtro = { q: "", letra: filtro.letra === b.dataset.letra ? "" : b.dataset.letra };
    q.value = "";
    pintarLetras(contenido);
    cargarCajon(contenido, id);
  }));
  contenido.querySelector("[data-alta]")?.addEventListener("click", async () => {
    const r = await formularioPaciente();
    if (r?.id) location.hash = `#/fichero/${r.id}`;
  });
  await Promise.all([cargarCajon(contenido, id), id ? pintarFicha(contenido, id) : null]);
}

function pintarLetras(contenido) {
  contenido.querySelectorAll("[data-letra]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.letra === filtro.letra)));
}

async function cargarCajon(contenido, actualId) {
  const cajon = contenido.querySelector("[data-cajon]");
  const r = await api(`/api/pacientes?q=${encodeURIComponent(filtro.q)}&letra=${encodeURIComponent(filtro.letra)}`);
  if (!contenido.isConnected) return;
  if (!r.total) {
    cajon.innerHTML = `<div class="vacio"><b>El fichero está vacío.</b>Da de alta al primer paciente, o apúntalo directamente al darle cita.</div>`;
    return;
  }
  if (!r.pacientes.length) {
    cajon.innerHTML = `<div class="vacio"><b>Ninguna ficha coincide.</b>${filtro.q ? `Prueba solo con el primer apellido o con el teléfono.` : `No hay apellidos con la «${esc(filtro.letra)}».`}</div>`;
    return;
  }
  cajon.innerHTML = r.pacientes.map((p) => `
    <button type="button" class="cajon__ficha" data-id="${p.id}" ${p.id === actualId ? 'aria-current="true"' : ""}>
      <b>${esc(p.apellidos)}, ${esc(p.nombre)}</b>
      ${p.proxima ? `<span class="hora" title="Próxima cita">${esc(fechaCorta(p.proxima))}<br>${hora(p.proxima)}</span>` : "<span></span>"}
      <small>${esc([p.telefono, p.documento].filter(Boolean).join(" · ") || "Sin teléfono")}</small>
    </button>`).join("") + `<p class="cajon__pie">${r.recortado ? "Se ven las 300 primeras: afina la búsqueda." : plural(r.pacientes.length, "ficha", "fichas")}${r.pacientes.length !== r.total ? ` de ${r.total}` : ""}</p>`;
  cajon.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => { location.hash = `#/fichero/${b.dataset.id}`; }));
}

async function pintarFicha(contenido, id) {
  const zona = contenido.querySelector("[data-zona-ficha]");
  let r;
  try { r = await api(`/api/pacientes/${id}`); } catch (err) { zona.innerHTML = `<div class="vacio"><b>No se ha encontrado la ficha.</b>${esc(err.message)}</div>`; return; }
  const p = r.paciente;
  document.title = `${p.apellidos}, ${p.nombre} · Fichero · Volante`;
  const anos = edad(p.nacimiento, estado.hoy);
  const ahora = `${estado.hoy} 23:59:59`;
  const futuras = r.citas.filter((c) => c.empieza > `${estado.hoy} 00:00:00` && (c.estado === "pendiente" || c.estado === "confirmada")).reverse();
  const historial = r.citas.filter((c) => !futuras.includes(c));
  const faltas = historial.filter((c) => c.estado === "no_acudio").length;
  const dato = (titulo, valor) => `<div><dt>${titulo}</dt><dd>${valor || "—"}</dd></div>`;
  const destinoFalta = p.canal === "correo" ? !p.email : p.canal === "ninguno" ? false : !p.telefono;
  zona.innerHTML = `
    <article class="ficha">
      <div class="ficha__cabeza">
        <div><span class="rotulo">Ficha nº ${p.id}</span><h2>${esc(p.apellidos)}, ${esc(p.nombre)}</h2></div>
        <div class="acciones">
          <a class="boton boton--plano boton--chico" href="#/fichero" data-volver>Volver al cajón</a>
          ${puede("pacientes") ? `<button class="boton boton--chico" type="button" data-editar>${icono("lapiz", 14)} Editar</button>` : ""}
          ${puede("citas") ? `<button class="boton boton--chico" type="button" data-espera>Lista de espera</button>
          <button class="boton boton--tinta boton--chico" type="button" data-cita>Dar cita</button>` : ""}
        </div>
      </div>
      <dl class="ficha__datos">
        ${dato("Documento", esc(p.documento))}
        ${dato("Nacimiento", p.nacimiento ? `${fechaNum(p.nacimiento)}${anos !== null ? ` · ${anos} años` : ""}` : "")}
        ${dato("Teléfono", p.telefono ? `<a href="tel:${esc(p.telefono.replace(/\s/g, ""))}">${esc(p.telefono)}</a>` : "")}
        ${dato("Correo", p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : "")}
        ${dato("Avisos por", esc(CANALES[p.canal]) + (destinoFalta ? ` <span style="color:var(--peligro)">· falta el ${p.canal === "correo" ? "correo" : "teléfono"}</span>` : ""))}
        ${dato("Dirección", esc(p.direccion))}
      </dl>
      ${p.notas ? `<p class="nota-paciente">${esc(p.notas)}</p>` : ""}
      ${faltas >= 2 ? `<p class="nota-paciente" style="border-color:var(--peligro)">Ha faltado ${faltas} veces sin avisar.</p>` : ""}

      <section class="seccion"><h3>Próximas citas <span class="mono rotulo">${futuras.length}</span></h3>
        ${futuras.length ? `<ul class="renglones">${futuras.map((c) => renglon(c)).join("")}</ul>` : `<p class="vacio">No tiene ninguna cita por delante.</p>`}
      </section>
      <section class="seccion"><h3>Historial <span class="mono rotulo">${historial.length}</span></h3>
        ${historial.length ? `<ul class="renglones">${historial.map((c) => renglon(c, true)).join("")}</ul>` : `<p class="vacio">Todavía no ha venido a la consulta.</p>`}
      </section>
      <section class="seccion"><h3>Avisos mandados</h3>
        ${r.avisos.length ? `<ul class="linea-avisos">${r.avisos.map((a) => `<li class="${a.estado}"><span>${esc(tipoAviso(a.tipo))} · ${esc(CANALES[a.canal])}</span>
          <span class="mono">${esc(etiquetaAviso(a.estado))} · ${esc(cuandoRelativo(a.enviado_en || a.programado, ahora))}</span></li>`).join("")}</ul>` : `<p class="vacio">Ninguno todavía.</p>`}
      </section>
      ${puede("borrar_paciente") ? `<div class="acciones acciones--pie" style="margin-top:32px"><button class="boton boton--plano boton--chico" type="button" data-borrar style="color:var(--peligro)">Borrar la ficha y todo su historial</button></div>` : ""}
    </article>`;
  zona.querySelector("[data-cita]")?.addEventListener("click", () => apuntar({ paciente: p }).then((x) => x && pintarFicha(contenido, id)));
  zona.querySelector("[data-espera]")?.addEventListener("click", () => formularioEspera({ paciente: p }));
  zona.querySelector("[data-editar]")?.addEventListener("click", async () => {
    if (await formularioPaciente(p)) { pintarFicha(contenido, id); cargarCajon(contenido, id); }
  });
  zona.querySelector("[data-borrar]")?.addEventListener("click", async () => {
    const ok = await confirmar("¿Borrar la ficha?", `Se borran ${p.nombre} ${p.apellidos}, sus ${r.citas.length} citas y sus avisos. No se puede deshacer: úsalo cuando el paciente ejerza su derecho de supresión.`, { boton: "Borrar para siempre", peligro: true });
    if (!ok) return;
    try { await api(`/api/pacientes/${id}`, { metodo: "DELETE" }); } catch (err) { return nota(err.message, { error: true }); }
    nota("Ficha borrada.");
    location.hash = "#/fichero";
  });
}

function renglon(c, pasado = false) {
  return `<li>
    <a class="mono" href="#/libro/${c.empieza.slice(0, 10)}">${esc(fechaNum(c.empieza))}</a>
    <span class="mono">${hora(c.empieza)}</span>
    <span class="quien"><span class="tampon" style="--c:var(--t-${esc(c.color)})"></span><span>${esc(c.medico)}${c.motivo ? ` · ${esc(c.motivo)}` : ""}</span></span>
    ${c.estado !== "pendiente" ? `<span class="sello sello--${c.estado}">${esc(ESTADOS[c.estado])}</span>` : `<span class="rotulo">${pasado ? "Sin sellar" : "Sin confirmar"}</span>`}
    ${c.nota ? `<span class="nota">${esc(c.nota)}</span>` : ""}
  </li>`;
}

export function formularioPaciente(p = null) {
  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>${p ? "Editar la ficha" : "Paciente nuevo"}</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <div class="filas">
          <label class="campo"><span>Nombre</span><input name="nombre" required maxlength="60" value="${esc(p?.nombre)}" autocomplete="off"></label>
          <label class="campo"><span>Apellidos</span><input name="apellidos" required maxlength="80" value="${esc(p?.apellidos)}" autocomplete="off"></label>
        </div>
        <div class="filas">
          <label class="campo"><span>DNI / NIE</span><input name="documento" maxlength="20" value="${esc(p?.documento)}" autocomplete="off" autocapitalize="characters"></label>
          <label class="campo"><span>Nacimiento</span><input name="nacimiento" type="date" max="${estado.hoy}" value="${esc(p?.nacimiento)}"></label>
        </div>
        <div class="filas">
          <label class="campo"><span>Teléfono móvil</span><input name="telefono" type="tel" inputmode="tel" maxlength="20" value="${esc(p?.telefono)}" autocomplete="off"></label>
          <label class="campo"><span>Correo</span><input name="email" type="email" maxlength="120" value="${esc(p?.email)}" autocomplete="off"></label>
          <label class="campo"><span>Recordatorios por</span><select name="canal">${opciones(Object.entries(CANALES), p?.canal || "correo")}</select>
            <small>El correo sale solo; SMS y WhatsApp se mandan desde la bandeja.</small></label>
        </div>
        <label class="campo"><span>Dirección</span><input name="direccion" maxlength="160" value="${esc(p?.direccion)}" autocomplete="off"></label>
        <label class="campo"><span>Avisos para recepción</span><textarea name="notas" maxlength="2000" rows="2" placeholder="Alergias, si viene acompañado, cuándo prefiere que le llamen…">${esc(p?.notas)}</textarea>
          <small>Se ve al abrir cada cita. No es la historia clínica.</small></label>
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">${p ? "Guardar los cambios" : "Abrir la ficha"}</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    form.nombre.focus();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const boton = form.querySelector("button[type=submit]");
      boton.disabled = true;
      try {
        const datos = datosFormulario(form);
        const r = p ? await api(`/api/pacientes/${p.id}`, { metodo: "PUT", datos }) : await api("/api/pacientes", { metodo: "POST", datos });
        nota(p ? "Ficha guardada." : "Ficha abierta.");
        cerrar(r);
      } catch (err) {
        form.querySelector(".mensaje-error").textContent = err.message;
      } finally { boton.disabled = false; }
    });
  });
}
