// Utilidades compartidas: API, formato en español, iconos y avisos flotantes.

export const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
export const DIAS_CORTOS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
export const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
export const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
export const COLORES = { tinta: "Azul tinta", bermellon: "Bermellón", verde: "Verde", violeta: "Violeta", ocre: "Ocre", petroleo: "Petróleo" };
export const ESTADOS = { pendiente: "Sin confirmar", confirmada: "Confirmada", atendida: "Atendido", no_acudio: "No acudió", anulada: "Anulada" };
export const CANALES = { correo: "Correo", sms: "SMS", whatsapp: "WhatsApp", ninguno: "Sin avisos" };
export const ROLES = { direccion: "Dirección", recepcion: "Recepción", medico: "Médico" };

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

export class ErrorApi extends Error {
  constructor(estado, mensaje, codigo) { super(mensaje); this.estado = estado; this.codigo = codigo; }
}

export async function api(ruta, { metodo = "GET", datos } = {}) {
  const opciones = { method: metodo, headers: { "X-Volante": "1" }, credentials: "same-origin" };
  if (datos !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(datos);
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new ErrorApi(0, "No hay conexión con el servidor. Comprueba la red y vuelve a intentarlo.");
  }
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    if (respuesta.status === 401 && !ruta.startsWith("/api/entrar") && !ruta.startsWith("/api/clave")) {
      document.dispatchEvent(new CustomEvent("volante:sesion"));
    }
    throw new ErrorApi(respuesta.status, cuerpo.error || "Algo ha fallado en el servidor.", cuerpo.codigo);
  }
  return cuerpo;
}

// ---------- fechas (todas en la hora de la consulta, como texto «AAAA-MM-DD HH:MM:SS») ----------
export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function deIso(texto) {
  const [a, m, d] = texto.slice(0, 10).split("-").map(Number);
  return new Date(a, m - 1, d, 12);
}
export function sumarDias(texto, n) {
  const d = deIso(texto);
  d.setDate(d.getDate() + n);
  return iso(d);
}
export const lunesDe = (texto) => sumarDias(texto, -((deIso(texto).getDay() + 6) % 7));
export const hora = (momento) => String(momento || "").slice(11, 16);
export const minutosDe = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
export const aHHMM = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
export function diaSemana(texto) { return DIAS[(deIso(texto).getDay() + 6) % 7]; }
export function fechaLarga(texto, { año = false } = {}) {
  const d = deIso(texto);
  return `${diaSemana(texto)} ${d.getDate()} de ${MESES[d.getMonth()]}${año ? ` de ${d.getFullYear()}` : ""}`;
}
export function fechaCorta(texto) {
  const d = deIso(texto);
  return `${DIAS_CORTOS[(d.getDay() + 6) % 7]} ${d.getDate()} ${MESES_CORTOS[d.getMonth()]}`;
}
export function fechaNum(texto) {
  const d = deIso(texto);
  return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
}
export function cuandoRelativo(momento, ahora) {
  if (!momento) return "";
  const dia = momento.slice(0, 10), hoy = ahora.slice(0, 10);
  if (dia === hoy) return `hoy, ${hora(momento)}`;
  if (dia === sumarDias(hoy, 1)) return `mañana, ${hora(momento)}`;
  if (dia === sumarDias(hoy, -1)) return `ayer, ${hora(momento)}`;
  return `${fechaCorta(dia)}, ${hora(momento)}`;
}
export function edad(nacimiento, hoy) {
  if (!nacimiento) return null;
  const [a, m, d] = nacimiento.split("-").map(Number);
  const [ha, hm, hd] = hoy.split("-").map(Number);
  return ha - a - (hm < m || (hm === m && hd < d) ? 1 : 0);
}
/** «Dra. Inés Vidal Roca» → «IV» */
export const iniciales = (nombre) => String(nombre || "").replace(/^(dra?\.|dr\.)\s*/i, "").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
export const avatar = (nombre, color) => `<span class="avatar" style="--c:var(--t-${color || "tinta"})" aria-hidden="true">${esc(iniciales(nombre))}</span>`;
export const nombreCompleto = (p) => `${p.apellidos}, ${p.nombre}`;
export const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

export function tipoAviso(tipo) {
  if (tipo === "reserva") return "Al dar la cita";
  if (tipo === "manual") return "A mano";
  if (tipo === "oferta") return "Hueco de la lista de espera";
  const h = Number(String(tipo).replace("antes_", ""));
  return h % 24 === 0 && h >= 24 ? `${h / 24} día${h === 24 ? "" : "s"} antes` : `${h} h antes`;
}

// ---------- iconos (trazo de 1,75 px, estilo lápiz técnico) ----------
const TRAZOS = {
  libro: '<path d="M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/><path d="M9 8.5h6"/>',
  semana: '<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M8 3v4M16 3v4M4 10h16"/><path d="M8 14h2M12 14h2M16 14h0"/>',
  espera: '<path d="M7 4h10M7 20h10"/><path d="M8 4c0 4 8 4 8 8s-8 4-8 8"/><path d="M16 4c0 4-8 4-8 8"/>',
  fichero: '<rect x="4" y="5" width="16" height="14" rx="2.5"/><circle cx="9.5" cy="11" r="2"/><path d="M6.5 16c.6-1.6 1.7-2.4 3-2.4s2.4.8 3 2.4M14.5 10h3M14.5 13.5h3"/>',
  avisos: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  medicos: '<path d="M7 4v5a4 4 0 0 0 8 0V4"/><path d="M11 13v2.5a4.5 4.5 0 0 0 9 0V13"/><circle cx="20" cy="11.5" r="1.6"/>',
  informe: '<path d="M4 20h16"/><rect x="6" y="11" width="3" height="6" rx="1"/><rect x="11" y="7" width="3" height="10" rx="1"/><rect x="16" y="13" width="3" height="4" rx="1"/>',
  ajustes: '<circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4L18 18M6 18l1.6-1.6M16.4 7.6L18 6"/>',
  izquierda: '<path d="M15 6l-6 6 6 6"/>',
  derecha: '<path d="M9 6l6 6-6 6"/>',
  cerrar: '<path d="M6 6l12 12M18 6L6 18"/>',
  mas: '<path d="M12 5v14M5 12h14"/>',
  campana: '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  bandeja: '<path d="M4 13l2.5-7h11L20 13v5H4z"/><path d="M4 13h5l1 2h4l1-2h5"/>',
  correo: '<rect x="3.5" y="6" width="17" height="12" rx="1"/><path d="M4 7l8 6 8-6"/>',
  movil: '<rect x="7" y="3" width="10" height="18" rx="1.5"/><path d="M11 18h2"/>',
  burbuja: '<path d="M5 18.5l1.2-3.3A7 7 0 1 1 9 18z"/>',
  copiar: '<rect x="8" y="8" width="11" height="12" rx="1"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/>',
  salir: '<path d="M14 5h4a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1h-4"/><path d="M10 8l-4 4 4 4M6 12h10"/>',
  luna: '<path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5z"/>',
  sol: '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/>',
  imprimir: '<path d="M7 9V4h10v5"/><rect x="4" y="9" width="16" height="7" rx="1"/><path d="M7 14h10v6H7z"/>',
  buscar: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  lapiz: '<path d="M5 19l1-4L16 5l3 3L9 18z"/><path d="M14 7l3 3"/>',
  reloj: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
};
export const icono = (nombre, tam = 18) =>
  `<svg width="${tam}" height="${tam}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${TRAZOS[nombre] || ""}</svg>`;

// ---------- avisos flotantes ----------
export function nota(texto, { error = false, accion, alPulsar, segundos = 5 } = {}) {
  let caja = document.querySelector(".notas");
  if (!caja) {
    caja = document.createElement("div");
    caja.className = "notas";
    caja.setAttribute("role", "status");
    caja.setAttribute("aria-live", "polite");
    document.body.append(caja);
  }
  const el = document.createElement("div");
  el.className = `nota${error ? " nota--error" : ""}`;
  el.innerHTML = `<span>${esc(texto)}</span>${accion ? `<button type="button">${esc(accion)}</button>` : ""}`;
  if (accion) el.querySelector("button").addEventListener("click", () => { el.remove(); alPulsar?.(); });
  caja.append(el);
  setTimeout(() => el.remove(), segundos * 1000);
}

// Abre un <dialog> y devuelve una promesa con lo que resuelva «cerrar(valor)».
export function dialogo(html, alAbrir) {
  return new Promise((resolver) => {
    const d = document.createElement("dialog");
    d.className = "impreso";
    d.innerHTML = html;
    document.body.append(d);
    let valor;
    const cerrar = (v) => { valor = v; d.close(); };
    d.addEventListener("close", () => { d.remove(); resolver(valor); });
    d.addEventListener("click", (e) => { if (e.target === d) cerrar(); });
    d.querySelectorAll("[data-cerrar]").forEach((b) => b.addEventListener("click", () => cerrar()));
    d.showModal();
    alAbrir?.(d, cerrar);
  });
}

// «extra» añade una segunda salida ({ valor, texto }), por ejemplo «esta y las siguientes de la serie».
export function confirmar(titulo, texto, { boton = "Sí", peligro = false, extra = null } = {}) {
  return dialogo(`
    <div class="impreso__cabeza"><h2>${esc(titulo)}</h2></div>
    <div class="impreso__cuerpo"><p>${esc(texto)}</p></div>
    <div class="impreso__pie">
      <button class="boton" type="button" data-cerrar>Volver</button>
      ${extra ? `<button class="boton ${peligro ? "boton--peligro" : ""}" type="button" data-extra>${esc(extra.texto)}</button>` : ""}
      <button class="boton ${peligro ? "boton--peligro" : "boton--tinta"}" type="button" data-si>${esc(boton)}</button>
    </div>`, (d, cerrar) => {
    d.querySelector("[data-si]").addEventListener("click", () => cerrar(true));
    d.querySelector("[data-extra]")?.addEventListener("click", () => cerrar(extra.valor));
    d.querySelector("[data-si]").focus();
  });
}

export function datosFormulario(form) {
  const datos = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") datos[el.name] = el.checked;
    else if (el.type === "radio") { if (el.checked) datos[el.name] = el.value; }
    else datos[el.name] = el.value.trim();
  }
  return datos;
}

export const opciones = (pares, actual) =>
  pares.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(actual ?? "") ? " selected" : ""}>${esc(t)}</option>`).join("");
