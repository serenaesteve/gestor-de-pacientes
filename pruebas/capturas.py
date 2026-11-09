"""Capturas de Volante en escritorio y móvil, y errores de consola. Uso:
    /root/life-dashboard/.venv/bin/python pruebas/capturas.py http://127.0.0.1:8113 FECHA
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8113"
FECHA = sys.argv[2] if len(sys.argv) > 2 else "2026-11-10"
SALIDA = Path(__file__).with_name("capturas")
SALIDA.mkdir(exist_ok=True)
errores = []

def sesion(p, ancho, alto, nombre, esquema="light"):
    nav = p.chromium.launch()
    ctx = nav.new_context(viewport={"width": ancho, "height": alto}, color_scheme=esquema, device_scale_factor=1)
    pag = ctx.new_page()
    pag.on("console", lambda m: m.type in ("error", "warning") and errores.append(f"{nombre}: {m.text}"))
    pag.on("pageerror", lambda e: errores.append(f"{nombre}: {e}"))
    pag.goto(URL)
    pag.fill("input[name=usuario]", "direccion")
    pag.fill("input[name=contrasena]", "volante-demo")
    pag.click("button[type=submit]")
    pag.wait_for_selector(".membrete h1")
    return nav, pag

def foto(pag, nombre, completa=False):
    pag.wait_for_timeout(500)
    pag.screenshot(path=str(SALIDA / f"{nombre}.png"), full_page=completa)

with sync_playwright() as p:
    nav, pag = sesion(p, 1440, 900, "escritorio")
    pag.goto(f"{URL}/#/libro/{FECHA}"); pag.wait_for_selector(".anotacion")
    foto(pag, "01-libro")
    pag.click(".anotacion--confirmada >> nth=0"); pag.wait_for_selector(".tarjeta-cita")
    foto(pag, "02-tarjeta")
    pag.keyboard.press("Escape")
    pag.click(".hueco >> nth=2"); pag.wait_for_selector("dialog[open]")
    pag.fill("dialog input[type=search]", "gar"); pag.wait_for_timeout(500)
    foto(pag, "03-apuntar")
    pag.click("dialog .impreso__pie [data-cerrar]")
    pag.goto(f"{URL}/#/semana/1/{FECHA}"); pag.wait_for_selector(".anotacion")
    foto(pag, "04-semana")
    pag.goto(f"{URL}/#/fichero"); pag.wait_for_selector(".cajon__ficha")
    pag.click(".cajon__ficha >> nth=3"); pag.wait_for_selector(".ficha")
    foto(pag, "05-fichero")
    pag.goto(f"{URL}/#/medicos"); pag.wait_for_selector(".plantilla")
    foto(pag, "06-medicos", True)
    pag.goto(f"{URL}/#/avisos/bandeja"); pag.wait_for_selector(".bandejas")
    foto(pag, "07-avisos")
    pag.goto(f"{URL}/#/ajustes"); pag.wait_for_selector(".ajustes")
    foto(pag, "08-ajustes", True)
    pag.goto(f"{URL}/#/espera"); pag.wait_for_selector(".lista-espera")
    foto(pag, "16-espera")
    pag.goto(f"{URL}/#/informe/{FECHA[:7]}"); pag.wait_for_selector(".grafico svg")
    pag.hover(".g-dia >> nth=8")
    foto(pag, "17-informe", True)
    pag.goto(f"{URL}/#/libro/{FECHA}"); pag.wait_for_selector(".anotacion")
    pag.click(".anotacion--atendida >> nth=0"); pag.wait_for_selector(".tarjeta-cita")
    foto(pag, "18-tarjeta-atendida")
    nav.close()

    nav, pag = sesion(p, 390, 844, "movil")
    pag.goto(f"{URL}/#/libro/{FECHA}"); pag.wait_for_selector(".anotacion")
    foto(pag, "09-movil-libro")
    pag.click(".columna[data-visible] .anotacion >> nth=0"); pag.wait_for_selector(".tarjeta-cita")
    foto(pag, "10-movil-tarjeta")
    pag.goto(f"{URL}/#/fichero"); pag.wait_for_selector(".cajon__ficha")
    foto(pag, "11-movil-fichero")
    pag.goto(f"{URL}/#/espera"); pag.wait_for_selector(".lista-espera")
    pag.click("[data-mas]")
    foto(pag, "19-movil-espera-mas")
    pag.goto(f"{URL}/#/informe/{FECHA[:7]}"); pag.wait_for_selector(".grafico svg")
    foto(pag, "20-movil-informe", True)
    ancho = pag.evaluate("document.documentElement.scrollWidth")
    if ancho > 390: errores.append(f"movil: scroll horizontal ({ancho}px)")
    nav.close()

    nav, pag = sesion(p, 1440, 900, "oscuro", "dark")
    pag.goto(f"{URL}/#/libro/{FECHA}"); pag.wait_for_selector(".anotacion")
    foto(pag, "12-oscuro")
    nav.close()

    nav = p.chromium.launch(); pag = nav.new_page(viewport={"width": 1440, "height": 900})
    pag.on("pageerror", lambda e: errores.append(f"portada: {e}"))
    pag.goto(URL); pag.wait_for_selector(".portada")
    foto(pag, "13-portada")
    nav.close()

print("\n".join(errores) or "Consola limpia")
