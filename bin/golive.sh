#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "usage: $0 <domain>   e.g. $0 kaidofleet.com" >&2
  exit 1
fi
DOMAIN="$1"
IP=$(curl -s -m 10 https://api.ipify.org)

RESOLVED=$(dig +short A "$DOMAIN" | tail -1)
if [ -z "$RESOLVED" ]; then
  echo "DNS: $DOMAIN does not resolve yet. Add an A record pointing to $IP, then run this again." >&2
  exit 1
fi
if [ "$RESOLVED" != "$IP" ]; then
  echo "DNS: $DOMAIN resolves to $RESOLVED but this server is $IP. Fix the A record, then run this again." >&2
  exit 1
fi
echo "DNS ok: $DOMAIN -> $IP"

if grep -q "^$DOMAIN {" /etc/caddy/Caddyfile 2>/dev/null; then
  echo "Caddy: block for $DOMAIN already present, leaving it alone"
else
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%Y%m%d-%H%M%S)"
  cat >> /etc/caddy/Caddyfile <<CADDY

$DOMAIN {
	reverse_proxy 127.0.0.1:8790
	encode gzip
	log {
		output file /var/log/caddy/kaido-access.log {
			roll_size 10mb
			roll_keep 10
		}
		format json
	}
}
CADDY
  echo "Caddy: added block for $DOMAIN"
fi

sed -i \
  -e "s|^APP_ENV=.*|APP_ENV=production|" \
  -e "s|^APP_URL=.*|APP_URL=https://$DOMAIN|" \
  -e "s|^BEHIND_PROXY=.*|BEHIND_PROXY=true|" \
  .env
echo "Config: production mode, APP_URL=https://$DOMAIN, trusting the proxy"

caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && echo "Caddy: config valid"

LOGFILE="/var/log/caddy/kaido-access.log"
if [ ! -f "$LOGFILE" ]; then
  CADDY_USER=$(ps -o user= -p "$(pgrep -f 'caddy run' | head -1)" 2>/dev/null || echo caddy)
  touch "$LOGFILE" && chown "$CADDY_USER":"$CADDY_USER" "$LOGFILE"
  echo "Caddy: created $LOGFILE owned by $CADDY_USER"
fi

if ! systemctl reload caddy; then
  echo "Caddy: reload failed — the old config is still serving. See journalctl -u caddy" >&2
  echo "Kaido: restarting anyway so app config matches .env" >&2
fi
systemctl restart kaido
sleep 3

systemctl is-active --quiet kaido && echo "Kaido: running" || { echo "Kaido: FAILED, see journalctl -u kaido" >&2; exit 1; }
CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 25 "https://$DOMAIN/login" || true)
echo "https://$DOMAIN/login -> $CODE"
if [ "$CODE" = "200" ]; then
  echo
  echo "Live at https://$DOMAIN"
  echo "Note: production mode means a user with no linked Telegram cannot sign in from a new device."
else
  echo "Certificate may still be issuing. Wait a minute and retry; journalctl -u caddy shows progress." >&2
fi
