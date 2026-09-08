#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/brainxp}"
cd "$APP_DIR"

DC=(docker compose)

[[ -f .env ]] || { echo "$APP_DIR/.env tidak ada. Salin dari .env.example lalu isi."; exit 1; }

echo "==> Membangkitkan rahasia Garage bila belum ada"
if [[ ! -f deploy/garage.toml ]]; then
  RPC_SECRET="$(openssl rand -hex 32)"
  ADMIN_TOKEN="$(openssl rand -base64 32)"
  METRICS_TOKEN="$(openssl rand -base64 32)"
  sed -e "s|__RPC_SECRET__|$RPC_SECRET|" \
      -e "s|__ADMIN_TOKEN__|$ADMIN_TOKEN|" \
      -e "s|__METRICS_TOKEN__|$METRICS_TOKEN|" \
      deploy/garage.toml.tpl > deploy/garage.toml
  chmod 600 deploy/garage.toml
  echo "    deploy/garage.toml dibuat"
else
  echo "    deploy/garage.toml sudah ada, dilewati"
fi

echo "==> Menghidupkan basis data, Redis, dan Garage"
"${DC[@]}" up -d postgres redis garage

echo "==> Menunggu Garage siap"
for i in $(seq 1 30); do
  "${DC[@]}" exec -T garage /garage status &>/dev/null && break
  sleep 2
done

echo "==> Menyusun layout Garage"
NODE_ID="$("${DC[@]}" exec -T garage /garage status | awk '/^[0-9a-f]{16}/ {print $1; exit}')"
if [[ -z "$NODE_ID" ]]; then echo "gagal membaca node id Garage"; "${DC[@]}" logs --tail 40 garage; exit 1; fi

if "${DC[@]}" exec -T garage /garage layout show 2>/dev/null | grep -q "$NODE_ID"; then
  echo "    layout sudah ada, dilewati"
else
  "${DC[@]}" exec -T garage /garage layout assign -z dc1 -c 10G "$NODE_ID"
  "${DC[@]}" exec -T garage /garage layout apply --version 1
fi

echo "==> Membuat bucket dan kunci akses"
BUCKET="$(grep -E '^S3_BUCKET=' .env | cut -d= -f2-)"
BUCKET="${BUCKET:-brainxp-materials}"
"${DC[@]}" exec -T garage /garage bucket create "$BUCKET" 2>/dev/null || echo "    bucket sudah ada"

if "${DC[@]}" exec -T garage /garage key list 2>/dev/null | grep -q brainxp-app; then
  echo "    kunci brainxp-app sudah ada"
  echo
  echo "    Kunci lama tidak dapat ditampilkan ulang. Bila S3_ACCESS_KEY di .env kosong,"
  echo "    hapus kuncinya lalu jalankan ulang skrip ini:"
  echo "      "${DC[@]}" exec garage /garage key delete --yes brainxp-app"
else
  KEYOUT="$("${DC[@]}" exec -T garage /garage key create brainxp-app)"
  echo "$KEYOUT" | sed 's/^/    /'
  KEY_ID="$(echo "$KEYOUT"  | awk '/Key ID/    {print $NF}')"
  KEY_SEC="$(echo "$KEYOUT" | awk '/Secret key/{print $NF}')"
  "${DC[@]}" exec -T garage /garage bucket allow --read --write --owner "$BUCKET" --key brainxp-app

  if [[ -n "$KEY_ID" && -n "$KEY_SEC" ]]; then
    sed -i "s|^S3_ACCESS_KEY=.*|S3_ACCESS_KEY=$KEY_ID|" .env
    sed -i "s|^S3_SECRET_KEY=.*|S3_SECRET_KEY=$KEY_SEC|" .env
    echo "    kredensial S3 ditulis ke .env"
  fi
fi

echo "==> Menerapkan migrasi basis data"
"${DC[@]}" run --rm api python -m app.migrate

echo "==> Menghidupkan seluruh layanan"
"${DC[@]}" up -d

echo
"${DC[@]}" ps
echo
echo "Bootstrap selesai. Cek kesehatan:"
echo "  curl -s localhost:8000/health   (dari dalam VPS)"
