// Ajustes: el centro, las reglas de los recordatorios, el equipo y la contraseña propia.
import { estado, membrete, puede } from "./app.js";
import { api, esc, nota, dialogo, confirmar, datosFormulario, opciones, ROLES, tipoAviso, cuandoRelativo, fechaLarga, sumarDias } from "./util.js";

export async function mostrar(contenido) {
  document.title = "Ajustes · Volante";
  membrete({ titulo: "Ajustes", subtitulo: estado.ajustes.centro || "" });
  const aj = await api("/api/ajustes");
  if (!contenido.isConnected) return;
  estado.ajustes = aj;
  const manda = puede("ajustes");
  const dis = manda ? "" : "disabled";
  let horas = (aj.avisos_horas || "").split(",").filter(Boolean).map(Number);

  contenido.innerHTML = `
    <div class="ajustes">
      <section>
        <header><h2>El centro</h2><p>Sale en el membrete, en los recordatorios y en la página de cita del paciente.</p></header>
        <form data-centro>
          <label class="campo"><span>Nombre</span><input name="centro" maxlength="80" value="${esc(aj.centro)}" ${dis} required></label>
          <label class="campo"><span>Dirección</span><input name="direccion" maxlength="160" value="${esc(aj.direccion)}" ${dis} autocomplete="street-address"></label>
          <label class="campo"><span>Teléfono para cambios</span><input name="telefono" maxlength="30" value="${esc(aj.telefono)}" ${dis} type="tel"></label>
          ${manda ? `<div class="acciones"><button class="boton boton--tinta" type="submit">Guardar</button></div>` : ""}
        </form>
      </section>

      <section>
        <header><h2>Recordatorios</h2><p>Se programan solos al dar cada cita. Si cambias las horas, las citas ya dadas pasan a seguir la regla nueva.</p></header>
        <form data-avisos>
          <div class="campo"><span>Avisar antes de la cita</span>
            <div class="fichas-horas" data-horas></div>
            ${manda ? `<div class="acciones" style="margin-top:8px"><label class="campo" style="width:auto"><span class="sr">Horas antes</span>
              <input type="number" min="1" max="336" step="1" placeholder="horas" data-nueva-hora></label>
              <button class="boton boton--chico" type="button" data-anadir-hora>Añadir aviso</button></div>
              <small>En horas: 24 es un día antes; 2, dos horas antes. Como mucho cuatro.</small>` : ""}
          </div>
          <label class="casilla"><input type="checkbox" name="aviso_reserva" ${aj.aviso_reserva === "si" ? "checked" : ""} ${dis}> Mandar también un aviso al dar o mover la cita, con el enlace para confirmarla o anularla</label>
          <label class="casilla"><input type="checkbox" name="citas_por_enlace" ${aj.citas_por_enlace !== "no" ? "checked" : ""} ${dis}> Que el paciente pueda pedir otra cita desde su enlace (con su mismo médico, dos como mucho)</label>
          <label class="campo" style="max-width:320px"><span>Lista de espera: horas para contestar a una oferta</span>
            <input type="number" name="oferta_horas" min="1" max="48" value="${esc(aj.oferta_horas || "3")}" ${dis} inputmode="numeric">
            <small>Si no contesta, el hueco pasa al siguiente. Nunca más tarde de una hora antes de la cita.</small></label>
          <div class="campo"><span>Así le llega por correo</span><p class="muestra" data-muestra></p></div>
          ${manda ? `<div class="acciones"><button class="boton boton--tinta" type="submit">Guardar las reglas</button></div>` : ""}
          <p style="font-size:var(--t-s);color:var(--tinta-2)">${aj.correo_configurado ? "El servidor de correo está configurado: los correos salen solos." : "Sin servidor de correo: los avisos esperan en la bandeja para mandarlos a mano."}</p>
        </form>
      </section>

      ${puede("equipo") ? `<section>
        <header><h2>Equipo</h2><p>Una cuenta por persona. Recepción da citas y lleva el fichero; cada médico ve todo el libro, sella sus citas y escribe sus notas clínicas.</p></header>
        <div><ul class="equipo" data-equipo><li class="cargando">Cargando…</li></ul>
          <div class="acciones" style="margin-top:12px"><button class="boton boton--chico" type="button" data-miembro>Nueva cuenta</button></div></div>
      </section>` : ""}

      <section>
        <header><h2>Tu contraseña</h2><p>Entras como <b>${esc(estado.yo.usuario)}</b> (${esc(ROLES[estado.yo.rol])}).</p></header>
        <form data-clave>
          <label class="campo"><span>Contraseña actual</span><input name="actual" type="password" autocomplete="current-password" required></label>
          <label class="campo"><span>Contraseña nueva</span><input name="nueva" type="password" autocomplete="new-password" minlength="10" required><small>10 caracteres como mínimo.</small></label>
          <p class="mensaje-error" role="alert"></p>
          <div class="acciones"><button class="boton" type="submit">Cambiar la contraseña</button></div>
        </form>
      </section>

      ${puede("equipo") && estado.yo.centro_id !== 1 ? `<section class="ajustes__baja">
        <header><h2>Borrar el centro</h2><p>Se borra todo, para siempre: pacientes, citas, avisos, médicos y las cuentas de todo el equipo.</p></header>
        <form data-baja>
          <label class="campo"><span>Escribe tu contraseña para confirmarlo</span><input name="contrasena" type="password" autocomplete="current-password" required></label>
          <p class="mensaje-error" role="alert"></p>
          <div class="acciones"><button class="boton boton--peligro" type="submit">Borrar ${esc(aj.centro)} y todos sus datos</button></div>
        </form>
      </section>` : ""}
    </div>`;

  const zonaHoras = contenido.querySelector("[data-horas]");
  const muestra = contenido.querySelector("[data-muestra]");
  const pintarHoras = () => {
    zonaHoras.innerHTML = horas.length
      ? horas.sort((a, b) => b - a).map((h) => `<span>${esc(tipoAviso(`antes_${h}`))}${manda ? `<button type="button" data-quitar-hora="${h}" aria-label="Quitar el aviso de ${h} horas">×</button>` : ""}</span>`).join("")
      : `<small>Sin avisos antes de la cita.</small>`;
    const c = contenido.querySelector("[data-centro]");
    const centro = c.centro.value || "la consulta";
    const manana = `${fechaLarga(sumarDias(estado.hoy, 1), { año: true })}, a las 10:20`;
    muestra.textContent = `Asunto: Recordatorio de su cita: ${manana}\n\nHola, Ana:\n\nLe recordamos su cita en ${centro}:\n\n  ${manana[0].toUpperCase() + manana.slice(1)}\n  ${estado.medicos[0]?.nombre || "Dra. …"}${estado.medicos[0]?.consulta ? ` · ${estado.medicos[0].consulta}` : ""}\n  ${c.direccion.value}\n\nPara confirmar que viene, o anularla si no puede: (enlace personal)\n\nSi no puede venir, avísenos y daremos el hueco a otra persona.${c.telefono.value ? `\nTeléfono: ${c.telefono.value}` : ""}`;
  };
  pintarHoras();
  contenido.querySelector("[data-centro]").addEventListener("input", pintarHoras);
  zonaHoras.addEventListener("click", (e) => {
    const b = e.target.closest("[data-quitar-hora]");
    if (b) { horas = horas.filter((h) => h !== Number(b.dataset.quitarHora)); pintarHoras(); }
  });
  contenido.querySelector("[data-anadir-hora]")?.addEventListener("click", () => {
    const campo = contenido.querySelector("[data-nueva-hora]");
    const h = Math.round(Number(campo.value));
    if (!h || h < 1 || h > 336) return nota("Pon un número de horas entre 1 y 336 (dos semanas).", { error: true });
    if (horas.length >= 4) return nota("Como mucho cuatro avisos antes de cada cita.", { error: true });
    if (!horas.includes(h)) horas.push(h);
    campo.value = "";
    pintarHoras();
  });

  contenido.querySelector("[data-centro]").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { estado.ajustes = await api("/api/ajustes", { metodo: "PUT", datos: datosFormulario(e.target) }); nota("Datos del centro guardados."); membrete({ titulo: "Ajustes", subtitulo: estado.ajustes.centro }); }
    catch (err) { nota(err.message, { error: true }); }
  });
  contenido.querySelector("[data-avisos]").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      estado.ajustes = await api("/api/ajustes", { metodo: "PUT", datos: {
        avisos_horas: horas.join(","), aviso_reserva: e.target.aviso_reserva.checked ? "si" : "no",
        citas_por_enlace: e.target.citas_por_enlace.checked ? "si" : "no", oferta_horas: e.target.oferta_horas.value,
      } });
      nota("Reglas guardadas. Los recordatorios de las citas ya dadas se han reprogramado.");
    } catch (err) { nota(err.message, { error: true }); }
  });
  contenido.querySelector("[data-clave]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = e.target.querySelector(".mensaje-error");
    error.textContent = "";
    try { await api("/api/clave", { metodo: "POST", datos: datosFormulario(e.target) }); e.target.reset(); nota("Contraseña cambiada."); }
    catch (err) { error.textContent = err.message; }
  });
  if (puede("equipo")) pintarEquipo(contenido);
  contenido.querySelector("[data-baja]")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const error = e.target.querySelector(".mensaje-error");
    error.textContent = "";
    const ok = await confirmar("¿Borrar el centro entero?", `${aj.centro}: se borran todos sus pacientes, citas, avisos y cuentas. No se puede deshacer.`,
      { boton: "Borrarlo para siempre", peligro: true });
    if (!ok) return;
    try {
      await api("/api/centro", { metodo: "DELETE", datos: { contrasena: e.target.contrasena.value } });
    } catch (err) { error.textContent = err.message; return; }
    location.replace(location.pathname);    // carga de cero, sin pasar por ninguna sección con la sesión ya borrada
  });
}

async function pintarEquipo(contenido) {
  const lista = contenido.querySelector("[data-equipo]");
  const gente = await api("/api/equipo");
  const medico = (id) => estado.medicos.find((m) => m.id === id)?.nombre;
  lista.innerHTML = gente.map((u) => `
    <li><span><b>${esc(u.nombre)}</b><small class="mono">${esc(u.usuario)} · ${esc(ROLES[u.rol])}${u.medico_id ? ` · ${esc(medico(u.medico_id) || "")}` : ""}${u.ultimo_acceso ? ` · entró ${esc(cuandoRelativo(u.ultimo_acceso, `${estado.hoy} 00:00:00`))}` : " · aún no ha entrado"}</small></span>
      <button class="boton boton--plano boton--chico" type="button" data-nueva-clave="${u.id}">Poner contraseña</button>
      ${u.id === estado.yo.id ? `<span class="rotulo">Tú</span>` : `<button class="boton boton--chico ${u.activo ? "boton--peligro" : ""}" type="button" data-activo="${u.id}" data-valor="${u.activo ? 0 : 1}">${u.activo ? "Desactivar" : "Activar"}</button>`}
    </li>`).join("");
  lista.querySelectorAll("[data-activo]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/equipo/${b.dataset.activo}`, { metodo: "PUT", datos: { activo: b.dataset.valor === "1" } }); } catch (err) { return nota(err.message, { error: true }); }
    pintarEquipo(contenido);
  }));
  lista.querySelectorAll("[data-nueva-clave]").forEach((b) => b.addEventListener("click", async () => {
    const clave = await dialogo(`<form novalidate><div class="impreso__cabeza"><h2>Contraseña nueva</h2></div>
      <div class="impreso__cuerpo"><label class="campo"><span>Contraseña (10 caracteres como mínimo)</span><input name="c" type="text" minlength="10" autocomplete="off" required></label>
      <p style="font-size:var(--t-s);color:var(--tinta-2)">Dísela en persona. Su sesión abierta se cierra.</p></div>
      <div class="impreso__pie"><button class="boton" type="button" data-cerrar>Cancelar</button><button class="boton boton--tinta" type="submit">Guardar</button></div></form>`,
    (d, cerrar) => { d.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); cerrar(e.target.c.value); }); d.querySelector("input").focus(); });
    if (!clave) return;
    try { await api(`/api/equipo/${b.dataset.nuevaClave}`, { metodo: "PUT", datos: { contrasena: clave } }); nota("Contraseña cambiada."); } catch (err) { nota(err.message, { error: true }); }
  }));
  contenido.querySelector("[data-miembro]").onclick = async () => {
    const ok = await dialogo(`
      <form novalidate>
        <div class="impreso__cabeza"><h2>Nueva cuenta</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
        <div class="impreso__cuerpo">
          <div class="filas">
            <label class="campo"><span>Nombre</span><input name="nombre" required maxlength="80"></label>
            <label class="campo"><span>Usuario</span><input name="usuario" required maxlength="30" autocapitalize="none" spellcheck="false" autocomplete="off"></label>
          </div>
          <div class="filas">
            <label class="campo"><span>Papel</span><select name="rol">${opciones(Object.entries(ROLES), "recepcion")}</select></label>
            <label class="campo" data-medico hidden><span>Es el médico</span><select name="medico_id">${opciones(estado.medicos.map((m) => [m.id, m.nombre]))}</select></label>
          </div>
          <label class="campo"><span>Contraseña inicial</span><input name="contrasena" type="text" minlength="10" required autocomplete="off"><small>Que la cambie al entrar, desde Ajustes.</small></label>
        </div>
        <div class="impreso__pie"><p class="mensaje-error" role="alert"></p><button class="boton" type="button" data-cerrar>Cancelar</button><button class="boton boton--tinta" type="submit">Crear la cuenta</button></div>
      </form>`, (d, cerrar) => {
      const form = d.querySelector("form");
      const zonaMedico = form.querySelector("[data-medico]");
      form.rol.addEventListener("change", () => { zonaMedico.hidden = form.rol.value !== "medico"; });
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const datos = datosFormulario(form);
        if (datos.rol !== "medico") delete datos.medico_id;
        try { await api("/api/equipo", { metodo: "POST", datos }); cerrar(true); } catch (err) { form.querySelector(".mensaje-error").textContent = err.message; }
      });
    });
    if (ok) { nota("Cuenta creada."); pintarEquipo(contenido); }
  };
}
