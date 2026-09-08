#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${SPEC_DIR:-/var/www/brainxp-spec}"

cd "$ROOT"

if python3 -c "import fastapi" >/dev/null 2>&1 && [[ -d app ]]; then
  if ! python3 scripts/gen_openapi.py --check >/dev/null 2>&1; then
    echo "Spesifikasi basi. Jalankan: python scripts/gen_openapi.py"
    exit 1
  fi
else
  echo "Dependensi aplikasi tidak ada di sini, memakai openapi.json apa adanya."
  echo "Kesegarannya dijaga CI lewat tests/test_openapi_current.py."
fi

[[ -f openapi.json ]] || { echo "openapi.json tidak ada."; exit 1; }

sudo install -d -m 755 "$TARGET"
sudo install -m 644 openapi.json "$TARGET/openapi.json"
sudo rm -f "$TARGET/API.md"
sudo install -m 644 deploy/spec/index.html "$TARGET/index.html"
sudo install -m 644 deploy/spec/favicon.svg "$TARGET/favicon.svg"

VERSION="$(python3 -c 'import json;print(json.load(open("openapi.json"))["info"]["version"])' 2>/dev/null || echo "0")"
PATHS="$(python3 -c 'import json;print(len(json.load(open("openapi.json"))["paths"]))' 2>/dev/null || echo "0")"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo "-")"
printf '{"version":"%s","paths":%s,"commit":"%s","published_at":"%s"}\n' \
  "$VERSION" "$PATHS" "$COMMIT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  | sudo tee "$TARGET/version.json" >/dev/null
sudo chmod 644 "$TARGET/version.json"

echo "Spesifikasi terbit: versi $VERSION, $PATHS path, commit $COMMIT"
