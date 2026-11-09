"""Pruebas de la lista de espera, la sala, las series, el justificante, la cita pedida por el
paciente, el informe del mes y el modo con servidor SBD (uno temporal, nunca el de producción)."""

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from pruebas.test_volante import BaseVolante, Cliente, LUNES, RAIZ, PruebaCitas, PruebaRecordatorios, PruebaEnlacePaciente

from sbd.cliente import Cliente as ClienteSBD

SBD_COMPLETO = Path("/root/sbd")


class PruebaListaEspera(BaseVolante):
    def preparar(self):
        self.m = self.medico()
        self.a = self.paciente()
        self.b = self.paciente(nombre="Berta", apellidos="Bueno", email="berta@example.com")
        self.c2 = self.paciente(nombre="Carla", apellidos="Campos", email="carla@example.com")
        _, r = self.cita(self.m, self.a)          # lunes 16, 10:00
        self.cid = r["id"]
        for p in (self.b, self.c2):
            estado, r = self.c.pedir("POST", "/api/espera", {"paciente_id": p, "medico_id": self.m})
            self.assertEqual(estado, 200, r)

    def ofertas(self):
        with self.bd.conexion() as con:
            return con.consultar("buscar ofertas como o unir espera como e en e.id = o.espera_id ordenar o.id mostrar o.id como id, o.estado como estado, e.paciente_id como paciente, o.caduca_en como caduca_en")

    def enlace(self, oid):
        return re.search(r"/o/(\d+)/([\w-]+)", self.app.cartero.enlace_oferta(oid)).groups()

    def test_anular_ofrece_el_hueco_y_aceptar_da_la_cita(self):
        self.preparar()
        _, r = self.c.pedir("POST", f"/api/citas/{self.cid}/estado", {"estado": "anulada"})
        self.assertEqual(r["ofertas"][0]["paciente"], "Berta Bueno")
        o = self.ofertas()[0]
        self.assertEqual((o["paciente"], o["estado"], o["caduca_en"]), (self.b, "abierta", "2026-11-09 11:00:00"))
        self.app.cartero.repartir(self.reloj[0])
        _, bandeja = self.c.pedir("GET", "/api/avisos?vista=bandeja")
        oferta = [a for a in bandeja["avisos"] if a["tipo"] == "oferta"][0]
        self.assertIn("/o/", oferta["cuerpo"])
        self.assertIn("hueco", oferta["cuerpo"])
        oid, firma = self.enlace(o["id"])
        anonimo = Cliente(self.puerto)
        self.assertEqual(anonimo.pedir("GET", f"/api/o/{oid}/{'z' * 24}")[0], 404)
        estado, r = anonimo.pedir("POST", f"/api/o/{oid}/{firma}", {"accion": "aceptar"})
        self.assertEqual((estado, r["estado"]), (200, "aceptada"), r)
        self.assertIn("/c/", r["enlace_cita"])
        with self.bd.conexion() as con:
            nueva = con.una('buscar citas donde paciente_id = ? y estado != "anulada"', [self.b])
            e = con.una("buscar espera donde paciente_id = ?", [self.b])
        self.assertEqual((nueva["empieza"], nueva["origen"], nueva["estado"]), ("2026-11-16 10:00:00", "espera", "confirmada"))
        self.assertEqual((e["estado"], e["cita_id"]), ("citada", nueva["id"]))
        self.assertEqual(anonimo.pedir("POST", f"/api/o/{oid}/{firma}", {"accion": "aceptar"})[0], 409)

    def test_rechazar_y_caducar_pasan_al_siguiente(self):
        self.preparar()
        self.c.pedir("POST", f"/api/citas/{self.cid}/estado", {"estado": "anulada"})
        oid, firma = self.enlace(self.ofertas()[0]["id"])
        Cliente(self.puerto).pedir("POST", f"/api/o/{oid}/{firma}", {"accion": "rechazar"})
        estados = [(o["paciente"], o["estado"]) for o in self.ofertas()]
        self.assertEqual(estados, [(self.b, "rechazada"), (self.c2, "abierta")])
        # La de Carla caduca a las 3 horas y no hay nadie más: el hueco se queda libre.
        self.reloj[0] = LUNES + timedelta(hours=3, minutes=1)
        self.c.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})
        self.app.cartero.repartir(self.reloj[0])
        self.assertEqual([o["estado"] for o in self.ofertas()], ["rechazada", "caducada"])
        _, lista = self.c.pedir("GET", "/api/espera")
        self.assertEqual([x["estado"] for x in lista], ["esperando", "esperando"])

    def test_si_recepcion_da_el_hueco_la_oferta_se_cierra(self):
        self.preparar()
        self.c.pedir("POST", f"/api/citas/{self.cid}/estado", {"estado": "anulada"})
        oid, firma = self.enlace(self.ofertas()[0]["id"])
        otro = self.paciente(nombre="Dani", apellidos="Díaz", email="dani@example.com")
        self.assertEqual(self.cita(self.m, otro)[0], 200)
        self.assertEqual(self.ofertas()[0]["estado"], "ocupada")
        estado, r = Cliente(self.puerto).pedir("POST", f"/api/o/{oid}/{firma}", {"accion": "aceptar"})
        self.assertEqual(estado, 409)

    def test_deshacer_la_anulacion_retira_la_oferta(self):
        self.preparar()
        self.c.pedir("POST", f"/api/citas/{self.cid}/estado", {"estado": "anulada"})
        self.assertEqual(self.c.pedir("POST", f"/api/citas/{self.cid}/estado", {"estado": "pendiente", "deshacer": True})[0], 200)
        self.assertEqual(self.ofertas()[0]["estado"], "ocupada")

    def test_franja_y_paciente_sin_avisos(self):
        m = self.medico()
        sin = self.paciente(canal="ninguno", email="s@example.com")
        estado, r = self.c.pedir("POST", "/api/espera", {"paciente_id": sin, "medico_id": m})
        self.assertEqual(estado, 409)
        tarde = self.paciente(nombre="Tere", apellidos="Tarde", email="t@example.com")
        self.c.pedir("POST", "/api/espera", {"paciente_id": tarde, "especialidad": "Medicina de familia", "franja": "tarde"})
        a = self.paciente(nombre="Ana2", apellidos="X", email="a2@example.com")
        _, r = self.cita(m, a)
        _, r = self.c.pedir("POST", f"/api/citas/{r['id']}/estado", {"estado": "anulada"})
        self.assertEqual(r["ofertas"], [])     # el hueco es de mañana


class PruebaSala(BaseVolante):
    def test_llegada_paso_atendida_y_justificante(self):
        m, p = self.medico(), self.paciente(documento="12345678Z")
        _, r = self.cita(m, p, fecha="2026-11-09", hora="09:20")
        cid = r["id"]
        self.reloj[0] = datetime(2026, 11, 9, 9, 5)
        self.assertEqual(self.c.pedir("GET", f"/api/citas/{cid}/justificante")[0], 409)
        self.assertEqual(self.c.pedir("POST", f"/api/citas/{cid}/sala", {"accion": "llega"})[0], 200)
        _, libro = self.c.pedir("GET", "/api/libro?fecha=2026-11-09")
        self.assertEqual(libro["resumen"]["en_sala"], 1)
        self.assertFalse([a for a in self.avisos(cid) if a["estado"] == "pendiente"])
        self.reloj[0] = datetime(2026, 11, 9, 9, 23)
        self.c.pedir("POST", f"/api/citas/{cid}/sala", {"accion": "pasa"})
        self.reloj[0] = datetime(2026, 11, 9, 9, 41)
        self.c.pedir("POST", f"/api/citas/{cid}/estado", {"estado": "atendida"})
        _, j = self.c.pedir("GET", f"/api/citas/{cid}/justificante")
        self.assertEqual((j["desde"], j["hasta"], j["documento"]), ("2026-11-09 09:05:00", "2026-11-09 09:41:00", "12345678Z"))
        cid_v, firma = re.search(r"/v/(\d+)/([\w-]+)", j["verificar"]).groups()
        estado, v = Cliente(self.puerto).pedir("GET", f"/api/v/{cid_v}/{firma}")
        self.assertEqual((estado, v["iniciales"], v["codigo"]), (200, "A.G.L.", j["codigo"]))
        self.assertNotIn("documento", v)
        self.assertEqual(Cliente(self.puerto).pedir("GET", f"/api/v/{cid_v}/{'q' * 24}")[0], 404)
        # La firma de una cita no abre el justificante, ni al revés.
        estado, _ = Cliente(self.puerto).pedir("GET", f"/api/c/{cid_v}/{firma}")
        self.assertEqual(estado, 404)

    def test_solo_las_de_hoy(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)
        self.assertEqual(self.c.pedir("POST", f"/api/citas/{r['id']}/sala", {"accion": "llega"})[0], 409)


class PruebaSeries(BaseVolante):
    def test_serie_semanal_salta_lo_que_no_cabe(self):
        m, p = self.medico(), self.paciente()
        self.c.pedir("POST", f"/api/medicos/{m}/ausencias", {"desde": "2026-11-30", "hasta": "2026-11-30", "motivo": "Congreso"})
        datos = {"medico_id": m, "paciente_id": p, "fecha": "2026-11-16", "hora": "10:00", "minutos": 20, "repetir": "semana", "veces": 4}
        _, previa = self.c.pedir("POST", "/api/citas/serie", datos)
        self.assertEqual([x["cabe"] for x in previa], [True, True, False, True])
        self.assertIn("Congreso", previa[2]["motivo"])
        estado, r = self.c.pedir("POST", "/api/citas", datos)
        self.assertEqual((estado, len(r["ids"]), r["saltadas"][0]["fecha"]), (200, 3, "2026-11-30"))
        self.app.cartero.repartir(self.reloj[0])
        reserva = [a for a in self.avisos(r["ids"][0]) if a["tipo"] == "reserva"][0]
        self.assertIn("las 2 siguientes de la serie", reserva["cuerpo"])
        self.assertIn("lunes 7 de diciembre", reserva["cuerpo"])
        self.assertFalse([a for a in self.avisos(r["ids"][1]) if a["tipo"] == "reserva"])
        _, libro = self.c.pedir("GET", "/api/libro?fecha=2026-11-23")
        c = libro["columnas"][0]["citas"][0]
        self.assertEqual((c["serie_n"], c["serie_total"]), (2, 3))
        _, r2 = self.c.pedir("POST", f"/api/citas/{r['ids'][1]}/estado", {"estado": "anulada", "serie": True})
        self.assertEqual(r2["anuladas"], 2)
        with self.bd.conexion() as con:
            estados = [x["estado"] for x in con.consultar("buscar citas ordenar empieza mostrar estado")]
        self.assertEqual(estados, ["pendiente", "anulada", "anulada"])

    def test_serie_mensual_fin_de_mes(self):
        fechas = self.app._fechas_serie(datetime(2026, 1, 31, 10, 0), "mes", 3)
        self.assertEqual([f.date().isoformat() for f in fechas], ["2026-01-31", "2026-02-28", "2026-03-31"])


class PruebaPedirPorEnlace(BaseVolante):
    def test_pedir_otra_cita(self):
        m, p = self.medico(), self.paciente()
        _, r = self.cita(m, p)
        cid, firma = re.search(r"/c/(\d+)/([\w-]+)", self.app.cartero.enlace(r["id"])).groups()
        anon = Cliente(self.puerto)
        _, h = anon.pedir("GET", f"/api/c/{cid}/{firma}/huecos?desde=2026-11-16")
        self.assertEqual(h["dias"][0]["fecha"], "2026-11-16")
        self.assertNotIn("10:00", [x["hora"] for x in h["dias"][0]["huecos"]])
        self.assertEqual(anon.pedir("POST", f"/api/c/{cid}/{firma}/pedir", {"fecha": "2026-11-16", "hora": "10:00"})[0], 409)
        self.assertEqual(anon.pedir("POST", f"/api/c/{cid}/{firma}/pedir", {"fecha": "2026-11-16", "hora": "10:05"})[0], 409)  # no es un hueco
        estado, n = anon.pedir("POST", f"/api/c/{cid}/{firma}/pedir", {"fecha": "2026-11-23", "hora": "11:00"})
        self.assertEqual(estado, 200, n)
        self.assertEqual(anon.pedir("GET", "/api" + n["enlace"])[1]["empieza"], "2026-11-23 11:00:00")
        anon.pedir("POST", f"/api/c/{cid}/{firma}/pedir", {"fecha": "2026-11-23", "hora": "11:20"})
        estado, r3 = anon.pedir("POST", f"/api/c/{cid}/{firma}/pedir", {"fecha": "2026-11-23", "hora": "11:40"})
        self.assertEqual(estado, 409)
        self.assertIn("dos citas", r3["error"])
        self.c.pedir("PUT", "/api/ajustes", {"citas_por_enlace": "no"})
        self.assertEqual(anon.pedir("GET", f"/api/c/{cid}/{firma}/huecos")[0], 403)


class PruebaInforme(BaseVolante):
    def test_cifras_del_mes(self):
        m = self.medico()   # lunes de 9 a 14: noviembre 2026 tiene 5 lunes → 1500 min
        a, b = self.paciente(), self.paciente(nombre="Bea", email="b@example.com")
        _, r1 = self.cita(m, a, fecha="2026-11-09", hora="09:20")
        _, r2 = self.cita(m, b, fecha="2026-11-09", hora="09:40")
        _, r3 = self.cita(m, a, fecha="2026-11-16", hora="09:40")
        self.c.pedir("POST", f"/api/citas/{r3['id']}/estado", {"estado": "anulada"})
        self.reloj[0] = datetime(2026, 11, 9, 9, 10)
        self.c.pedir("POST", f"/api/citas/{r1['id']}/sala", {"accion": "llega"})
        self.reloj[0] = datetime(2026, 11, 9, 9, 22)
        self.c.pedir("POST", f"/api/citas/{r1['id']}/sala", {"accion": "pasa"})
        self.reloj[0] = datetime(2026, 11, 9, 12, 0)
        self.c.pedir("POST", "/api/entrar", {"usuario": "direccion", "contrasena": "una clave larga"})
        self.c.pedir("POST", f"/api/citas/{r1['id']}/estado", {"estado": "atendida"})
        self.c.pedir("POST", f"/api/citas/{r2['id']}/estado", {"estado": "no_acudio"})
        estado, inf = self.c.pedir("GET", "/api/informe?mes=2026-11")
        self.assertEqual(estado, 200, inf)
        fila = inf["medicos"][0]
        self.assertEqual((fila["minutos_consulta"], fila["minutos_citados"], fila["citas"], fila["anuladas"]), (1500, 40, 2, 1))
        self.assertEqual((fila["faltas"], fila["espera_media"]), (0.5, 12))
        self.assertEqual(inf["totales"]["anuladas_centro"], 1)
        self.assertEqual(len(inf["por_dia"]), 30)

    def test_solo_direccion(self):
        self.c.pedir("POST", "/api/equipo", {"usuario": "mostrador", "nombre": "R", "rol": "recepcion", "contrasena": "clave de recepcion"})
        rec = Cliente(self.puerto)
        rec.pedir("POST", "/api/entrar", {"usuario": "mostrador", "contrasena": "clave de recepcion"})
        self.assertEqual(rec.pedir("GET", "/api/informe")[0], 403)


# ---------------------------------------------------------------- modo servidor SBD

def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SBDTemporal:
    """Un servidor de SBD de usar y tirar, con un usuario que puede crear bases."""
    proceso = None

    @classmethod
    def arrancar(cls):
        if cls.proceso:
            return
        cls.carpeta = tempfile.mkdtemp(prefix="volante-sbd-")
        sbd = lambda orden: subprocess.run([sys.executable, "-m", "sbd", cls.carpeta, "-e", orden], cwd=RAIZ,
                                           capture_output=True, text=True, check=True).stdout
        sbd('crear usuario volante_app clave "una clave de prueba larga" puede todo')
        cls.clave = re.search(r"sbd_k\S+", sbd('crear clave api para volante_app llamada "pruebas"')).group(0)
        puerto = _puerto_libre()
        # El servidor necesita el panel web de SBD, que la copia de Volante no lleva: se usa el SBD completo.
        cls.proceso = subprocess.Popen([sys.executable, "-m", "sbd", "servidor", cls.carpeta, "--puerto", str(puerto), "--silencio"],
                                       cwd=SBD_COMPLETO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.url = f"http://127.0.0.1:{puerto}"
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + "/salud", timeout=1)
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("el SBD temporal no arranca")

    @classmethod
    def parar(cls):
        if cls.proceso:
            cls.proceso.terminate()
            cls.proceso.wait()
            shutil.rmtree(cls.carpeta, ignore_errors=True)
            cls.proceso = None


class EnServidorSBD:
    """Repite las pruebas de la clase con la base en un servidor SBD (una base nueva por prueba)."""
    contador = 0

    @classmethod
    def setUpClass(cls):
        SBDTemporal.arrancar()

    def setUp(self):
        EnServidorSBD.contador += 1
        base = f"prueba{EnServidorSBD.contador}"
        ClienteSBD(SBDTemporal.url, SBDTemporal.clave).ejecutar(f"crear base {base}")
        self._sbd_json = {"url": SBDTemporal.url, "clave": SBDTemporal.clave, "base": base}
        super().setUp()

    def antes_de_crear(self, carpeta):
        Path(carpeta, "sbd.json").write_text(json.dumps(self._sbd_json))


class PruebaCitasEnServidor(EnServidorSBD, PruebaCitas):
    def test_esta_en_el_servidor(self):
        self.assertTrue(self.bd.remota)
        m, p = self.medico(), self.paciente()
        self.cita(m, p)
        filas = ClienteSBD(SBDTemporal.url, SBDTemporal.clave, self._sbd_json["base"]).consultar("buscar citas mostrar empieza")
        self.assertEqual(filas, [{"empieza": "2026-11-16 10:00:00"}])

    def test_transaccion_que_falla_no_deja_nada(self):
        m, p = self.medico(), self.paciente()
        datos = {"medico_id": m, "paciente_id": p, "fecha": "2026-11-16", "hora": "10:00", "minutos": 20, "repetir": "semana", "veces": 3}
        self.cita(m, p, fecha="2026-11-16")   # la primera de la serie choca: no se crea ninguna
        self.assertEqual(self.c.pedir("POST", "/api/citas", datos)[0], 409)
        self.assertEqual(ClienteSBD(SBDTemporal.url, SBDTemporal.clave, self._sbd_json["base"]).ejecutar("buscar citas mostrar contar()").escalar(), 1)


class PruebaRecordatoriosEnServidor(EnServidorSBD, PruebaRecordatorios):
    pass


class PruebaEnlaceEnServidor(EnServidorSBD, PruebaEnlacePaciente):
    pass


class PruebaEsperaEnServidor(EnServidorSBD, PruebaListaEspera):
    pass


def tearDownModule():
    SBDTemporal.parar()
