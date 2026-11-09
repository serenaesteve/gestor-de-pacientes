"""Datos de ejemplo para ver Volante funcionando. Todo es inventado: nombres, teléfonos y correos
(@example.com, un dominio reservado que no entrega a nadie). Solo se siembra en una base vacía."""

import random
from datetime import datetime, timedelta

from . import agenda, recordatorios, seguridad
from .bd import CENTRO

CLAVE_DEMO = "volante-demo"

MEDICOS = [
    ("Dra. Inés Vidal Roca", "Medicina de familia", "Consulta 1", "tinta",
     [(d, "09:00", "14:00", 15) for d in range(1, 6)] + [(2, "16:00", "19:00", 15), (4, "16:00", "19:00", 15)]),
    ("Dr. Tomás Arregui Sanz", "Pediatría", "Consulta 2", "verde",
     [(d, "08:30", "13:30", 20) for d in (1, 3, 5)] + [(2, "15:00", "18:00", 20)]),
    ("Dra. Lucía Benlloch Mas", "Dermatología", "Consulta 4", "violeta",
     [(d, "10:00", "14:00", 30) for d in (2, 4)] + [(d, "16:00", "18:00", 30) for d in (2, 4)]),
    ("Dr. Marcos Ferrer Gil", "Traumatología", "Consulta 3", "bermellon",
     [(d, "15:00", "20:00", 20) for d in range(1, 6)]),
]

NOMBRES = ["Ana", "Pablo", "Lucía", "Javier", "Marta", "Sergio", "Carmen", "Daniel", "Elena", "Raúl", "Nuria", "Hugo",
           "Irene", "Álvaro", "Sara", "Iker", "Paula", "Mario", "Rocío", "Adrián", "Noelia", "Óscar", "Julia", "Víctor",
           "Alba", "Gonzalo", "Lorena", "Rubén", "Claudia", "Jaime", "Aitana", "Héctor", "Begoña", "Ismael", "Celia",
           "Joaquín", "Inmaculada", "Bruno", "Montserrat", "Nicolás"]
APELLIDOS = ["García", "Martínez", "López", "Sánchez", "Pérez", "Gómez", "Ruiz", "Díaz", "Moreno", "Muñoz", "Álvarez",
             "Romero", "Navarro", "Torres", "Domínguez", "Vázquez", "Ramos", "Gil", "Serrano", "Blanco", "Molina", "Ortega",
             "Delgado", "Castro", "Ortiz", "Rubio", "Marín", "Iglesias", "Garrido", "Cortés", "Medina", "Castillo",
             "Santana", "Lozano", "Cano", "Prieto", "Calvo", "Pascual", "Herrera", "Peña"]
MOTIVOS = {
    "Medicina de familia": ["Revisión de tensión", "Renovar receta", "Resultados de análisis", "Dolor de garganta", "Control de diabetes",
                            "Certificado médico", "Mareos", "Revisión anual", None],
    "Pediatría": ["Revisión de los 2 años", "Vacuna", "Fiebre", "Control de peso", "Tos persistente", None],
    "Dermatología": ["Revisión de lunares", "Acné", "Eccema", "Resultado de biopsia", None],
    "Traumatología": ["Dolor de rodilla", "Revisión tras esguince", "Lumbalgia", "Hombro", "Ver radiografía", None],
}


def sembrar(app, semilla=7, cuentas=True, pequeno=False, ajustes_centro=True):
    """Llena una base vacía. Devuelve los usuarios creados, o [] si ya había datos.
    Con cuentas=False no crea las cuentas de ejemplo (su contraseña está en el README): es lo que se
    usa en un servidor publicado, donde solo entra la cuenta de dirección creada a mano.
    pequeno=True (los centros creados desde la web): menos días y pacientes, para que mil centros de prueba
    no llenen la memoria del SBD. ajustes_centro=False deja el nombre que eligió quien lo creó."""
    rnd = random.Random(semilla)
    ahora = app.reloj()
    hoy = ahora.date()
    with app.bd.conexion("volante · demo") as con:
        if con.valor("buscar medicos mostrar contar()") or (cuentas and con.valor("buscar usuarios mostrar contar()")):
            return []
        with con.transaccion():
            if ajustes_centro:
                con.ejecutar('actualizar ajustes poner valor = "Centro Médico Plaza Mayor" donde clave = "centro"')
            con.ejecutar('actualizar ajustes poner valor = "Plaza Mayor 4, 1.º · 46001 Valencia" donde clave = "direccion"')
            con.ejecutar('actualizar ajustes poner valor = "960 000 000" donde clave = "telefono"')
            medicos = []
            for i, (nombre, esp, consulta, color, franjas) in enumerate(MEDICOS):
                mid = con.ejecutar(
                    "insertar en medicos { nombre: ?, especialidad: ?, consulta: ?, color: ?, colegiado: ?, creado_en: ? } devolver id",
                    [nombre, esp, consulta, color, f"46/28{i}0{i + 3}{i * 7}", agenda.a_sbd(ahora)]).scalar()
                for dia, desde, hasta, minutos in franjas:
                    con.ejecutar("insertar en horarios { medico_id: ?, dia: ?, desde: ?, hasta: ?, minutos: ? }", [mid, dia, desde, hasta, minutos])
                medicos.append({"id": mid, "especialidad": esp,
                                "franjas": [{"dia": d, "desde": a, "hasta": b, "minutos": m} for d, a, b, m in franjas]})
            # Congreso del traumatólogo la semana que viene, para que se vea una ausencia.
            jueves = hoy + timedelta(days=(3 - hoy.weekday()) % 7 + 7)
            con.ejecutar("insertar en ausencias { medico_id: ?, desde: ?, hasta: ?, motivo: ? }",
                         [medicos[3]["id"], jueves.isoformat(), (jueves + timedelta(days=1)).isoformat(), "Congreso SECOT"])

            pacientes = []
            usados = set()
            for i in range(28 if pequeno else 46):
                while True:
                    n, a1, a2 = rnd.choice(NOMBRES), rnd.choice(APELLIDOS), rnd.choice(APELLIDOS)
                    if (n, a1) not in usados and a1 != a2:
                        usados.add((n, a1))
                        break
                canal = rnd.choices(["correo", "whatsapp", "sms", "ninguno"], [6, 3, 1, 1])[0]
                email = f"{_ascii(n)}.{_ascii(a1)}@example.com" if canal == "correo" or rnd.random() < .3 else None
                pid = con.ejecutar(
                    """insertar en pacientes { nombre: ?, apellidos: ?, documento: ?, nacimiento: ?, telefono: ?, email: ?, canal: ?, notas: ?, creado_en: ? }
                       devolver id""",
                    [n, f"{a1} {a2}", f"{rnd.randint(10_000_000, 99_999_999)}{'TRWAGMYFPDXBNJZSQVHLCKE'[i % 23]}",
                     f"{rnd.randint(1940, 2022)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                     f"6{rnd.randint(10, 99)} {rnd.randint(100, 999)} {rnd.randint(100, 999)}", email, canal,
                     rnd.choice([None, None, None, "Alergia a la penicilina", "Prefiere que le llamen por la tarde", "Viene con su hija"]),
                     agenda.a_sbd(ahora)]).scalar()
                pacientes.append(pid)

            citas_futuras = []
            for m in medicos:
                for delta in (range(-7, 15) if pequeno else range(-10, 22)):
                    d = hoy + timedelta(days=delta)
                    for f in agenda.franjas_del_dia(m["franjas"], d):
                        if m["id"] == medicos[3]["id"] and jueves <= d <= jueves + timedelta(days=1):
                            continue
                        t = datetime.combine(d, agenda.hora(f["desde"]))
                        tope = datetime.combine(d, agenda.hora(f["hasta"]))
                        paso = timedelta(minutes=f["minutos"])
                        ocupacion = 0.72 if delta <= 2 else max(0.15, 0.6 - delta * 0.025)
                        while t + paso <= tope:
                            if rnd.random() < ocupacion:
                                pasada = t + paso <= ahora
                                if pasada:
                                    estado = rnd.choices(["atendida", "no_acudio", "anulada"], [86, 9, 5])[0]
                                else:
                                    estado = rnd.choices(["pendiente", "confirmada", "anulada"], [55, 40, 5])[0]
                                # Sala de espera: llegan un poco antes, pasan con algo de retraso
                                llegada = entra = sale = None
                                if estado == "atendida":
                                    llegada = t - timedelta(minutes=rnd.randint(0, 14))
                                    entra = t + timedelta(minutes=rnd.choice([0, 2, 4, 6, 9, 13, 18]))
                                    sale = entra + paso - timedelta(minutes=rnd.randint(0, 4))
                                cid = con.ejecutar(
                                    """insertar en citas { paciente_id: ?, medico_id: ?, empieza: ?, termina: ?, motivo: ?, estado: ?, origen: ?,
                                         creada_en: ?, confirmada_en: ?, anulada_en: ?, anulada_por: ?, llegada: ?, entra: ?, atendida_en: ? } devolver id""",
                                    [rnd.choice(pacientes), m["id"], agenda.a_sbd(t), agenda.a_sbd(t + paso), rnd.choice(MOTIVOS[m["especialidad"]]),
                                     estado, rnd.choice(["recepcion", "telefono"]), agenda.a_sbd(t - timedelta(days=rnd.randint(2, 20))),
                                     agenda.a_sbd(ahora - timedelta(hours=rnd.randint(1, 40))) if estado == "confirmada" else None,
                                     agenda.a_sbd(ahora - timedelta(days=1)) if estado == "anulada" else None,
                                     rnd.choice(["recepcion", "paciente"]) if estado == "anulada" else None,
                                     *(agenda.a_sbd(x) if x else None for x in (llegada, entra, sale))]).scalar()
                                if not pasada and estado != "anulada":
                                    citas_futuras.append(cid)
                            t += paso
            for cid in citas_futuras:
                recordatorios.programar(con, cid, ahora, nueva=rnd.random() < 0.03)

            # Lista de espera: cinco personas que quieren adelantar su cita
            for i, pid in enumerate(rnd.sample(pacientes, 8)):
                p = con.una("buscar pacientes donde id = ?", [pid])
                if p["canal"] == "ninguno" or (p["canal"] == "correo" and not p["email"]):
                    continue
                m = medicos[i % len(medicos)]
                con.ejecutar("""insertar en espera { paciente_id: ?, medico_id: ?, especialidad: ?, desde: ?, franja: ?, minutos: ?, motivo: ?, creado_en: ? }""",
                             [pid, m["id"] if i % 3 else None, m["especialidad"], hoy.isoformat(), rnd.choice(["cualquiera", "manana", "tarde"]),
                              m["franjas"][0]["minutos"], rnd.choice(MOTIVOS[m["especialidad"]]), agenda.a_sbd(ahora - timedelta(days=rnd.randint(1, 9)))])

            if not cuentas:
                return ["(sin cuentas de ejemplo)"]
            usuarios = [("direccion", "Dirección del centro", "direccion", None),
                        ("recepcion", "Mostrador de recepción", "recepcion", None),
                        ("ividal", "Inés Vidal", "medico", medicos[0]["id"])]
            resumen = seguridad.cifrar_contrasena(CLAVE_DEMO, 20_000)
            for usuario, nombre, rol, medico_id in usuarios:
                con.ejecutar("insertar en usuarios { usuario: ?, nombre: ?, rol: ?, centro_id: ?, medico_id: ?, hash_contrasena: ?, creado_en: ? }",
                             [usuario, nombre, rol, CENTRO.get() or 1, medico_id, resumen, agenda.a_sbd(ahora)])
    app.despertar.set()
    return [u[0] for u in usuarios]


def _ascii(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()
