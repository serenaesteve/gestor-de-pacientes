"""Lista de espera: cuando se anula una cita, el hueco se ofrece a quien espera.

  · ofrecer_hueco: busca al primero de la lista que encaje (por orden de llegada) y le manda un aviso
    con un enlace propio. La oferta caduca a las «oferta_horas» (3 por defecto) o una hora antes del
    hueco, lo que llegue antes.
  · aceptar: si el hueco sigue libre, se convierte en su cita; si alguien lo ha cogido entretanto,
    la oferta queda «ocupada» y la persona vuelve a su sitio en la lista.
  · rechazar o caducar: la persona vuelve a esperar y el hueco pasa al siguiente.
Un mismo hueco no se ofrece dos veces a la misma persona.
"""

from datetime import timedelta

from . import agenda, recordatorios

MARGEN = timedelta(hours=1)    # no se ofrece un hueco que empieza en menos de una hora


def _franja_encaja(franja, inicio):
    if franja == "manana":
        return inicio.hour < 14
    if franja == "tarde":
        return inicio.hour >= 14
    return True


def ofrecer_hueco(con, medico_id, inicio, fin, ahora):
    """Ofrece [inicio, fin) del médico al primero que encaje. Devuelve la oferta creada o None."""
    if inicio - MARGEN <= ahora:
        return None
    medico = con.una("buscar medicos donde id = ? y activo = verdadero", [medico_id])
    if not medico:
        return None
    # ¿Sigue libre? (otra cita puede haberlo ocupado ya, o haber otra oferta abierta para él)
    if con.una("""buscar citas donde medico_id = ? y empieza < ? y termina > ? y estado en ["pendiente", "confirmada", "atendida", "no_acudio"]
                  mostrar id""", [medico_id, agenda.a_sbd(fin), agenda.a_sbd(inicio)]):
        return None
    if con.una('buscar ofertas donde medico_id = ? y empieza = ? y estado = "abierta" mostrar id', [medico_id, agenda.a_sbd(inicio)]):
        return None
    ya = {f["espera_id"] for f in con.consultar("buscar ofertas donde medico_id = ? y empieza = ? mostrar espera_id",
                                                [medico_id, agenda.a_sbd(inicio)])}
    dia = inicio.date().isoformat()
    candidatos = con.consultar(
        """buscar espera donde estado = "esperando" y desde <= ? y (hasta es nulo o hasta >= ?)
             y (medico_id = ? o (medico_id es nulo y especialidad = ?))
           ordenar creado_en, id""",
        [dia, dia, medico_id, medico["especialidad"]])
    for e in candidatos:
        if e["id"] in ya or not _franja_encaja(e["franja"], inicio):
            continue
        paciente = con.una("buscar pacientes donde id = ?", [e["paciente_id"]])
        canal, destino = recordatorios.destino_de(paciente)
        if not canal or not destino:
            continue
        # Que no choque con otra cita suya
        if con.una("""buscar citas donde paciente_id = ? y empieza < ? y termina > ? y estado en ["pendiente", "confirmada"] mostrar id""",
                   [e["paciente_id"], agenda.a_sbd(fin), agenda.a_sbd(inicio)]):
            continue
        horas = int(recordatorios.leer_ajustes(con).get("oferta_horas") or 3)
        caduca = min(ahora + timedelta(hours=horas), inicio - MARGEN)
        oid = con.ejecutar(
            """insertar en ofertas { espera_id: ?, medico_id: ?, empieza: ?, termina: ?, caduca_en: ?, creada_en: ? } devolver id""",
            [e["id"], medico_id, agenda.a_sbd(inicio), agenda.a_sbd(fin), agenda.a_sbd(caduca), agenda.a_sbd(ahora)]).scalar()
        con.ejecutar('actualizar espera poner estado = "ofrecida" donde id = ?', [e["id"]])
        con.ejecutar("""insertar en recordatorios { oferta_id: ?, tipo: "oferta", canal: ?, destino: ?, programado: ?, creado_en: ? }""",
                     [oid, canal, destino, agenda.a_sbd(ahora), agenda.a_sbd(ahora)])
        return {"id": oid, "paciente": f"{paciente['nombre']} {paciente['apellidos']}", "caduca_en": agenda.a_sbd(caduca)}
    return None


def _cerrar(con, oferta, estado, ahora, volver=True):
    con.ejecutar("actualizar ofertas poner estado = ?, respondida_en = ? donde id = ?", [estado, agenda.a_sbd(ahora), oferta["id"]])
    con.ejecutar('actualizar recordatorios poner estado = "anulado" donde oferta_id = ? y estado = "pendiente"', [oferta["id"]])
    if volver:
        con.ejecutar('actualizar espera poner estado = "esperando" donde id = ? y estado = "ofrecida"', [oferta["espera_id"]])


def aceptar(con, oferta_id, ahora):
    """Convierte la oferta en cita. Devuelve el id de la cita; lanza ValueError con el motivo si no se puede."""
    o = con.una("buscar ofertas donde id = ?", [oferta_id])
    if not o:
        raise ValueError("Esta oferta ya no existe.")
    if o["estado"] != "abierta":
        raise ValueError({"aceptada": "Ya aceptó este hueco: su cita está dada.", "caducada": "Esta oferta ha caducado y el hueco ha pasado a otra persona.",
                          "rechazada": "Dijo que este hueco no le venía bien.", "ocupada": "Lo sentimos: este hueco ya lo ha cogido otra persona."}[o["estado"]])
    inicio, fin = agenda.de_sbd(o["empieza"]), agenda.de_sbd(o["termina"])
    if agenda.de_sbd(o["caduca_en"]) <= ahora:
        siguiente(con, o, "caducada", ahora)
        raise ValueError("Esta oferta ha caducado y el hueco ha pasado a otra persona.")
    if con.una("""buscar citas donde medico_id = ? y empieza < ? y termina > ? y estado en ["pendiente", "confirmada", "atendida", "no_acudio"] mostrar id""",
               [o["medico_id"], agenda.a_sbd(fin), agenda.a_sbd(inicio)]):
        _cerrar(con, o, "ocupada", ahora)
        raise ValueError("Lo sentimos: este hueco ya lo ha cogido otra persona. Sigue en la lista de espera.")
    e = con.una("buscar espera donde id = ?", [o["espera_id"]])
    cid = con.ejecutar(
        """insertar en citas { paciente_id: ?, medico_id: ?, empieza: ?, termina: ?, motivo: ?, origen: "espera", creada_en: ?,
             estado: "confirmada", confirmada_en: ? } devolver id""",
        [e["paciente_id"], o["medico_id"], o["empieza"], o["termina"], e["motivo"], agenda.a_sbd(ahora), agenda.a_sbd(ahora)]).scalar()
    _cerrar(con, o, "aceptada", ahora, volver=False)
    con.ejecutar('actualizar espera poner estado = "citada", cita_id = ? donde id = ?', [cid, e["id"]])
    # Si tenía otra cita más tarde con ese médico, se queda: recepción decide si la anula.
    recordatorios.programar(con, cid, ahora)
    return cid


def siguiente(con, oferta, estado, ahora):
    """Cierra la oferta (rechazada o caducada) y ofrece el mismo hueco al siguiente de la lista."""
    _cerrar(con, oferta, estado, ahora)
    return ofrecer_hueco(con, oferta["medico_id"], agenda.de_sbd(oferta["empieza"]), agenda.de_sbd(oferta["termina"]), ahora)


def caducar(con, ahora):
    """Lo llama el planificador: las ofertas vencidas pasan al siguiente. Devuelve cuántas."""
    vencidas = con.consultar('buscar ofertas donde estado = "abierta" y caduca_en <= ?', [agenda.a_sbd(ahora)])
    for o in vencidas:
        siguiente(con, o, "caducada", ahora)
    return len(vencidas)
