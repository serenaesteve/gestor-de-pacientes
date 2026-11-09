"""Cuentas nuevas desde la web: cada una es un centro con sus propias tablas y nadie ve lo de los demás."""

import re
import unittest

from pruebas.test_volante import BaseVolante, Cliente
from pruebas.test_mejoras import EnServidorSBD
from api.bd import CENTRO, TABLAS_CENTRO, prefijo


class PruebaCentros(BaseVolante):
    def registrar(self, usuario="otra", centro="Clínica Otra", ejemplo=False, cliente=None):
        c = cliente or Cliente(self.puerto)
        estado, r = c.pedir("POST", "/api/registro", {"usuario": usuario, "nombre": "Otra Persona", "contrasena": "otra clave larga",
                                                       "centro": centro, "ejemplo": ejemplo})
        self.assertEqual(estado, 200, r)
        return c

    def test_el_centro_nuevo_tiene_las_mismas_tablas(self):
        self.registrar()
        with self.bd.conexion(centro="global") as con:
            tablas = {f[0] for f in con.ejecutar("tablas").rows}
            for t in TABLAS_CENTRO:
                self.assertIn(f"c2_{t}", tablas)
                self.assertEqual(con.consultar(f"describir {t}"), [
                    {**f, "claves": f["claves"].replace("c2_", "")} for f in con.consultar(f"describir c2_{t}")], t)
        _, yo = self.c.pedir("GET", "/api/yo")
        self.assertEqual(yo["yo"]["centro_id"], 1)

    def test_nadie_ve_lo_de_otro_centro(self):
        m1, p1 = self.medico(), self.paciente()
        _, r1 = self.cita(m1, p1)
        otra = self.registrar()
        _, yo = otra.pedir("GET", "/api/yo")
        self.assertEqual((yo["yo"]["centro_id"], yo["yo"]["centro"]), (2, "Clínica Otra"))
        self.assertEqual(otra.pedir("GET", "/api/pacientes")[1]["total"], 0)
        self.assertEqual(otra.pedir("GET", f"/api/pacientes/{p1}")[0], 404)
        self.assertEqual(otra.pedir("GET", "/api/medicos")[1], [])
        self.assertEqual(otra.pedir("GET", "/api/libro?fecha=2026-11-16")[1]["columnas"], [])
        self.assertEqual(otra.pedir("POST", f"/api/citas/{r1['id']}/estado", {"estado": "anulada"})[0], 404)
        self.assertEqual(otra.pedir("GET", "/api/ajustes")[1]["centro"], "Clínica Otra")
        # El equipo: cada dirección ve y toca solo el suyo
        _, eq = otra.pedir("GET", "/api/equipo")
        self.assertEqual([u["usuario"] for u in eq], ["otra"])
        self.assertEqual(otra.pedir("PUT", "/api/equipo/1", {"activo": False})[0], 404)
        self.assertEqual(otra.pedir("POST", "/api/equipo", {"usuario": "doc2", "nombre": "D", "rol": "medico", "medico_id": m1, "contrasena": "clave de medico"})[0], 400)
        # Lo que crea la otra no aparece en el centro 1, aunque los números de ficha coincidan
        _, pm = otra.pedir("POST", "/api/medicos", {"nombre": "Dr. Otro", "especialidad": "Pediatría"})
        _, pp = otra.pedir("POST", "/api/pacientes", {"nombre": "Zoe", "apellidos": "Zamora", "email": "z@example.com"})
        self.assertEqual((pm["id"], pp["id"]), (1, 1))
        self.assertEqual([p["nombre"] for p in self.c.pedir("GET", "/api/pacientes")[1]["pacientes"]], ["Ana"])
        self.assertEqual([p["nombre"] for p in otra.pedir("GET", "/api/pacientes")[1]["pacientes"]], ["Zoe"])

    def test_enlaces_y_avisos_de_cada_centro(self):
        m1, p1 = self.medico(), self.paciente()
        _, r1 = self.cita(m1, p1)
        otra = self.registrar()
        _, m = otra.pedir("POST", "/api/medicos", {"nombre": "Dr. Otro", "especialidad": "Pediatría"})
        otra.pedir("PUT", f"/api/medicos/{m['id']}/horario", {"franjas": [{"dia": 1, "desde": "09:00", "hasta": "14:00", "minutos": 20}]})
        _, p = otra.pedir("POST", "/api/pacientes", {"nombre": "Zoe", "apellidos": "Zamora", "email": "z@example.com"})
        _, r2 = otra.pedir("POST", "/api/citas", {"medico_id": m["id"], "paciente_id": p["id"], "fecha": "2026-11-16", "hora": "10:00"})
        self.app.cartero.repartir(self.reloj[0])          # el planificador recorre todos los centros
        b1 = self.c.pedir("GET", "/api/avisos?vista=bandeja")[1]["avisos"]
        b2 = otra.pedir("GET", "/api/avisos?vista=bandeja")[1]["avisos"]
        self.assertEqual([a["nombre"] for a in b1], ["Ana"])
        self.assertEqual([a["nombre"] for a in b2], ["Zoe"])
        enlace2 = re.search(r"/c/2/(\d+)/([\w-]+)", b2[0]["cuerpo"])
        self.assertIsNotNone(enlace2, b2[0]["cuerpo"])
        self.assertIn("Clínica Otra", b2[0]["cuerpo"])
        enlace1 = re.search(r"/c/(\d+)/([\w-]+)", b1[0]["cuerpo"])       # el centro 1 conserva el formato de siempre
        anon = Cliente(self.puerto)
        self.assertEqual(anon.pedir("GET", f"/api/c/2/{enlace2.group(1)}/{enlace2.group(2)}")[1]["nombre"], "Zoe")
        self.assertEqual(anon.pedir("GET", f"/api/c/{enlace1.group(1)}/{enlace1.group(2)}")[1]["nombre"], "Ana")
        # La firma de un centro no vale en otro
        self.assertEqual(anon.pedir("GET", f"/api/c/{enlace2.group(1)}/{enlace2.group(2)}")[0], 404)
        self.assertEqual(anon.pedir("GET", f"/api/c/2/{enlace1.group(1)}/{enlace1.group(2)}")[0], 404)
        self.assertEqual(anon.pedir("GET", f"/api/c/9/{enlace2.group(1)}/{enlace2.group(2)}")[0], 404)
        self.assertEqual(anon.pedir("GET", f"/c/2/{enlace2.group(1)}/{enlace2.group(2)}/cita.ics")[0], 200)

    def test_con_datos_de_ejemplo(self):
        otra = self.registrar(ejemplo=True)
        self.assertEqual(len(otra.pedir("GET", "/api/medicos")[1]), 4)
        self.assertGreater(otra.pedir("GET", "/api/pacientes")[1]["total"], 10)
        self.assertEqual(otra.pedir("GET", "/api/ajustes")[1]["centro"], "Clínica Otra")
        self.assertEqual(self.c.pedir("GET", "/api/medicos")[1], [])        # el centro 1, intacto

    def test_usuario_repetido_y_limite_por_hora(self):
        estado, _ = Cliente(self.puerto).pedir("POST", "/api/registro", {"usuario": "direccion", "nombre": "X", "contrasena": "otra clave larga", "centro": "X"})
        self.assertEqual(estado, 409)
        for i in range(3):                                     # el 409 de antes no gasta intento: hacen falta tres altas
            self.registrar(usuario=f"centro{i}")
        estado, r = Cliente(self.puerto).pedir("POST", "/api/registro", {"usuario": "otro9", "nombre": "X", "contrasena": "otra clave larga", "centro": "X"})
        self.assertEqual(estado, 429)

    def test_borrar_el_centro(self):
        otra = self.registrar(ejemplo=True)
        self.assertEqual(otra.pedir("DELETE", "/api/centro", {"contrasena": "mala"})[0], 401)
        estado, r = otra.pedir("DELETE", "/api/centro", {"contrasena": "otra clave larga"})
        self.assertEqual((estado, r), (200, {"borrado": True}))
        with self.bd.conexion(centro="global") as con:
            self.assertFalse([f[0] for f in con.ejecutar("tablas").rows if f[0].startswith("c2_")])
            self.assertIsNone(con.una('buscar usuarios donde usuario = "otra"'))
        self.assertEqual(otra.pedir("GET", "/api/libro")[0], 401)
        self.assertEqual(self.c.pedir("DELETE", "/api/centro", {"contrasena": "una clave larga"})[0], 403)
        self.registrar()                                           # el nombre de usuario queda libre otra vez

    def test_formularios_mal_rellenados_no_gastan_intentos(self):
        c = Cliente(self.puerto)
        for datos in ({"usuario": "ab"}, {"usuario": "serena", "contrasena": "corta"}, {"usuario": "a/b"}, {"usuario": "x" * 31}):
            estado, _ = c.pedir("POST", "/api/registro", {"nombre": "S", "centro": "C", "contrasena": "una clave larga", **datos})
            self.assertEqual(estado, 400, datos)
        # Tildes, mayúsculas, espacios y @: se normaliza igual al crear y al entrar
        estado, r = c.pedir("POST", "/api/registro", {"usuario": "  Lucía Peña ", "nombre": "Lucía", "centro": "Consulta Peña",
                                                       "contrasena": "una clave larga"})
        self.assertEqual(estado, 200, r)
        self.assertEqual(c.pedir("GET", "/api/yo")[1]["yo"]["usuario"], "lucia.pena")
        for forma in ("Lucía Peña", "lucia.pena", "LUCIA PENA"):
            self.assertEqual(Cliente(self.puerto).pedir("POST", "/api/entrar", {"usuario": forma, "contrasena": "una clave larga"})[0], 200, forma)
        estado, r = c.pedir("POST", "/api/registro", {"usuario": "serena@example.com", "nombre": "S", "centro": "C", "contrasena": "una clave larga"})
        self.assertEqual(estado, 200, r)
        estado, r = c.pedir("POST", "/api/registro", {"usuario": "lucia.pena", "nombre": "S", "centro": "C", "contrasena": "una clave larga"})
        self.assertEqual((estado, r.get("codigo")), (409, "usuario"))

    def test_sin_registro(self):
        self.app.registro = False
        estado, r = Cliente(self.puerto).pedir("POST", "/api/registro", {"usuario": "x" * 4, "nombre": "X", "contrasena": "otra clave larga", "centro": "X"})
        self.assertEqual(estado, 403)

    def test_sin_centro_no_se_ejecuta_nada(self):
        CENTRO.set(None)
        with self.assertRaises(RuntimeError):
            with self.bd.conexion() as con:
                con.ejecutar("buscar citas")
        self.assertEqual(prefijo(1), "")
        self.assertEqual(prefijo(12), "c12_")


class PruebaCentrosEnServidor(EnServidorSBD, PruebaCentros):
    pass


def tearDownModule():
    from pruebas.test_mejoras import SBDTemporal
    SBDTemporal.parar()


if __name__ == "__main__":
    unittest.main()
