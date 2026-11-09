"""Cuentas de la agenda: franjas, huecos libres y choques entre citas.

Todo trabaja con datetime «ingenuos» en la hora de la consulta. SBD devuelve las fechas como texto
«AAAA-MM-DD HH:MM:SS» y las recibe igual.
"""

from datetime import date, datetime, time, timedelta

FORMATO = "%Y-%m-%d %H:%M:%S"
ACTIVAS = ("pendiente", "confirmada")          # citas que ocupan hueco y esperan al paciente
OCUPAN = ("pendiente", "confirmada", "atendida", "no_acudio")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def a_sbd(momento):
    return momento.strftime(FORMATO)


def de_sbd(valor):
    if valor is None or isinstance(valor, datetime):
        return valor
    texto = str(valor).replace("T", " ")
    for formato in (FORMATO, "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            pass
    raise ValueError(f"«{valor}» no es una fecha con hora (AAAA-MM-DD HH:MM)")


def fecha(valor):
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ValueError(f"«{valor}» no es una fecha (AAAA-MM-DD)") from None


def hora(texto):
    """«9:05» o «09:05» → time. Rechaza lo que no sea una hora del día."""
    try:
        h, m = str(texto).strip().split(":")
        return time(int(h), int(m))
    except (ValueError, TypeError):
        raise ValueError(f"«{texto}» no es una hora (HH:MM)") from None


def hhmm(t):
    return f"{t.hour:02d}:{t.minute:02d}"


def se_solapan(a_ini, a_fin, b_ini, b_fin):
    return a_ini < b_fin and b_ini < a_fin


def franjas_del_dia(franjas, dia):
    """Las franjas de un médico que tocan ese día de la semana, ordenadas."""
    n = dia.isoweekday()
    return sorted((f for f in franjas if int(f["dia"]) == n), key=lambda f: hora(f["desde"]))


def ausencia_en(ausencias, dia):
    for a in ausencias:
        if fecha(a["desde"]) <= dia <= fecha(a["hasta"]):
            return a
    return None


def dentro_de_horario(franjas, inicio, fin):
    """¿Cabe [inicio, fin) entera en una franja de ese día?"""
    for f in franjas_del_dia(franjas, inicio.date()):
        f_ini = datetime.combine(inicio.date(), hora(f["desde"]))
        f_fin = datetime.combine(inicio.date(), hora(f["hasta"]))
        if f_ini <= inicio and fin <= f_fin:
            return f
    return None


def huecos(franjas, ausencias, citas, dia, ahora):
    """Huecos libres de un día: cada franja se trocea en citas de su duración y se quitan las que
    chocan con una cita que ocupa sitio o que ya han empezado."""
    if ausencia_en(ausencias, dia):
        return []
    ocupadas = [(de_sbd(c["empieza"]), de_sbd(c["termina"])) for c in citas if c["estado"] in OCUPAN]
    libres = []
    for f in franjas_del_dia(franjas, dia):
        paso = timedelta(minutes=int(f["minutos"]))
        t = datetime.combine(dia, hora(f["desde"]))
        tope = datetime.combine(dia, hora(f["hasta"]))
        while t + paso <= tope:
            if t > ahora and not any(se_solapan(t, t + paso, i, e) for i, e in ocupadas):
                libres.append({"hora": hhmm(t), "minutos": int(f["minutos"])})
            t += paso
    return libres


def validar_franjas(franjas):
    """Normaliza las franjas que manda el editor de horario y comprueba que no se pisan."""
    limpias = []
    for f in franjas:
        try:
            dia = int(f.get("dia"))
            desde, hasta = hora(f.get("desde")), hora(f.get("hasta"))
            minutos = int(f.get("minutos") or 20)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Cada franja necesita día, hora de inicio, hora de fin y minutos por cita.") from None
        if not 1 <= dia <= 7:
            raise ValueError("El día de la semana va de 1 (lunes) a 7 (domingo).")
        if desde >= hasta:
            raise ValueError(f"El {DIAS[dia - 1]}, la franja de {hhmm(desde)} termina antes de empezar.")
        if not 5 <= minutos <= 240:
            raise ValueError("Cada cita dura entre 5 y 240 minutos.")
        limpias.append({"dia": dia, "desde": hhmm(desde), "hasta": hhmm(hasta), "minutos": minutos})
    limpias.sort(key=lambda f: (f["dia"], f["desde"]))
    for a, b in zip(limpias, limpias[1:]):
        if a["dia"] == b["dia"] and hora(b["desde"]) < hora(a["hasta"]):
            raise ValueError(f"El {DIAS[a['dia'] - 1]} hay dos franjas que se pisan ({a['desde']}–{a['hasta']} y {b['desde']}–{b['hasta']}).")
    return limpias


def fecha_larga(momento):
    """«lunes 9 de noviembre de 2026»"""
    return f"{DIAS[momento.isoweekday() - 1]} {momento.day} de {MESES[momento.month - 1]} de {momento.year}"
