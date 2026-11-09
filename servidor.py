#!/usr/bin/env python3
"""Volante: pacientes, médicos, horarios, citas y recordatorios automáticos de una consulta.

    python3 servidor.py                          # http://127.0.0.1:8103, datos en ./datos
    python3 servidor.py --demo                   # con médicos, pacientes y citas de ejemplo (inventados)
    python3 servidor.py --datos /srv/volante/datos --publico --url-publica https://citas.ejemplo.es

Los avisos por correo salen solos si existe datos/correo.json (ver README). Sin él, se quedan en la
bandeja de recepción con el texto ya escrito.
"""

import argparse
import json
import mimetypes
import os
import re
import secrets
import signal
import sys
import threading
import time
import unicodedata
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
sys.path.insert(0, str(RAIZ))

from api import agenda, espera, recordatorios, seguridad  # noqa: E402
from api import informe as informe_mod  # noqa: E402
from api.bd import CENTRO, GLOBAL, BaseDatos, abrir as abrir_bd  # noqa: E402
from sbd import SBDError  # noqa: E402

COOKIE = "volante_sesion"
RELOJ_FALSO = datetime.strptime(os.environ["VOLANTE_RELOJ"], "%Y-%m-%d %H:%M") if os.environ.get("VOLANTE_RELOJ") else None
ARRANQUE = datetime.now(ZoneInfo("Europe/Madrid")).replace(tzinfo=None, microsecond=0)
DURACION_SESION = timedelta(hours=12)          # una jornada: en un mostrador compartido no conviene más
MAX_CUERPO = 256 * 1024
USUARIO_VALIDO = re.compile(r"^[a-z0-9._@+-]{3,30}$")


def normalizar_usuario(texto_usuario):
    """«Lucía Pérez» → «lucia.perez»: sin tildes, en minúsculas y con puntos en vez de espacios.
    Se hace igual al crear la cuenta y al entrar, así que se puede escribir de las dos maneras."""
    t = unicodedata.normalize("NFD", str(texto_usuario or "").strip().lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").replace("ñ", "n")
    return re.sub(r"\s+", ".", t)
HORA_VALIDA = re.compile(r"^\d{1,2}:\d{2}$")
ITERACIONES = int(os.environ.get("VOLANTE_ITERACIONES", "0")) or None
COLORES = ("tinta", "bermellon", "verde", "violeta", "ocre", "petroleo")
ROLES = ("direccion", "recepcion", "medico")
MAX_CENTROS = int(os.environ.get("VOLANTE_MAX_CENTROS", "200"))   # tope de centros creados desde la web
CANALES = ("correo", "sms", "whatsapp", "ninguno")

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/calendar", ".ics")


class Limitador:
    """Ventana deslizante por IP: frena a quien prueba contraseñas o enlaces."""

    def __init__(self, maximo, segundos):
        self.maximo, self.segundos = maximo, segundos
        self._golpes = defaultdict(deque)
        self._cerrojo = threading.Lock()

    def permitir(self, clave, anotar=True):
        limite = time.monotonic() - self.segundos
        with self._cerrojo:
            cola = self._golpes[clave]
            while cola and cola[0] < limite:
                cola.popleft()
            if len(cola) >= self.maximo:
                return False
            if anotar:
                cola.append(time.monotonic())
            return True

    def anotar(self, clave):
        with self._cerrojo:
            self._golpes[clave].append(time.monotonic())


class ErrorApi(Exception):
    def __init__(self, estado, mensaje, codigo=None):
        super().__init__(mensaje)
        self.estado, self.mensaje, self.codigo = estado, mensaje, codigo


def texto(datos, clave, largo, obligatorio=False, nombre=None):
    valor = datos.get(clave)
    valor = "" if valor is None else str(valor).strip()
    if obligatorio and not valor:
        raise ErrorApi(400, f"Falta {nombre or clave}.")
    if len(valor) > largo:
        raise ErrorApi(400, f"{(nombre or clave).capitalize()} es demasiado largo (máximo {largo} caracteres).")
    return valor or None


def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def entero(valor, nombre):
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ErrorApi(400, f"{nombre} no es un número válido.") from None


def dia_param(valor, defecto):
    if not valor:
        return defecto
    try:
        return agenda.fecha(valor)
    except ValueError as err:
        raise ErrorApi(400, str(err)) from None


class Aplicacion:
    def __init__(self, bd, dir_datos, url_publica, publico=False):
        self.bd = bd
        self.publico = publico
        self.dir_datos = str(dir_datos)
        self.secreto = self._secreto(Path(dir_datos) / ".secreto-enlaces")
        self.cartero = recordatorios.Cartero(bd, self.secreto, url_publica, self.dir_datos, ruta=self.ruta)
        self.limite_acceso = Limitador(10, 600)
        self.limite_publico = Limitador(60, 600)
        self.limite_registro = Limitador(3, 3600)     # centros nuevos por IP y hora
        self.registro = True
        self.despertar = threading.Event()
        with bd.conexion(centro=GLOBAL) as con:
            zona = con.valor('buscar ajustes donde clave = "zona" mostrar valor') or "Europe/Madrid"
        self.zona = ZoneInfo(zona)

    @staticmethod
    def _secreto(ruta):
        if not ruta.exists():
            ruta.write_bytes(secrets.token_bytes(32))
            os.chmod(ruta, 0o600)
        return ruta.read_bytes()

    def reloj(self):
        """La hora de la consulta, sin zona: así se guardan todas las citas.
        Solo para desarrollo: VOLANTE_RELOJ="2026-11-10 10:30" hace que el servidor arranque a esa hora."""
        real = datetime.now(self.zona).replace(tzinfo=None, microsecond=0)
        if RELOJ_FALSO:
            return RELOJ_FALSO + (real - ARRANQUE)
        return real

    def ahora(self):
        return agenda.a_sbd(self.reloj())

    # ---- enlaces públicos: llevan el centro (salvo el centro 1, por los enlaces que ya se mandaron) ----
    @staticmethod
    def _tipo_firma(tipo):
        centro = CENTRO.get()
        return tipo if centro in (None, 1) else f"{tipo}@{centro}"

    def firmar(self, tipo, ident):
        return recordatorios.firma(self.secreto, ident, self._tipo_firma(tipo))

    def firma_valida(self, tipo, ident, firma):
        return recordatorios.firma_valida(self.secreto, ident, firma, self._tipo_firma(tipo))

    def ruta(self, letra, ident):
        tipo = {"c": "cita", "o": "oferta", "v": "justificante"}[letra]
        centro = CENTRO.get()
        return f"/{letra}/{'' if centro in (None, 1) else f'{centro}/'}{ident}/{self.firmar(tipo, ident)}"

    # ================= cuentas =================

    def hay_cuentas(self):
        with self.bd.conexion(centro=GLOBAL) as con:
            return bool(con.valor("buscar usuarios mostrar contar()"))

    def usuario_de(self, token):
        if not token:
            return None
        with self.bd.conexion(centro=GLOBAL) as con:
            return con.una(
                """buscar sesiones como s unir usuarios como u en u.id = s.usuario_id unir centros como c en c.id = u.centro_id
                   donde s.token_hash = ? y s.expira_en > ? y u.activo = verdadero
                   mostrar u.id como id, u.usuario como usuario, u.nombre como nombre, u.rol como rol, u.medico_id como medico_id,
                           u.centro_id como centro_id, c.nombre como centro""",
                [seguridad.huella_token(token), self.ahora()],
            )

    def _abrir_sesion(self, con, uid):
        token = seguridad.nuevo_token()
        con.ejecutar("borrar de sesiones donde expira_en < ?", [self.ahora()])
        con.ejecutar("insertar en sesiones { token_hash: ?, usuario_id: ?, expira_en: ? }",
                     [seguridad.huella_token(token), uid, agenda.a_sbd(self.reloj() + DURACION_SESION)])
        con.ejecutar("actualizar usuarios poner ultimo_acceso = ? donde id = ?", [self.ahora(), uid])
        return token

    def _validar_cuenta(self, datos):
        usuario = normalizar_usuario(datos.get("usuario"))
        if not USUARIO_VALIDO.match(usuario):
            raise ErrorApi(400, "El usuario lleva de 3 a 30 caracteres: letras, números, punto, guion, guion bajo o @.", "usuario")
        nombre = texto(datos, "nombre", 80, True, "el nombre")
        contrasena = str(datos.get("contrasena", ""))
        if len(contrasena) < 10:
            raise ErrorApi(400, "La contraseña necesita 10 caracteres como mínimo: aquí hay datos de salud.", "contrasena")
        return usuario, nombre, contrasena

    def puesta_en_marcha(self, datos):
        """La primera cuenta, de dirección. Solo funciona mientras no haya ninguna."""
        if self.publico and not datos.get("_desde_consola"):
            # En Internet, la primera persona que abriese la web se quedaría con la consulta.
            raise ErrorApi(403, "En el servidor publicado, la cuenta de dirección se crea desde la consola: python3 servidor.py --alta-direccion USUARIO")
        usuario, nombre, contrasena = self._validar_cuenta(datos)
        resumen = seguridad.cifrar_contrasena(contrasena, ITERACIONES)
        with self.bd.conexion("alta", GLOBAL) as con:     # el centro 1 no lleva prefijo: sus tablas y las comunes van juntas
            with con.transaccion():
                if con.valor("buscar usuarios mostrar contar()"):
                    raise ErrorApi(409, "Volante ya está en marcha: entra con tu cuenta.")
                centro = texto(datos, "centro", 80)
                if centro:
                    con.ejecutar('actualizar ajustes poner valor = ? donde clave = "centro"', [centro])
                    con.ejecutar("actualizar centros poner nombre = ? donde id = 1", [centro])
                uid = con.ejecutar('insertar en usuarios { usuario: ?, nombre: ?, rol: "direccion", centro_id: 1, hash_contrasena: ?, creado_en: ? } devolver id',
                                   [usuario, nombre, resumen, self.ahora()]).scalar()
                token = self._abrir_sesion(con, uid)
        return token

    def entrar(self, datos):
        usuario = normalizar_usuario(datos.get("usuario"))
        contrasena = str(datos.get("contrasena", ""))
        with self.bd.conexion("acceso", GLOBAL) as con:
            fila = con.una("buscar usuarios donde usuario = ? mostrar id, hash_contrasena, activo", [usuario])
            ok = seguridad.comprobar_contrasena(contrasena, fila["hash_contrasena"] if fila else seguridad.hash_senuelo())
            if not fila or not ok:
                raise ErrorApi(401, "Usuario o contraseña incorrectos.")
            if not fila["activo"]:
                raise ErrorApi(403, "Esta cuenta está desactivada. Habla con dirección.")
            with con.transaccion():
                return self._abrir_sesion(con, fila["id"])

    def salir(self, token):
        if token:
            with self.bd.conexion(centro=GLOBAL) as con:
                con.ejecutar("borrar de sesiones donde token_hash = ?", [seguridad.huella_token(token)])

    def cambiar_clave(self, yo, datos):
        nueva = str(datos.get("nueva", ""))
        if len(nueva) < 10:
            raise ErrorApi(400, "La contraseña nueva necesita 10 caracteres como mínimo.")
        with self.bd.conexion(f"clave · cuenta {yo['id']}", GLOBAL) as con:
            resumen = con.valor("buscar usuarios donde id = ? mostrar hash_contrasena", [yo["id"]])
            if not seguridad.comprobar_contrasena(str(datos.get("actual", "")), resumen):
                raise ErrorApi(401, "La contraseña actual no es correcta.")
            con.ejecutar("actualizar usuarios poner hash_contrasena = ? donde id = ?",
                         [seguridad.cifrar_contrasena(nueva, ITERACIONES), yo["id"]])
        return {"ok": True}

    # ---- centros nuevos desde la web ----

    def registrar(self, datos):
        """Cuenta nueva = centro nuevo, vacío o con datos de ejemplo. Nadie ve los centros de los demás."""
        if not self.registro:
            raise ErrorApi(403, "Ahora mismo no se pueden crear cuentas nuevas.")
        usuario, nombre, contrasena = self._validar_cuenta(datos)
        nombre_centro = texto(datos, "centro", 80, True, "el nombre del centro")
        ejemplo = bool(datos.get("ejemplo"))
        resumen = seguridad.cifrar_contrasena(contrasena, ITERACIONES)
        with self.bd.conexion("registro", GLOBAL) as con:
            if con.una("buscar usuarios donde usuario = ? mostrar id", [usuario]):
                raise ErrorApi(409, "Ese usuario ya existe. Elige otro o entra con tu contraseña.", "usuario")
            if con.valor("buscar centros mostrar contar()") >= MAX_CENTROS:
                raise ErrorApi(503, "Ahora mismo no se admiten más centros nuevos.")
            cid = con.ejecutar("insertar en centros { nombre: ?, creado_en: ?, ejemplo: ? } devolver id",
                               [nombre_centro, self.ahora(), ejemplo]).scalar()
        try:
            zona = str(self.zona)
            self.bd.crear_centro(cid, {"centro": nombre_centro, "zona": zona})
            with self.bd.conexion("registro", GLOBAL) as con:
                with con.transaccion():
                    uid = con.ejecutar('insertar en usuarios { usuario: ?, nombre: ?, rol: "direccion", centro_id: ?, hash_contrasena: ?, creado_en: ? } devolver id',
                                       [usuario, nombre, cid, resumen, self.ahora()]).scalar()
                    token = self._abrir_sesion(con, uid)
        except BaseException:
            # Que no quede un centro a medias: ni sus tablas ni su fila.
            try:
                self.bd.borrar_centro(cid)
            finally:
                with self.bd.conexion("registro", GLOBAL) as con:
                    con.ejecutar("borrar de centros donde id = ?", [cid])
            raise
        if ejemplo:
            from api import demo
            marca = CENTRO.set(cid)
            try:
                demo.sembrar(self, cuentas=False, pequeno=True, ajustes_centro=False)
            finally:
                CENTRO.reset(marca)
        return token

    def borrar_centro(self, yo, datos):
        """Dirección borra su centro entero: pacientes, citas, avisos, médicos y todas las cuentas."""
        if yo["centro_id"] == 1:
            raise ErrorApi(403, "Este centro no se puede borrar desde la web.")
        with self.bd.conexion(f"baja · cuenta {yo['id']}", GLOBAL) as con:
            resumen = con.valor("buscar usuarios donde id = ? mostrar hash_contrasena", [yo["id"]])
        if not seguridad.comprobar_contrasena(str(datos.get("contrasena", "")), resumen or seguridad.hash_senuelo()):
            raise ErrorApi(401, "La contraseña no es correcta: el centro sigue como estaba.")
        self.bd.borrar_centro(yo["centro_id"])
        with self.bd.conexion(f"baja · cuenta {yo['id']}", GLOBAL) as con:
            con.ejecutar("borrar de centros donde id = ?", [yo["centro_id"]])   # en cascada, sus cuentas y sesiones
        return {"borrado": True}

    # ---- equipo (solo dirección, solo de su centro) ----

    def equipo(self, yo):
        with self.bd.conexion(centro=GLOBAL) as con:
            return con.consultar("buscar usuarios donde centro_id = ? ordenar nombre mostrar id, usuario, nombre, rol, medico_id, activo, ultimo_acceso",
                                 [yo["centro_id"]])

    def crear_miembro(self, yo, datos):
        usuario, nombre, contrasena = self._validar_cuenta(datos)
        rol = datos.get("rol")
        if rol not in ROLES:
            raise ErrorApi(400, "El papel es dirección, recepción o médico.")
        medico_id = datos.get("medico_id") or None
        if rol == "medico":
            with self.bd.conexion(f"equipo · cuenta {yo['id']}") as con:      # el médico, en las tablas de su centro
                if not medico_id or not con.una("buscar medicos donde id = ?", [entero(medico_id, "El médico")]):
                    raise ErrorApi(400, "Una cuenta de médico va unida a su ficha de médico.")
        with self.bd.conexion(f"equipo · cuenta {yo['id']}", GLOBAL) as con:
            if con.una("buscar usuarios donde usuario = ? mostrar id", [usuario]):
                raise ErrorApi(409, "Ese usuario ya existe.")
            con.ejecutar("insertar en usuarios { usuario: ?, nombre: ?, rol: ?, centro_id: ?, medico_id: ?, hash_contrasena: ?, creado_en: ? }",
                         [usuario, nombre, rol, yo["centro_id"], int(medico_id) if rol == "medico" else None,
                          seguridad.cifrar_contrasena(contrasena, ITERACIONES), self.ahora()])
        return {"ok": True}

    def cambiar_miembro(self, yo, uid, datos):
        with self.bd.conexion(f"equipo · cuenta {yo['id']}", GLOBAL) as con:
            fila = con.una("buscar usuarios donde id = ? y centro_id = ?", [uid, yo["centro_id"]])
            if not fila:
                raise ErrorApi(404, "Esa cuenta no existe.")
            if "activo" in datos:
                activo = bool(datos["activo"])
                if uid == yo["id"] and not activo:
                    raise ErrorApi(400, "No puedes desactivar tu propia cuenta.")
                con.ejecutar("actualizar usuarios poner activo = ? donde id = ?", [activo, uid])
                if not activo:
                    con.ejecutar("borrar de sesiones donde usuario_id = ?", [uid])
            if datos.get("contrasena"):
                if len(str(datos["contrasena"])) < 10:
                    raise ErrorApi(400, "La contraseña necesita 10 caracteres como mínimo.")
                con.ejecutar("actualizar usuarios poner hash_contrasena = ? donde id = ?",
                             [seguridad.cifrar_contrasena(str(datos["contrasena"]), ITERACIONES), uid])
                con.ejecutar("borrar de sesiones donde usuario_id = ?", [uid])
        return {"ok": True}

    # ================= ajustes =================

    def ajustes(self):
        with self.bd.conexion() as con:
            a = recordatorios.leer_ajustes(con)
        a.pop("version_esquema", None)
        a["correo_configurado"] = recordatorios.config_correo(self.dir_datos) is not None
        return a

    def guardar_ajustes(self, datos):
        cambios = {}
        for clave, largo in (("centro", 80), ("direccion", 160), ("telefono", 30)):
            if clave in datos:
                cambios[clave] = texto(datos, clave, largo) or ""
        if "centro" in cambios and not cambios["centro"]:
            raise ErrorApi(400, "El centro necesita un nombre: sale en todos los avisos.")
        if "avisos_horas" in datos:
            horas = recordatorios.horas_de_aviso({"avisos_horas": str(datos["avisos_horas"])})
            if len(horas) > 4:
                raise ErrorApi(400, "Como mucho cuatro avisos antes de cada cita.")
            cambios["avisos_horas"] = ",".join(str(h) for h in horas)
        if "aviso_reserva" in datos:
            cambios["aviso_reserva"] = "si" if datos["aviso_reserva"] in (True, "si") else "no"
        if "citas_por_enlace" in datos:
            cambios["citas_por_enlace"] = "si" if datos["citas_por_enlace"] in (True, "si") else "no"
        if "oferta_horas" in datos:
            h = entero(datos["oferta_horas"], "Las horas de la oferta")
            if not 1 <= h <= 48:
                raise ErrorApi(400, "Una oferta de la lista de espera dura entre 1 y 48 horas.")
            cambios["oferta_horas"] = str(h)
        if "centro" in cambios:
            with self.bd.conexion("ajustes", GLOBAL) as con:
                con.ejecutar("actualizar centros poner nombre = ? donde id = ?", [cambios["centro"], CENTRO.get()])
        with self.bd.conexion("ajustes") as con:
            with con.transaccion():
                for clave, valor in cambios.items():
                    con.ejecutar("insertar o actualizar en ajustes { clave: ?, valor: ? }", [clave, valor])
                if "avisos_horas" in cambios:
                    # Las citas que ya estaban dadas pasan a seguir la regla nueva.
                    ahora = self.reloj()
                    for c in con.consultar('buscar citas donde empieza > ? y estado en ["pendiente", "confirmada"] mostrar id',
                                           [agenda.a_sbd(ahora)]):
                        recordatorios.programar(con, c["id"], ahora)
        return self.ajustes()

    # ================= médicos y horarios =================

    def medicos(self, todos=False):
        with self.bd.conexion() as con:
            filtro = "" if todos else "donde activo = verdadero "
            meds = con.consultar(f"buscar medicos {filtro}ordenar id")
            franjas = con.consultar("buscar horarios ordenar medico_id, dia, desde")
            hoy = self.reloj().date().isoformat()
            ausencias = con.consultar("buscar ausencias donde hasta >= ? ordenar desde", [hoy])
        por = defaultdict(list)
        for f in franjas:
            por[f["medico_id"]].append(f)
        aus = defaultdict(list)
        for a in ausencias:
            aus[a["medico_id"]].append(a)
        for m in meds:
            m["franjas"] = por[m["id"]]
            m["ausencias"] = aus[m["id"]]
            m["horas_semana"] = round(sum(
                (datetime.combine(date.min, agenda.hora(f["hasta"])) - datetime.combine(date.min, agenda.hora(f["desde"]))).seconds
                for f in por[m["id"]]) / 3600, 1)
        return meds

    def _datos_medico(self, datos):
        color = datos.get("color") or "tinta"
        if color not in COLORES:
            raise ErrorApi(400, "Ese color de tampón no existe.")
        return [texto(datos, "nombre", 80, True, "el nombre"), texto(datos, "especialidad", 60, True, "la especialidad"),
                texto(datos, "colegiado", 20), texto(datos, "consulta", 30), color,
                texto(datos, "telefono", 20), texto(datos, "email", 120)]

    def crear_medico(self, datos):
        valores = self._datos_medico(datos)
        with self.bd.conexion("medicos") as con:
            mid = con.ejecutar(
                """insertar en medicos { nombre: ?, especialidad: ?, colegiado: ?, consulta: ?, color: ?, telefono: ?, email: ?, creado_en: ? }
                   devolver id""", valores + [self.ahora()]).scalar()
        return {"id": mid}

    def cambiar_medico(self, mid, datos):
        valores = self._datos_medico(datos)
        activo = bool(datos.get("activo", True))
        with self.bd.conexion("medicos") as con:
            if not con.una("buscar medicos donde id = ?", [mid]):
                raise ErrorApi(404, "Ese médico no existe.")
            if not activo:
                futuras = con.valor('buscar citas donde medico_id = ? y empieza > ? y estado en ["pendiente", "confirmada"] mostrar contar()',
                                    [mid, self.ahora()])
                if futuras:
                    raise ErrorApi(409, f"Tiene {futuras} cita{'s' if futuras != 1 else ''} por delante. Muévelas o anúlalas antes de darle de baja.")
            con.ejecutar("""actualizar medicos poner nombre = ?, especialidad = ?, colegiado = ?, consulta = ?, color = ?, telefono = ?,
                            email = ?, activo = ? donde id = ?""", valores + [activo, mid])
        return {"ok": True}

    def guardar_horario(self, mid, datos):
        try:
            franjas = agenda.validar_franjas(datos.get("franjas") or [])
        except ValueError as err:
            raise ErrorApi(400, str(err)) from None
        with self.bd.conexion("horarios") as con:
            if not con.una("buscar medicos donde id = ?", [mid]):
                raise ErrorApi(404, "Ese médico no existe.")
            with con.transaccion():
                con.ejecutar("borrar de horarios donde medico_id = ?", [mid])
                for f in franjas:
                    con.ejecutar("insertar en horarios { medico_id: ?, dia: ?, desde: ?, hasta: ?, minutos: ? }",
                                 [mid, f["dia"], f["desde"], f["hasta"], f["minutos"]])
                # Citas ya dadas que se quedan fuera del horario nuevo: no se tocan, pero se avisa.
                fuera = []
                for c in con.consultar('buscar citas donde medico_id = ? y empieza > ? y estado en ["pendiente", "confirmada"] ordenar empieza',
                                       [mid, self.ahora()]):
                    if not agenda.dentro_de_horario(franjas, agenda.de_sbd(c["empieza"]), agenda.de_sbd(c["termina"])):
                        fuera.append(c["empieza"])
        return {"ok": True, "citas_fuera": fuera}

    def crear_ausencia(self, mid, datos):
        try:
            desde, hasta = agenda.fecha(datos.get("desde")), agenda.fecha(datos.get("hasta") or datos.get("desde"))
        except ValueError as err:
            raise ErrorApi(400, str(err)) from None
        if hasta < desde:
            raise ErrorApi(400, "La ausencia termina antes de empezar.")
        motivo = texto(datos, "motivo", 120)
        with self.bd.conexion("ausencias") as con:
            if not con.una("buscar medicos donde id = ?", [mid]):
                raise ErrorApi(404, "Ese médico no existe.")
            afectadas = con.valor(
                'buscar citas donde medico_id = ? y empieza >= ? y empieza < ? y estado en ["pendiente", "confirmada"] mostrar contar()',
                [mid, f"{desde} 00:00:00", f"{hasta + timedelta(days=1)} 00:00:00"])
            con.ejecutar("insertar en ausencias { medico_id: ?, desde: ?, hasta: ?, motivo: ? }",
                         [mid, desde.isoformat(), hasta.isoformat(), motivo])
        return {"ok": True, "citas_afectadas": afectadas}

    def borrar_ausencia(self, aid):
        with self.bd.conexion("ausencias") as con:
            con.ejecutar("borrar de ausencias donde id = ?", [aid])
        return {"ok": True}

    # ================= pacientes =================

    def _datos_paciente(self, datos):
        canal = datos.get("canal") or "correo"
        if canal not in CANALES:
            raise ErrorApi(400, "El canal de avisos es correo, SMS, WhatsApp o ninguno.")
        nacimiento = texto(datos, "nacimiento", 10)
        if nacimiento:
            try:
                n = agenda.fecha(nacimiento)
            except ValueError as err:
                raise ErrorApi(400, str(err)) from None
            if n > self.reloj().date() or n.year < 1900:
                raise ErrorApi(400, "La fecha de nacimiento no es posible.")
        email = texto(datos, "email", 120)
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ErrorApi(400, "El correo no parece válido (falta la @ o el dominio).")
        telefono = texto(datos, "telefono", 20)
        if telefono and len(re.sub(r"\D", "", telefono)) < 9:
            raise ErrorApi(400, "El teléfono necesita 9 cifras como mínimo.")
        documento = texto(datos, "documento", 20)
        return {
            "nombre": texto(datos, "nombre", 60, True, "el nombre"),
            "apellidos": texto(datos, "apellidos", 80, True, "los apellidos"),
            "documento": documento.upper().replace(" ", "") if documento else None,
            "nacimiento": nacimiento, "telefono": telefono, "email": email,
            "direccion": texto(datos, "direccion", 160), "notas": texto(datos, "notas", 2000), "canal": canal,
        }

    def pacientes(self, q="", letra=""):
        with self.bd.conexion() as con:
            filas = con.consultar("buscar pacientes ordenar apellidos, nombre mostrar id, nombre, apellidos, documento, telefono, email, nacimiento, canal")
            proximas = {f["paciente_id"]: f["proxima"] for f in con.consultar(
                'buscar citas donde empieza > ? y estado en ["pendiente", "confirmada"] agrupar paciente_id mostrar paciente_id, minimo(empieza) como proxima',
                [self.ahora()])}
        q = sin_tildes(q).strip()
        letra = sin_tildes(letra)[:1]
        res = []
        for f in filas:
            if letra and not sin_tildes(f["apellidos"]).startswith(letra):
                continue
            if q:
                pajar = sin_tildes(" ".join(str(f[k] or "") for k in ("nombre", "apellidos", "documento", "telefono", "email")))
                pajar_tel = re.sub(r"\D", "", f["telefono"] or "")
                if not all(trozo in pajar or (trozo.isdigit() and trozo in pajar_tel) for trozo in q.split()):
                    continue
            f["proxima"] = proximas.get(f["id"])
            res.append(f)
        return {"total": len(filas), "pacientes": res[:300], "recortado": len(res) > 300}

    def paciente(self, yo, pid):
        with self.bd.conexion() as con:
            p = con.una("buscar pacientes donde id = ?", [pid])
            if not p:
                raise ErrorApi(404, "Ese paciente no está en el fichero.")
            citas = con.consultar(
                """buscar citas como c unir medicos como m en m.id = c.medico_id donde c.paciente_id = ?
                   ordenar c.empieza desc
                   mostrar c.id como id, c.empieza como empieza, c.termina como termina, c.estado como estado, c.motivo como motivo,
                           c.nota como nota, c.medico_id como medico_id, m.nombre como medico, m.especialidad como especialidad, m.color como color""",
                [pid])
            avisos = con.consultar(
                """buscar recordatorios como r unir citas como c en c.id = r.cita_id donde c.paciente_id = ?
                   ordenar r.programado desc limite 60
                   mostrar r.id como id, r.cita_id como cita_id, r.tipo como tipo, r.canal como canal, r.estado como estado,
                           r.programado como programado, r.enviado_en como enviado_en, r.error como error""", [pid])
        if not self.ve_notas(yo):
            for c in citas:
                c.pop("nota", None)
        return {"paciente": p, "citas": citas, "avisos": avisos}

    def crear_paciente(self, datos):
        d = self._datos_paciente(datos)
        with self.bd.conexion("pacientes") as con:
            if d["documento"] and con.una("buscar pacientes donde documento = ? mostrar id", [d["documento"]]):
                raise ErrorApi(409, "Ya hay un paciente con ese documento en el fichero.")
            pid = con.ejecutar(
                """insertar en pacientes { nombre: ?, apellidos: ?, documento: ?, nacimiento: ?, telefono: ?, email: ?, direccion: ?,
                     notas: ?, canal: ?, creado_en: ? } devolver id""",
                [d["nombre"], d["apellidos"], d["documento"], d["nacimiento"], d["telefono"], d["email"], d["direccion"],
                 d["notas"], d["canal"], self.ahora()]).scalar()
        return {"id": pid}

    def cambiar_paciente(self, pid, datos):
        d = self._datos_paciente(datos)
        with self.bd.conexion("pacientes") as con:
            if not con.una("buscar pacientes donde id = ? mostrar id", [pid]):
                raise ErrorApi(404, "Ese paciente no está en el fichero.")
            if d["documento"] and con.una("buscar pacientes donde documento = ? y id != ? mostrar id", [d["documento"], pid]):
                raise ErrorApi(409, "Ya hay otro paciente con ese documento.")
            with con.transaccion():
                con.ejecutar("""actualizar pacientes poner nombre = ?, apellidos = ?, documento = ?, nacimiento = ?, telefono = ?, email = ?,
                                direccion = ?, notas = ?, canal = ? donde id = ?""",
                             [d["nombre"], d["apellidos"], d["documento"], d["nacimiento"], d["telefono"], d["email"], d["direccion"],
                              d["notas"], d["canal"], pid])
                # Si cambia el correo, el teléfono o el canal, los avisos pendientes van al sitio nuevo.
                ahora = self.reloj()
                for c in con.consultar('buscar citas donde paciente_id = ? y empieza > ? y estado en ["pendiente", "confirmada"] mostrar id',
                                       [pid, agenda.a_sbd(ahora)]):
                    recordatorios.programar(con, c["id"], ahora)
        return {"ok": True}

    def borrar_paciente(self, pid):
        """Borra la ficha con todas sus citas y avisos (derecho de supresión). Solo dirección."""
        with self.bd.conexion("pacientes · supresión") as con:
            con.ejecutar("borrar de pacientes donde id = ?", [pid])
        return {"ok": True}

    # ================= citas =================

    @staticmethod
    def ve_notas(yo):
        return yo["rol"] in ("medico", "direccion")

    def _citas_rango(self, con, yo, desde, hasta, medico_id=None):
        filtro = "c.empieza >= ? y c.empieza < ?"
        params = [f"{desde} 00:00:00", f"{hasta} 00:00:00"]
        if medico_id:
            filtro += " y c.medico_id = ?"
            params.append(medico_id)
        citas = con.consultar(
            f"""buscar citas como c unir pacientes como p en p.id = c.paciente_id donde {filtro}
                ordenar c.empieza
                mostrar c.id como id, c.medico_id como medico_id, c.paciente_id como paciente_id, c.empieza como empieza,
                        c.termina como termina, c.estado como estado, c.motivo como motivo, c.nota como nota, c.origen como origen,
                        c.confirmada_en como confirmada_en, c.anulada_por como anulada_por, c.llegada como llegada, c.entra como entra,
                        c.atendida_en como atendida_en, c.serie como serie,
                        p.nombre como nombre, p.apellidos como apellidos, p.telefono como telefono, p.canal como canal,
                        p.email como email, p.notas como notas_paciente, p.nacimiento como nacimiento""", params)
        avisos = defaultdict(list)
        if citas:
            for r in con.consultar(
                    f"""buscar recordatorios como r unir citas como c en c.id = r.cita_id donde {filtro}
                        ordenar r.programado mostrar r.cita_id como cita_id, r.tipo como tipo, r.estado como estado,
                        r.programado como programado, r.canal como canal""", params):
                avisos[r["cita_id"]].append(r)
        series = {}
        if any(c["serie"] for c in citas):
            for f in con.consultar(f"""buscar citas donde serie en (buscar citas como c donde {filtro} y c.serie no es nulo mostrar c.serie)
                                        y estado != "anulada" ordenar empieza mostrar id, serie""", params):
                series.setdefault(f["serie"], []).append(f["id"])
        ve = self.ve_notas(yo)
        for c in citas:
            if c["serie"] and c["id"] in series.get(c["serie"], []):
                c["serie_n"], c["serie_total"] = series[c["serie"]].index(c["id"]) + 1, len(series[c["serie"]])
            c["avisos"] = avisos[c["id"]]
            c["minutos"] = int((agenda.de_sbd(c["termina"]) - agenda.de_sbd(c["empieza"])).total_seconds() // 60)
            if not ve:
                c.pop("nota", None)
        return citas

    def libro(self, yo, dia):
        """La hoja de un día: médicos activos con sus franjas, citas y huecos."""
        ahora = self.reloj()
        meds = self.medicos()
        with self.bd.conexion() as con:
            citas = self._citas_rango(con, yo, dia, dia + timedelta(days=1))
            ausencias = con.consultar("buscar ausencias donde desde <= ? y hasta >= ?", [dia.isoformat(), dia.isoformat()])
        aus = {a["medico_id"]: a for a in ausencias}
        por = defaultdict(list)
        for c in citas:
            por[c["medico_id"]].append(c)
        columnas = []
        for m in meds:
            aus_m = [aus[m["id"]]] if m["id"] in aus else []
            columnas.append({
                "medico": {k: m[k] for k in ("id", "nombre", "especialidad", "consulta", "color")},
                "franjas": agenda.franjas_del_dia(m["franjas"], dia),
                "ausencia": aus_m[0] if aus_m else None,
                "citas": por[m["id"]],
                "huecos": agenda.huecos(m["franjas"], aus_m, por[m["id"]], dia, ahora),
            })
        return {"fecha": dia.isoformat(), "ahora": agenda.a_sbd(ahora), "columnas": columnas}

    def semana(self, yo, medico_id, lunes):
        lunes = lunes - timedelta(days=lunes.weekday())
        ahora = self.reloj()
        meds = {m["id"]: m for m in self.medicos(todos=True)}
        m = meds.get(medico_id)
        if not m:
            raise ErrorApi(404, "Ese médico no existe.")
        with self.bd.conexion() as con:
            citas = self._citas_rango(con, yo, lunes, lunes + timedelta(days=7), medico_id)
            ausencias = con.consultar("buscar ausencias donde medico_id = ? y desde <= ? y hasta >= ?",
                                      [medico_id, (lunes + timedelta(days=6)).isoformat(), lunes.isoformat()])
        dias = []
        for i in range(7):
            d = lunes + timedelta(days=i)
            del_dia = [c for c in citas if c["empieza"][:10] == d.isoformat()]
            aus = agenda.ausencia_en(ausencias, d)
            dias.append({"fecha": d.isoformat(), "franjas": agenda.franjas_del_dia(m["franjas"], d), "ausencia": aus,
                         "citas": del_dia, "huecos": agenda.huecos(m["franjas"], [aus] if aus else [], del_dia, d, ahora)})
        return {"medico": {k: m[k] for k in ("id", "nombre", "especialidad", "consulta", "color")},
                "lunes": lunes.isoformat(), "ahora": agenda.a_sbd(ahora), "dias": dias}

    def huecos(self, medico_id, dia, dias=1):
        """Huecos libres de un médico desde un día; con dias > 1 sirve para «primer hueco libre»."""
        ahora = self.reloj()
        meds = {m["id"]: m for m in self.medicos()}
        m = meds.get(medico_id)
        if not m:
            raise ErrorApi(404, "Ese médico no existe o está de baja.")
        fin = dia + timedelta(days=dias)
        with self.bd.conexion() as con:
            citas = con.consultar("buscar citas donde medico_id = ? y empieza >= ? y empieza < ? mostrar empieza, termina, estado",
                                  [medico_id, f"{dia} 00:00:00", f"{fin} 00:00:00"])
            ausencias = con.consultar("buscar ausencias donde medico_id = ? y hasta >= ? y desde < ?", [medico_id, dia.isoformat(), fin.isoformat()])
        res = []
        for i in range(dias):
            d = dia + timedelta(days=i)
            h = agenda.huecos(m["franjas"], ausencias, [c for c in citas if c["empieza"][:10] == d.isoformat()], d, ahora)
            if h:
                res.append({"fecha": d.isoformat(), "huecos": h})
        return res

    def _comprobar(self, con, medico_id, paciente_id, inicio, fin, excluir, forzar):
        m = con.una("buscar medicos donde id = ? y activo = verdadero", [medico_id])
        if not m:
            raise ErrorApi(404, "Ese médico no existe o está de baja.")
        if not con.una("buscar pacientes donde id = ? mostrar id", [paciente_id]):
            raise ErrorApi(404, "Ese paciente no está en el fichero.")
        if inicio <= self.reloj():
            raise ErrorApi(400, "Esa hora ya ha pasado.")
        if inicio.date() != fin.date():
            raise ErrorApi(400, "Una cita no puede pasar de un día a otro.")
        rango = [agenda.a_sbd(inicio - timedelta(hours=6)), agenda.a_sbd(fin)]
        for c in con.consultar(
                """buscar citas como c unir pacientes como p en p.id = c.paciente_id
                   donde c.medico_id = ? y c.id != ? y c.empieza >= ? y c.empieza < ? y c.estado en ["pendiente", "confirmada", "atendida", "no_acudio"]
                   mostrar c.empieza como empieza, c.termina como termina, p.nombre como nombre, p.apellidos como apellidos""",
                [medico_id, excluir or 0] + rango):
            if agenda.se_solapan(inicio, fin, agenda.de_sbd(c["empieza"]), agenda.de_sbd(c["termina"])):
                raise ErrorApi(409, f"Choca con la cita de {c['nombre']} {c['apellidos']} a las {c['empieza'][11:16]}.", "choque")
        if forzar:
            return m
        franjas = con.consultar("buscar horarios donde medico_id = ?", [medico_id])
        ausencias = con.consultar("buscar ausencias donde medico_id = ?", [medico_id])
        aus = agenda.ausencia_en(ausencias, inicio.date())
        if aus:
            motivo = f" ({aus['motivo']})" if aus.get("motivo") else ""
            raise ErrorApi(409, f"{m['nombre']} no pasa consulta ese día{motivo}. ¿Darla igualmente?", "ausencia")
        if not agenda.dentro_de_horario(franjas, inicio, fin):
            raise ErrorApi(409, f"Queda fuera del horario de {m['nombre']}. ¿Darla igualmente?", "fuera_horario")
        otra = con.una(
            """buscar citas como c unir medicos como m en m.id = c.medico_id
               donde c.paciente_id = ? y c.id != ? y c.empieza < ? y c.termina > ? y c.estado en ["pendiente", "confirmada"]
               mostrar c.empieza como empieza, m.nombre como medico""",
            [paciente_id, excluir or 0, agenda.a_sbd(fin), agenda.a_sbd(inicio)])
        if otra:
            raise ErrorApi(409, f"El paciente ya tiene cita a esa hora con {otra['medico']} ({otra['empieza'][11:16]}). ¿Darla igualmente?", "paciente_ocupado")
        return m

    @staticmethod
    def _momento(datos):
        try:
            inicio = agenda.de_sbd(f"{datos.get('fecha')} {datos.get('hora')}")
        except ValueError:
            raise ErrorApi(400, "Falta el día o la hora de la cita.") from None
        minutos = entero(datos.get("minutos") or 20, "La duración")
        if not 5 <= minutos <= 240:
            raise ErrorApi(400, "Una cita dura entre 5 y 240 minutos.")
        return inicio, inicio + timedelta(minutes=minutos)

    # ---- crear, series, mover y estados ----

    REPETIR = {"semana": 7, "2semanas": 14, "4semanas": 28, "mes": None}

    def _fechas_serie(self, inicio, repetir, veces):
        if repetir not in self.REPETIR:
            raise ErrorApi(400, "La repetición es cada semana, cada 2 semanas, cada 4 semanas o cada mes.")
        veces = entero(veces, "Las veces")
        if not 2 <= veces <= 26:
            raise ErrorApi(400, "Una serie lleva de 2 a 26 citas.")
        fechas = []
        for n in range(veces):
            if self.REPETIR[repetir]:
                fechas.append(inicio + timedelta(days=self.REPETIR[repetir] * n))
            else:  # el mismo día del mes; si no existe (31 de abril), el último del mes
                mes = inicio.month - 1 + n
                año, mes = inicio.year + mes // 12, mes % 12 + 1
                dia = min(inicio.day, [31, 29 if año % 4 == 0 and (año % 100 or año % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1])
                fechas.append(inicio.replace(year=año, month=mes, day=dia))
        return fechas

    def previa_serie(self, datos):
        """Qué fechas de una serie caben y cuáles no (y por qué), sin guardar nada."""
        inicio, fin = self._momento(datos)
        medico_id = entero(datos.get("medico_id"), "El médico")
        paciente_id = entero(datos.get("paciente_id"), "El paciente")
        duracion = fin - inicio
        res = []
        with self.bd.conexion() as con:
            for f in self._fechas_serie(inicio, datos.get("repetir"), datos.get("veces")):
                try:
                    self._comprobar(con, medico_id, paciente_id, f, f + duracion, None, False)
                    res.append({"fecha": f.date().isoformat(), "hora": agenda.hhmm(f), "cabe": True})
                except ErrorApi as err:
                    res.append({"fecha": f.date().isoformat(), "hora": agenda.hhmm(f), "cabe": False, "motivo": err.mensaje.replace(" ¿Darla igualmente?", "")})
        return res

    def crear_cita(self, yo, datos):
        inicio, fin = self._momento(datos)
        medico_id = entero(datos.get("medico_id"), "El médico")
        paciente_id = entero(datos.get("paciente_id"), "El paciente")
        origen = datos.get("origen") if datos.get("origen") in ("recepcion", "telefono") else "recepcion"
        motivo = texto(datos, "motivo", 160)
        ahora = self.reloj()
        forzar = bool(datos.get("forzar"))
        with self.bd.conexion(f"citas · cuenta {yo['id']}") as con:
            with con.transaccion():
                if datos.get("repetir"):
                    # Serie: se dan las que caben; las que chocan se saltan y se dicen. La primera tiene que caber.
                    serie = secrets.token_hex(6)
                    ids, saltadas = [], []
                    for f in self._fechas_serie(inicio, datos["repetir"], datos.get("veces")):
                        try:
                            self._comprobar(con, medico_id, paciente_id, f, f + (fin - inicio), None, forzar and not ids)
                        except ErrorApi as err:
                            if not ids:
                                raise
                            saltadas.append({"fecha": f.date().isoformat(), "motivo": err.mensaje.replace(" ¿Darla igualmente?", "")})
                            continue
                        ids.append(self._insertar_cita(con, yo, paciente_id, medico_id, f, f + (fin - inicio), motivo, origen, ahora, serie))
                    for n, cid in enumerate(ids):
                        recordatorios.programar(con, cid, ahora, nueva=n == 0)   # un solo «cita dada», con todas las fechas
                    resultado = {"id": ids[0], "ids": ids, "saltadas": saltadas, "serie": serie}
                else:
                    self._comprobar(con, medico_id, paciente_id, inicio, fin, None, forzar)
                    cid = self._insertar_cita(con, yo, paciente_id, medico_id, inicio, fin, motivo, origen, ahora)
                    recordatorios.programar(con, cid, ahora, nueva=True)
                    resultado = {"id": cid}
        self.despertar.set()
        return resultado

    def _insertar_cita(self, con, yo, paciente_id, medico_id, inicio, fin, motivo, origen, ahora, serie=None):
        cid = con.ejecutar(
            """insertar en citas { paciente_id: ?, medico_id: ?, empieza: ?, termina: ?, motivo: ?, origen: ?, creada_en: ?, creada_por: ?, serie: ? }
               devolver id""",
            [paciente_id, medico_id, agenda.a_sbd(inicio), agenda.a_sbd(fin), motivo, origen, agenda.a_sbd(ahora), yo["id"] if yo else None, serie]).scalar()
        self._cerrar_ofertas_que_chocan(con, medico_id, inicio, fin, ahora)
        return cid

    @staticmethod
    def _cerrar_ofertas_que_chocan(con, medico_id, inicio, fin, ahora):
        """Si recepción da a mano un hueco que estaba ofrecido a la lista de espera, la oferta se cierra."""
        for o in con.consultar('buscar ofertas donde medico_id = ? y estado = "abierta" y empieza < ? y termina > ?',
                               [medico_id, agenda.a_sbd(fin), agenda.a_sbd(inicio)]):
            espera._cerrar(con, o, "ocupada", ahora)

    def _liberar(self, con, medico_id, inicio, fin, ahora):
        """Un hueco que se queda libre (anulación o cita movida) se ofrece a la lista de espera."""
        return espera.ofrecer_hueco(con, medico_id, inicio, fin, ahora)

    def mover_cita(self, yo, cid, datos):
        ahora = self.reloj()
        oferta = None
        with self.bd.conexion(f"citas · cuenta {yo['id']}") as con:
            c = con.una("buscar citas donde id = ?", [cid])
            if not c:
                raise ErrorApi(404, "Esa cita no existe.")
            if c["estado"] not in agenda.ACTIVAS:
                raise ErrorApi(409, "Solo se mueven citas pendientes o confirmadas.")
            if c["llegada"]:
                raise ErrorApi(409, "El paciente ya está en la sala de espera.")
            actual_ini, actual_fin = agenda.de_sbd(c["empieza"]), agenda.de_sbd(c["termina"])
            datos = {"fecha": datos.get("fecha") or actual_ini.date().isoformat(), "hora": datos.get("hora") or agenda.hhmm(actual_ini),
                     "minutos": datos.get("minutos") or int((actual_fin - actual_ini).total_seconds() // 60),
                     "medico_id": datos.get("medico_id") or c["medico_id"], "motivo": datos.get("motivo", c["motivo"]),
                     "forzar": datos.get("forzar")}
            inicio, fin = self._momento(datos)
            medico_id = entero(datos["medico_id"], "El médico")
            with con.transaccion():
                self._comprobar(con, medico_id, c["paciente_id"], inicio, fin, cid, bool(datos["forzar"]))
                cambia_hora = inicio != actual_ini or medico_id != c["medico_id"]
                con.ejecutar("actualizar citas poner empieza = ?, termina = ?, medico_id = ?, motivo = ?, estado = ?, confirmada_en = ? donde id = ?",
                             [agenda.a_sbd(inicio), agenda.a_sbd(fin), medico_id, texto(datos, "motivo", 160),
                              "pendiente" if cambia_hora else c["estado"], None if cambia_hora else c["confirmada_en"], cid])
                self._cerrar_ofertas_que_chocan(con, medico_id, inicio, fin, ahora)
                # Una cita movida vuelve a «pendiente» y lleva aviso de cita nueva: la hora que sabía el paciente ya no vale.
                recordatorios.programar(con, cid, ahora, nueva=cambia_hora)
                if cambia_hora:
                    oferta = self._liberar(con, c["medico_id"], actual_ini, actual_fin, ahora)
        self.despertar.set()
        return {"ok": True, "oferta": oferta}

    def estado_cita(self, yo, cid, datos):
        estado = datos.get("estado")
        if estado not in ("pendiente", "confirmada", "atendida", "no_acudio", "anulada"):
            raise ErrorApi(400, "Estado de cita desconocido.")
        ahora = self.reloj()
        ofertas = []
        with self.bd.conexion(f"citas · cuenta {yo['id']}") as con:
            c = con.una("buscar citas donde id = ?", [cid])
            if not c:
                raise ErrorApi(404, "Esa cita no existe.")
            if yo["rol"] == "medico" and c["medico_id"] != yo["medico_id"] and estado in ("atendida", "no_acudio"):
                raise ErrorApi(403, "Solo puedes marcar como atendidas las citas de tu consulta.")
            empieza = agenda.de_sbd(c["empieza"])
            if estado in ("atendida", "no_acudio") and empieza > ahora + timedelta(minutes=30) and not c["llegada"]:
                raise ErrorApi(409, "Todavía no ha llegado la hora de esta cita.")
            if estado in ("pendiente", "confirmada") and c["estado"] == "anulada" and empieza <= ahora:
                raise ErrorApi(409, "Esa cita ya pasó: da una nueva.")
            if estado in ("pendiente", "confirmada") and c["estado"] == "anulada":
                # Volver a darla solo si el hueco sigue libre
                otra = con.una("""buscar citas donde medico_id = ? y id != ? y empieza < ? y termina > ? y estado en ["pendiente", "confirmada", "atendida", "no_acudio"]
                                  mostrar id""", [c["medico_id"], cid, c["termina"], c["empieza"]])
                if otra:
                    raise ErrorApi(409, "Ese hueco ya lo ocupa otra cita: da una nueva.")
            cambios = {"estado": estado}
            if estado == "confirmada" and not c["confirmada_en"]:
                cambios["confirmada_en"] = agenda.a_sbd(ahora)
            if estado == "anulada":
                cambios.update(anulada_en=agenda.a_sbd(ahora), anulada_por="recepcion")
            if estado == "atendida" and c["estado"] != "atendida":
                cambios["atendida_en"] = agenda.a_sbd(ahora)
            if estado in ("pendiente", "confirmada") and c["estado"] in ("atendida", "no_acudio"):
                cambios.update(atendida_en=None)
            if estado == "no_acudio":
                cambios.update(llegada=None, entra=None)
            if "nota" in datos:
                if yo["rol"] != "medico" or c["medico_id"] != yo["medico_id"]:
                    raise ErrorApi(403, "La nota clínica la escribe el médico de la cita.")
                cambios["nota"] = texto(datos, "nota", 4000)
            # «Anular esta y las siguientes» de una serie
            ids = [cid]
            if estado == "anulada" and datos.get("serie") and c["serie"]:
                ids += [x["id"] for x in con.consultar(
                    'buscar citas donde serie = ? y id != ? y empieza > ? y estado en ["pendiente", "confirmada"] mostrar id',
                    [c["serie"], cid, c["empieza"]])]
            with con.transaccion():
                poner = ", ".join(f"{k} = ?" for k in cambios)
                for i in ids:
                    fila = c if i == cid else con.una("buscar citas donde id = ?", [i])
                    if i != cid and fila["estado"] not in agenda.ACTIVAS:
                        continue
                    con.ejecutar(f"actualizar citas poner {poner} donde id = ?", list(cambios.values()) + [i])
                    # Volver a dar una cita anulada manda otra vez el aviso de «cita dada», salvo si es un «deshacer» inmediato.
                    recordatorios.programar(con, i, ahora, nueva=c["estado"] == "anulada" and estado in agenda.ACTIVAS and not datos.get("deshacer"))
                    if estado == "anulada" and fila["estado"] in agenda.ACTIVAS:
                        o = self._liberar(con, fila["medico_id"], agenda.de_sbd(fila["empieza"]), agenda.de_sbd(fila["termina"]), ahora)
                        if o:
                            ofertas.append(o)
                if c["estado"] == "anulada" and estado in agenda.ACTIVAS:
                    self._cerrar_ofertas_que_chocan(con, c["medico_id"], empieza, agenda.de_sbd(c["termina"]), ahora)
        self.despertar.set()
        return {"ok": True, "anuladas": len(ids) if estado == "anulada" else 0, "ofertas": ofertas}

    def sala(self, yo, cid, accion):
        """La sala de espera: «llega» (recepción) y «pasa» (a la consulta). «deshacer» quita la llegada."""
        ahora = self.reloj()
        with self.bd.conexion(f"sala · cuenta {yo['id']}") as con:
            c = con.una("buscar citas donde id = ?", [cid])
            if not c:
                raise ErrorApi(404, "Esa cita no existe.")
            if c["estado"] not in agenda.ACTIVAS:
                raise ErrorApi(409, "Esa cita ya está cerrada.")
            if c["empieza"][:10] != ahora.date().isoformat():
                raise ErrorApi(409, "Solo se marca la llegada de las citas de hoy.")
            if accion == "llega":
                con.ejecutar("actualizar citas poner llegada = ?, estado = \"confirmada\", confirmada_en = si_nulo(confirmada_en, ?) donde id = ?",
                             [agenda.a_sbd(ahora), agenda.a_sbd(ahora), cid])
                # Ya está aquí: el aviso de «2 h antes» no hace falta.
                con.ejecutar('actualizar recordatorios poner estado = "anulado", error = "Ya estaba en la sala." donde cita_id = ? y estado = "pendiente"', [cid])
            elif accion == "pasa":
                if yo["rol"] == "medico" and c["medico_id"] != yo["medico_id"]:
                    raise ErrorApi(403, "Solo puedes hacer pasar a tus pacientes.")
                con.ejecutar("actualizar citas poner entra = ?, llegada = si_nulo(llegada, ?) donde id = ?", [agenda.a_sbd(ahora), agenda.a_sbd(ahora), cid])
            elif accion == "deshacer":
                con.ejecutar("actualizar citas poner llegada = nulo, entra = nulo donde id = ?", [cid])
                recordatorios.programar(con, cid, ahora)
            else:
                raise ErrorApi(400, "Acción de sala desconocida.")
        return {"ok": True}

    def justificante(self, cid):
        with self.bd.conexion() as con:
            c = con.una(
                """buscar citas como c unir pacientes como p en p.id = c.paciente_id unir medicos como m en m.id = c.medico_id donde c.id = ?
                   mostrar c.id como id, c.empieza como empieza, c.termina como termina, c.llegada como llegada, c.atendida_en como atendida_en,
                           c.estado como estado, p.nombre como nombre, p.apellidos como apellidos, p.documento como documento,
                           m.nombre como medico, m.especialidad como especialidad, m.colegiado como colegiado""", [cid])
            if not c:
                raise ErrorApi(404, "Esa cita no existe.")
            a = recordatorios.leer_ajustes(con)
        if c["estado"] != "atendida" and not c["llegada"]:
            raise ErrorApi(409, "Solo hay justificante de las citas a las que el paciente vino.")
        desde = c["llegada"] or c["empieza"]
        hasta = c["atendida_en"] or c["termina"]
        if hasta < desde:
            hasta = c["termina"]
        ruta = self.ruta("v", cid)
        return {**c, "desde": desde, "hasta": hasta, "centro": a.get("centro"), "direccion_centro": a.get("direccion"),
                "telefono_centro": a.get("telefono"), "codigo": ruta.rsplit("/", 1)[1][:10].upper(),
                "verificar": f"{self.cartero.url_publica}{ruta}"}

    def verificar_justificante(self, cid, firma):
        if not self.firma_valida("justificante", cid, firma):
            raise ErrorApi(404, "Este justificante no es válido.")
        j = self.justificante(cid)
        # Quien verifica solo ve lo que dice el papel, con las iniciales del paciente.
        iniciales = "".join(f"{x[0]}." for x in f"{j['nombre']} {j['apellidos']}".split() if x)
        return {"valido": True, "iniciales": iniciales, "fecha": j["desde"][:10], "desde": j["desde"], "hasta": j["hasta"],
                "especialidad": j["especialidad"], "centro": j["centro"], "codigo": j["codigo"]}

    def recordar_ya(self, yo, cid):
        with self.bd.conexion(f"avisos · cuenta {yo['id']}") as con:
            try:
                recordatorios.aviso_manual(con, cid, self.reloj())
            except ValueError as err:
                raise ErrorApi(409, str(err)) from None
        self.despertar.set()
        self.cartero.repartir(self.reloj(), CENTRO.get())
        return {"ok": True}

    # ================= lista de espera =================

    def lista_espera(self, ver="activa"):
        filtro = 'e.estado en ["esperando", "ofrecida"]' if ver == "activa" else 'e.estado en ["citada", "retirada"]'
        with self.bd.conexion() as con:
            filas = con.consultar(
                f"""buscar espera como e {{
                      unir pacientes como p en p.id = e.paciente_id
                      unir opcional medicos como m en m.id = e.medico_id
                      donde {filtro}
                      ordenar e.creado_en, e.id
                      limite 300
                      mostrar e.id como id, e.paciente_id como paciente_id, e.medico_id como medico_id, e.especialidad como especialidad,
                              e.desde como desde, e.hasta como hasta, e.franja como franja, e.minutos como minutos, e.motivo como motivo,
                              e.estado como estado, e.cita_id como cita_id, e.creado_en como creado_en,
                              p.nombre como nombre, p.apellidos como apellidos, p.telefono como telefono, p.canal como canal,
                              m.nombre como medico, m.color como color
                    }}""")
            abiertas = {o["espera_id"]: o for o in con.consultar('buscar ofertas donde estado = "abierta"')}
            historial = defaultdict(list)
            if filas:
                for o in con.consultar(f"""buscar ofertas como o unir espera como e en e.id = o.espera_id donde {filtro}
                                           ordenar o.creada_en mostrar o.espera_id como espera_id, o.empieza como empieza, o.estado como estado"""):
                    historial[o["espera_id"]].append(o)
            citas = {}
            ids = [f["cita_id"] for f in filas if f["cita_id"]]
            if ids:
                for c in con.consultar("buscar citas donde id en (buscar espera donde cita_id no es nulo mostrar cita_id) mostrar id, empieza"):
                    citas[c["id"]] = c["empieza"]
        for f in filas:
            f["oferta"] = abiertas.get(f["id"])
            f["ofertas"] = historial[f["id"]]
            f["cita_empieza"] = citas.get(f["cita_id"])
        return filas

    def apuntar_espera(self, yo, datos):
        paciente_id = entero(datos.get("paciente_id"), "El paciente")
        medico_id = datos.get("medico_id") or None
        hoy = self.reloj().date()
        try:
            desde = agenda.fecha(datos.get("desde")) if datos.get("desde") else hoy
            hasta = agenda.fecha(datos["hasta"]) if datos.get("hasta") else None
        except ValueError as err:
            raise ErrorApi(400, str(err)) from None
        if hasta and hasta < desde:
            raise ErrorApi(400, "La fecha límite es anterior a la de inicio.")
        franja = datos.get("franja") or "cualquiera"
        if franja not in ("cualquiera", "manana", "tarde"):
            raise ErrorApi(400, "La franja es mañana, tarde o cualquiera.")
        minutos = entero(datos.get("minutos") or 20, "La duración")
        with self.bd.conexion(f"espera · cuenta {yo['id']}") as con:
            p = con.una("buscar pacientes donde id = ?", [paciente_id])
            if not p:
                raise ErrorApi(404, "Ese paciente no está en el fichero.")
            if medico_id:
                m = con.una("buscar medicos donde id = ? y activo = verdadero", [entero(medico_id, "El médico")])
                if not m:
                    raise ErrorApi(404, "Ese médico no existe o está de baja.")
                especialidad = m["especialidad"]
            else:
                especialidad = texto(datos, "especialidad", 60, True, "la especialidad")
            canal, destino = recordatorios.destino_de(p)
            if not canal or not destino:
                raise ErrorApi(409, "Para la lista de espera hace falta poder avisarle: pon su correo o teléfono y el canal de avisos en su ficha.")
            if con.una('buscar espera donde paciente_id = ? y especialidad = ? y estado en ["esperando", "ofrecida"] mostrar id', [paciente_id, especialidad]):
                raise ErrorApi(409, f"Ya está en la lista de espera de {especialidad}.")
            eid = con.ejecutar(
                """insertar en espera { paciente_id: ?, medico_id: ?, especialidad: ?, desde: ?, hasta: ?, franja: ?, minutos: ?, motivo: ?, creado_en: ? }
                   devolver id""",
                [paciente_id, int(medico_id) if medico_id else None, especialidad, desde.isoformat(), hasta.isoformat() if hasta else None,
                 franja, minutos, texto(datos, "motivo", 160), self.ahora()]).scalar()
        return {"id": eid}

    def cambiar_espera(self, yo, eid, datos):
        estado = datos.get("estado")
        if estado not in ("retirada", "esperando", "citada"):
            raise ErrorApi(400, "Solo se puede retirar, citar o volver a poner en la lista.")
        ahora = self.reloj()
        with self.bd.conexion(f"espera · cuenta {yo['id']}") as con:
            e = con.una("buscar espera donde id = ?", [eid])
            if not e:
                raise ErrorApi(404, "Esa entrada de la lista no existe.")
            with con.transaccion():
                if estado == "retirada":
                    for o in con.consultar('buscar ofertas donde espera_id = ? y estado = "abierta"', [eid]):
                        espera.siguiente(con, o, "rechazada", ahora)
                if estado == "citada":
                    cita_id = entero(datos.get("cita_id"), "La cita")
                    if not con.una("buscar citas donde id = ? y paciente_id = ?", [cita_id, e["paciente_id"]]):
                        raise ErrorApi(400, "Esa cita no es de este paciente.")
                    for o in con.consultar('buscar ofertas donde espera_id = ? y estado = "abierta"', [eid]):
                        espera.siguiente(con, o, "rechazada", ahora)
                    con.ejecutar('actualizar espera poner estado = "citada", cita_id = ? donde id = ?', [cita_id, eid])
                else:
                    con.ejecutar("actualizar espera poner estado = ? donde id = ?", [estado, eid])
        self.despertar.set()
        return {"ok": True}

    def oferta_publica(self, oid, firma):
        if not self.firma_valida("oferta", oid, firma):
            raise ErrorApi(404, "Este enlace no es válido. Llame a la consulta si tiene dudas.")
        with self.bd.conexion() as con:
            o = con.una(
                """buscar ofertas como o unir espera como e en e.id = o.espera_id unir pacientes como p en p.id = e.paciente_id
                     unir medicos como m en m.id = o.medico_id donde o.id = ?
                   mostrar o.id como id, o.empieza como empieza, o.termina como termina, o.estado como estado, o.caduca_en como caduca_en,
                           e.cita_id como cita_id, p.nombre como nombre, m.nombre como medico, m.especialidad como especialidad, m.consulta como consulta""",
                [oid])
            if not o:
                raise ErrorApi(404, "Esta oferta ya no existe.")
            a = recordatorios.leer_ajustes(con)
        if o["estado"] == "abierta" and agenda.de_sbd(o["caduca_en"]) <= self.reloj():
            o["estado"] = "caducada"
        if o["estado"] == "aceptada" and o["cita_id"]:
            o["enlace_cita"] = self.ruta("c", o["cita_id"])
        o.pop("cita_id", None)
        o["centro"], o["direccion"], o["telefono_centro"] = a.get("centro"), a.get("direccion"), a.get("telefono")
        return o

    def accion_oferta(self, oid, firma, accion):
        self.oferta_publica(oid, firma)
        ahora = self.reloj()
        with self.bd.conexion(f"paciente · oferta {oid}") as con:
            try:
                with con.transaccion():
                    if accion == "aceptar":
                        espera.aceptar(con, oid, ahora)
                    elif accion == "rechazar":
                        o = con.una("buscar ofertas donde id = ?", [oid])
                        if o["estado"] != "abierta":
                            raise ValueError("Esta oferta ya está cerrada.")
                        espera.siguiente(con, o, "rechazada", ahora)
                    else:
                        raise ErrorApi(400, "Acción desconocida.")
            except ValueError as err:
                raise ErrorApi(409, str(err)) from None
        self.despertar.set()
        return self.oferta_publica(oid, firma)

    # ================= avisos =================

    def avisos(self, vista):
        ahora = self.ahora()
        filtros = {
            "bandeja": ('r.estado = "en_bandeja"', "programado", False),
            "proximos": ('r.estado = "pendiente"', "programado", False),
            "enviados": ('r.estado = "enviado"', "enviado_en", True),
            "problemas": ('r.estado en ["fallido", "omitido", "anulado"]', "programado", True),
        }
        if vista not in filtros:
            raise ErrorApi(400, "Esa bandeja no existe.")
        donde, orden, desc = filtros[vista]
        comunes = """r.id como id, r.cita_id como cita_id, r.oferta_id como oferta_id, r.tipo como tipo, r.canal como canal, r.destino como destino,
                     r.programado como programado, r.estado como estado, r.intentos como intentos, r.enviado_en como enviado_en,
                     r.error como error, r.asunto como asunto, r.cuerpo como cuerpo"""
        with self.bd.conexion() as con:
            de_citas = con.consultar(
                f"""buscar recordatorios como r {{
                      unir citas como c en c.id = r.cita_id
                      unir pacientes como p en p.id = c.paciente_id
                      unir medicos como m en m.id = c.medico_id
                      donde {donde}
                      ordenar r.{orden}{" desc" if desc else ""}
                      limite 200
                      mostrar {comunes}, c.empieza como empieza, c.estado como estado_cita, p.nombre como nombre, p.apellidos como apellidos,
                              m.nombre como medico, m.color como color
                    }}""")
            de_ofertas = con.consultar(
                f"""buscar recordatorios como r {{
                      unir ofertas como o en o.id = r.oferta_id
                      unir espera como e en e.id = o.espera_id
                      unir pacientes como p en p.id = e.paciente_id
                      unir medicos como m en m.id = o.medico_id
                      donde {donde}
                      ordenar r.{orden}{" desc" if desc else ""}
                      limite 100
                      mostrar {comunes}, o.empieza como empieza, o.estado como estado_oferta, o.caduca_en como caduca_en,
                              p.nombre como nombre, p.apellidos como apellidos, m.nombre como medico, m.color como color
                    }}""")
            cuentas = {f["estado"]: f["n"] for f in con.consultar("buscar recordatorios agrupar estado mostrar estado, contar() como n")}
            hoy = con.valor('buscar recordatorios donde estado = "enviado" y enviado_en >= ? mostrar contar()', [ahora[:10] + " 00:00:00"])
        filas = sorted(de_citas + de_ofertas, key=lambda f: f[orden] or "", reverse=desc)[:200]
        # Una oferta que ya se cerró no hace falta mandarla: se aparta de la bandeja.
        if vista == "bandeja":
            filas = [f for f in filas if f.get("estado_oferta") in (None, "abierta")]
        return {"vista": vista, "avisos": filas, "cuentas": cuentas, "enviados_hoy": hoy,
                "correo_configurado": recordatorios.config_correo(self.dir_datos) is not None}

    def aviso_enviado(self, yo, rid):
        with self.bd.conexion(f"avisos · cuenta {yo['id']}") as con:
            r = con.una("buscar recordatorios donde id = ?", [rid])
            if not r:
                raise ErrorApi(404, "Ese aviso no existe.")
            if r["estado"] not in ("en_bandeja", "fallido"):
                raise ErrorApi(409, "Ese aviso no está esperando a que lo mandes.")
            con.ejecutar('actualizar recordatorios poner estado = "enviado", enviado_en = ?, error = ? donde id = ?',
                         [self.ahora(), f"Mandado a mano por {yo['nombre']}"[:200], rid])
        return {"ok": True}

    def aviso_reintentar(self, yo, rid):
        with self.bd.conexion(f"avisos · cuenta {yo['id']}") as con:
            r = con.una("buscar recordatorios donde id = ?", [rid])
            if not r or r["estado"] not in ("en_bandeja", "fallido"):
                raise ErrorApi(409, "Ese aviso no se puede reintentar.")
            con.ejecutar('actualizar recordatorios poner estado = "pendiente", intentos = 0, programado = ? donde id = ?', [self.ahora(), rid])
        self.cartero.repartir(self.reloj(), CENTRO.get())
        return {"ok": True}

    # ================= hoja del día (cifras) =================

    def resumen(self, dia):
        d0, d1 = f"{dia} 00:00:00", f"{dia + timedelta(days=1)} 00:00:00"
        with self.bd.conexion() as con:
            por_estado = {f["estado"]: f["n"] for f in con.consultar(
                "buscar citas donde empieza >= ? y empieza < ? agrupar estado mostrar estado, contar() como n", [d0, d1])}
            en_sala = con.valor('buscar citas donde empieza >= ? y empieza < ? y llegada no es nulo y entra es nulo y estado en ["pendiente", "confirmada"] mostrar contar()', [d0, d1])
            bandeja = con.valor('buscar recordatorios donde estado en ["en_bandeja", "fallido"] mostrar contar()')
            espera_n = con.valor('buscar espera donde estado en ["esperando", "ofrecida"] mostrar contar()')
        return {"por_estado": por_estado, "en_sala": en_sala, "bandeja": bandeja, "espera": espera_n}

    # ================= informe del mes =================

    def informe(self, mes):
        try:
            año, m = (int(x) for x in mes.split("-"))
            ini = date(año, m, 1)
        except (ValueError, AttributeError):
            raise ErrorApi(400, "El mes va como AAAA-MM.") from None
        fin = date(año + (m == 12), m % 12 + 1, 1)
        return informe_mod.calcular(self.bd, ini, fin, self.reloj())

    # ================= enlace del paciente =================

    def cita_publica(self, cid, firma):
        if not self.firma_valida("cita", cid, firma):
            raise ErrorApi(404, "Este enlace no es válido. Llame a la consulta para cualquier cambio.")
        with self.bd.conexion() as con:
            c = con.una(
                """buscar citas como c unir pacientes como p en p.id = c.paciente_id unir medicos como m en m.id = c.medico_id
                   donde c.id = ?
                   mostrar c.id como id, c.empieza como empieza, c.termina como termina, c.estado como estado, p.nombre como nombre,
                           c.medico_id como medico_id, m.activo como medico_activo,
                           m.nombre como medico, m.especialidad como especialidad, m.consulta como consulta""", [cid])
            if not c:
                raise ErrorApi(404, "Esta cita ya no existe. Llame a la consulta si tiene dudas.")
            a = recordatorios.leer_ajustes(con)
        c["pasada"] = agenda.de_sbd(c["empieza"]) <= self.reloj()
        c["centro"], c["direccion"], c["telefono_centro"] = a.get("centro"), a.get("direccion"), a.get("telefono")
        c["puede_pedir"] = a.get("citas_por_enlace", "si") == "si" and bool(c.pop("medico_activo"))
        return c

    def accion_publica(self, cid, firma, accion):
        c = self.cita_publica(cid, firma)
        if c["pasada"]:
            raise ErrorApi(409, "Esta cita ya ha pasado.")
        if c["estado"] not in agenda.ACTIVAS:
            raise ErrorApi(409, "Esta cita ya no está en pie." if c["estado"] == "anulada" else "Esta cita ya no se puede cambiar.")
        ahora = self.reloj()
        with self.bd.conexion(f"paciente · cita {cid}") as con:
            with con.transaccion():
                if accion == "confirmar":
                    con.ejecutar('actualizar citas poner estado = "confirmada", confirmada_en = ? donde id = ?', [agenda.a_sbd(ahora), cid])
                elif accion == "anular":
                    con.ejecutar('actualizar citas poner estado = "anulada", anulada_en = ?, anulada_por = "paciente" donde id = ?',
                                 [agenda.a_sbd(ahora), cid])
                else:
                    raise ErrorApi(400, "Acción desconocida.")
                recordatorios.programar(con, cid, ahora)
                if accion == "anular":
                    self._liberar(con, c["medico_id"], agenda.de_sbd(c["empieza"]), agenda.de_sbd(c["termina"]), ahora)
        self.despertar.set()
        return self.cita_publica(cid, firma)

    MAX_PEDIDAS = 2       # citas futuras que un paciente puede tener pedidas por su enlace a la vez

    def huecos_publicos(self, cid, firma, desde):
        """Los huecos del mismo médico en las dos semanas que se piden: solo días y horas, nada de nadie."""
        c = self.cita_publica(cid, firma)
        if not c["puede_pedir"]:
            raise ErrorApi(403, "Para pedir otra cita, llame a la consulta.")
        hoy = self.reloj().date()
        desde = max(desde, hoy)
        if desde > hoy + timedelta(days=90):
            return {"desde": desde.isoformat(), "dias": [], "fin": True}
        return {"desde": desde.isoformat(), "dias": self.huecos(c["medico_id"], desde, 14), "fin": False}

    def pedir_cita(self, cid, firma, datos):
        c = self.cita_publica(cid, firma)
        if not c["puede_pedir"]:
            raise ErrorApi(403, "Para pedir otra cita, llame a la consulta.")
        inicio, _ = self._momento({"fecha": datos.get("fecha"), "hora": datos.get("hora"), "minutos": 20})
        ahora = self.reloj()
        with self.bd.conexion(f"paciente · desde cita {cid}") as con:
            paciente_id = con.valor("buscar citas donde id = ? mostrar paciente_id", [cid])
            pedidas = con.valor('buscar citas donde paciente_id = ? y origen = "paciente" y empieza > ? y estado en ["pendiente", "confirmada"] mostrar contar()',
                                [paciente_id, agenda.a_sbd(ahora)])
            if pedidas >= self.MAX_PEDIDAS:
                raise ErrorApi(409, "Ya tiene dos citas pedidas por internet. Para más, llame a la consulta.")
            # Solo vale una hora que de verdad sea un hueco libre: con su duración, y dentro del horario.
            libres = self.huecos(c["medico_id"], inicio.date(), 1)
            hueco = next((h for d in libres for h in d["huecos"] if h["hora"] == agenda.hhmm(inicio)), None)
            if not hueco:
                raise ErrorApi(409, "Esa hora acaba de ocuparse. Elija otra.")
            fin = inicio + timedelta(minutes=hueco["minutos"])
            with con.transaccion():
                try:
                    self._comprobar(con, c["medico_id"], paciente_id, inicio, fin, None, False)
                except ErrorApi as err:
                    if err.codigo == "paciente_ocupado":
                        raise ErrorApi(409, "Ya tiene otra cita a esa hora.") from None
                    raise
                nueva = self._insertar_cita(con, None, paciente_id, c["medico_id"], inicio, fin, None, "paciente", ahora)
                recordatorios.programar(con, nueva, ahora, nueva=True)
        self.despertar.set()
        return {"id": nueva, "enlace": self.ruta("c", nueva)}

    def ics(self, cid, firma):
        c = self.cita_publica(cid, firma)
        ini, fin = agenda.de_sbd(c["empieza"]), agenda.de_sbd(c["termina"])

        def esc(t):
            return str(t or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

        zona = str(self.zona)
        lugar = ", ".join(x for x in (c["consulta"], c["direccion"]) if x)
        lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Volante//Citas//ES", "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
                  f"UID:cita-{cid}@volante", f"DTSTAMP:{datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')}",
                  f"DTSTART;TZID={zona}:{ini.strftime('%Y%m%dT%H%M%S')}", f"DTEND;TZID={zona}:{fin.strftime('%Y%m%dT%H%M%S')}",
                  f"SUMMARY:{esc('Cita con ' + c['medico'])}", f"LOCATION:{esc(lugar or c['centro'])}",
                  f"DESCRIPTION:{esc((c['centro'] or '') + (' · Tel. ' + c['telefono_centro'] if c['telefono_centro'] else ''))}",
                  "BEGIN:VALARM", "TRIGGER:-PT2H", "ACTION:DISPLAY", "DESCRIPTION:Cita médica", "END:VALARM",
                  "END:VEVENT", "END:VCALENDAR"]
        return ("\r\n".join(lineas) + "\r\n").encode("utf-8")


# ================= HTTP =================

PERMISOS = {
    "direccion": {"citas", "pacientes", "borrar_paciente", "medicos", "ajustes", "equipo", "avisos", "informe"},
    "recepcion": {"citas", "pacientes", "medicos", "avisos"},
    "medico": {"citas", "pacientes", "avisos"},
}
ESTATICOS = {"index.html", "cita.html", "privacidad.html", "favicon.svg", "css", "js", "fuentes"}


class Manejador(BaseHTTPRequestHandler):
    server_version = "Volante/1"
    app: Aplicacion = None
    protocol_version = "HTTP/1.1"

    def log_message(self, formato, *args):
        if os.environ.get("VOLANTE_SILENCIO"):
            return
        # Las rutas de paciente llevan la firma del enlace: no se apunta en el registro.
        sys.stderr.write(f"{self.log_date_time_string()} {self.ip()} {re.sub(r'/([cov])/(\d+)/[^/ ?]+', r'/\1/\2/…', formato % args)}\n")

    def ip(self):
        if self.app.publico:
            reenviada = self.headers.get("X-Forwarded-For", "")
            if reenviada:
                return reenviada.split(",")[-1].strip()
        return self.client_address[0]

    def token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[COOKIE].value if COOKIE in cookie else None

    def cabeceras_seguridad(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")

    def responder(self, estado, datos, tipo, cookie=None, cache="no-store", extra=None):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", cache)
        self.cabeceras_seguridad()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(datos)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True     # el navegador se fue antes de la respuesta (cambió de página)

    def json(self, estado, cuerpo, cookie=None):
        self.responder(estado, json.dumps(cuerpo, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8", cookie)

    def cookie_sesion(self, token):
        segura = "; Secure" if self.app.publico else ""
        if token is None:
            return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{segura}"
        return f"{COOKIE}={token}; Path=/; Max-Age={int(DURACION_SESION.total_seconds())}; HttpOnly; SameSite=Strict{segura}"

    def leer_crudo(self):
        """Lee el cuerpo entero antes de responder nada: con HTTP/1.1 la conexión sigue abierta y un
        cuerpo sin leer se tomaría por la petición siguiente."""
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = 0
        self._crudo = b""
        self._demasiado = largo > MAX_CUERPO
        if self._demasiado:
            self.close_connection = True
            return
        if largo > 0:
            self._crudo = self.rfile.read(largo)

    def cuerpo(self):
        if getattr(self, "_demasiado", False):
            raise ErrorApi(413, "La petición es demasiado grande.")
        if not getattr(self, "_crudo", b""):
            return {}
        try:
            datos = json.loads(self._crudo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ErrorApi(400, "La petición no trae un JSON válido.") from None
        if not isinstance(datos, dict):
            raise ErrorApi(400, "La petición no trae un JSON válido.")
        return datos

    def do_GET(self):
        ruta = urlsplit(self.path).path
        if ruta.startswith("/api/"):
            return self.api("GET")
        if re.fullmatch(r"/[ov]/(?:\d+/)?\d+/[A-Za-z0-9_-]{10,40}", ruta):
            return self.estatico("/cita.html")
        m = re.fullmatch(r"/c/(?:(\d+)/)?(\d+)/([A-Za-z0-9_-]{10,40})(/cita\.ics)?", ruta)
        if m and m.group(4):
            def ics():
                marca = CENTRO.set(None)
                try:
                    self.centro_publico(m.group(1))
                    self.responder(200, self.app.ics(int(m.group(2)), m.group(3)), "text/calendar; charset=utf-8",
                                   extra={"Content-Disposition": 'attachment; filename="cita.ics"'})
                finally:
                    CENTRO.reset(marca)
            return self.envolver(ics)
        if m:
            return self.estatico("/cita.html")
        return self.estatico(ruta)

    do_HEAD = do_GET

    def do_POST(self):
        return self.api("POST")

    def do_PUT(self):
        return self.api("PUT")

    def do_DELETE(self):
        return self.api("DELETE")

    def envolver(self, funcion):
        try:
            return funcion()
        except ErrorApi as err:
            self.json(err.estado, {"error": err.mensaje, **({"codigo": err.codigo} if err.codigo else {})})
        except SBDError as err:
            self.log_message("SBD: %s", err)
            if getattr(err, "tipo", None) == "conexion":
                return self.json(503, {"error": "No hay conexión con la base de datos. Vuelve a intentarlo en un momento."})
            self.json(500, {"error": "La base de datos no ha podido hacer el cambio. No se ha guardado nada."})

    def api(self, metodo):
        self.leer_crudo()
        # El centro va con cada petición; con keep-alive el mismo hilo atiende varias, así que se limpia siempre.
        marca = CENTRO.set(None)
        try:
            self.envolver(lambda: self._api(metodo))
        finally:
            CENTRO.reset(marca)

    def centro_publico(self, texto_centro):
        """El centro de un enlace de paciente: el 1 si no lo lleva; 404 si ya no existe."""
        centro = int(texto_centro) if texto_centro else 1
        with self.app.bd.conexion(centro=GLOBAL) as con:
            if not con.una("buscar centros donde id = ? mostrar id", [centro]):
                raise ErrorApi(404, "Este enlace ya no es válido.")
        CENTRO.set(centro)

    def _api(self, metodo):
        partes = urlsplit(self.path)
        ruta = partes.path
        q = {k: v[0] for k, v in parse_qs(partes.query).items()}
        app = self.app
        # Lo que cambia algo lleva una cabecera propia: un formulario de otra web no puede ponerla.
        if metodo != "GET" and self.headers.get("X-Volante") != "1":
            raise ErrorApi(403, "Petición rechazada.")

        # ---- enlace del paciente (sin cuenta, con firma) ----
        m = re.fullmatch(r"/api/([cov])/(?:(\d+)/)?(\d+)/([A-Za-z0-9_-]{10,40})(/huecos|/pedir)?", ruta)
        if m:
            if not app.limite_publico.permitir(self.ip()):
                raise ErrorApi(429, "Demasiadas peticiones seguidas. Espere unos minutos.")
            self.centro_publico(m.group(2))
            tipo, ident, firma, sub = m.group(1), int(m.group(3)), m.group(4), m.group(5)
            if tipo == "c" and sub == "/huecos" and metodo == "GET":
                return self.json(200, app.huecos_publicos(ident, firma, dia_param(q.get("desde"), app.reloj().date())))
            if tipo == "c" and sub == "/pedir" and metodo == "POST":
                return self.json(200, app.pedir_cita(ident, firma, self.cuerpo()))
            if sub:
                raise ErrorApi(404, "No existe esa ruta.")
            if tipo == "c" and metodo == "GET":
                return self.json(200, app.cita_publica(ident, firma))
            if tipo == "c" and metodo == "POST":
                return self.json(200, app.accion_publica(ident, firma, self.cuerpo().get("accion")))
            if tipo == "o" and metodo == "GET":
                return self.json(200, app.oferta_publica(ident, firma))
            if tipo == "o" and metodo == "POST":
                return self.json(200, app.accion_oferta(ident, firma, self.cuerpo().get("accion")))
            if tipo == "v" and metodo == "GET":
                return self.json(200, app.verificar_justificante(ident, firma))

        # ---- cuentas ----
        if ruta == "/api/estado" and metodo == "GET":
            return self.json(200, {"puesta_en_marcha": not app.hay_cuentas() and not app.publico, "registro": app.registro})
        if ruta == "/api/registro" and metodo == "POST":
            # Solo cuentan las cuentas que se crean de verdad: un formulario mal rellenado no gasta intentos.
            if not app.limite_registro.permitir(self.ip(), anotar=False):
                raise ErrorApi(429, "Ya se han creado tres cuentas desde aquí en la última hora. Prueba más tarde.")
            token = app.registrar(self.cuerpo())
            app.limite_registro.anotar(self.ip())
            return self.json(200, {"ok": True}, cookie=self.cookie_sesion(token))
        if ruta in ("/api/alta", "/api/entrar") and metodo == "POST":
            # Solo cuentan los intentos fallidos: un mostrador con varias personas entra muchas veces al día.
            if not app.limite_acceso.permitir(self.ip(), anotar=ruta == "/api/alta"):
                raise ErrorApi(429, "Demasiados intentos fallidos seguidos. Espera unos minutos.")
            datos = self.cuerpo()
            try:
                token = app.puesta_en_marcha(datos) if ruta == "/api/alta" else app.entrar(datos)
            except ErrorApi as err:
                if err.estado == 401:
                    app.limite_acceso.anotar(self.ip())
                raise
            return self.json(200, {"ok": True}, cookie=self.cookie_sesion(token))
        if ruta == "/api/salir" and metodo == "POST":
            app.salir(self.token())
            return self.json(200, {"ok": True}, cookie=self.cookie_sesion(None))

        yo = app.usuario_de(self.token())
        if ruta == "/api/yo" and metodo == "GET":
            return self.json(200, {"yo": yo, "permisos": sorted(PERMISOS[yo["rol"]]) if yo else [], "ahora": app.ahora()})
        if not yo:
            raise ErrorApi(401, "Tu sesión ha terminado. Vuelve a entrar.")
        CENTRO.set(yo["centro_id"])     # a partir de aquí, todas las órdenes van a las tablas de su centro
        puede = PERMISOS[yo["rol"]]

        def exigir(permiso):
            if permiso not in puede:
                raise ErrorApi(403, "Tu cuenta no tiene permiso para esto.")

        if ruta == "/api/clave" and metodo == "POST":
            return self.json(200, app.cambiar_clave(yo, self.cuerpo()))
        hoy = app.reloj().date()

        # ---- agenda ----
        if ruta == "/api/libro" and metodo == "GET":
            dia = dia_param(q.get("fecha"), hoy)
            return self.json(200, {**app.libro(yo, dia), "resumen": app.resumen(dia)})
        if ruta == "/api/semana" and metodo == "GET":
            return self.json(200, app.semana(yo, entero(q.get("medico"), "El médico"), dia_param(q.get("desde"), hoy)))
        if ruta == "/api/huecos" and metodo == "GET":
            dias = max(1, min(60, entero(q.get("dias") or 1, "Los días")))
            return self.json(200, app.huecos(entero(q.get("medico"), "El médico"), dia_param(q.get("fecha"), hoy), dias))
        if ruta == "/api/citas" and metodo == "POST":
            exigir("citas")
            return self.json(200, app.crear_cita(yo, self.cuerpo()))
        if ruta == "/api/citas/serie" and metodo == "POST":
            exigir("citas")
            return self.json(200, app.previa_serie(self.cuerpo()))
        m = re.fullmatch(r"/api/citas/(\d+)(/estado|/recordar|/sala|/justificante)?", ruta)
        if m:
            exigir("citas")
            cid, sub = int(m.group(1)), m.group(2)
            if sub == "/sala" and metodo == "POST":
                return self.json(200, app.sala(yo, cid, self.cuerpo().get("accion")))
            if sub == "/justificante" and metodo == "GET":
                return self.json(200, app.justificante(cid))
            if sub is None and metodo == "PUT":
                return self.json(200, app.mover_cita(yo, cid, self.cuerpo()))
            if sub == "/estado" and metodo == "POST":
                return self.json(200, app.estado_cita(yo, cid, self.cuerpo()))
            if sub == "/recordar" and metodo == "POST":
                return self.json(200, app.recordar_ya(yo, cid))

        # ---- lista de espera ----
        if ruta == "/api/espera":
            exigir("citas")
            if metodo == "GET":
                return self.json(200, app.lista_espera(q.get("ver", "activa")))
            if metodo == "POST":
                return self.json(200, app.apuntar_espera(yo, self.cuerpo()))
        m = re.fullmatch(r"/api/espera/(\d+)", ruta)
        if m and metodo == "PUT":
            exigir("citas")
            return self.json(200, app.cambiar_espera(yo, int(m.group(1)), self.cuerpo()))

        # ---- informe ----
        if ruta == "/api/informe" and metodo == "GET":
            exigir("informe")
            return self.json(200, app.informe(q.get("mes") or hoy.isoformat()[:7]))

        # ---- pacientes ----
        if ruta == "/api/pacientes":
            if metodo == "GET":
                return self.json(200, app.pacientes(q.get("q", ""), q.get("letra", "")))
            if metodo == "POST":
                exigir("pacientes")
                return self.json(200, app.crear_paciente(self.cuerpo()))
        m = re.fullmatch(r"/api/pacientes/(\d+)", ruta)
        if m:
            pid = int(m.group(1))
            if metodo == "GET":
                return self.json(200, app.paciente(yo, pid))
            if metodo == "PUT":
                exigir("pacientes")
                return self.json(200, app.cambiar_paciente(pid, self.cuerpo()))
            if metodo == "DELETE":
                exigir("borrar_paciente")
                return self.json(200, app.borrar_paciente(pid))

        # ---- médicos y horarios ----
        if ruta == "/api/medicos":
            if metodo == "GET":
                return self.json(200, app.medicos(todos=q.get("todos") == "1"))
            if metodo == "POST":
                exigir("medicos")
                return self.json(200, app.crear_medico(self.cuerpo()))
        m = re.fullmatch(r"/api/medicos/(\d+)(/horario|/ausencias)?", ruta)
        if m:
            exigir("medicos")
            mid, sub = int(m.group(1)), m.group(2)
            if sub is None and metodo == "PUT":
                return self.json(200, app.cambiar_medico(mid, self.cuerpo()))
            if sub == "/horario" and metodo == "PUT":
                return self.json(200, app.guardar_horario(mid, self.cuerpo()))
            if sub == "/ausencias" and metodo == "POST":
                return self.json(200, app.crear_ausencia(mid, self.cuerpo()))
        m = re.fullmatch(r"/api/ausencias/(\d+)", ruta)
        if m and metodo == "DELETE":
            exigir("medicos")
            return self.json(200, app.borrar_ausencia(int(m.group(1))))

        # ---- avisos ----
        if ruta == "/api/avisos" and metodo == "GET":
            exigir("avisos")
            return self.json(200, app.avisos(q.get("vista", "bandeja")))
        m = re.fullmatch(r"/api/avisos/(\d+)/(enviado|reintentar)", ruta)
        if m and metodo == "POST":
            exigir("avisos")
            rid = int(m.group(1))
            return self.json(200, app.aviso_enviado(yo, rid) if m.group(2) == "enviado" else app.aviso_reintentar(yo, rid))

        # ---- ajustes y equipo ----
        if ruta == "/api/ajustes":
            if metodo == "GET":
                return self.json(200, app.ajustes())
            if metodo == "PUT":
                exigir("ajustes")
                return self.json(200, app.guardar_ajustes(self.cuerpo()))
        if ruta == "/api/equipo":
            exigir("equipo")
            if metodo == "GET":
                return self.json(200, app.equipo(yo))
            if metodo == "POST":
                return self.json(200, app.crear_miembro(yo, self.cuerpo()))
        if ruta == "/api/centro" and metodo == "DELETE":
            exigir("equipo")
            if not app.limite_acceso.permitir(self.ip()):
                raise ErrorApi(429, "Demasiados intentos seguidos. Espera unos minutos.")
            return self.json(200, app.borrar_centro(yo, self.cuerpo()), cookie=self.cookie_sesion(None))
        m = re.fullmatch(r"/api/equipo/(\d+)", ruta)
        if m and metodo == "PUT":
            exigir("equipo")
            return self.json(200, app.cambiar_miembro(yo, int(m.group(1)), self.cuerpo()))

        raise ErrorApi(404, "No existe esa ruta.")

    def estatico(self, ruta):
        if ruta in ("/", ""):
            ruta = "/index.html"
        partes = [p for p in ruta.split("/") if p]
        destino = None
        if partes and not any(p in ("..", ".") or "\\" in p for p in partes):
            destino = (WEB / Path(*partes)).resolve()
        valido = destino is not None and WEB in destino.parents and destino.is_file() and destino.relative_to(WEB).parts[0] in ESTATICOS
        if not valido:
            return self.responder(404, "No encontrado".encode(), "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo == "image/svg+xml":
            tipo += "; charset=utf-8"
        cache = "public, max-age=604800" if partes[0] == "fuentes" else "no-cache"
        self.responder(200, destino.read_bytes(), tipo, cache=cache)


def planificador(app, parar):
    """Hilo que reparte los avisos: cada 30 s, o al momento cuando se da o se mueve una cita."""
    while not parar.is_set():
        try:
            app.cartero.repartir(app.reloj())
        except Exception as err:  # noqa: BLE001 - un aviso roto no debe parar los demás
            print(f"Avisos: {type(err).__name__}: {err}", file=sys.stderr, flush=True)
        app.despertar.wait(30)
        app.despertar.clear()


def crear_servidor(dir_datos, host="127.0.0.1", puerto=8103, publico=False, url_publica=None):
    Path(dir_datos).mkdir(parents=True, exist_ok=True)
    bd = abrir_bd(dir_datos)
    bd.preparar()
    app = Aplicacion(bd, dir_datos, url_publica or f"http://{host}:{puerto}", publico)
    manejador = type("ManejadorVolante", (Manejador,), {"app": app})
    servidor = ThreadingHTTPServer((host, puerto), manejador)
    servidor.daemon_threads = True
    return servidor, app, bd


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8103)
    parser.add_argument("--datos", default=str(RAIZ / "datos"), help="carpeta donde SBD guarda la base «volante»")
    parser.add_argument("--publico", action="store_true", help="detrás de un proxy con HTTPS: cookies Secure y X-Forwarded-For")
    parser.add_argument("--url-publica", help="dirección con la que el paciente abre su enlace (https://…)")
    parser.add_argument("--demo", action="store_true", help="si la base está vacía, la llena con datos de ejemplo inventados")
    parser.add_argument("--sin-copias", action="store_true", help="no hace la copia diaria de la base en datos/.copias")
    parser.add_argument("--sin-registro", action="store_true", help="no deja crear cuentas (y centros) nuevos desde la web")
    parser.add_argument("--alta-direccion", metavar="USUARIO", help="crea la cuenta de dirección (pide nombre y contraseña) y sale")
    args = parser.parse_args()

    if args.alta_direccion:
        import getpass
        Path(args.datos).mkdir(parents=True, exist_ok=True)
        bd = abrir_bd(args.datos)
        bd.preparar()
        app = Aplicacion(bd, args.datos, args.url_publica or "http://127.0.0.1")
        try:
            nombre = input("Nombre de quien dirige: ").strip()
            centro = input("Nombre del centro (Intro para dejarlo): ").strip()
            clave = getpass.getpass("Contraseña (10 caracteres como mínimo): ")
            if clave != getpass.getpass("Repítela: "):
                sys.exit("Las contraseñas no coinciden.")
            app.puesta_en_marcha({"usuario": args.alta_direccion, "nombre": nombre, "contrasena": clave, "centro": centro, "_desde_consola": True})
            print(f"Cuenta «{args.alta_direccion}» creada. Ya puedes entrar en la web.")
        except ErrorApi as err:
            sys.exit(err.mensaje)
        finally:
            bd.cerrar()
        return

    servidor, app, bd = crear_servidor(args.datos, args.host, args.puerto, args.publico, args.url_publica)
    app.registro = not args.sin_registro
    if args.demo:
        from api import demo
        CENTRO.set(1)
        cuentas = demo.sembrar(app)
        CENTRO.set(None)
        if cuentas:
            print("Datos de ejemplo creados. Cuentas (contraseña: volante-demo):", ", ".join(cuentas), flush=True)

    parar = threading.Event()

    def copias():
        while not parar.is_set():
            try:
                bd.copia_diaria(14)
            except Exception as err:  # noqa: BLE001
                print(f"No se pudo hacer la copia diaria: {err}", file=sys.stderr, flush=True)
            parar.wait(6 * 3600)

    if not args.sin_copias and not bd.remota:     # con servidor SBD, las copias las hace él
        threading.Thread(target=copias, daemon=True).start()
    threading.Thread(target=planificador, args=(app, parar), daemon=True).start()

    def al_parar(*_):
        parar.set()
        app.despertar.set()
        threading.Thread(target=servidor.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, al_parar)
    signal.signal(signal.SIGINT, al_parar)
    print(f"Volante en http://{args.host}:{args.puerto} · {bd.descripcion} · hora de la consulta: {app.reloj():%d/%m/%Y %H:%M} ({app.zona})", flush=True)
    try:
        servidor.serve_forever()
    finally:
        bd.cerrar()


if __name__ == "__main__":
    main()
