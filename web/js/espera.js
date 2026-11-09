// Lista de espera: quién quiere cita antes, y qué huecos se le han ofrecido.
import { estado, membrete, puede, refrescarBandeja } from "./app.js";
import { api, esc, icono, nota, dialogo, opciones, fechaCorta, fechaNum, hora, cuandoRelativo, plural, CANALES } from "./util.js";
import { apuntar } from "./cita-form.js";

const FRANJAS = { cualquiera: "Cualquier hora", manana: "Por la mañana", tarde: "Por la tarde" };
const OFERTA = { abierta: "Ofrecido", aceptada: "Lo cogió", rechazada: "No le venía bien", caducada: "No contestó", ocupada: "Lo cogió otro" };

export async function mostrar(contenido, { params }) {
  const ver = params[0] === "cerradas" ? "cerradas" : "activa";
  document.title = "Lista de espera · Volante";
  contenido.innerHTML = `<p class="cargando">Mirando la lista…</p>`;
  const lista = await api(`/api/espera?ver=${ver}`);
  if (!contenido.isConnected) return;
  const ofrecidas = lista.filter((e) => e.estado === "ofrecida").length;
  membrete({
    titulo: "Lista de espera", subtitulo: "Para adelantar citas",
    casillas: ver === "activa" ? `<div class="casillas"><div><b>${lista.length}</b><span class="rotulo">Esperando</span></div>
      <div><b>${ofrecidas}</b><span class="rotulo">Con oferta</span></div></div>` : "",
  });
  contenido.innerHTML = `
    <div class="barra">
      ${puede("citas") ? `<button class="boton boton--tinta" type="button" data-apuntar>${icono("mas", 16)} Apuntar en la lista</button>` : ""}
      <span class="barra__hueco"></span>
    </div>
    <p class="explica">Cuando se anula una cita, su hueco se ofrece solo al primero de la lista que encaje (mismo médico, o cualquiera de su especialidad, y la franja que prefiere).
      Le llega un aviso con un enlace para quedárselo; si no contesta en ${esc(estado.ajustes.oferta_horas || "3")} h, pasa al siguiente.</p>
    <nav class="bandejas" aria-label="Lista">
      <a href="#/espera" ${ver === "activa" ? 'aria-current="page"' : ""}>En la lista</a>
      <a href="#/espera/cerradas" ${ver === "cerradas" ? 'aria-current="page"' : ""}>Ya citados o retirados</a>
    </nav>
    ${lista.length ? `<ol class="lista-espera">${lista.map((e, i) => fila(e, i, ver)).join("")}</ol>`
      : `<div class="vacio"><b>${ver === "activa" ? "Nadie espera." : "Todavía no hay nadie aquí."}</b>${ver === "activa" ? "Apunta a quien quiera una cita antes de la que le dieron, o a quien no encontró hueco." : ""}</div>`}`;
  contenido.querySelector("[data-apuntar]")?.addEventListener("click", async () => { if (await formularioEspera()) mostrar(contenido, { params }); });
  contenido.querySelector(".lista-espera")?.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-accion]");
    if (!b) return;
    const entrada = lista.find((x) => x.id === Number(b.dataset.id));
    if (b.dataset.accion === "cita") {
      const r = await apuntar({ paciente: { id: entrada.paciente_id, nombre: entrada.nombre, apellidos: entrada.apellidos, telefono: entrada.telefono },
        medico_id: entrada.medico_id || estado.medicos.find((m) => m.especialidad === entrada.especialidad)?.id, minutos: entrada.minutos, motivo: entrada.motivo });
      if (r) {
        await api(`/api/espera/${entrada.id}`, { metodo: "PUT", datos: { estado: "citada", cita_id: r.id } }).catch(() => {});
        nota(`${entrada.nombre} sale de la lista: ya tiene cita.`);
        mostrar(contenido, { params });
      }
      return;
    }
    try {
      await api(`/api/espera/${entrada.id}`, { metodo: "PUT", datos: { estado: b.dataset.accion } });
    } catch (err) { return nota(err.message, { error: true }); }
    nota(b.dataset.accion === "retirada" ? `${entrada.nombre} ${entrada.apellidos} sale de la lista.` : `${entrada.nombre} vuelve a la lista.`);
    refrescarBandeja();
    mostrar(contenido, { params });
  });
}

function fila(e, i, ver) {
  const quien = e.medico ? esc(e.medico) : `cualquiera de ${esc(e.especialidad)}`;
  const plazo = e.hasta ? `del ${fechaNum(e.desde)} al ${fechaNum(e.hasta)}` : `desde el ${fechaNum(e.desde)}`;
  const historial = e.ofertas.filter((o) => o.estado !== "abierta");
  return `<li class="lista-espera__fila lista-espera__fila--${e.estado}">
    <span class="lista-espera__puesto mono" aria-label="Puesto ${i + 1}">${ver === "activa" ? String(i + 1).padStart(2, "0") : "·"}</span>
    <div class="lista-espera__quien">
      <a href="#/fichero/${e.paciente_id}"><b>${esc(e.apellidos)}, ${esc(e.nombre)}</b></a>
      <small>${quien} · ${esc(FRANJAS[e.franja])} · ${plazo}${e.motivo ? ` · ${esc(e.motivo)}` : ""}</small>
      <small class="mono">Apuntado ${esc(cuandoRelativo(e.creado_en, `${estado.hoy} 00:00:00`))} · avisos por ${esc(CANALES[e.canal])}</small>
      ${historial.length ? `<small>Huecos ofrecidos: ${historial.map((o) => `${esc(fechaCorta(o.empieza))} ${hora(o.empieza)} (${esc(OFERTA[o.estado])})`).join(", ")}</small>` : ""}
    </div>
    <div class="lista-espera__estado">
      ${e.oferta ? `<span class="sello sello--en_sala">Ofrecido</span><small class="mono">${esc(fechaCorta(e.oferta.empieza))} ${hora(e.oferta.empieza)}<br>contesta hasta las ${hora(e.oferta.caduca_en)}</small>`
        : e.estado === "citada" ? `<span class="sello sello--confirmada">Citado</span>${e.cita_empieza ? `<small class="mono">${esc(fechaCorta(e.cita_empieza))} ${hora(e.cita_empieza)}</small>` : ""}`
        : e.estado === "retirada" ? `<span class="sello sello--anulada">Retirado</span>` : `<span class="rotulo">Esperando</span>`}
    </div>
    ${puede("citas") ? `<div class="acciones">
      ${ver === "activa" ? `<button class="boton boton--chico" type="button" data-accion="cita" data-id="${e.id}">Darle cita</button>
        <button class="boton boton--plano boton--chico" type="button" data-accion="retirada" data-id="${e.id}">Sacar de la lista</button>`
        : e.estado === "retirada" ? `<button class="boton boton--plano boton--chico" type="button" data-accion="esperando" data-id="${e.id}">Volver a la lista</button>` : ""}
    </div>` : ""}
  </li>`;
}

/** El impreso para apuntar a alguien en la lista. ini: { paciente, medico_id, motivo } */
export function formularioEspera(ini = {}) {
  const especialidades = [...new Set(estado.medicos.map((m) => m.especialidad))];
  let paciente = ini.paciente || null;
  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>Apuntar en la lista de espera</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <div class="campo"><span>Paciente</span><div data-paciente></div></div>
        <div class="filas">
          <label class="campo"><span>Con</span><select name="quien">
            ${estado.medicos.map((m) => `<option value="m${m.id}" ${m.id === ini.medico_id ? "selected" : ""}>${esc(m.nombre)}</option>`).join("")}
            ${especialidades.map((e) => `<option value="e${esc(e)}">Cualquiera de ${esc(e)}</option>`).join("")}
          </select></label>
          <label class="campo"><span>Mejor</span><select name="franja">${opciones(Object.entries(FRANJAS), "cualquiera")}</select></label>
        </div>
        <div class="filas">
          <label class="campo"><span>A partir del</span><input type="date" name="desde" value="${estado.hoy}" min="${estado.hoy}"></label>
          <label class="campo"><span>Y no más tarde del (opcional)</span><input type="date" name="hasta" min="${estado.hoy}"></label>
        </div>
        <label class="campo"><span>Motivo</span><input name="motivo" maxlength="160" value="${esc(ini.motivo || "")}"></label>
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">Apuntar en la lista</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    const zona = form.querySelector("[data-paciente]");
    const pintar = () => {
      if (paciente) {
        zona.innerHTML = `<div class="elegido"><b>${esc(paciente.apellidos)}, ${esc(paciente.nombre)}</b><button class="boton boton--plano boton--chico" type="button" data-cambiar>Cambiar</button></div>`;
        zona.querySelector("[data-cambiar]").onclick = () => { paciente = null; pintar(); };
        return;
      }
      zona.innerHTML = `<div class="buscador"><input type="search" placeholder="Apellidos, nombre, DNI o teléfono" autocomplete="off" aria-label="Buscar paciente">
        <ul class="buscador__lista" hidden></ul></div>`;
      const entrada = zona.querySelector("input"), lista = zona.querySelector("ul");
      let resultados = [], t;
      entrada.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(async () => {
          if (entrada.value.trim().length < 2) { lista.hidden = true; return; }
          resultados = (await api(`/api/pacientes?q=${encodeURIComponent(entrada.value.trim())}`)).pacientes.slice(0, 8);
          lista.hidden = !resultados.length;
          lista.innerHTML = resultados.map((p, i) => `<li><button type="button" data-i="${i}"><span>${esc(p.apellidos)}, ${esc(p.nombre)}</span><small>${esc(p.telefono || "")}</small></button></li>`).join("");
        }, 160);
      });
      lista.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) { paciente = resultados[Number(b.dataset.i)]; pintar(); } });
      setTimeout(() => entrada.focus(), 30);
    };
    pintar();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const error = form.querySelector(".mensaje-error");
      if (!paciente) { error.textContent = "Elige al paciente."; return; }
      const quien = form.quien.value;
      const datos = {
        paciente_id: paciente.id, franja: form.franja.value, desde: form.desde.value, hasta: form.hasta.value || null, motivo: form.motivo.value,
        ...(quien.startsWith("m") ? { medico_id: Number(quien.slice(1)) } : { especialidad: quien.slice(1) }),
      };
      const m = estado.medicos.find((x) => x.id === datos.medico_id);
      datos.minutos = m?.franjas[0]?.minutos || 20;
      try {
        await api("/api/espera", { metodo: "POST", datos });
        nota(`${paciente.nombre} ${paciente.apellidos} está en la lista de espera.`);
        cerrar(true);
      } catch (err) { error.textContent = err.message; }
    });
  });
}

export const resumen = (n) => plural(n, "persona espera", "personas esperan");
