// Papeles que salen por la impresora (o a PDF): la hoja del día y el justificante de asistencia.
// Se monta un bloque .impresion que solo se ve al imprimir; la pantalla no cambia.
import { estado } from "./app.js";
import { esc, hora, fechaLarga, fechaNum, ESTADOS } from "./util.js";

function imprimir(html, titulo) {
  document.querySelector(".impresion")?.remove();
  const el = document.createElement("div");
  el.className = "impresion";
  el.innerHTML = html;
  document.body.append(el);
  const antes = document.title;
  document.title = titulo;          // el nombre que propone el navegador al guardar como PDF
  const limpiar = () => { el.remove(); document.title = antes; removeEventListener("afterprint", limpiar); };
  addEventListener("afterprint", limpiar);
  requestAnimationFrame(() => print());
}

const cabecera = () => `
  <header class="impresion__membrete">
    <div><b>${esc(estado.ajustes.centro || "")}</b><span>${esc(estado.ajustes.direccion || "")}${estado.ajustes.telefono ? ` · Tel. ${esc(estado.ajustes.telefono)}` : ""}</span></div>
  </header>`;

/** columnas: [{ titulo, subtitulo, citas, ausencia }] — una por médico (día) o por día (semana). */
export function hojaDelDia(columnas, titulo) {
  const bloques = columnas.filter((c) => c.citas.some((x) => x.estado !== "anulada") || c.ausencia).map((c) => {
    const vivas = c.citas.filter((x) => x.estado !== "anulada");
    return `
      <section class="impresion__bloque">
        <h2>${esc(c.titulo)} <small>${esc(c.subtitulo || "")}</small></h2>
        ${c.ausencia ? `<p>No pasa consulta: ${esc(c.ausencia.motivo || "ausente")}.</p>` : `
        <table>
          <thead><tr><th>Hora</th><th>Paciente</th><th>Teléfono</th><th>Motivo</th><th>Estado</th><th>Llegó</th></tr></thead>
          <tbody>${vivas.map((x) => `<tr>
            <td class="mono">${hora(x.empieza)}</td>
            <td><b>${esc(x.apellidos)}, ${esc(x.nombre)}</b>${x.notas_paciente ? `<br><small>${esc(x.notas_paciente)}</small>` : ""}</td>
            <td class="mono">${esc(x.telefono || "")}</td>
            <td>${esc(x.motivo || "")}</td>
            <td>${x.estado === "pendiente" ? "Sin confirmar" : esc(ESTADOS[x.estado])}</td>
            <td class="casilla-papel">${x.llegada ? hora(x.llegada) : "☐"}</td></tr>`).join("")}</tbody>
        </table>`}
      </section>`;
  });
  imprimir(`${cabecera()}<h1>${esc(titulo)}</h1>${bloques.join("") || "<p>No hay citas en esta hoja.</p>"}
    <footer class="impresion__pie">Impreso el ${fechaNum(estado.hoy)} · Volante</footer>`, `Hoja ${titulo}`);
}

export function justificante(j) {
  const nombre = `${j.nombre} ${j.apellidos}`;
  imprimir(`${cabecera()}
    <article class="impresion__justificante">
      <h1>Justificante de asistencia</h1>
      <p>Se hace constar que <b>${esc(nombre)}</b>${j.documento ? `, con documento <b>${esc(j.documento)}</b>,` : ""} ha asistido a consulta de
        <b>${esc(j.especialidad)}</b> con ${esc(j.medico)}${j.colegiado ? ` (col. ${esc(j.colegiado)})` : ""}
        el <b>${esc(fechaLarga(j.desde, { año: true }))}</b>, entre las <b>${hora(j.desde)}</b> y las <b>${hora(j.hasta)}</b>.</p>
      <p>Y para que conste a los efectos oportunos, se expide el presente justificante.</p>
      <div class="impresion__firma"><span>Firma y sello del centro</span></div>
      <p class="impresion__codigo">Código de verificación <b class="mono">${esc(j.codigo)}</b><br>
        Comprobar en <span class="mono">${esc(j.verificar)}</span></p>
      <p class="impresion__legal">Este documento solo acredita la asistencia y la hora. No contiene información clínica.</p>
    </article>`, `Justificante ${nombre} ${j.desde.slice(0, 10)}`);
}
