#!/bin/bash
# Conecta Volante con el SBD de producción: base «gestorpacientes», un usuario solo para ella y una clave de API.
#   sudo bash despliegue/integrar-sbd.sh
# 1. Copia de seguridad de los datos de SBD (sin parar el servidor: el «sbd» de terminal respeta sus cerrojos).
# 2. Crea la base si no existe y el usuario «gestorpacientes_app» con «puede todo en gestorpacientes»
#    (crea sus tablas, pero no ve las demás bases ni administra el servidor).
# 3. Crea una clave de API y la guarda en /srv/volante/datos/sbd.json (volante:volante 600).
#    La clave no va nunca al repositorio. Si ya existe ese archivo, no hace nada.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "✕ hay que ejecutarlo como root" >&2; exit 1; }
SBD=/srv/sbd/venv/bin/sbd
DATOS=/srv/sbd/datos
ARCHIVO=/srv/volante/datos/sbd.json
BASE=gestorpacientes
USUARIO=gestorpacientes_app
RESPALDO="/root/sbd/respaldos/$(date +%Y%m%d-%H%M%S)-antes-de-integrar-volante"
sbd() { (cd /srv/sbd && sudo -u sbd "$SBD" "$DATOS" -e "$1"); }

if [ -f "$ARCHIVO" ]; then
  echo "✓ Volante ya está conectado a SBD ($ARCHIVO). No se cambia nada."
  exit 0
fi
id volante >/dev/null 2>&1 || useradd --system --home-dir /srv/volante --shell /usr/sbin/nologin volante
install -d -o root -g volante -m 750 /srv/volante
install -d -o volante -g volante -m 700 /srv/volante/datos

echo "· 1/3 copia de seguridad de SBD"
mkdir -p "$RESPALDO" && chmod 700 "$RESPALDO"
cp -a "$DATOS" "$RESPALDO/datos"
echo "  $RESPALDO"

echo "· 2/3 base «$BASE» y usuario «$USUARIO»"
sbd "crear base $BASE si no existe" >/dev/null
if ! sbd 'usuarios' | grep -q "^$USUARIO "; then
  sbd "crear usuario $USUARIO clave \"$(openssl rand -hex 24)\" puede todo en $BASE" >/dev/null
fi

echo "· 3/3 clave de API"
CLAVE=$(sbd "crear clave api para $USUARIO llamada \"Volante · gestorpacientes.serenaesteve.com\"" | grep -o 'sbd_k[^ ]*')
[ -n "$CLAVE" ] || { echo "✕ no se ha podido crear la clave de API" >&2; exit 1; }
umask 077
python3 - "$ARCHIVO" "$CLAVE" "$BASE" <<'PY'
import json, sys
ruta, clave, base = sys.argv[1:]
with open(ruta, "w") as f:
    json.dump({"url": "http://127.0.0.1:8090", "clave": clave, "base": base}, f, indent=2)
PY
chown volante:volante "$ARCHIVO"
chmod 600 "$ARCHIVO"
echo "✓ Volante conectado a la base «$BASE» de SBD."
