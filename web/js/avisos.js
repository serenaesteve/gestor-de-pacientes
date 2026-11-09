// Avisos: la bandeja de salida de recordatorios.
import { estado, membrete, refrescarBandeja } from "./app.js";
import { api, esc, icono, nota, CANALES, tipoAviso, cuandoRelativo, hora, fechaCorta, plural } from "./util.js";

const VISTAS = [
  ["bandeja", "Por mandar"],
  ["proximos", "Programados"],
  ["enviados", "Enviados"],
  ["problemas", "No salieron"],
];

export async function mostrar(contenido, { params }) {
  const vista = VISTAS.some(([v]) => v === params[0]) ? params[0] : "bandeja";
  document.title = "Avisos · Volante";
  contenido.innerHTML = `<p class="cargando">Mirando la bandeja…</p>`;
  const r = await api(`/api/avisos?vista=${vista}`);
  if (!contenido.isConnected) return;
  const c = r.cuentas;
  const porMandar = (c.en_bandeja || 0) + (c.fallido || 0);
  membrete({
    titulo: "Recordatorios", subtitulo: "Bandeja de salida",
    casillas: `<div class="casillas">
      <div class="${porMandar ? "alerta" : ""}"><b>${c.en_bandeja || 0}</b><span class="rotulo">Por mandar</span></div>
      <div><b>${c.pendiente || 0}</b><span class="rotulo">Programados</span></div>
      <div><b>${r.enviados_hoy}</b><span class="rotulo">Enviados hoy</span></div></div>`,
  });
  const cuenta = { bandeja: c.en_bandeja || 0, proximos: c.pendiente || 0, enviados: c.enviado || 0, problemas: (c.fallido || 0) + (c.omitido || 0) + (c.anulado || 0) };
  const reglas = (estado.ajustes.avisos_horas || "").split(",").filter(Boolean).map((h) => tipoAviso(`antes_${h}`).toLowerCase());
  contenido.innerHTML = `
    <div class="aviso-correo ${r.correo_configurado ? "aviso-correo--ok" : ""}">
      ${icono(r.correo_configurado ? "correo" : "bandeja", 20)}
      <p>${r.correo_configurado
        ? `Los recordatorios por correo salen solos${reglas.length ? ` (${esc(reglas.join(" y "))} de cada cita)` : ""}. Los de SMS y WhatsApp llegan aquí con el texto hecho: ábrelos en el móvil del centro y márcalos como enviados.`
        : `No hay servidor de correo configurado, así que <b>ningún aviso sale solo</b>: llegan aquí a su hora con el texto hecho, para mandarlos con un toque desde el correo, el WhatsApp o los SMS del centro. Se configura en el servidor (README, «Correo»).`}</p>
    </div>
    <nav class="bandejas" aria-label="Bandejas">
      ${VISTAS.map(([v, n]) => `<a href="#/avisos/${v}" ${v === vista ? 'aria-current="page"' : ""}>${n}<span class="mono">${cuenta[v]}</span></a>`).join("")}
    </nav>
    ${r.avisos.length ? `<div class="tarjetas">${r.avisos.map((a) => tarjetita(a, vista, r.correo_configurado)).join("")}</div>` : vacio(vista)}`;
  contenido.querySelector(".tarjetas")?.addEventListener("click", (e) => accion(e, r.avisos, contenido, params));
}

function vacio(vista) {
  const textos = {
    bandeja: ["Nada por mandar.", "Cuando a un recordatorio le llegue su hora y no pueda salir solo, aparecerá aquí."],
    proximos: ["No hay recordatorios programados.", "Se programan solos al dar una cita a un paciente con correo o teléfono."],
    enviados: ["Todavía no ha salido ninguno.", "Aquí quedan los que se mandaron, solos o a mano."],
    problemas: ["Sin problemas.", "Aquí se ven los que fallaron, los de citas anuladas y los que ya no tocaba mandar."],
  }[vista];
  return `<div class="vacio"><b>${textos[0]}</b>${textos[1]}</div>`;
}

function tarjetita(a, vista, correoOk) {
  const ahora = `${estado.hoy} 00:00:00`;
  const matasellos = {
    enviado: `Enviado<span class="mono">${esc(fechaCorta(a.enviado_en || a.programado))}</span>`,
    en_bandeja: `Por mandar`,
    pendiente: `Sale<span class="mono">${esc(fechaCorta(a.programado))}</span><span class="mono">${hora(a.programado)}</span>`,
    fallido: `Falló`, anulado: `Anulado`, omitido: `No tocaba`,
  }[a.estado];
  const texto = a.cuerpo || "";
  const telefono = (a.destino || "").replace(/[^\d+]/g, "");
  const telIntl = telefono.startsWith("+") ? telefono.slice(1) : telefono.length === 9 ? `34${telefono}` : telefono;
  const mandar = vista === "bandeja" || a.estado === "fallido" ? `
    <div class="acciones">
      ${a.canal === "whatsapp" ? `<a class="boton boton--tinta boton--chico" target="_blank" rel="noopener" href="https://wa.me/${esc(telIntl)}?text=${encodeURIComponent(texto)}" data-abrir="${a.id}">${icono("burbuja", 14)} Abrir WhatsApp</a>` : ""}
      ${a.canal === "sms" ? `<a class="boton boton--tinta boton--chico" href="sms:${esc(telefono)}?body=${encodeURIComponent(texto)}" data-abrir="${a.id}">${icono("movil", 14)} Abrir SMS</a>` : ""}
      ${a.canal === "correo" ? `<a class="boton boton--tinta boton--chico" href="mailto:${esc(a.destino)}?subject=${encodeURIComponent(a.asunto || "")}&body=${encodeURIComponent(texto)}" data-abrir="${a.id}">${icono("correo", 14)} Abrir correo</a>` : ""}
      <button class="boton boton--chico" type="button" data-copiar="${a.id}">${icono("copiar", 14)} Copiar</button>
      <button class="boton boton--chico" type="button" data-enviado="${a.id}">Ya lo he mandado</button>
      ${a.canal === "correo" && correoOk ? `<button class="boton boton--plano boton--chico" type="button" data-reintentar="${a.id}">Reintentar solo</button>` : ""}
    </div>` : "";
  return `
    <article class="tarjetita" data-aviso="${a.id}">
      <span class="matasellos matasellos--${a.estado}" aria-label="Estado: ${esc(a.estado)}">${matasellos}</span>
      <div class="tarjetita__para"><div><b>${esc(a.nombre)} ${esc(a.apellidos)}</b>
        <small>${esc(CANALES[a.canal])} · ${esc(a.destino || "sin destino")}</small></div></div>
      <p class="tarjetita__cita"><span class="rotulo">${esc(tipoAviso(a.tipo))}</span> · cita ${esc(cuandoRelativo(a.empieza, ahora))} con ${esc(a.medico)}
        ${a.estado_cita === "anulada" ? " · <b>anulada</b>" : ""}</p>
      ${texto ? `<p class="tarjetita__texto" data-texto="${a.id}">${esc(texto)}</p>
        ${texto.split("\n").length > 3 || texto.length > 180 ? `<button class="boton boton--plano boton--chico" type="button" data-ver-texto="${a.id}" style="justify-self:start">Ver el texto entero</button>` : ""}` : ""}
      ${a.error && a.estado !== "en_bandeja" ? `<p class="tarjetita__error">${esc(a.error)}</p>` : ""}
      ${mandar}
    </article>`;
}

async function accion(e, avisos, contenido, params) {
  const b = e.target.closest("[data-copiar],[data-enviado],[data-reintentar],[data-ver-texto],[data-abrir]");
  if (!b) return;
  const a = avisos.find((x) => String(x.id) === (b.dataset.copiar || b.dataset.enviado || b.dataset.reintentar || b.dataset.verTexto || b.dataset.abrir));
  if (b.dataset.verTexto) {
    const t = contenido.querySelector(`[data-texto="${a.id}"]`);
    const abierto = t.toggleAttribute("data-abierto");
    b.textContent = abierto ? "Plegar el texto" : "Ver el texto entero";
    return;
  }
  if (b.dataset.abrir) {
    // Tras abrir la app de mensajes se ofrece marcarlo, sin hacerlo por su cuenta: puede que no llegue a mandarse.
    setTimeout(() => nota("¿Lo has mandado?", { accion: "Marcar como enviado", segundos: 10, alPulsar: () => marcar(a, contenido, params) }), 400);
    return;
  }
  if (b.dataset.copiar) {
    try { await navigator.clipboard.writeText(a.cuerpo || ""); nota("Texto copiado."); } catch { nota("No se ha podido copiar: selecciona el texto a mano.", { error: true }); }
    return;
  }
  if (b.dataset.enviado) return marcar(a, contenido, params);
  if (b.dataset.reintentar) {
    b.disabled = true;
    try { await api(`/api/avisos/${a.id}/reintentar`, { metodo: "POST" }); nota("Reintentado."); } catch (err) { nota(err.message, { error: true }); }
    await mostrar(contenido, { params });
    refrescarBandeja();
  }
}

async function marcar(a, contenido, params) {
  try { await api(`/api/avisos/${a.id}/enviado`, { metodo: "POST" }); } catch (err) { return nota(err.message, { error: true }); }
  const tarjeta = contenido.querySelector(`[data-aviso="${a.id}"]`);
  tarjeta?.querySelector(".matasellos")?.classList.add("sello--cae");
  nota(`Aviso a ${a.nombre} marcado como enviado.`);
  setTimeout(async () => { await mostrar(contenido, { params }); refrescarBandeja(); }, 450);
}

export const resumenBandeja = (n) => plural(n, "aviso por mandar", "avisos por mandar");
