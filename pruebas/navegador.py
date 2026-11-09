"""Prueba de punta a punta en Chromium, con su propio servidor y datos de ejemplo en una carpeta temporal.

  1. apuntar una serie semanal para una paciente nueva
  2. moverla arrastrando a otro médico
  3. sala de espera: llega, pasa, atendido, justificante
  4. lista de espera: anular una cita ofrece el hueco; la paciente lo acepta desde su enlace
  5. la paciente pide otra cita desde su enlace
  6. el informe del mes se dibuja
  7. una cuenta nueva crea su centro, no ve los demás y lo borra

    /root/life-dashboard/.venv/bin/python pruebas/navegador.py
"""
import os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

RAIZ = Path(__file__).resolve().parent.parent
CAPTURAS = RAIZ / "pruebas/capturas"
CAPTURAS.mkdir(exist_ok=True)
s = socket.socket(); s.bind(("127.0.0.1", 0)); PUERTO = s.getsockname()[1]; s.close()
URL = f"http://127.0.0.1:{PUERTO}"
hoy = date.today()
DIA = hoy + timedelta(days=(1 - hoy.weekday()) % 7 + 7)          # el martes de la semana que viene
datos = tempfile.mkdtemp(prefix="volante-nav-")
env = {**os.environ, "VOLANTE_ITERACIONES": "1000", "VOLANTE_SILENCIO": "1", "VOLANTE_RELOJ": f"{DIA} 08:30"}
proc = subprocess.Popen([sys.executable, str(RAIZ / "servidor.py"), "--datos", datos, "--puerto", str(PUERTO), "--demo", "--sin-copias"],
                        env=env, stdout=subprocess.DEVNULL)
errores, impresiones = [], []
paso = lambda texto: print(f"  ✓ {texto}", flush=True)

try:
    for _ in range(60):
        try: urllib.request.urlopen(URL + "/api/estado"); break
        except OSError: time.sleep(0.2)
    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1440, "height": 1300})
        ctx.add_init_script("window.print = () => {};")   # el diálogo de imprimir no existe sin pantalla
        pag = ctx.new_page()
        pag.on("pageerror", lambda e: errores.append(str(e)))
        pag.on("console", lambda m: m.type == "error" and errores.append(m.text))
        pag.goto(URL)
        pag.fill("[name=usuario]", "recepcion"); pag.fill("[name=contrasena]", "volante-demo")
        pag.click("button[type=submit]")
        pag.wait_for_selector(".membrete h1")
        pag.goto(f"{URL}/#/libro/{DIA}")
        pag.wait_for_selector(".columna")

        # 1. Serie semanal para una paciente nueva, en el primer hueco libre de la primera columna
        hueco = pag.locator(".columna >> nth=0").locator(".hueco").first
        hora = hueco.get_attribute("data-hueco")
        hueco.click()
        pag.fill("dialog input[type=search]", "Prueba, Nadia")
        pag.click("dialog [data-nuevo]")
        pag.fill("dialog [name=p_telefono]", "699 000 111")
        pag.fill("dialog [name=p_email]", "nadia@example.com")
        pag.select_option("dialog [name=repetir]", "semana")
        pag.fill("dialog [name=veces]", "3")
        pag.click("dialog button[type=submit]")
        pag.wait_for_selector("dialog .renglones--serie")
        pag.click("dialog [data-si]")
        pag.wait_for_selector("dialog[open]", state="detached")
        anot = pag.locator(".anotacion", has_text="Prueba, Nadia")
        expect(anot).to_have_count(1)
        expect(anot.locator(".anotacion__serie")).to_have_text("1/3")
        paso(f"serie de 3 citas apuntada ({hora})")

        # 2. Arrastrarla a un hueco del segundo médico
        destino = pag.locator(".columna >> nth=1").locator(".hueco").first
        hora2 = destino.get_attribute("data-hueco")
        anot.drag_to(destino)
        expect(pag.locator(".nota", has_text="→")).to_have_count(1)
        expect(pag.locator(".columna >> nth=1").locator(".anotacion", has_text="Prueba, Nadia")).to_have_count(1)
        paso(f"arrastrada a otro médico ({hora2})")

        # 3. Sala de espera: llega, pasa, atendido y justificante
        pag.locator(".anotacion", has_text="Prueba, Nadia").click()
        pag.click(".tarjeta-cita [data-sala=llega]")
        expect(pag.locator(".sala", has_text="Prueba, Nadia")).to_have_count(1)
        pag.screenshot(path=str(CAPTURAS / "21-sala.png"))
        pag.locator(".sala li", has_text="Prueba, Nadia").locator("[data-rapido=pasa]").click()
        expect(pag.locator(".sala li.dentro", has_text="Prueba, Nadia")).to_have_count(1)
        pag.locator(".sala li", has_text="Prueba, Nadia").locator("[data-rapido=atendida]").click()
        expect(pag.locator(".anotacion--atendida", has_text="Prueba, Nadia")).to_have_count(1)
        pag.locator(".anotacion", has_text="Prueba, Nadia").click()
        pag.click(".tarjeta-cita [data-justificante]")
        expect(pag.locator(".impresion__justificante")).to_contain_text("Nadia Prueba")
        codigo = pag.locator(".impresion__codigo .mono").nth(1).inner_text()
        paso("sala de espera y justificante")
        pag.keyboard.press("Escape")

        # 4. Lista de espera: Nadia se apunta con el primer médico; se anula una cita suya de la tarde
        pag.goto(f"{URL}/#/espera")
        pag.click("[data-apuntar]")
        pag.fill("dialog input[type=search]", "Prueba")
        pag.click("dialog .buscador__lista button")
        pag.click("dialog button[type=submit]")
        expect(pag.locator(".lista-espera__fila", has_text="Prueba, Nadia")).to_have_count(1)
        pag.goto(f"{URL}/#/libro/{DIA}")
        pag.wait_for_selector(".columna")
        primera = pag.locator(".columna >> nth=0")
        candidata = primera.locator(".anotacion--movible:not(.anotacion--anulada)").last
        candidata.click()
        pag.click(".tarjeta-cita [data-anular]")
        pag.click("dialog [data-si]")
        expect(pag.locator(".nota", has_text="lista de espera")).to_have_count(1)
        # El aviso lo reparte el planificador en su hilo, un instante después: se recarga la bandeja hasta verlo.
        tarjeta = pag.locator(".tarjetita", has_text="Hueco de la lista de espera")
        for _ in range(20):
            pag.goto(f"{URL}/#/libro/{DIA}"); pag.goto(f"{URL}/#/avisos/bandeja"); pag.wait_for_selector(".bandejas")
            if tarjeta.count():
                break
            pag.wait_for_timeout(500)
        expect(tarjeta).to_have_count(1)
        enlace = re.search(r"http://\S+/o/\d+/[\w-]+", tarjeta.locator(".tarjetita__texto").inner_text()).group(0)
        pac = ctx.new_page()
        pac.set_viewport_size({"width": 390, "height": 844})
        pac.on("pageerror", lambda e: errores.append("paciente: " + str(e)))
        pac.goto(enlace)
        expect(pac.locator("[data-accion=aceptar]")).to_have_count(1)
        pac.screenshot(path=str(CAPTURAS / "22-oferta.png"))
        pac.click("[data-accion=aceptar]")
        expect(pac.locator(".carton__sello")).to_have_text("Reservada")
        paso("hueco de la lista de espera ofrecido y aceptado")

        # 5. Desde su cita, pide otra
        pac.click("text=Ver mi cita")
        pac.wait_for_selector("[data-otra]")
        pac.click("[data-otra]")
        pac.wait_for_selector(".carton__dias button")
        pac.locator(".carton__dias button").nth(1).click()
        pac.locator(".carton__pedir .horas-libres button").first.click()
        pac.screenshot(path=str(CAPTURAS / "23-pedir-cita.png"), full_page=True)
        pac.click("[data-reservar]")
        pac.wait_for_url(re.compile(r"/c/\d+/"))
        expect(pac.locator(".carton__hora")).to_be_visible()
        paso("otra cita pedida desde el enlace")

        # 6. Verificar el justificante y abrir el informe (como dirección)
        pac.goto(f"{URL}/")
        dire = nav.new_context(viewport={"width": 1280, "height": 900}).new_page()
        dire.on("pageerror", lambda e: errores.append("dirección: " + str(e)))
        dire.goto(URL)
        dire.fill("[name=usuario]", "direccion"); dire.fill("[name=contrasena]", "volante-demo")
        dire.click("button[type=submit]"); dire.wait_for_selector(".membrete h1")
        dire.goto(f"{URL}/#/informe/{DIA.isoformat()[:7]}")
        dire.wait_for_selector(".grafico svg .g-dia")
        dire.locator(".g-dia").nth(DIA.day - 1).hover()
        expect(dire.locator(".grafico__globo")).to_be_visible()
        dire.screenshot(path=str(CAPTURAS / "24-informe-globo.png"))
        paso(f"informe con su globo (justificante {codigo})")
        # 7. Cuenta nueva desde la portada: su propio centro, con datos de ejemplo, y luego lo borra
        nueva = nav.new_context(viewport={"width": 390, "height": 844}).new_page()
        nueva.on("pageerror", lambda e: errores.append("registro: " + str(e)))
        nueva.on("console", lambda m: m.type == "error" and errores.append("registro: " + m.text))
        nueva.goto(URL)
        nueva.click("[data-modo=registro]")
        nueva.fill("[name=centro]", "Consulta Prueba Norte"); nueva.fill("[name=nombre]", "Lola Norte")
        nueva.fill("[name=usuario]", "lola.norte"); nueva.fill("[name=contrasena]", "una clave bastante larga")
        nueva.check("[name=ejemplo]")
        nueva.screenshot(path=str(CAPTURAS / "25-registro.png"), full_page=True)
        nueva.click("button[type=submit]")
        nueva.wait_for_selector(".anotacion, .vacio", timeout=60000)
        nueva.goto(f"{URL}/#/fichero"); nueva.wait_for_selector(".cajon__ficha")
        assert "Prueba, Nadia" not in nueva.content(), "el centro nuevo ve pacientes de otro"
        nueva.goto(f"{URL}/#/ajustes"); nueva.wait_for_selector("[data-baja]")
        expect(nueva.locator("[name=centro]")).to_have_value("Consulta Prueba Norte")
        nueva.fill("[data-baja] [name=contrasena]", "una clave bastante larga")
        nueva.click("[data-baja] button[type=submit]")
        nueva.click("dialog [data-si]")
        nueva.wait_for_selector(".portada")
        paso("cuenta nueva con su centro, sin ver otros, y borrada")
        nav.close()
    if errores:
        print("Errores de consola:", *errores, sep="\n  "); sys.exit(1)
    print("Punta a punta: bien")
finally:
    proc.terminate(); proc.wait()
    shutil.rmtree(datos, ignore_errors=True)
