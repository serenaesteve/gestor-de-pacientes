"""Informe del mes: ocupación, asistencia, sala de espera, avisos y lista de espera.

Ocupación = minutos citados / minutos de consulta del mes completo (franjas del horario menos las
ausencias). Las citas anuladas no cuentan como ocupadas; las de «no acudió», sí (el hueco se perdió).
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from . import agenda


def _min(a, b):
    return int((agenda.de_sbd(b) - agenda.de_sbd(a)).total_seconds() // 60)


def calcular(bd, ini, fin, ahora):
    d0, d1 = f"{ini} 00:00:00", f"{fin} 00:00:00"
    with bd.conexion() as con:
        medicos = con.consultar("buscar medicos ordenar id")
        franjas = con.consultar("buscar horarios")
        ausencias = con.consultar("buscar ausencias donde desde < ? y hasta >= ?", [fin.isoformat(), ini.isoformat()])
        citas = con.consultar("""buscar citas donde empieza >= ? y empieza < ?
                                 mostrar id, medico_id, empieza, termina, estado, origen, confirmada_en, anulada_por, llegada, entra""", [d0, d1])
        avisos = con.consultar("buscar recordatorios donde programado >= ? y programado < ? mostrar tipo, canal, estado", [d0, d1])
        espera_nuevas = con.valor("buscar espera donde creado_en >= ? y creado_en < ? mostrar contar()", [d0, d1])
        ofertas = con.consultar("buscar ofertas donde creada_en >= ? y creada_en < ? mostrar estado", [d0, d1])
        esperando = con.valor('buscar espera donde estado en ["esperando", "ofrecida"] mostrar contar()')

    por_medico_franjas = defaultdict(list)
    for f in franjas:
        por_medico_franjas[f["medico_id"]].append(f)
    por_medico_aus = defaultdict(list)
    for a in ausencias:
        por_medico_aus[a["medico_id"]].append(a)

    dias = []
    d = ini
    while d < fin:
        dias.append(d)
        d += timedelta(days=1)

    filas = []
    totales = Counter()
    esperas_todas = []
    for m in medicos:
        ofertado = 0
        for dia in dias:
            if agenda.ausencia_en(por_medico_aus[m["id"]], dia):
                continue
            for f in agenda.franjas_del_dia(por_medico_franjas[m["id"]], dia):
                ofertado += (datetime.combine(dia, agenda.hora(f["hasta"])) - datetime.combine(dia, agenda.hora(f["desde"]))).seconds // 60
        suyas = [c for c in citas if c["medico_id"] == m["id"]]
        if not suyas and (not m["activo"] or not ofertado):
            continue
        cuenta = Counter(c["estado"] for c in suyas)
        citado = sum(_min(c["empieza"], c["termina"]) for c in suyas if c["estado"] in agenda.OCUPAN)
        cerradas = cuenta["atendida"] + cuenta["no_acudio"]
        esperas = [_min(c["llegada"], c["entra"]) for c in suyas if c["llegada"] and c["entra"]]
        esperas_todas += esperas
        vivas = [c for c in suyas if c["estado"] != "anulada"]
        fila = {
            "id": m["id"], "nombre": m["nombre"], "especialidad": m["especialidad"], "color": m["color"],
            "minutos_consulta": ofertado, "minutos_citados": citado,
            "ocupacion": round(citado / ofertado, 3) if ofertado else None,
            "citas": len(vivas), "atendidas": cuenta["atendida"], "no_acudio": cuenta["no_acudio"],
            "anuladas": cuenta["anulada"], "pendientes": cuenta["pendiente"] + cuenta["confirmada"],
            "faltas": round(cuenta["no_acudio"] / cerradas, 3) if cerradas else None,
            "espera_media": round(sum(esperas) / len(esperas)) if esperas else None,
        }
        filas.append(fila)
        for k in ("minutos_consulta", "minutos_citados", "citas", "atendidas", "no_acudio", "anuladas", "pendientes"):
            totales[k] += fila[k]

    vivas = [c for c in citas if c["estado"] != "anulada"]
    anuladas = [c for c in citas if c["estado"] == "anulada"]
    cerradas = totales["atendidas"] + totales["no_acudio"]
    por_dia = []
    for dia in dias:
        del_dia = [c for c in citas if c["empieza"][:10] == dia.isoformat()]
        n = Counter(c["estado"] for c in del_dia)
        por_dia.append({"fecha": dia.isoformat(), "atendidas": n["atendida"], "no_acudio": n["no_acudio"],
                        "pendientes": n["pendiente"] + n["confirmada"], "anuladas": n["anulada"]})
    canales = defaultdict(Counter)
    for a in avisos:
        canales[a["canal"]][a["estado"]] += 1
    of = Counter(o["estado"] for o in ofertas)
    return {
        "mes": ini.isoformat()[:7], "ahora": agenda.a_sbd(ahora), "cerrado": fin <= ahora.date(),
        "totales": {
            **totales,
            "ocupacion": round(totales["minutos_citados"] / totales["minutos_consulta"], 3) if totales["minutos_consulta"] else None,
            "faltas": round(totales["no_acudio"] / cerradas, 3) if cerradas else None,
            "confirmadas": round(sum(1 for c in vivas if c["confirmada_en"]) / len(vivas), 3) if vivas else None,
            "anuladas_paciente": sum(1 for c in anuladas if c["anulada_por"] == "paciente"),
            "anuladas_centro": sum(1 for c in anuladas if c["anulada_por"] != "paciente"),
            "espera_media": round(sum(esperas_todas) / len(esperas_todas)) if esperas_todas else None,
            "origen": dict(Counter(c["origen"] for c in vivas)),
        },
        "medicos": filas,
        "por_dia": por_dia,
        "avisos": {canal: dict(n) for canal, n in canales.items()},
        "espera": {"nuevas": espera_nuevas, "ofertas": len(ofertas), "aceptadas": of["aceptada"], "rechazadas": of["rechazada"],
                   "caducadas": of["caducada"], "ocupadas": of["ocupada"], "esperando": esperando},
    }
