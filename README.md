# Volante · libro de citas

**Publicado en https://gestorpacientes.serenaesteve.com**, con los datos en el SBD de producción (base `gestorpacientes`).

Gestión de una consulta médica: **pacientes, médicos, horarios, citas y recordatorios automáticos**, con lista de espera, sala de espera e informe del mes. La interfaz es el libro de citas de recepción: una hoja pautada por día con una columna por médico, huecos libres en los que se apunta con un clic y sellos de goma para cada estado (*confirmada*, *atendido*, *no acudió*). Los datos se guardan en **SBD**, con su lenguaje en español.

Solo usa Python 3.11 o superior y su biblioteca estándar. No hay dependencias.

```bash
python3 servidor.py --demo          # http://127.0.0.1:8103 con datos de ejemplo inventados
python3 servidor.py                 # base vacía: la web pide crear la cuenta de dirección
python3 -m unittest discover -s pruebas -t .     # 92 pruebas (algunas contra un SBD temporal, nunca el de producción)
```

Con `--demo` se crean las cuentas `direccion`, `recepcion` e `ividal` (una médica). Todas tienen la contraseña `volante-demo`. Los datos de ejemplo son inventados y los correos usan `@example.com`, un dominio reservado que no entrega a nadie.

## Estilo

Tema **gota** (`web/css/gota.css`, encima de `volante.css`), sacado del estilo del portafolio y de la librería gota:
- **Fondo y formas:** degradado pastel de rosa, melocotón, lila y menta. Las piezas son de cristal redondeado con el brillo de una gota.
- **Letras:** Playfair Display para los títulos, DM Sans para el texto y DM Mono para las horas, servidas desde `web/fuentes`.
- **Citas y estados:** cada cita es una pastilla del color de su médico (mezclado en OKLab para que el azul no vire a lila) y los estados son burbujas.
- **Navegación:** una cápsula donde la pestaña activa es una gota rosa que se desliza y se estira.
- **Modo oscuro:** ciruela con cristal.
- **Gráfico del informe:** azul, melocotón y rosa lila, una paleta validada para daltonismo y contraste.

## Cuentas y centros

En la pantalla de entrada, **«Crear cuenta nueva»** abre un centro propio: quien se registra queda como dirección de un centro vacío, o con médicos, pacientes y citas de ejemplo (inventados) si marca la casilla. Después da cuenta a su equipo (recepción y médicos) desde Ajustes → Equipo. `https://…/#/registro` abre el alta directamente.

- **Nadie ve lo de otro centro.** Cada centro tiene sus propias tablas en la base, con prefijo (`c2_citas`, `c2_pacientes`…). El centro 1, el primero, las tiene sin prefijo. Las órdenes se escriben con el nombre corto y la conexión les pone el prefijo del centro de la petición. Una orden sin centro no se ejecuta, así que un descuido da un error, no datos ajenos. `usuarios`, `sesiones` y `centros` son comunes.
- **Enlaces de pacientes:** llevan el centro (`/c/2/123/firma`) y la firma también lo incluye: la de un centro no abre nada en otro. Los del centro 1 conservan el formato de siempre.
- **Frenos:** como mucho 3 centros nuevos por hora desde la misma dirección y 200 en total (`VOLANTE_MAX_CENTROS`). Los datos de ejemplo de un centro nuevo son más pequeños que los de `--demo`. `--sin-registro` cierra el alta.
- **Baja:** dirección borra su centro entero desde Ajustes, con su contraseña: tablas, cuentas y sesiones. El centro 1 no se puede borrar desde la web. `privacidad.html` explica qué se guarda.

## Qué hace

| Sección | Para qué |
|---|---|
| **Libro** | La hoja del día con una columna por médico. Lo que está fuera de horario aparece tachado a lápiz, cada hueco libre es un renglón punteado («apuntar») y un hilo rojo marca la hora actual. Al pulsar una cita se abre su tarjeta, desde la que se puede confirmar, sellar como atendida o *no acudió*, mover, anular (con «Deshacer»), mandar un aviso al momento o escribir la nota clínica. |
| **Semana** | La semana de un médico. Sábado y domingo salen solo si pasa consulta esos días. |
| **Espera** | La lista de espera, por orden de llegada. Cuando se anula una cita, el hueco se ofrece solo al primero que encaje: mismo médico o cualquiera de su especialidad, y su franja (mañana o tarde). Le llega un aviso con un enlace para quedárselo. Si no contesta en 3 h (se cambia en Ajustes), pasa al siguiente. |
| **Informe** | Solo para dirección. Muestra el mes: ocupación por médico (minutos citados frente a minutos de consulta), faltas, confirmaciones, espera media en sala, anulaciones, avisos por canal, lista de espera y cómo se pidieron las citas. Lleva un gráfico de citas por día y se descarga en CSV (para Excel) o se imprime en PDF. |
| **Fichero** | El cajón de pacientes. Se busca por apellidos, nombre, DNI o teléfono, sin importar las tildes, o por la inicial en el uñero alfabético. La ficha muestra sus datos, las próximas citas, el historial con sellos, los avisos que se le han mandado y cuántas veces ha faltado. |
| **Médicos** | La ficha de cada médico, con el color de su tampón, su plantilla semanal de horario y sus ausencias (vacaciones, congresos). |
| **Avisos** | La bandeja de salida de los recordatorios, con cuatro listas: por mandar, programados, enviados y los que no salieron. |
| **Ajustes** | Los datos del centro, las reglas de los recordatorios con una vista previa del mensaje, el equipo y la contraseña de cada persona. |

**En el libro, además:**
- **Sala de espera:** recepción marca «Ha llegado» y la cita aparece arriba, en la sala, con los minutos que lleva esperando (en rojo a partir de 20). Desde ahí se pulsa «Pasar» y luego «Atendido». El médico solo ve la sala de su consulta.
- **Mover arrastrando:** una cita se arrastra a cualquier hueco libre. En la hoja del día puede cambiar de médico y en la semana, de día. Al paciente se le avisa de la hora nueva y se puede «Deshacer». En el móvil se usa «Mover».
- **Citas que se repiten:** cada semana, cada 2 o 4 semanas o cada mes, de 2 a 26 citas. Antes de apuntarlas, Volante enseña qué fechas caben y cuáles se saltan (por ausencias o choques). El paciente recibe un solo aviso con todas las fechas. Se puede anular «esta y las siguientes».
- **Hoja del día imprimible:** una tabla por médico con la hora, el paciente, el teléfono, el motivo y una casilla «llegó».
- **Justificante de asistencia:** para las citas a las que el paciente vino. Dice la hora de llegada y la de salida, lleva un código y un enlace de verificación (`/v/…`) que solo enseña las iniciales del paciente.

**Manejo rápido:**
- **Índice rápido** (`Ctrl K` o `/`, o el botón «Buscar o ir a…»): busca pacientes, salta a un día dicho como se dice («mañana», «el jueves», «15/11», «3 de diciembre», «+3», «en 2 semanas») o lanza una acción (apuntar cita, lista de espera, paciente nuevo).
- **Atajos:** `N` apunta una cita, `←` `→` pasan de día o de semana, `H` vuelve a hoy, `L` `S` `E` `F` `A` abren secciones y `?` enseña la chuleta. En el móvil se cambia de día deslizando la hoja.
- **Vistazo:** al dejar el ratón sobre una cita aparecen sus datos (teléfono, motivo, notas para recepción y el próximo aviso) sin abrirla.
- **El libro como papel:** la tapa se abre al entrar, la hoja se arranca del taco al cambiar de día y pasa de pestaña al cambiar de sección. Las citas nuevas o movidas se escriben a tinta, el papel se levanta al arrastrarlo, el hilo de «ahora» y los minutos de la sala avanzan solos, y en el informe las cifras cuentan y las barras crecen. Con «reducir movimiento» activado en el sistema, todo funciona igual, sin animaciones.

**El paciente, desde su enlace,** puede además pedir otra cita con su mismo médico. Ve los huecos libres de dos semanas en dos semanas y puede tener dos citas pedidas así a la vez. Se desactiva en Ajustes.

**Apuntar una cita:** primero se busca al paciente (o se da de alta en el mismo impreso). Después se elige médico y día, y se pulsa una de las horas libres o «Primer hueco libre», que busca en los próximos 60 días. Volante impide las citas que chocan con otra del mismo médico. Si la cita cae fuera de horario, en un día de ausencia o cuando el paciente ya tiene otra cita a esa hora, pregunta antes de darla.

**Papeles:**
- **Dirección:** puede hacerlo todo, incluido el equipo y los ajustes.
- **Recepción:** lleva las citas, el fichero, los médicos y los avisos.
- **Médico:** ve todo el libro, sella sus propias citas y escribe sus notas clínicas. Recepción no ve esas notas.

## Recordatorios automáticos

- **Ofertas de la lista de espera:** se mandan por el mismo canal que los recordatorios, con su propio enlace (`/o/…`). Cada tipo de enlace firma distinto: el de una cita no abre una oferta ni un justificante.
- **Cuándo se programan:** al dar una cita. Por defecto, un aviso con el enlace en el momento de darla, otro **48 h antes** y otro **2 h antes**; las horas se cambian en Ajustes. Si la cita se da con poca antelación, el aviso que ya no tocaba queda como «no tocaba».
- **Si la cita cambia:** al moverla, los avisos se rehacen y sale uno nuevo con la hora nueva. Al anularla, los pendientes se cancelan. Si cambian las reglas o el correo del paciente, las citas ya dadas se reprograman.
- **Quién los manda:** un hilo del servidor los reparte cada 30 segundos, y al momento cuando se da o se mueve una cita. El texto se escribe en el momento de enviarlo, con los datos de ese momento.
- **Por correo:** salen solos si hay un servidor SMTP configurado (siguiente apartado). Si el servidor de correo rechaza un aviso, se reintenta a los 5 minutos, y después de 3 fallos queda como fallido.
- **Sin SMTP, y siempre para SMS y WhatsApp:** el aviso llega a la bandeja con el texto ya escrito. Desde ahí se abre WhatsApp, la app de SMS o el correo con un toque, y luego se marca como enviado. No se ha integrado ninguna pasarela de SMS de pago.
- **El enlace del paciente** (`/c/<cita>/<firma>`) va firmado con HMAC. Con él, el paciente ve su cita, la confirma, la anula (el hueco queda libre al momento) o la añade a su calendario con un `.ics`. No enseña más datos de los necesarios.

### Correo

Se configura en `datos/correo.json` (o con variables `VOLANTE_SMTP_HOST`, `_PUERTO`, `_USUARIO`, `_CLAVE`, `_REMITENTE`, `_SEGURIDAD`):

```json
{ "host": "smtp.ejemplo.es", "puerto": 587, "usuario": "citas@ejemplo.es", "clave": "…", "remitente": "citas@ejemplo.es", "seguridad": "starttls" }
```

`seguridad` puede ser `starttls` (el valor por defecto), `ssl` (puerto 465) o `no`.

## Cómo está hecho

```
servidor.py           HTTP (biblioteca estándar), sesiones, permisos y rutas de la API
api/agenda.py         franjas, huecos libres, choques y fechas en español
api/recordatorios.py  programar, redactar, enviar (SMTP) y firmar el enlace del paciente
api/bd.py             acceso a SBD: local (carpeta) o servidor SBD por su API, con la misma interfaz
api/espera.py         lista de espera: ofrecer el hueco, aceptar, rechazar y caducar
api/informe.py        las cuentas del informe del mes
api/migraciones/      el esquema, escrito en SBD
api/demo.py           datos de ejemplo
sbd/                  copia de SBD
web/                  la interfaz: HTML, CSS y módulos JS, sin librerías
pruebas/              unittest del servidor y prueba de punta a punta en Chromium
```

- **Las horas:** todas van en la hora de la consulta (Europe/Madrid), aunque el servidor esté en UTC. Las calcula Python y SBD las recibe como parámetro.
- **Seguridad:**
  - **Contraseñas:** PBKDF2 con 600 000 iteraciones. Las sesiones duran 12 horas y se guardan como huella SHA-256. La cookie es HttpOnly y SameSite=Strict.
  - **Peticiones:** las que cambian algo llevan una cabecera propia, y la CSP solo permite scripts propios.
  - **Intentos fallidos:** se limitan, pero solo cuentan los que fallan.
  - **Registro de peticiones:** la firma del enlace del paciente no se apunta.
- **Copias:** al arrancar y cada día se hace una copia de la base en `datos/.copias` (se guardan 14 días).
- **Servidor SBD:** si existe `datos/sbd.json` (`{"url", "clave", "base"}`), Volante usa ese servidor por su API en vez de una base local. Las transacciones van en una sesión del servidor. En producción la base es `gestorpacientes`, con un usuario que solo llega a ella (`despliegue/integrar-sbd.sh`, que antes hace una copia de seguridad de SBD). Las copias diarias las hace el propio SBD.
- **Publicado (`--publico`):** la cuenta de dirección ya no se crea desde la web, para que no se la quede el primero que entre. Se crea en el servidor con `python3 servidor.py --datos … --alta-direccion USUARIO`. Para actualizar lo publicado: `sudo bash despliegue/desplegar.sh` desde esta carpeta (no toca los datos).

Pruebas en el navegador (Chromium con Playwright):

```bash
/root/life-dashboard/.venv/bin/python pruebas/navegador.py      # serie, arrastrar, sala, justificante, lista de espera, pedir cita, informe
/root/life-dashboard/.venv/bin/python pruebas/capturas.py URL   # capturas en escritorio, móvil y modo oscuro
```

Para desarrollar: `VOLANTE_RELOJ="2026-11-10 10:30" python3 servidor.py --demo` arranca el servidor a esa hora, para ver la sala de espera un día de consulta.
