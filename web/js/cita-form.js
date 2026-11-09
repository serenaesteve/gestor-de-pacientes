// El impreso de «Apuntar cita» y «Mover cita».
import { estado } from "./app.js";
import { api, esc, dialogo, confirmar, nota, fechaLarga, fechaCorta, CANALES, opciones, hora, plural } from "./util.js";
import { formularioEspera } from "./espera.js";

const DURACIONES = [10, 15, 20, 30, 45, 60, 90];
const CONFLICTOS = ["fuera_horario", "ausencia", "paciente_ocupado"];

/** Ejecuta enviar(false); si el servidor pregunta (fuera de horario, ausencia, paciente ocupado),
 *  lo pregunta a quien está en el mostrador y repite con forzar. Si dice que no, lanza null. */
export async function manejarConflicto(enviar) {
  try {
    return await enviar(false);
  } catch (err) {
    if (!CONFLICTOS.includes(err.codigo)) throw err;
    const ok = await confirmar("Revisa la cita", err.message, { boton: "Darla igualmente" });
    if (!ok) throw null;
    return enviar(true);
  }
}

export function apuntar(inicial = {}) {
  return impreso({ ...inicial, modo: "nueva" });
}

export function mover(cita) {
  return impreso({
    modo: "mover", cita, medico_id: cita.medico_id, fecha: cita.empieza.slice(0, 10), hora: hora(cita.empieza),
    minutos: cita.minutos, motivo: cita.motivo,
    paciente: { id: cita.paciente_id, nombre: cita.nombre, apellidos: cita.apellidos, telefono: cita.telefono },
  });
}

function impreso(ini) {
  const medicos = estado.medicos;
  const medico = medicos.find((m) => m.id === ini.medico_id) || medicos[0];
  if (!medico) { nota("Antes de dar citas, da de alta a un médico con su horario.", { error: true }); return Promise.resolve(null); }
  const sel = { paciente: ini.paciente || null, medico_id: medico.id, fecha: ini.fecha && ini.fecha >= estado.hoy ? ini.fecha : estado.hoy, hora: ini.hora || null, minutos: ini.minutos || null };
  const titulo = ini.modo === "mover" ? "Mover la cita" : "Apuntar cita";

  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>${titulo}</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <div class="campo" data-zona-paciente>
          <span>Paciente</span>
          <div data-paciente></div>
        </div>
        <div class="filas">
          <label class="campo"><span>Médico</span><select name="medico_id">${opciones(medicos.map((m) => [m.id, `${m.nombre} · ${m.especialidad}`]), sel.medico_id)}</select></label>
          <label class="campo"><span>Día</span><input type="date" name="fecha" value="${sel.fecha}" min="${estado.hoy}" required></label>
        </div>
        <div class="campo">
          <span>Hora</span>
          <div class="horas-libres" data-horas aria-live="polite"></div>
          <div class="acciones" style="margin-top:8px">
            <button class="boton boton--chico" type="button" data-primero>Primer hueco libre</button>
            <label class="casilla" style="font-size:var(--t-s)"><input type="checkbox" data-otra> Otra hora (fuera de los huecos)</label>
            <input type="time" name="hora_libre" step="300" hidden style="max-width:130px;border-bottom:1.5px solid var(--pauta);background:none;border-top:0;border-left:0;border-right:0;min-height:36px">
          </div>
        </div>
        <div class="filas">
          <label class="campo"><span>Duración</span><select name="minutos"></select></label>
          <label class="campo" style="grid-column:span 2"><span>Motivo</span><input name="motivo" maxlength="160" value="${esc(ini.motivo || "")}" placeholder="Revisión, resultados, primera visita…"></label>
        </div>
        ${ini.modo === "nueva" ? `<div class="filas">
          <label class="campo"><span>Repetir</span><select name="repetir">
            <option value="">No se repite</option><option value="semana">Cada semana</option><option value="2semanas">Cada 2 semanas</option>
            <option value="4semanas">Cada 4 semanas</option><option value="mes">Cada mes, el mismo día</option></select></label>
          <label class="campo" data-veces hidden><span>Citas en total</span><input type="number" name="veces" min="2" max="26" value="6" inputmode="numeric"></label>
        </div>` : ""}
        ${ini.modo === "nueva" ? `<fieldset class="campo" style="border:0;padding:0;margin:0"><legend class="rotulo" style="padding:0;margin-bottom:4px">La pide</legend>
          <div class="acciones"><label class="casilla"><input type="radio" name="origen" value="recepcion" checked> En el mostrador</label>
          <label class="casilla"><input type="radio" name="origen" value="telefono"> Por teléfono</label></div></fieldset>` : ""}
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">${ini.modo === "mover" ? "Mover la cita" : "Apuntar la cita"}</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    const error = form.querySelector(".mensaje-error");
    const zonaHoras = form.querySelector("[data-horas]");
    const selMinutos = form.minutos;
    const otra = form.querySelector("[data-otra]");
    const horaLibre = form.hora_libre;

    // ---- paciente ----
    const zonaPaciente = form.querySelector("[data-paciente]");
    const pintarPaciente = () => {
      if (sel.paciente) {
        zonaPaciente.innerHTML = `<div class="elegido"><span><b>${esc(sel.paciente.apellidos)}, ${esc(sel.paciente.nombre)}</b>
          ${sel.paciente.telefono ? `<small class="mono"> · ${esc(sel.paciente.telefono)}</small>` : ""}</span>
          ${ini.modo === "nueva" ? `<button class="boton boton--plano boton--chico" type="button" data-cambiar>Cambiar</button>` : ""}</div>`;
        zonaPaciente.querySelector("[data-cambiar]")?.addEventListener("click", () => { sel.paciente = null; pintarPaciente(); zonaPaciente.querySelector("input")?.focus(); });
        return;
      }
      zonaPaciente.innerHTML = `
        <div class="buscador">
          <input type="search" placeholder="Apellidos, nombre, DNI o teléfono" autocomplete="off" aria-label="Buscar paciente" role="combobox" aria-expanded="false" aria-controls="lista-pacientes">
          <ul class="buscador__lista" id="lista-pacientes" role="listbox" hidden></ul>
        </div>
        <button class="boton boton--plano boton--chico" type="button" data-nuevo style="margin-top:4px;justify-self:start">+ Paciente nuevo</button>`;
      const entrada = zonaPaciente.querySelector("input");
      const lista = zonaPaciente.querySelector("ul");
      let resultados = [], marcado = -1, temporizador;
      const pintarLista = () => {
        lista.hidden = !resultados.length;
        entrada.setAttribute("aria-expanded", String(!lista.hidden));
        lista.innerHTML = resultados.map((p, i) => `<li><button type="button" role="option" data-i="${i}" aria-selected="${i === marcado}">
          <span>${esc(p.apellidos)}, ${esc(p.nombre)}</span><small>${esc(p.telefono || p.documento || "")}</small></button></li>`).join("");
      };
      entrada.addEventListener("input", () => {
        clearTimeout(temporizador);
        const q = entrada.value.trim();
        if (q.length < 2) { resultados = []; pintarLista(); return; }
        temporizador = setTimeout(async () => {
          const r = await api(`/api/pacientes?q=${encodeURIComponent(q)}`);
          resultados = r.pacientes.slice(0, 8);
          marcado = resultados.length ? 0 : -1;
          pintarLista();
        }, 160);
      });
      entrada.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          marcado = Math.max(0, Math.min(resultados.length - 1, marcado + (e.key === "ArrowDown" ? 1 : -1)));
          pintarLista();
        } else if (e.key === "Enter" && marcado >= 0) {
          e.preventDefault();
          sel.paciente = resultados[marcado];
          pintarPaciente();
        }
      });
      lista.addEventListener("click", (e) => {
        const b = e.target.closest("[data-i]");
        if (b) { sel.paciente = resultados[Number(b.dataset.i)]; pintarPaciente(); }
      });
      zonaPaciente.querySelector("[data-nuevo]").addEventListener("click", () => pacienteNuevo(entrada.value));
      setTimeout(() => entrada.focus(), 30);
    };
    const pacienteNuevo = (texto) => {
      const [ap = "", ...resto] = texto.includes(",") ? texto.split(",").map((s) => s.trim()) : [texto.trim()];
      zonaPaciente.innerHTML = `
        <div class="filas" style="padding:12px;border:1px dashed var(--pauta)">
          <label class="campo"><span>Nombre</span><input name="p_nombre" maxlength="60" value="${esc(resto.join(" "))}" autocomplete="off"></label>
          <label class="campo"><span>Apellidos</span><input name="p_apellidos" maxlength="80" value="${esc(ap)}" autocomplete="off"></label>
          <label class="campo"><span>Teléfono</span><input name="p_telefono" type="tel" inputmode="tel" maxlength="20" autocomplete="off"></label>
          <label class="campo"><span>Correo</span><input name="p_email" type="email" maxlength="120" autocomplete="off"></label>
          <label class="campo"><span>Avisos por</span><select name="p_canal">${opciones(Object.entries(CANALES), "correo")}</select></label>
        </div>
        <button class="boton boton--plano boton--chico" type="button" data-buscar style="margin-top:4px;justify-self:start">Buscar en el fichero</button>`;
      zonaPaciente.querySelector("[data-buscar]").addEventListener("click", pintarPaciente);
      zonaPaciente.querySelector(ap ? "[name=p_nombre]" : "[name=p_apellidos]").focus();
    };
    pintarPaciente();

    // ---- huecos ----
    const medicoActual = () => medicos.find((m) => m.id === Number(form.medico_id.value));
    const duracionBase = () => {
      const m = medicoActual();
      const dia = ((new Date(`${form.fecha.value}T12:00`).getDay() + 6) % 7) + 1;
      return (m?.franjas.find((f) => f.dia === dia) || m?.franjas[0])?.minutos || 20;
    };
    const pintarDuraciones = () => {
      const base = sel.minutos || duracionBase();
      const lista = [...new Set([...DURACIONES, base])].sort((a, b) => a - b);
      selMinutos.innerHTML = opciones(lista.map((n) => [n, `${n} minutos`]), base);
    };
    const cargarHuecos = async () => {
      zonaHoras.innerHTML = `<span class="horas-libres__vacio">Buscando huecos…</span>`;
      const fecha = form.fecha.value;
      if (!fecha) { zonaHoras.innerHTML = ""; return; }
      let dias;
      try { dias = await api(`/api/huecos?medico=${form.medico_id.value}&fecha=${fecha}`); } catch (err) { zonaHoras.innerHTML = `<span class="mensaje-error">${esc(err.message)}</span>`; return; }
      const huecos = dias[0]?.huecos || [];
      const propia = ini.modo === "mover" && fecha === ini.fecha && Number(form.medico_id.value) === ini.medico_id ? ini.hora : null;
      const todas = propia && !huecos.some((h) => h.hora === propia) ? [{ hora: propia, minutos: ini.minutos, propia: true }, ...huecos].sort((a, b) => a.hora.localeCompare(b.hora)) : huecos;
      if (!todas.length) {
        const m = medicoActual();
        zonaHoras.innerHTML = `<span class="horas-libres__vacio">${esc(m.nombre)} no tiene huecos libres el ${esc(fechaLarga(fecha))}. Prueba «Primer hueco libre» u otro día.</span>
          ${ini.modo === "nueva" ? `<button class="boton boton--chico" type="button" data-a-espera>Apuntar en la lista de espera</button>` : ""}`;
        zonaHoras.querySelector("[data-a-espera]")?.addEventListener("click", () => {
          const medico_id = Number(form.medico_id.value);
          cerrar();
          formularioEspera({ paciente: sel.paciente, medico_id, motivo: form.motivo.value });
        });
        if (!otra.checked) sel.hora = null;
        return;
      }
      if (sel.hora && !todas.some((h) => h.hora === sel.hora) && !otra.checked) sel.hora = null;
      zonaHoras.innerHTML = todas.map((h) => `<button type="button" data-h="${h.hora}" data-m="${h.minutos}" aria-pressed="${h.hora === sel.hora}" ${h.propia ? 'title="Hora actual de la cita"' : ""}>${h.hora}</button>`).join("");
    };
    zonaHoras.addEventListener("click", (e) => {
      const b = e.target.closest("[data-h]");
      if (!b) return;
      sel.hora = b.dataset.h;
      otra.checked = false; horaLibre.hidden = true;
      zonaHoras.querySelectorAll("[data-h]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      error.textContent = "";
    });
    otra.addEventListener("change", () => {
      horaLibre.hidden = !otra.checked;
      if (otra.checked) { horaLibre.value = sel.hora || ""; horaLibre.focus(); zonaHoras.querySelectorAll("[data-h]").forEach((x) => x.setAttribute("aria-pressed", "false")); }
    });
    form.medico_id.addEventListener("change", () => { sel.minutos = null; pintarDuraciones(); cargarHuecos(); });
    form.fecha.addEventListener("change", () => { pintarDuraciones(); cargarHuecos(); });
    form.querySelector("[data-primero]").addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try {
        const dias = await api(`/api/huecos?medico=${form.medico_id.value}&fecha=${estado.hoy}&dias=60`);
        if (!dias.length) { error.textContent = "No hay huecos libres en los próximos 60 días."; return; }
        form.fecha.value = dias[0].fecha;
        sel.hora = dias[0].huecos[0].hora;
        otra.checked = false; horaLibre.hidden = true;
        pintarDuraciones();
        await cargarHuecos();
        nota(`Primer hueco: ${fechaCorta(dias[0].fecha)} a las ${sel.hora}.`);
      } finally { e.currentTarget.disabled = false; }
    });
    pintarDuraciones();
    cargarHuecos();
    form.repetir?.addEventListener("change", () => { form.querySelector("[data-veces]").hidden = !form.repetir.value; });

    // ---- guardar ----
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      error.textContent = "";
      const horaElegida = otra.checked ? horaLibre.value : sel.hora;
      if (!horaElegida) { error.textContent = "Elige una hora libre."; return; }
      const boton = form.querySelector("button[type=submit]");
      boton.disabled = true;
      try {
        let pacienteId = sel.paciente?.id;
        if (!pacienteId && ini.modo === "nueva") {
          if (!form.p_nombre) { error.textContent = "Busca al paciente o apúntalo como nuevo."; return; }
          const r = await api("/api/pacientes", { metodo: "POST", datos: {
            nombre: form.p_nombre.value, apellidos: form.p_apellidos.value, telefono: form.p_telefono.value, email: form.p_email.value, canal: form.p_canal.value,
          } });
          pacienteId = r.id;
          sel.paciente = { id: r.id, nombre: form.p_nombre.value.trim(), apellidos: form.p_apellidos.value.trim(), telefono: form.p_telefono.value.trim() };
          pintarPaciente();
        }
        const datos = {
          paciente_id: pacienteId, medico_id: Number(form.medico_id.value), fecha: form.fecha.value, hora: horaElegida,
          minutos: Number(selMinutos.value), motivo: form.motivo.value, origen: form.origen?.value,
        };
        if (form.repetir?.value) {
          datos.repetir = form.repetir.value;
          datos.veces = Number(form.veces.value);
          const previa = await api("/api/citas/serie", { metodo: "POST", datos });
          if (!(await confirmarSerie(previa))) return;
        }
        const enviar = (forzar) => ini.modo === "mover"
          ? api(`/api/citas/${ini.cita.id}`, { metodo: "PUT", datos: { ...datos, forzar } }).then(() => ({ id: ini.cita.id }))
          : api("/api/citas", { metodo: "POST", datos: { ...datos, forzar } });
        let r;
        try {
          r = await manejarConflicto(enviar);
        } catch (err) {
          if (err === null) return;
          throw err;
        }
        nota(ini.modo === "mover"
          ? `Cita movida al ${fechaCorta(datos.fecha)} a las ${datos.hora}. Se le avisará de la hora nueva.`
          : r.ids ? `${plural(r.ids.length, "cita apuntada", "citas apuntadas")} desde el ${fechaCorta(datos.fecha)}.${r.saltadas.length ? ` ${plural(r.saltadas.length, "fecha se ha saltado", "fechas se han saltado")}.` : ""}`
            : `Cita apuntada: ${fechaCorta(datos.fecha)} a las ${datos.hora}.`, { segundos: 7 });
        cerrar(r);
      } catch (err) {
        error.textContent = err.message;
      } finally {
        boton.disabled = false;
      }
    });
  });
}

// Antes de apuntar una serie se enseña qué fechas caben y cuáles no.
function confirmarSerie(previa) {
  const caben = previa.filter((x) => x.cabe).length;
  if (!previa[0].cabe) {
    nota(`La primera fecha no cabe: ${previa[0].motivo}`, { error: true, segundos: 8 });
    return Promise.resolve(false);
  }
  return dialogo(`
    <div class="impreso__cabeza"><h2>Serie de ${previa.length} citas</h2></div>
    <div class="impreso__cuerpo">
      <ul class="renglones renglones--serie">${previa.map((x) => `<li>
        <span class="mono">${esc(fechaCorta(x.fecha))}</span><span class="mono">${esc(x.hora)}</span>
        <span>${x.cabe ? "Cabe" : esc(x.motivo)}</span>
        <span class="sello sello--${x.cabe ? "confirmada" : "anulada"}">${x.cabe ? "Libre" : "Se salta"}</span></li>`).join("")}</ul>
      ${caben < previa.length ? `<p style="font-size:var(--t-s);color:var(--tinta-2)">Las que no caben se saltan: puedes darlas después a mano.</p>` : ""}
    </div>
    <div class="impreso__pie">
      <button class="boton" type="button" data-cerrar>Volver</button>
      <button class="boton boton--tinta" type="button" data-si>Apuntar ${plural(caben, "cita", "citas")}</button>
    </div>`, (d, cerrar) => { d.querySelector("[data-si]").addEventListener("click", () => cerrar(true)); });
}
