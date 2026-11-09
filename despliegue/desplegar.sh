#!/bin/bash
# Publica (o actualiza) Volante en gestorpacientes.serenaesteve.com. Se puede lanzar las veces que haga falta;
# nunca toca los datos (están en el SBD de producción, base «gestorpacientes»).
#   sudo bash despliegue/desplegar.sh
# La primera vez, antes: sudo bash despliegue/integrar-sbd.sh
set -euo pipefail

DOMINIO=gestorpacientes.serenaesteve.com
IP_SERVIDOR=82.165.244.40
PUERTO=8103
ORIGEN=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DIR=$ORIGEN/despliegue

[ -f /srv/volante/datos/sbd.json ] || { echo "✕ falta conectar con SBD: sudo bash despliegue/integrar-sbd.sh" >&2; exit 1; }

# 1. El código: de root y solo lectura para el servicio
install -d -o root -g volante -m 750 /srv/volante/app
rsync -a --delete --chown=root:volante --chmod=D750,F640 --exclude __pycache__ \
  "$ORIGEN/servidor.py" "$ORIGEN/api" "$ORIGEN/sbd" "$ORIGEN/web" /srv/volante/app/

# 2. El servicio (aplica las migraciones al arrancar)
install -m 644 "$DIR/volante.service" /etc/systemd/system/volante.service
systemctl daemon-reload
systemctl enable volante.service >/dev/null 2>&1
systemctl restart volante.service
sleep 2
systemctl is-active volante.service
echo "Servicio: $(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:$PUERTO/api/estado) en /api/estado"

# 3. Apache en el 80 (redirección y Let's Encrypt)
install -m 644 "$DIR/volante.conf" /etc/apache2/sites-available/volante.conf
a2ensite -q volante.conf

IP_DOMINIO=$(dig +short A "$DOMINIO" @1.1.1.1 | tail -1)
IPV6_DOMINIO=$(dig +short AAAA "$DOMINIO" @1.1.1.1 | tail -1)
if [ "$IP_DOMINIO" != "$IP_SERVIDOR" ] || [ -n "$IPV6_DOMINIO" ]; then
  apache2ctl -t 2>&1 | tail -1 && systemctl reload apache2
  echo "FALTA EL DNS: $DOMINIO apunta a ${IP_DOMINIO:-nada}${IPV6_DOMINIO:+ y a la IPv6 $IPV6_DOMINIO}; tiene que ser un A con $IP_SERVIDOR y sin AAAA."
  exit 0
fi
apache2ctl -t 2>&1 | tail -1
systemctl reload apache2
if [ ! -e "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
  certbot certonly --webroot -w /var/www/acme -d "$DOMINIO" --non-interactive --keep-until-expiring --deploy-hook "systemctl reload apache2"
fi

# 4. HTTPS
install -m 644 "$DIR/volante-ssl.conf" /etc/apache2/sites-available/volante-ssl.conf
a2ensite -q volante-ssl.conf
apache2ctl -t 2>&1 | tail -1
systemctl reload apache2
sleep 1
echo "Publicado: https://$DOMINIO → $(curl -s -o /dev/null -m 10 --resolve "$DOMINIO:443:$IP_SERVIDOR" -w '%{http_code}' "https://$DOMINIO/")"
