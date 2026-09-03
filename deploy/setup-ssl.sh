#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${DOMAIN:-satu-miliar-pertama-di-2027.biz.id}"
EMAIL="${EMAIL:?EMAIL wajib diisi}"
HOSTS="${HOSTS:-brainxp-api brainxp-s3 brainxp-console}"

ARGS=()
SKIPPED=()
for h in $HOSTS; do
  fqdn="$h.$DOMAIN"
  if getent hosts "$fqdn" >/dev/null 2>&1; then
    ARGS+=(-d "$fqdn")
  else
    SKIPPED+=("$fqdn")
  fi
done

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo "Dilewati karena belum punya DNS:"
  printf '  %s\n' "${SKIPPED[@]}"
fi

if [[ ${#ARGS[@]} -eq 0 ]]; then
  echo "Tidak ada domain yang siap. Tambahkan A record ke IP VPS lalu ulangi."
  exit 1
fi

sudo certbot --nginx --non-interactive --agree-tos --redirect \
  --email "$EMAIL" --expand "${ARGS[@]}"

sudo nginx -t
sudo systemctl reload nginx
echo
sudo certbot certificates 2>/dev/null | grep -E "Certificate Name|Domains|Expiry" | sed 's/^/  /'
