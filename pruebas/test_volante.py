"""Pruebas de Volante: agenda, API, permisos, recordatorios y enlace del paciente.

    python3 -m unittest discover -s pruebas -v

Cada prueba levanta el servidor en un puerto libre con una base SBD temporal y un reloj que se mueve
a mano, así que los recordatorios se prueban sin esperar. El correo va a un servidor SMTP falso.
"""

import http.client
import json
import os
import re
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["VOLANTE_ITERACIONES"] = "1000"
os.environ["VOLANTE_SILENCIO"] = "1"
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import servidor  # noqa: E402
from api.bd import CENTRO  # noqa: E402
from api import agenda, recordatorios  # noqa: E402

LUNES = datetime(2026, 11, 9, 8, 0)   # un lunes a las 8:00, hora de la consulta


class SMTPFalso(socketserver.ThreadingTCPServer):
    """Lo justo de SMTP para recibir un correo y guardarlo."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.recibidos = []
        self.rechazar = False
        super().__init__(("127.0.0.1", 0), self.Manejador)

    class Manejador(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 falso\r\n")
            datos, en_datos, para = [], False, []
            while True:
                linea = self.rfile.readline()
                if not linea:
                    return
                if en_datos:
                    if linea in (b".\r\n", b".\n"):
                        en_datos = False
                        self.server.recibidos.append({"para": para, "mensaje": b"".join(datos).decode("utf-8", "replace")})
                        self.wfile.write(b"250 guardado\r\n")
                    else:
                        datos.append(linea)
                    continue
                orden = linea.decode().strip().upper()
                if orden.startswith(("EHLO", "HELO")):
                    self.wfile.write(b"250 falso\r\n")
                elif orden.startswith("MAIL"):
                    self.wfile.write(b"550 no\r\n" if self.server.rechazar else b"250 ok\r\n")
                elif orden.startswith("RCPT"):
                    para.append(orden)
                    self.wfile.write(b"250 ok\r\n")
                elif orden == "DATA":
                    en_datos = True
                    self.wfile.write(b"354 adelante\r\n")
                elif orden == "QUIT":
                    self.wfile.write(b"221 adios\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")


class Cliente:
    def __init__(self, puerto):
        self.puerto = puerto
        self.cookie = None

    def pedir(self, metodo, ruta, datos=None, cabecera=True):
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        cab = {"Content-Type": "application/json"}
        if cabecera:
            cab["X-Volante"] = "1"
        if self.cookie:
            cab["Cookie"] = self.cookie
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        con.request(metodo, ruta, body=cuerpo, headers=cab)
        r = con.getresponse()
        crudo = r.read()
        galleta = r.getheader("Set-Cookie")
        if galleta:
            valor = galleta.split(";")[0]
            self.cookie = None if valor.endswith("=") else valor
        con.close()
        try:
            return r.status, json.loads(crudo)
        except ValueError:
            return r.status, crudo


class BaseVolante(unittest.TestCase):
    def setUp(self):
        CENTRO.set(1)      # lo que la prueba hace directamente (sin HTTP) va al centro 1
        self.dir = tempfile.mkdtemp(prefix="volante-prueba-")
        self.antes_de_crear(self.dir)
        self.srv, self.app, self.bd = servidor.crear_servidor(self.dir, puerto=0, url_publica="https://citas.example.com")
        self.reloj = [LUNES]
        self.app.reloj = lambda: self.reloj[0]
        self.puerto = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.c = Cliente(self.puerto)
        estado, _ = self.c.pedir("POST", "/api/alta", {"usuario": "direccion", "nombre": "Dirección", "contrasena": "una clave larga", "centro": "Centro de Prueba"})
        self.assertEqual(estado, 200)
        self.app.guardar_ajustes({"telefono": "960 000 000", "direccion": "Calle Mayor 1"})

    def antes_de_crear(self, carpeta):
        """Las pruebas con servidor SBD dejan aquí su datos/sbd.json."""

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.bd.cerrar()
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---- ayudas ----
    def medico(self, franjas=((1, "09:00", "14:00", 20),), nombre="Dra. Prueba"):
        _, r = self.c.pedir("POST", "/api/medicos", {"nombre": nombre, "especialidad": "Medicina de familia", "consulta": "Consulta 1"})
        estado, _ = self.c.pedir("PUT", f"/api/medicos/{r['id']}/horario",
                                 {"franjas": [{"dia": d, "desde": a, "hasta": b, "minutos": m} for d, a, b, m in franjas]})
        self.assertEqual(estado, 200)
        return r["id"]

    def paciente(self, **extra):
        datos = {"nombre": "Ana", "apellidos": "García López", "email": "ana@example.com", "telefono": "600 111 222", "canal": "correo", **extra}
        estado, r = self.c.pedir("POST", "/api/pacientes", datos)
        self.assertEqual(estado, 200, r)
        return r["id"]

    def cita(self, medico, paciente, fecha="2026-11-16", hora="10:00", minutos=20, **extra):
        return self.c.pedir("POST", "/api/citas", {"medico_id": medico, "paciente_id": paciente, "fecha": fecha, "hora": hora, "minutos": minutos, **extra})

    def avisos(self, cita_id):
        with self.bd.conexion() as con:
            return con.consultar("buscar recordatorios donde cita_id = ? ordenar programado", [cita_id])


class PruebaAgenda(unittest.TestCase):
    def test_huecos_quitan_lo_ocupado_y_lo_pasado(self):
        franjas = [{"dia": 1, "desde": "09:00", "hasta": "10:00", "minutos": 20}]
        citas = [{"empieza": "2026-11-09 09:20:00", "termina": "2026-11-09 09:40:00", "estado": "confirmada"},
                 {"empieza": "2026-11-09 09:40:00", "termina": "2026-11-09 10:00:00", "estado": "anulada"}]
        h = agenda.huecos(franjas, [], citas, date(2026, 11, 9), datetime(2026, 11, 9, 8, 0))
        self.assertEqual([x["hora"] for x in h], ["09:00", "09:40"])
        h = agenda.huecos(franjas, [], citas, date(2026, 11, 9), datetime(2026, 11, 9, 9, 10))
        self.assertEqual([x["hora"] for x in h], ["09:40"])

    def test_ausencia_deja_el_dia_sin_huecos(self):
        franjas = [{"dia": 1, "desde": "09:00", "hasta": "10:00", "minutos": 20}]
        aus = [{"desde": "2026-11-09", "hasta": "2026-11-10"}]
        self.assertEqual(agenda.huecos(franjas, aus, [], date(2026, 11, 9), LUNES), [])

    def test_franjas_que_se_pisan(self):
        with self.assertRaisesRegex(ValueError, "se pisan"):
            agenda.validar_franjas([{"dia": 2, "desde": "09:00", "hasta": "12:00"}, {"dia": 2, "desde": "11:00", "hasta": "13:00"}])
        with self.assertRaisesRegex(ValueError, "termina antes"):
            agenda.validar_franjas([{"dia": 2, "desde": "12:00", "hasta": "09:00"}])

    def test_firma_del_enlace(self):
        s = b"x" * 32
        f = recordatorios.firma(s, 7)
        self.assertTrue(recordatorios.firma_valida(s, 7, f))
        self.assertFalse(recordatorios.firma_valida(s, 8, f))
        self.assertFalse(recordatorios.firma_valida(b"y" * 32, 7, f))


class PruebaCuentas(BaseVolante):
    def test_puesta_en_marcha_solo_una_vez(self):
        otro = Cliente(self.puerto)
        estado, r = otro.pedir("POST", "/api/alta", {"usuario": "intruso", "nombre": "X", "contrasena": "otra clave larga"})
        self.assertEqual(estado, 409)

    def test_entrar_y_sin_sesion(self):
        otro = Cliente(self.puerto)
        self.assertEqual(otro.pedir("GET", "/api/libro")[0], 401)
        self.assertEqual(otro.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "mala"})[0], 401)
        self.assertEqual(otro.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})[0], 200)
        self.assertEqual(otro.pedir("GET", "/api/libro")[0], 200)

    def test_solo_frenan_los_intentos_fallidos(self):
        otro = Cliente(self.puerto)
        for _ in range(12):
            self.assertEqual(otro.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})[0], 200)
        for _ in range(10):
            otro.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "mala"})
        self.assertEqual(otro.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})[0], 429)

    def test_sin_cabecera_propia_se_rechaza(self):
        estado, _ = self.c.pedir("POST", "/api/medicos", {"nombre": "Dr. X", "especialidad": "Y"}, cabecera=False)
        self.assertEqual(estado, 403)

    def test_cuerpo_sin_leer_no_rompe_la_conexion(self):
        # Una respuesta de error en HTTP/1.1 no debe dejar el cuerpo en la conexión para la petición siguiente.
        con = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=5)
        con.request("POST", "/api/medicos", body=b'{"nombre": "x"}', headers={"Content-Type": "application/json"})
        r = con.getresponse(); r.read()
        self.assertEqual(r.status, 403)
        con.request("GET", "/api/estado")
        r = con.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn(b"puesta_en_marcha", r.read())
        con.close()

    def test_permisos_por_papel(self):
        m = self.medico()
        m2 = self.medico(nombre="Dr. Otro")
        p = self.paciente()
        self.assertEqual(self.c.pedir("POST", "/api/equipo", {"usuario": "mostrador", "nombre": "Recepción", "rol": "recepcion", "contrasena": "clave de recepcion"})[0], 200)
        self.assertEqual(self.c.pedir("POST", "/api/equipo", {"usuario": "doctora", "nombre": "Doctora", "rol": "medico", "medico_id": m, "contrasena": "clave de la doctora"})[0], 200)
        rec, med = Cliente(self.puerto), Cliente(self.puerto)
        rec.pedir("POST", "/api/entrar", {"usuario": "mostrador", "contrasena": "clave de recepcion"})
        med.pedir("POST", "/api/entrar", {"usuario": "doctora", "contrasena": "clave de la doctora"})
        self.assertEqual(rec.pedir("PUT", "/api/ajustes", {"centro": "Otro"})[0], 403)
        self.assertEqual(rec.pedir("DELETE", f"/api/pacientes/{p}")[0], 403)
        self.assertEqual(med.pedir("PUT", f"/api/medicos/{m}/horario", {"franjas": []})[0], 403)
        _, a = self.cita(m, p, "2026-11-09", "09:00")
        _, b = self.cita(m2, p, "2026-11-09", "10:00")
        self.reloj[0] = datetime(2026, 11, 9, 11, 0)
        self.assertEqual(med.pedir("POST", f"/api/citas/{b['id']}/estado", {"estado": "atendida"})[0], 403)
        self.assertEqual(med.pedir("POST", f"/api/citas/{a['id']}/estado", {"estado": "atendida", "nota": "Faringitis. Reposo."})[0], 200)
        # La nota clínica la ve el médico, no recepción.
        _, ficha_rec = rec.pedir("GET", f"/api/pacientes/{p}")
        _, ficha_med = med.pedir("GET", f"/api/pacientes/{p}")
        self.assertNotIn("nota", ficha_rec["citas"][0])
        self.assertIn("Faringitis", json.dumps(ficha_med, ensure_ascii=False))
        self.assertEqual(rec.pedir("POST", f"/api/citas/{a['id']}/estado", {"estado": "atendida", "nota": "x"})[0], 403)


class PruebaCitas(BaseVolante):
    def test_dar_cita_en_hueco_y_choques(self):
        m, p = self.medico(), self.paciente()
        estado, r = self.cita(m, p)
        self.assertEqual(estado, 200, r)
        _, huecos = self.c.pedir("GET", f"/api/huecos?medico={m}&fecha=2026-11-16")
        self.assertNotIn("10:00", [h["hora"] for h in huecos[0]["huecos"]])
        self.assertEqual(len(huecos[0]["huecos"]), 14)
        estado, r = self.cita(m, self.paciente(nombre="Luis", email="luis@example.com"), hora="10:10")
        self.assertEqual((estado, r.get("codigo")), (409, "choque"))
        # Ni forzando se pisa a otro paciente.
        estado, r = self.cita(m, p, hora="10:10", forzar=True)
        self.assertEqual(estado, 409)

    def test_fuera_de_horario_pide_confirmacion(self):
        m, p = self.medico(), self.paciente()
        estado, r = self.cita(m, p, hora="16:00")
        self.assertEqual((estado, r.get("codigo")), (409, "fuera_horario"))
        self.assertEqual(self.cita(m, p, hora="16:00", forzar=True)[0], 200)

    def test_ausencia_y_pasado(self):
        m, p = self.medico(), self.paciente()
        self.assertEqual(self.c.pedir("POST", f"/api/medicos/{m}/ausencias", {"desde": "2026-11-16", "hasta": "2026-11-16", "motivo": "Congreso"})[0], 200)
        estado, r = self.cita(m, p)
        self.assertEqual(r.get("codigo"), "ausencia")
        self.assertIn("Congreso", r["error"])
        self.assertEqual(self.cita(m, p, fecha="2026-11-02")[0], 400)

    def test_primer_hueco_libre_salta_dias(self):
        m = self.medico(franjas=((3, "09:00", "10:00", 30),))   # solo los miércoles
        _, dias = self.c.pedir("GET", f"/api/huecos?medico={m}&fecha=2026-11-09&dias=30")
        self.assertEqual(dias[0]["fecha"], "2026-11-11")
        self.assertEqual(dias[0]["huecos"][0]["hora"], "09:00")

    def test_libro_del_dia(self):
        m, p = self.medico(), self.paciente()
        self.cita(m, p, fecha="2026-11-09", hora="09:20")
        _, libro = self.c.pedir("GET", "/api/libro?fecha=2026-11-09")
        col = libro["columnas"][0]
        self.assertEqual(col["citas"][0]["apellidos"], "García López")
        self.assertEqual(col["citas"][0]["minutos"], 20)
        self.assertEqual(len(col["huecos"]), 14)
        self.assertEqual(libro["resumen"]["por_estado"], {"pendiente": 1})

    def test_busqueda_sin_tildes(self):
        self.paciente(nombre="Íñigo", apellidos="Muñoz Álvarez", email="i@example.com")
        _, r = self.c.pedir("GET", "/api/pacientes?q=munoz%20inigo")
        self.assertEqual(len(r["pacientes"]), 1)
        _, r = self.c.pedir("GET", "/api/pacientes?q=600111")
        self.assertEqual(len(r["pacientes"]), 1)
        _, r = self.c.pedir("GET", "/api/pacientes?letra=M")
        self.assertEqual(len(r["pacientes"]), 1)

    def test_baja_de_medico_con_citas(self):
        m, p = self.medico(), self.paciente()
        self.cita(m, p)
        estado, r = self.c.pedir("PUT", f"/api/medicos/{m}", {"nombre": "Dra. Prueba", "especialidad": "X", "activo": False})
        self.assertEqual(estado, 409)


class PruebaRecordatorios(BaseVolante):
    def test_se_programan_y_van_a_la_bandeja_sin_correo(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)  # lunes 16 a las 10:00; ahora es lunes 9 a las 8:00
        a = self.avisos(r["id"])
        self.assertEqual([(x["tipo"], x["programado"]) for x in a],
                         [("reserva", "2026-11-09 08:00:00"), ("antes_48", "2026-11-14 10:00:00"), ("antes_2", "2026-11-16 08:00:00")])
        self.app.cartero.repartir(self.reloj[0])
        a = self.avisos(r["id"])
        self.assertEqual([x["estado"] for x in a], ["en_bandeja", "pendiente", "pendiente"])
        self.assertIn("https://citas.example.com/c/", a[0]["cuerpo"])
        self.assertIn("Lunes 16 de noviembre de 2026, a las 10:00", a[0]["cuerpo"])
        # Llega la hora del de 48 h.
        self.reloj[0] = datetime(2026, 11, 14, 10, 1)
        self.app.cartero.repartir(self.reloj[0])
        self.assertEqual([x["estado"] for x in self.avisos(r["id"])], ["en_bandeja", "en_bandeja", "pendiente"])
        # Han pasado cinco días: la sesión de una jornada ha caducado.
        self.assertEqual(self.c.pedir("GET", "/api/avisos?vista=bandeja")[0], 401)
        self.c.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})
        _, bandeja = self.c.pedir("GET", "/api/avisos?vista=bandeja")
        self.assertEqual(len(bandeja["avisos"]), 2)
        self.assertFalse(bandeja["correo_configurado"])
        self.assertEqual(self.c.pedir("POST", f"/api/avisos/{a[0]['id']}/enviado")[0], 200)
        self.assertEqual(self.avisos(r["id"])[0]["estado"], "enviado")

    def test_correo_de_verdad_con_smtp(self):
        smtp = SMTPFalso()
        threading.Thread(target=smtp.serve_forever, daemon=True).start()
        Path(self.dir, "correo.json").write_text(json.dumps({"host": "127.0.0.1", "puerto": smtp.server_address[1], "remitente": "citas@example.com", "seguridad": "no"}))
        try:
            m, p = self.medico(), self.paciente()
            _, r = self.cita(m, p)
            self.app.cartero.repartir(self.reloj[0])
            a = self.avisos(r["id"])
            self.assertEqual(a[0]["estado"], "enviado", a[0]["error"])
            self.assertEqual(len(smtp.recibidos), 1)
            correo = smtp.recibidos[0]["mensaje"]
            self.assertIn("ana@example.com", correo)
            self.assertIn("Centro de Prueba", correo)
            # Si el servidor rechaza, se reintenta dos veces más y luego queda como fallido.
            smtp.rechazar = True
            self.reloj[0] = datetime(2026, 11, 14, 10, 1)
            for minutos in (0, 6, 12):
                self.app.cartero.repartir(self.reloj[0] + timedelta(minutes=minutos))
            aviso48 = self.avisos(r["id"])[1]
            self.assertEqual((aviso48["estado"], aviso48["intentos"]), ("fallido", 3))
        finally:
            smtp.shutdown(); smtp.server_close()

    def test_mover_rehace_y_anular_cancela(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)
        self.app.cartero.repartir(self.reloj[0])
        self.assertEqual(self.c.pedir("PUT", f"/api/citas/{r['id']}", {"fecha": "2026-11-23", "hora": "11:00"})[0], 200)
        a = self.avisos(r["id"])
        tipos = [(x["tipo"], x["estado"]) for x in a]
        self.assertIn(("reserva", "en_bandeja"), tipos)       # el aviso de la hora vieja queda como historial
        self.assertIn(("antes_48", "pendiente"), tipos)
        self.assertIn("2026-11-21 11:00:00", [x["programado"] for x in a])
        self.assertEqual(sum(1 for x in a if x["tipo"] == "reserva"), 2)  # y sale otro con la hora nueva
        self.c.pedir("POST", f"/api/citas/{r['id']}/estado", {"estado": "anulada"})
        self.assertFalse([x for x in self.avisos(r["id"]) if x["estado"] == "pendiente"])
        self.assertIn("anulado", [x["estado"] for x in self.avisos(r["id"])])

    def test_cita_con_poca_antelacion_omite_lo_que_ya_paso(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p, fecha="2026-11-09", hora="13:00")   # dentro de 5 h
        estados = {x["tipo"]: x["estado"] for x in self.avisos(r["id"])}
        self.assertEqual(estados, {"reserva": "pendiente", "antes_48": "omitido", "antes_2": "pendiente"})

    def test_sin_avisos_si_el_paciente_no_quiere(self):
        m = self.medico()
        p = self.paciente(canal="ninguno")
        _, r = self.cita(m, p)
        self.assertEqual(self.avisos(r["id"]), [])
        self.assertEqual(self.c.pedir("POST", f"/api/citas/{r['id']}/recordar")[0], 409)

    def test_cambiar_las_horas_reprograma(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)
        self.assertEqual(self.c.pedir("PUT", "/api/ajustes", {"avisos_horas": "24"})[0], 200)
        pendientes = [x["tipo"] for x in self.avisos(r["id"]) if x["estado"] == "pendiente"]
        self.assertEqual(pendientes, ["antes_24"])

    def test_whatsapp_va_a_la_bandeja_aunque_haya_correo(self):
        Path(self.dir, "correo.json").write_text(json.dumps({"host": "127.0.0.1", "puerto": 1, "remitente": "x@example.com"}))
        m = self.medico()
        p = self.paciente(canal="whatsapp")
        _, r = self.cita(m, p)
        self.app.cartero.repartir(self.reloj[0])
        a = self.avisos(r["id"])[0]
        self.assertEqual((a["estado"], a["destino"]), ("en_bandeja", "600 111 222"))
        self.assertLess(len(a["cuerpo"]), 400)


class PruebaEnlacePaciente(BaseVolante):
    def enlace(self, cita_id):
        return re.search(r"/c/(\d+)/([\w-]+)", self.app.cartero.enlace(cita_id)).groups()

    def test_confirmar_anular_y_calendario(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)
        cid, firma = self.enlace(r["id"])
        anonimo = Cliente(self.puerto)
        self.assertEqual(anonimo.pedir("GET", f"/api/c/{cid}/{'x' * 24}")[0], 404)
        estado, c = anonimo.pedir("GET", f"/api/c/{cid}/{firma}")
        self.assertEqual((estado, c["estado"], c["nombre"]), (200, "pendiente", "Ana"))
        self.assertNotIn("telefono", c)    # el enlace no enseña más datos de los necesarios
        estado, c = anonimo.pedir("POST", f"/api/c/{cid}/{firma}", {"accion": "confirmar"})
        self.assertEqual(c["estado"], "confirmada")
        estado, ics = anonimo.pedir("GET", f"/c/{cid}/{firma}/cita.ics")
        self.assertEqual(estado, 200)
        self.assertIn(b"DTSTART;TZID=Europe/Madrid:20261116T100000", ics)
        estado, pagina = anonimo.pedir("GET", f"/c/{cid}/{firma}")
        self.assertIn(b"Su cita", pagina)
        estado, c = anonimo.pedir("POST", f"/api/c/{cid}/{firma}", {"accion": "anular"})
        self.assertEqual((c["estado"]), "anulada")
        self.assertFalse([x for x in self.avisos(r["id"]) if x["estado"] == "pendiente"])
        self.assertEqual(anonimo.pedir("POST", f"/api/c/{cid}/{firma}", {"accion": "confirmar"})[0], 409)
        # El hueco vuelve a estar libre.
        _, huecos = self.c.pedir("GET", f"/api/huecos?medico={m}&fecha=2026-11-16")
        self.assertIn("10:00", [h["hora"] for h in huecos[0]["huecos"]])


class PruebaPublicado(unittest.TestCase):
    def test_en_internet_no_se_pone_en_marcha_desde_la_web(self):
        d = tempfile.mkdtemp(prefix="volante-pub-")
        try:
            srv, app, bd = servidor.crear_servidor(d, puerto=0, publico=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            c = Cliente(srv.server_address[1])
            self.assertEqual(c.pedir("GET", "/api/estado")[1]["puesta_en_marcha"], False)
            estado, r = c.pedir("POST", "/api/alta", {"usuario": "yo", "nombre": "Yo", "contrasena": "una clave larga"})
            self.assertEqual(estado, 403)
            self.assertIn("--alta-direccion", r["error"])
            app.puesta_en_marcha({"usuario": "jefa", "nombre": "Jefa", "contrasena": "una clave larga", "_desde_consola": True})
            self.assertEqual(c.pedir("POST", "/api/entrar", {"usuario": "jefa", "contrasena": "una clave larga"})[0], 200)
            srv.shutdown(); srv.server_close(); bd.cerrar()
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PruebaDemo(unittest.TestCase):
    def test_siembra_en_base_vacia(self):
        d = tempfile.mkdtemp(prefix="volante-demo-")
        try:
            srv, app, bd = servidor.crear_servidor(d, puerto=0)
            app.reloj = lambda: LUNES
            CENTRO.set(1)
            from api import demo
            self.assertEqual(demo.sembrar(app), ["direccion", "recepcion", "ividal"])
            self.assertEqual(demo.sembrar(app), [])
            libro = app.libro({"rol": "direccion"}, LUNES.date())
            self.assertEqual(len(libro["columnas"]), 4)
            self.assertTrue(any(c["citas"] for c in libro["columnas"]))
            srv.server_close(); bd.cerrar()
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
