"""Recordatorios automáticos de citas.

Cómo funciona:
  · Al dar, mover o anular una cita se llama a «programar»: borra los avisos que aún esperaban y
    crea los que tocan según los ajustes (por defecto, uno al darla, otro 48 h antes y otro 2 h antes).
  · El planificador (un hilo del servidor) llama a «repartir» cada 30 segundos, o enseguida cuando
    se da una cita: manda lo que ya ha llegado a su hora.
  · Por correo salen solos si hay un servidor SMTP configurado (datos/correo.json o variables
    VOLANTE_SMTP_*). Si no lo hay, y siempre para SMS y WhatsApp, el aviso queda «en bandeja»:
    recepción lo ve con el texto hecho y un botón para mandarlo desde su móvil o su correo.

El texto se escribe al enviar, no al programar: si mientras tanto cambia la consulta o el teléfono
del centro, el aviso sale con lo de ahora.
"""

import base64
import hashlib
import hmac
import json
import os
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import agenda

REINTENTOS = 3
ESPERA_REINTENTO = timedelta(minutes=5)


# ---------- enlace firmado para el paciente ----------

def firma(secreto, ident, tipo="cita"):
    """Firma corta de un enlace público: cita (confirmar/anular), oferta (lista de espera) o
    justificante (verificar). Cada tipo firma distinto: la firma de una cita no abre una oferta."""
    mac = hmac.new(secreto, f"{tipo}:{int(ident)}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")


def firma_valida(secreto, ident, dada, tipo="cita"):
    try:
        return hmac.compare_digest(firma(secreto, ident, tipo), str(dada))
    except (TypeError, ValueError):
        return False


# ---------- correo ----------

def config_correo(directorio_datos):
    """Lee la configuración SMTP. Devuelve None si no hay: entonces los correos van a la bandeja."""
    ruta = os.path.join(directorio_datos, "correo.json")
    cfg = {}
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            cfg = json.load(f)
    for clave in ("host", "puerto", "usuario", "clave", "remitente", "seguridad"):
        valor = os.environ.get(f"VOLANTE_SMTP_{clave.upper()}")
        if valor:
            cfg[clave] = valor
    if not cfg.get("host") or not cfg.get("remitente"):
        return None
    cfg["puerto"] = int(cfg.get("puerto") or 587)
    cfg["seguridad"] = cfg.get("seguridad") or ("ssl" if cfg["puerto"] == 465 else "starttls")
    return cfg


def enviar_correo(cfg, para, asunto, cuerpo, nombre_centro):
    mensaje = EmailMessage()
    mensaje["From"] = formataddr((nombre_centro, cfg["remitente"]))
    mensaje["To"] = para
    mensaje["Subject"] = asunto
    mensaje["Message-ID"] = make_msgid(domain=cfg["remitente"].split("@")[-1])
    mensaje.set_content(cuerpo)
    contexto = ssl.create_default_context()
    if cfg["seguridad"] == "ssl":
        servidor = smtplib.SMTP_SSL(cfg["host"], cfg["puerto"], timeout=20, context=contexto)
    else:
        servidor = smtplib.SMTP(cfg["host"], cfg["puerto"], timeout=20)
    with servidor:
        if cfg["seguridad"] == "starttls":
            servidor.starttls(context=contexto)
        if cfg.get("usuario"):
            servidor.login(cfg["usuario"], cfg.get("clave", ""))
        servidor.send_message(mensaje)


# ---------- ajustes y textos ----------

def leer_ajustes(con):
    return {f["clave"]: f["valor"] for f in con.consultar("buscar ajustes")}


def horas_de_aviso(ajustes):
    horas = []
    for trozo in str(ajustes.get("avisos_horas", "")).split(","):
        trozo = trozo.strip()
        if trozo:
            try:
                h = int(trozo)
            except ValueError:
                continue
            if 1 <= h <= 24 * 14 and h not in horas:
                horas.append(h)
    return sorted(horas, reverse=True)


def destino_de(paciente):
    canal = paciente.get("canal") or "correo"
    if canal == "ninguno":
        return None, None
    destino = paciente.get("email") if canal == "correo" else paciente.get("telefono")
    destino = (destino or "").strip()
    return (canal, destino) if destino else (canal, None)


def redactar_oferta(oferta, paciente, medico, ajustes, enlace):
    """El aviso a quien está en la lista de espera: un hueco libre, con enlace y hora límite."""
    empieza = agenda.de_sbd(oferta["empieza"])
    cuando = f"{agenda.fecha_larga(empieza)}, a las {agenda.hhmm(empieza)}"
    caduca = agenda.de_sbd(oferta["caduca_en"])
    limite = f"{'hoy' if caduca.date() == agenda.de_sbd(oferta['creada_en']).date() else agenda.fecha_larga(caduca)} a las {agenda.hhmm(caduca)}"
    centro = ajustes.get("centro") or "la consulta"
    asunto = f"Hueco libre: {cuando}"
    if (paciente.get("canal") or "correo") == "correo":
        cuerpo = "\n".join([
            f"Hola, {paciente['nombre']}:", "",
            f"Está en la lista de espera de {centro} y se ha quedado libre un hueco:", "",
            f"  {cuando[0].upper() + cuando[1:]}", f"  {medico['nombre']}" + (f" · {medico['consulta']}" if medico.get("consulta") else ""), "",
            f"Si lo quiere, resérvelo aquí antes de {limite}: {enlace}",
            "Si no le viene bien, puede decirlo en el mismo enlace y seguirá en la lista.", "", centro])
        return asunto, cuerpo
    return asunto, (f"{centro}: hueco libre el {cuando} con {medico['nombre']}. Si lo quiere, resérvelo antes de {limite}: {enlace}")


def redactar(tipo, cita, paciente, medico, ajustes, enlace, otras=()):
    """Asunto y cuerpo de un aviso. SMS y WhatsApp llevan una versión corta. «otras» son las demás
    citas de la serie, que se listan en el aviso de «cita dada»."""
    empieza = agenda.de_sbd(cita["empieza"])
    cuando = f"{agenda.fecha_larga(empieza)}, a las {agenda.hhmm(empieza)}"
    centro = ajustes.get("centro") or "la consulta"
    quien = medico["nombre"]
    lugar = " · ".join(x for x in (medico.get("especialidad"), medico.get("consulta")) if x)
    direccion = ajustes.get("direccion") or ""
    telefono = ajustes.get("telefono") or ""
    if tipo == "reserva":
        asunto = f"Cita dada: {cuando}"
        entrada = f"Le hemos dado cita en {centro}:"
    else:
        asunto = f"Recordatorio de su cita: {cuando}"
        entrada = f"Le recordamos su cita en {centro}:"

    if (paciente.get("canal") or "correo") == "correo":
        lineas = [f"Hola, {paciente['nombre']}:", "", entrada, "",
                  f"  {cuando[0].upper() + cuando[1:]}", f"  {quien}" + (f" · {lugar}" if lugar else "")]
        if direccion:
            lineas.append(f"  {direccion}")
        if tipo == "reserva" and otras:
            lineas += ["", f"Y {'la siguiente' if len(otras) == 1 else f'las {len(otras)} siguientes'} de la serie, a la misma hora salvo que se diga:"]
            for o in otras:
                m = agenda.de_sbd(o["empieza"])
                lineas.append(f"  · {agenda.fecha_larga(m)}, {agenda.hhmm(m)}")
            lineas.append("Le recordaremos cada una antes de la fecha.")
        lineas += ["", f"Para confirmar que viene, o anularla si no puede: {enlace}", "",
                   "Si no puede venir, avísenos y daremos el hueco a otra persona."]
        if telefono:
            lineas.append(f"Teléfono: {telefono}")
        lineas += ["", centro]
        return asunto, "\n".join(lineas)

    corto = f"{centro}: {'cita dada' if tipo == 'reserva' else 'le recordamos su cita'} el {cuando} con {quien}"
    if tipo == "reserva" and otras:
        corto += f" (y {len(otras)} más de la serie: " + ", ".join(f"{agenda.de_sbd(o['empieza']).day}/{agenda.de_sbd(o['empieza']).month}" for o in otras) + ")"
    if medico.get("consulta"):
        corto += f" ({medico['consulta']})"
    corto += f". Confirmar o anular: {enlace}"
    return asunto, corto


# ---------- programar ----------

def programar(con, cita_id, ahora, nueva=False):
    """Rehace los avisos pendientes de una cita. Se llama al darla, moverla, cambiarla o anularla.

    Los avisos ya enviados o en bandeja se quedan como historial. Si la cita ya no espera a nadie
    (anulada, atendida…), los pendientes pasan a «anulado» para que se vea que no salieron.
    """
    cita = con.una("buscar citas donde id = ?", [cita_id])
    if not cita:
        return
    if cita["estado"] not in agenda.ACTIVAS:
        con.ejecutar('actualizar recordatorios poner estado = "anulado" donde cita_id = ? y estado = "pendiente"', [cita_id])
        return
    con.ejecutar('borrar de recordatorios donde cita_id = ? y estado = "pendiente"', [cita_id])
    empieza = agenda.de_sbd(cita["empieza"])
    if empieza <= ahora:
        return
    paciente = con.una("buscar pacientes donde id = ?", [cita["paciente_id"]])
    canal, destino = destino_de(paciente)
    if not canal or not destino:
        return
    ajustes = leer_ajustes(con)
    filas = []
    if nueva and ajustes.get("aviso_reserva", "si") == "si":
        filas.append(("reserva", ahora, "pendiente"))
    enviados = {f["tipo"] for f in con.consultar(
        'buscar recordatorios donde cita_id = ? y estado en ["enviado", "en_bandeja"] mostrar tipo', [cita_id])}
    for h in horas_de_aviso(ajustes):
        tipo = f"antes_{h}"
        cuando = empieza - timedelta(hours=h)
        if cuando > ahora:
            filas.append((tipo, cuando, "pendiente"))
        elif nueva and tipo not in enviados:
            filas.append((tipo, cuando, "omitido"))
    for tipo, cuando, estado in filas:
        con.ejecutar(
            """insertar en recordatorios { cita_id: ?, tipo: ?, canal: ?, destino: ?, programado: ?, estado: ?, creado_en: ?,
                 error: ? }""",
            [cita_id, tipo, canal, destino, agenda.a_sbd(cuando), estado, agenda.a_sbd(ahora),
             "Cuando se dio la cita ya había pasado su hora." if estado == "omitido" else None],
        )


def aviso_manual(con, cita_id, ahora):
    """Un aviso que sale ya, pedido desde recepción."""
    cita = con.una("buscar citas donde id = ?", [cita_id])
    if not cita or cita["estado"] not in agenda.ACTIVAS:
        raise ValueError("Solo se avisa de citas que siguen en pie.")
    if agenda.de_sbd(cita["empieza"]) <= ahora:
        raise ValueError("Esa cita ya ha empezado.")
    paciente = con.una("buscar pacientes donde id = ?", [cita["paciente_id"]])
    canal, destino = destino_de(paciente)
    if not canal:
        raise ValueError("Este paciente ha pedido no recibir avisos (canal «ninguno» en su ficha).")
    if not destino:
        raise ValueError("Falta el " + ("correo" if canal == "correo" else "teléfono") + " del paciente en su ficha.")
    con.ejecutar(
        "insertar en recordatorios { cita_id: ?, tipo: \"manual\", canal: ?, destino: ?, programado: ?, creado_en: ? }",
        [cita_id, canal, destino, agenda.a_sbd(ahora), agenda.a_sbd(ahora)],
    )


# ---------- repartir ----------

class Cartero:
    """Manda los avisos que han llegado a su hora. Lo usa el hilo del planificador."""

    def __init__(self, bd, secreto, url_publica, dir_datos, ruta=None):
        self.bd = bd
        self.secreto = secreto
        self.url_publica = url_publica.rstrip("/")
        self.dir_datos = dir_datos
        # ruta(letra, id) → «/c/…/firma» del centro en curso; la pone la aplicación (los enlaces llevan el centro)
        self.ruta = ruta or (lambda letra, ident: f"/{letra}/{ident}/{firma(self.secreto, ident, {'c': 'cita', 'o': 'oferta'}[letra])}")

    def enlace(self, cita_id):
        return self.url_publica + self.ruta("c", cita_id)

    def enlace_oferta(self, oferta_id):
        return self.url_publica + self.ruta("o", oferta_id)

    def repartir(self, ahora, centro=None):
        """Reparte los avisos vencidos de un centro, o de todos. Devuelve cuántos ha tratado."""
        from .bd import CENTRO, GLOBAL
        if centro is None:
            with self.bd.conexion("volante · avisos", GLOBAL) as con:
                centros = [f["id"] for f in con.consultar("buscar centros ordenar id mostrar id")] if any(
                    f[0] == "centros" for f in con.ejecutar("tablas").rows) else [1]
        else:
            centros = [centro]
        total = 0
        for c in centros:
            marca = CENTRO.set(c)
            try:
                total += self._repartir_centro(ahora)
            finally:
                CENTRO.reset(marca)
        return total

    def _repartir_centro(self, ahora):
        """El envío SMTP va fuera del cerrojo de la base."""
        from . import espera
        with self.bd.conexion("volante · avisos") as con:
            with con.transaccion():
                espera.caducar(con, ahora)
            vencidos = con.consultar(
                'buscar recordatorios donde estado = "pendiente" y programado <= ? ordenar programado limite 50',
                [agenda.a_sbd(ahora)])
            ajustes = leer_ajustes(con)
            trabajo = []
            for r in vencidos:
                if r["oferta_id"]:
                    o = con.una("buscar ofertas donde id = ?", [r["oferta_id"]])
                    if not o or o["estado"] != "abierta":
                        con.ejecutar('actualizar recordatorios poner estado = "anulado" donde id = ?', [r["id"]])
                        continue
                    e = con.una("buscar espera donde id = ?", [o["espera_id"]])
                    paciente = con.una("buscar pacientes donde id = ?", [e["paciente_id"]])
                    medico = con.una("buscar medicos donde id = ?", [o["medico_id"]])
                    asunto, cuerpo = redactar_oferta(o, {**paciente, "canal": r["canal"]}, medico, ajustes, self.enlace_oferta(o["id"]))
                    trabajo.append((r, asunto, cuerpo))
                    continue
                cita = con.una("buscar citas donde id = ?", [r["cita_id"]])
                if cita is None or cita["estado"] not in agenda.ACTIVAS:
                    con.ejecutar('actualizar recordatorios poner estado = "anulado" donde id = ?', [r["id"]])
                    continue
                if agenda.de_sbd(cita["empieza"]) <= ahora:
                    con.ejecutar('actualizar recordatorios poner estado = "omitido", error = "La cita ya había empezado." donde id = ?', [r["id"]])
                    continue
                paciente = con.una("buscar pacientes donde id = ?", [cita["paciente_id"]])
                medico = con.una("buscar medicos donde id = ?", [cita["medico_id"]])
                otras = []
                if r["tipo"] == "reserva" and cita["serie"]:
                    otras = con.consultar('buscar citas donde serie = ? y empieza > ? y estado en ["pendiente", "confirmada"] ordenar empieza mostrar empieza',
                                          [cita["serie"], cita["empieza"]])
                asunto, cuerpo = redactar(r["tipo"], cita, {**paciente, "canal": r["canal"]}, medico, ajustes, self.enlace(cita["id"]), otras)
                trabajo.append((r, asunto, cuerpo))

        cfg = config_correo(self.dir_datos) if any(r["canal"] == "correo" for r, *_ in trabajo) else None
        resultados = []
        for r, asunto, cuerpo in trabajo:
            if r["canal"] != "correo":
                resultados.append((r, asunto, cuerpo, "en_bandeja", "SMS y WhatsApp se mandan a mano desde la bandeja."))
            elif cfg is None:
                resultados.append((r, asunto, cuerpo, "en_bandeja", "No hay servidor de correo configurado."))
            else:
                try:
                    enviar_correo(cfg, r["destino"], asunto, cuerpo, ajustes.get("centro") or "Consulta")
                    resultados.append((r, asunto, cuerpo, "enviado", None))
                except (OSError, smtplib.SMTPException) as err:
                    resultados.append((r, asunto, cuerpo, "error", f"{type(err).__name__}: {err}"[:300]))

        with self.bd.conexion("volante · avisos") as con:
            for r, asunto, cuerpo, estado, error in resultados:
                if estado == "error":
                    intentos = int(r["intentos"] or 0) + 1
                    if intentos >= REINTENTOS:
                        con.ejecutar('actualizar recordatorios poner estado = "fallido", intentos = ?, error = ?, asunto = ?, cuerpo = ? donde id = ?',
                                     [intentos, error, asunto, cuerpo, r["id"]])
                    else:
                        con.ejecutar("actualizar recordatorios poner intentos = ?, error = ?, programado = ? donde id = ?",
                                     [intentos, error, agenda.a_sbd(ahora + ESPERA_REINTENTO), r["id"]])
                else:
                    con.ejecutar("actualizar recordatorios poner estado = ?, error = ?, asunto = ?, cuerpo = ?, enviado_en = ? donde id = ? y estado = \"pendiente\"",
                                 [estado, error, asunto, cuerpo, agenda.a_sbd(ahora) if estado == "enviado" else None, r["id"]])
        return len(resultados)
