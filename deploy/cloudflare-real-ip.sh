#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-/etc/nginx/conf.d/cloudflare-real-ip.conf}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

{
  for url in https://www.cloudflare.com/ips-v4 https://www.cloudflare.com/ips-v6; do
    curl -fsS --max-time 20 "$url" | while read -r cidr; do
      [[ -n "$cidr" ]] && echo "set_real_ip_from $cidr;"
    done
  done
  echo "real_ip_header CF-Connecting-IP;"
  echo "real_ip_recursive on;"
} > "$TMP"

grep -q "^set_real_ip_from" "$TMP" || { echo "Daftar IP Cloudflare kosong, dibatalkan."; exit 1; }

sudo install -m 644 "$TMP" "$TARGET"
sudo nginx -t
sudo systemctl reload nginx
echo "rentang tepercaya: $(grep -c '^set_real_ip_from' "$TARGET")"
