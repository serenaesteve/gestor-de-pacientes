// Informe del mes: ocupación por médico, asistencia, sala de espera, avisos y lista de espera.
import { estado, membrete, recordarDia } from "./app.js";
import { api, esc, icono, MESES, deIso, fechaCorta, CANALES } from "./util.js";
import { contar } from "./vivo.js";

const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)} %`);
const horas = (min) => `${(min / 60).toLocaleString("es-ES", { maximumFractionDigits: 1 })} h`;
const SERIES = [
  { clave: "atendidas", nombre: "Atendidas", color: "var(--g-atendida)" },
  { clave: "no_acudio", nombre: "No acudió", color: "var(--g-falta)" },
  { clave: "pendientes", nombre: "Por venir", color: "var(--g-pendiente)" },
];

function mesVecino(mes, n) {
  const [a, m] = mes.split("-").map(Number);
  const d = new Date(a, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export async function mostrar(contenido, { params }) {
  const mes = /^\d{4}-\d{2}$/.test(params[0] || "") ? params[0] : estado.hoy.slice(0, 7);
  recordarDia(`${mes}-01`);
  const [a, m] = mes.split("-").map(Number);
  const nombreMes = `${MESES[m - 1]} de ${a}`;
  document.title = `Informe de ${nombreMes} · Volante`;
  contenido.innerHTML = `<p class="cargando">Haciendo las cuentas del mes…</p>`;
  const ancho = Math.max(300, contenido.clientWidth - 48);   // el gráfico se dibuja a su tamaño real: la letra no se estira
  const inf = await api(`/api/informe?mes=${mes}`);
  if (!contenido.isConnected) return;
  const t = inf.totales;
  membrete({ titulo: nombreMes[0].toUpperCase() + nombreMes.slice(1), subtitulo: "Informe del mes" });

  contenido.innerHTML = `
    <div class="barra">
      <a class="boton boton--chico" href="#/informe/${mesVecino(mes, -1)}">${icono("izquierda", 14)} ${esc(MESES[(m + 10) % 12])}</a>
      <a class="boton boton--chico" href="#/informe/${mesVecino(mes, 1)}">${esc(MESES[m % 12])} ${icono("derecha", 14)}</a>
      <span class="barra__hueco"></span>
      <button class="boton boton--plano" type="button" data-csv>Descargar CSV</button>
      <button class="boton boton--plano" type="button" data-pdf>${icono("imprimir", 16)} Imprimir o guardar en PDF</button>
    </div>
    ${inf.cerrado ? "" : `<p class="explica">El mes aún no ha terminado: la ocupación cuenta las citas ya dadas para los días que quedan.</p>`}

    <section class="cifras" aria-label="Resumen del mes">
      ${cifra(pct(t.ocupacion), "Ocupación", `${horas(t.minutos_citados || 0)} citadas de ${horas(t.minutos_consulta || 0)} de consulta`)}
      ${cifra(t.citas || 0, "Citas", `${t.atendidas || 0} atendidas · ${t.pendientes || 0} por venir`)}
      ${cifra(pct(t.faltas), "No acudieron", `${t.no_acudio || 0} de ${(t.atendidas || 0) + (t.no_acudio || 0)} citas ya pasadas`)}
      ${cifra(pct(t.confirmadas), "Confirmadas", "de las citas que siguen en pie")}
      ${cifra(t.espera_media === null ? "—" : `${t.espera_media}′`, "Espera en sala", "de media, de la llegada a pasar")}
      ${cifra((t.anuladas_paciente || 0) + (t.anuladas_centro || 0), "Anuladas", `${t.anuladas_paciente || 0} por el paciente · ${t.anuladas_centro || 0} en el centro`)}
    </section>

    <section class="seccion">
      <h3>Citas por día</h3>
      ${grafico(inf.por_dia, ancho)}
    </section>

    <section class="seccion">
      <h3>Por médico</h3>
      ${inf.medicos.length ? tablaMedicos(inf.medicos) : `<p class="vacio">Ningún médico pasó consulta este mes.</p>`}
    </section>

    <div class="informe__pareja">
      <section class="seccion">
        <h3>Recordatorios</h3>
        ${tablaAvisos(inf.avisos)}
      </section>
      <section class="seccion">
        <h3>Lista de espera</h3>
        <dl class="informe__lista">
          <div><dt>Apuntados este mes</dt><dd>${inf.espera.nuevas}</dd></div>
          <div><dt>Huecos ofrecidos</dt><dd>${inf.espera.ofertas}</dd></div>
          <div><dt>Aceptados</dt><dd>${inf.espera.aceptadas}</dd></div>
          <div><dt>No les venía bien o no contestaron</dt><dd>${inf.espera.rechazadas + inf.espera.caducadas}</dd></div>
          <div><dt>Siguen esperando hoy</dt><dd>${inf.espera.esperando}</dd></div>
        </dl>
        <h3 style="margin-top:24px">Cómo se pidieron</h3>
        <dl class="informe__lista">
          ${[["recepcion", "En el mostrador"], ["telefono", "Por teléfono"], ["paciente", "El paciente, desde su enlace"], ["espera", "Desde la lista de espera"]]
            .map(([k, n]) => `<div><dt>${n}</dt><dd>${t.origen?.[k] || 0}</dd></div>`).join("")}
        </dl>
      </section>
    </div>`;
  conectarGrafico(contenido);
  contar(contenido);
  contenido.querySelector("[data-pdf]").addEventListener("click", () => print());
  contenido.querySelector("[data-csv]").addEventListener("click", () => descargarCSV(inf));
}

// Las cifras cuentan desde cero al abrir el informe (data-cuenta); sin movimiento, salen ya hechas.
const cifra = (valor, titulo, detalle) => {
  const m = String(valor).match(/^(\d+)(.*)$/);
  const cuenta = m ? ` data-cuenta="${m[1]}" data-sufijo="${esc(m[2])}"` : "";
  return `<div class="cifra"><span class="rotulo">${esc(titulo)}</span><b${cuenta}>${esc(String(valor))}</b><small>${esc(detalle)}</small></div>`;
};

// ---------- gráfico de barras apiladas, un día por barra ----------
function grafico(dias, W) {
  const max = Math.max(1, ...dias.map((d) => d.atendidas + d.no_acudio + d.pendientes));
  const paso = max <= 10 ? 2 : max <= 25 ? 5 : max <= 60 ? 10 : 20;
  const tope = Math.ceil(max / paso) * paso;
  const H = W < 500 ? 180 : 240, IZQ = 32, ABAJO = 26, ARRIBA = 8;
  const ancho = (W - IZQ) / dias.length;
  const cada = ancho < 14 ? 5 : ancho < 24 ? 2 : 1;      // etiquetas de día que caben sin pisarse
  const barra = Math.max(4, Math.min(18, ancho - 6));
  const y = (v) => ARRIBA + (H - ARRIBA - ABAJO) * (1 - v / tope);
  const rejilla = [];
  for (let v = 0; v <= tope; v += paso) {
    rejilla.push(`<line x1="${IZQ}" x2="${W}" y1="${y(v)}" y2="${y(v)}" class="g-rejilla${v === 0 ? " g-base" : ""}"/>
      <text x="${IZQ - 6}" y="${y(v) + 3}" class="g-eje" text-anchor="end">${v}</text>`);
  }
  const barras = dias.map((d, i) => {
    const x = IZQ + i * ancho + (ancho - barra) / 2;
    const dia = deIso(d.fecha);
    const finde = dia.getDay() === 0 || dia.getDay() === 6;
    let base = 0;
    const visibles = SERIES.filter((s) => d[s.clave] > 0);
    const trozos = visibles.map((s, j) => {
      const v = d[s.clave];
      const y0 = y(base), y1 = y(base + v);
      base += v;
      const alto = Math.max(1, y0 - y1 - (j < visibles.length - 1 ? 2 : 0));   // 2 px de papel entre trozos
      const arriba = y0 - alto;
      if (j === visibles.length - 1) {     // el extremo de arriba, redondeado
        const r = Math.min(4, barra / 2, alto);
        return `<path d="M${x},${y0} V${arriba + r} Q${x},${arriba} ${x + r},${arriba} H${x + barra - r} Q${x + barra},${arriba} ${x + barra},${arriba + r} V${y0} Z" fill="${s.color}"/>`;
      }
      return `<rect x="${x}" y="${arriba}" width="${barra}" height="${alto}" fill="${s.color}"/>`;
    }).join("");
    const etiqueta = (dia.getDate() === 1 || dia.getDate() % cada === 0) && (dias.length - 1 - i >= cada / 2 || i === dias.length - 1)
      ? `<text x="${x + barra / 2}" y="${H - 8}" class="g-eje${finde ? " g-eje--finde" : ""}" text-anchor="middle">${dia.getDate()}</text>` : "";
    return `<g class="g-dia" data-i="${i}" style="--i:${i}">${trozos}${etiqueta}
      <rect class="g-diana" x="${IZQ + i * ancho}" y="${ARRIBA}" width="${ancho}" height="${H - ARRIBA - ABAJO}" fill="transparent"/></g>`;
  }).join("");
  return `
    <div class="grafico">
      <ul class="leyenda">${SERIES.map((s) => `<li><span style="background:${s.color}"></span>${s.nombre}</li>`).join("")}</ul>
      <div class="grafico__lienzo">
        <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Citas de cada día del mes, por estado. Los datos están en la tabla de debajo.">${rejilla.join("")}${barras}</svg>
        <div class="grafico__globo" hidden></div>
      </div>
      <details class="grafico__tabla"><summary>Ver los datos en una tabla</summary>
        <table><thead><tr><th>Día</th>${SERIES.map((s) => `<th>${s.nombre}</th>`).join("")}<th>Anuladas</th></tr></thead>
        <tbody>${dias.map((d) => `<tr><td>${esc(fechaCorta(d.fecha))}</td><td>${d.atendidas}</td><td>${d.no_acudio}</td><td>${d.pendientes}</td><td>${d.anuladas}</td></tr>`).join("")}</tbody></table>
      </details>
    </div>`;
}

function conectarGrafico(contenido) {
  const lienzo = contenido.querySelector(".grafico__lienzo");
  if (!lienzo) return;
  const globo = lienzo.querySelector(".grafico__globo");
  const dias = [...contenido.querySelectorAll(".grafico__tabla tbody tr")].map((tr) => [...tr.children].map((td) => td.textContent));
  lienzo.addEventListener("pointermove", (e) => {
    const g = e.target.closest(".g-dia");
    lienzo.querySelectorAll(".g-dia--activo").forEach((x) => x !== g && x.classList.remove("g-dia--activo"));
    if (!g) { globo.hidden = true; return; }
    g.classList.add("g-dia--activo");
    const [dia, at, fa, pe, an] = dias[Number(g.dataset.i)];
    globo.innerHTML = `<b>${esc(dia)}</b>
      ${SERIES.map((s, i) => `<span><i style="background:${s.color}"></i>${s.nombre}<b class="mono">${[at, fa, pe][i]}</b></span>`).join("")}
      ${Number(an) ? `<span><i></i>Anuladas<b class="mono">${an}</b></span>` : ""}`;
    globo.hidden = false;
    const caja = lienzo.getBoundingClientRect();
    const x = e.clientX - caja.left;
    globo.style.left = `${Math.min(caja.width - globo.offsetWidth - 4, Math.max(4, x + 12))}px`;
    globo.style.top = `${Math.max(0, e.clientY - caja.top - globo.offsetHeight - 12)}px`;
  });
  lienzo.addEventListener("pointerleave", () => { globo.hidden = true; lienzo.querySelectorAll(".g-dia--activo").forEach((x) => x.classList.remove("g-dia--activo")); });
}

function tablaMedicos(medicos) {
  return `<div class="tabla-desliza"><table class="tabla-informe">
    <thead><tr><th>Médico</th><th>Ocupación</th><th>Consulta</th><th>Citas</th><th>Atendidas</th><th>No acudió</th><th>Anuladas</th><th>Espera</th></tr></thead>
    <tbody>${medicos.map((m) => `<tr>
      <td><span class="quien"><span class="tampon" style="--c:var(--t-${esc(m.color)})"></span><span><b>${esc(m.nombre)}</b><small>${esc(m.especialidad)}</small></span></span></td>
      <td><span class="medidor" role="img" aria-label="Ocupación ${pct(m.ocupacion)}"><span style="width:${Math.min(100, Math.round((m.ocupacion || 0) * 100))}%"></span></span><b class="mono">${pct(m.ocupacion)}</b></td>
      <td class="mono">${horas(m.minutos_consulta)}</td>
      <td class="mono">${m.citas}</td>
      <td class="mono">${m.atendidas}</td>
      <td class="mono">${m.no_acudio}${m.faltas !== null ? ` <small>(${pct(m.faltas)})</small>` : ""}</td>
      <td class="mono">${m.anuladas}</td>
      <td class="mono">${m.espera_media === null ? "—" : `${m.espera_media}′`}</td></tr>`).join("")}</tbody></table></div>`;
}

function tablaAvisos(avisos) {
  const canales = Object.keys(avisos);
  if (!canales.length) return `<p class="vacio">Ningún recordatorio tocaba este mes.</p>`;
  const cols = [["enviado", "Enviados"], ["en_bandeja", "Por mandar"], ["pendiente", "Programados"], ["fallido", "Fallaron"], ["anulado", "Anulados"]];
  return `<div class="tabla-desliza"><table class="tabla-informe">
    <thead><tr><th>Canal</th>${cols.map(([, n]) => `<th>${n}</th>`).join("")}</tr></thead>
    <tbody>${canales.map((c) => `<tr><td>${esc(CANALES[c] || c)}</td>${cols.map(([k]) => `<td class="mono">${avisos[c][k] || 0}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function descargarCSV(inf) {
  const filas = [["medico", "especialidad", "minutos_consulta", "minutos_citados", "ocupacion", "citas", "atendidas", "no_acudio", "anuladas", "espera_media_min"]];
  for (const m of inf.medicos) {
    filas.push([m.nombre, m.especialidad, m.minutos_consulta, m.minutos_citados, m.ocupacion ?? "", m.citas, m.atendidas, m.no_acudio, m.anuladas, m.espera_media ?? ""]);
  }
  filas.push([]);
  filas.push(["dia", "atendidas", "no_acudio", "por_venir", "anuladas"]);
  for (const d of inf.por_dia) filas.push([d.fecha, d.atendidas, d.no_acudio, d.pendientes, d.anuladas]);
  const csv = filas.map((f) => f.map((v) => {
    const t = typeof v === "number" ? String(v).replace(".", ",") : String(v ?? "");   // decimales con coma, como los lee Excel en español
    return /[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  }).join(";")).join("\r\n");
  // BOM para que Excel en español lo abra con las tildes bien y el «;» como separador
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `informe-${inf.mes}.csv` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
