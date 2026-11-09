// Médicos: su ficha, la plantilla semanal de horario y las ausencias.
import { estado, membrete, puede, cargarMedicos } from "./app.js";
import { api, esc, icono, nota, dialogo, datosFormulario, opciones, confirmar, DIAS, COLORES, fechaNum, plural, minutosDe, avatar } from "./util.js";

const INICIO = 7 * 60, FIN = 21 * 60;   // la regla del semanario: de 7:00 a 21:00

export async function mostrar(contenido) {
  document.title = "Médicos · Volante";
  membrete({ titulo: "Médicos y horarios", subtitulo: "Plantilla de cada consulta" });
  let todos;
  try { todos = await api(`/api/medicos?todos=1`); } catch (err) { contenido.innerHTML = `<p class="vacio">${esc(err.message)}</p>`; return; }
  if (!contenido.isConnected) return;
  const edita = puede("medicos");
  const activos = todos.filter((m) => m.activo), bajas = todos.filter((m) => !m.activo);
  contenido.innerHTML = `
    <div class="barra">
      ${edita ? `<button class="boton boton--tinta" type="button" data-alta>${icono("mas", 16)} Dar de alta un médico</button>` : `<p class="rotulo">Solo dirección y recepción cambian horarios</p>`}
    </div>
    <div class="medicos">
      ${activos.length ? activos.map((m) => plantilla(m, edita)).join("") : `<div class="vacio"><b>Aún no hay médicos.</b>Da de alta al primero con su especialidad y su consulta, y después ponle el horario semanal: de ahí salen los huecos del libro.</div>`}
      ${bajas.length ? `<section class="seccion"><h3>De baja</h3><ul class="renglones">${bajas.map((m) => `<li><span></span><span></span><span class="quien"><span>${esc(m.nombre)} · ${esc(m.especialidad)}</span></span>
        ${edita ? `<button class="boton boton--chico" type="button" data-reactivar="${m.id}">Volver a dar de alta</button>` : ""}</li>`).join("")}</ul></section>` : ""}
    </div>`;
  const porId = Object.fromEntries(todos.map((m) => [m.id, m]));
  const recargar = async () => { await cargarMedicos(); mostrar(contenido); };
  contenido.querySelector("[data-alta]")?.addEventListener("click", async () => { if (await fichaMedico()) recargar(); });
  contenido.querySelectorAll("[data-editar]").forEach((b) => b.addEventListener("click", async () => { if (await fichaMedico(porId[b.dataset.editar])) recargar(); }));
  contenido.querySelectorAll("[data-horario]").forEach((b) => b.addEventListener("click", async () => { if (await editorHorario(porId[b.dataset.horario])) recargar(); }));
  contenido.querySelectorAll("[data-ausencia]").forEach((b) => b.addEventListener("click", async () => { if (await nuevaAusencia(porId[b.dataset.ausencia])) recargar(); }));
  contenido.querySelectorAll("[data-quitar-ausencia]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/ausencias/${b.dataset.quitarAusencia}`, { metodo: "DELETE" }); } catch (err) { return nota(err.message, { error: true }); }
    nota("Ausencia quitada: vuelven sus huecos."); recargar();
  }));
  contenido.querySelectorAll("[data-reactivar]").forEach((b) => b.addEventListener("click", async () => {
    const m = porId[b.dataset.reactivar];
    try { await api(`/api/medicos/${m.id}`, { metodo: "PUT", datos: { ...m, activo: true } }); } catch (err) { return nota(err.message, { error: true }); }
    recargar();
  }));
}

function plantilla(m, edita) {
  const regla = [];
  for (let t = INICIO; t <= FIN; t += 120) regla.push(`<span style="left:${((t - INICIO) / (FIN - INICIO)) * 100}%">${String(t / 60).padStart(2, "0")}:00</span>`);
  const dias = DIAS.map((nombre, i) => {
    const franjas = m.franjas.filter((f) => f.dia === i + 1);
    if (!franjas.length && i >= 5) return "";
    return `<div class="semanario__dia"><span>${nombre.slice(0, 3)}</span><div class="semanario__carril">
      ${franjas.map((f) => {
        const a = Math.max(INICIO, minutosDe(f.desde)), b = Math.min(FIN, minutosDe(f.hasta));
        return `<span class="semanario__bloque" style="left:${((a - INICIO) / (FIN - INICIO)) * 100}%;width:${((b - a) / (FIN - INICIO)) * 100}%;--c:var(--t-${esc(m.color)})"
          title="${esc(`${f.desde}–${f.hasta}, citas de ${f.minutos} min`)}">${f.desde}–${f.hasta} · ${f.minutos}′</span>`;
      }).join("")}
    </div></div>`;
  }).join("");
  return `
    <article class="plantilla">
      <div class="plantilla__cabeza">
        <div>
          <h2>${avatar(m.nombre, m.color)}${esc(m.nombre)}</h2>
          <p>${esc([m.especialidad, m.consulta, m.colegiado ? `Col. ${m.colegiado}` : ""].filter(Boolean).join(" · "))}</p>
          <p class="mono" style="font-size:var(--t-xs);color:var(--tinta-3)">${m.franjas.length ? `${String(m.horas_semana).replace(".", ",")} h de consulta a la semana` : "Sin horario: no tiene huecos en el libro"}</p>
        </div>
        <div class="acciones">
          <a class="boton boton--plano boton--chico" href="#/semana/${m.id}/${estado.hoy}">Ver su semana</a>
          ${edita ? `<button class="boton boton--chico" type="button" data-editar="${m.id}">Datos</button>
          <button class="boton boton--chico" type="button" data-ausencia="${m.id}">Ausencia</button>
          <button class="boton boton--tinta boton--chico" type="button" data-horario="${m.id}">Horario</button>` : ""}
        </div>
      </div>
      <div class="semanario" aria-label="Horario semanal de ${esc(m.nombre)}">
        <div class="semanario__regla" aria-hidden="true">${regla.join("")}</div>
        ${dias}
      </div>
      ${m.ausencias.length ? `<ul class="ausencias">${m.ausencias.map((a) => `<li><span class="sello sello--anulada">Ausente</span>
        <span class="mono">${a.desde === a.hasta ? fechaNum(a.desde) : `${fechaNum(a.desde)} – ${fechaNum(a.hasta)}`}</span>
        <span>${esc(a.motivo || "")}</span>
        ${edita ? `<button class="boton boton--plano boton--chico" type="button" data-quitar-ausencia="${a.id}">Quitar</button>` : ""}</li>`).join("")}</ul>` : ""}
    </article>`;
}

function fichaMedico(m = null) {
  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>${m ? "Datos del médico" : "Alta de médico"}</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <label class="campo"><span>Nombre como lo verá el paciente</span><input name="nombre" required maxlength="80" value="${esc(m?.nombre)}" placeholder="Dra. Nombre Apellido"></label>
        <div class="filas">
          <label class="campo"><span>Especialidad</span><input name="especialidad" required maxlength="60" value="${esc(m?.especialidad)}" list="especialidades"></label>
          <label class="campo"><span>Consulta o sala</span><input name="consulta" maxlength="30" value="${esc(m?.consulta)}" placeholder="Consulta 2"></label>
          <label class="campo"><span>Nº de colegiado</span><input name="colegiado" maxlength="20" value="${esc(m?.colegiado)}"></label>
        </div>
        <datalist id="especialidades">${["Medicina de familia", "Pediatría", "Enfermería", "Dermatología", "Traumatología", "Ginecología", "Cardiología", "Fisioterapia", "Psicología", "Odontología", "Oftalmología"].map((e) => `<option value="${e}">`).join("")}</datalist>
        <div class="filas">
          <label class="campo"><span>Teléfono</span><input name="telefono" type="tel" maxlength="20" value="${esc(m?.telefono)}"></label>
          <label class="campo"><span>Correo</span><input name="email" type="email" maxlength="120" value="${esc(m?.email)}"></label>
        </div>
        <fieldset class="campo" style="border:0;padding:0;margin:0"><legend class="rotulo" style="padding:0;margin-bottom:8px">Color de su tampón en el libro</legend>
          <div class="colores">${Object.entries(COLORES).map(([c, n]) => `<label title="${n}"><input type="radio" name="color" value="${c}" ${c === (m?.color || "tinta") ? "checked" : ""} aria-label="${n}"><span style="--c:var(--t-${c})"></span></label>`).join("")}</div>
        </fieldset>
        ${m ? `<label class="casilla"><input type="checkbox" name="activo" ${m.activo ? "checked" : ""}> En activo (si lo quitas, deja de salir en el libro)</label>` : ""}
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">${m ? "Guardar" : "Dar de alta"}</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    form.nombre.focus();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const datos = datosFormulario(form);
      if (!m) datos.activo = true;
      try {
        const r = m ? await api(`/api/medicos/${m.id}`, { metodo: "PUT", datos }) : await api("/api/medicos", { metodo: "POST", datos });
        nota(m ? "Datos guardados." : "Médico dado de alta. Ahora ponle el horario.");
        cerrar(r);
      } catch (err) { form.querySelector(".mensaje-error").textContent = err.message; }
    });
  });
}

function editorHorario(m) {
  let franjas = m.franjas.map((f) => ({ dia: f.dia, desde: f.desde, hasta: f.hasta, minutos: f.minutos }));
  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>Horario de ${esc(m.nombre)}</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <p style="font-size:var(--t-s);color:var(--tinta-2)">Cada franja es un tramo en que pasa consulta. De ella salen los huecos: de 9:00 a 14:00 con citas de 20 minutos son 15 huecos. Las citas ya dadas no se tocan.</p>
        <div class="franjas-editor" data-franjas></div>
        <div class="acciones">
          <button class="boton boton--chico" type="button" data-anadir>${icono("mas", 14)} Añadir franja</button>
          <button class="boton boton--plano boton--chico" type="button" data-copiar>Copiar el lunes al resto de la semana laboral</button>
        </div>
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">Guardar el horario</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    const zona = d.querySelector("[data-franjas]");
    const leer = () => {
      franjas = [...zona.querySelectorAll(".franjas-editor__fila")].map((f) => ({
        dia: Number(f.querySelector("[name=dia]").value), desde: f.querySelector("[name=desde]").value,
        hasta: f.querySelector("[name=hasta]").value, minutos: Number(f.querySelector("[name=minutos]").value),
      }));
    };
    const pintar = () => {
      zona.innerHTML = franjas.length ? franjas.map((f, i) => `
        <div class="franjas-editor__fila">
          <label class="campo"><span>Día</span><select name="dia">${opciones(DIAS.map((n, j) => [j + 1, n]), f.dia)}</select></label>
          <label class="campo"><span>Desde</span><input name="desde" type="time" step="300" value="${f.desde}" required></label>
          <label class="campo"><span>Hasta</span><input name="hasta" type="time" step="300" value="${f.hasta}" required></label>
          <label class="campo"><span>Cita de</span><select name="minutos">${opciones([5, 10, 15, 20, 25, 30, 40, 45, 60, 90].map((n) => [n, `${n} min`]), f.minutos)}</select></label>
          <button type="button" class="quitar" data-quitar="${i}" aria-label="Quitar esta franja">${icono("cerrar", 16)}</button>
        </div>`).join("") : `<p class="vacio">Sin franjas: no tendrá huecos en el libro.</p>`;
    };
    pintar();
    zona.addEventListener("click", (e) => {
      const b = e.target.closest("[data-quitar]");
      if (!b) return;
      leer(); franjas.splice(Number(b.dataset.quitar), 1); pintar();
    });
    d.querySelector("[data-anadir]").addEventListener("click", () => {
      leer();
      const ultima = franjas[franjas.length - 1];
      franjas.push(ultima ? { ...ultima, dia: Math.min(7, ultima.dia + 1) } : { dia: 1, desde: "09:00", hasta: "14:00", minutos: 20 });
      pintar();
      zona.lastElementChild.querySelector("select")?.focus();
    });
    d.querySelector("[data-copiar]").addEventListener("click", () => {
      leer();
      const lunes = franjas.filter((f) => f.dia === 1);
      if (!lunes.length) { form.querySelector(".mensaje-error").textContent = "Pon primero las franjas del lunes."; return; }
      franjas = [...lunes, ...[2, 3, 4, 5].flatMap((dia) => lunes.map((f) => ({ ...f, dia }))), ...franjas.filter((f) => f.dia >= 6)];
      pintar();
    });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      leer();
      try {
        const r = await api(`/api/medicos/${m.id}/horario`, { metodo: "PUT", datos: { franjas } });
        nota(r.citas_fuera.length ? `Horario guardado. ${plural(r.citas_fuera.length, "cita ya dada queda", "citas ya dadas quedan")} fuera de él: revísalas en su semana.` : "Horario guardado.", { segundos: 8 });
        cerrar(r);
      } catch (err) { form.querySelector(".mensaje-error").textContent = err.message; }
    });
  });
}

function nuevaAusencia(m) {
  return dialogo(`
    <form novalidate>
      <div class="impreso__cabeza"><h2>Ausencia de ${esc(m.nombre)}</h2><button class="boton boton--plano" type="button" data-cerrar>Cerrar</button></div>
      <div class="impreso__cuerpo">
        <div class="filas">
          <label class="campo"><span>Desde</span><input name="desde" type="date" required min="${estado.hoy}" value="${estado.hoy}"></label>
          <label class="campo"><span>Hasta (incluido)</span><input name="hasta" type="date" required min="${estado.hoy}" value="${estado.hoy}"></label>
        </div>
        <label class="campo"><span>Motivo</span><input name="motivo" maxlength="120" placeholder="Vacaciones, congreso, guardia…"></label>
        <p style="font-size:var(--t-s);color:var(--tinta-2)">Esos días no tendrá huecos. Si ya tenía citas, siguen dadas: muévelas desde su semana.</p>
      </div>
      <div class="impreso__pie">
        <p class="mensaje-error" role="alert"></p>
        <button class="boton" type="button" data-cerrar>Cancelar</button>
        <button class="boton boton--tinta" type="submit">Apuntar la ausencia</button>
      </div>
    </form>`, (d, cerrar) => {
    const form = d.querySelector("form");
    form.desde.addEventListener("change", () => { if (form.hasta.value < form.desde.value) form.hasta.value = form.desde.value; form.hasta.min = form.desde.value; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const r = await api(`/api/medicos/${m.id}/ausencias`, { metodo: "POST", datos: datosFormulario(form) });
        if (r.citas_afectadas) {
          await confirmar("Ausencia apuntada", `Ojo: ${plural(r.citas_afectadas, "cita ya dada cae", "citas ya dadas caen")} en esos días. Muévelas o anúlalas desde su semana para avisar a los pacientes.`, { boton: "Entendido" });
        } else nota("Ausencia apuntada.");
        cerrar(r);
      } catch (err) { form.querySelector(".mensaje-error").textContent = err.message; }
    });
  });
}
