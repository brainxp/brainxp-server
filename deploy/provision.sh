#!/usr/bin/env bash
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-brainxp}"
SSH_PUBKEY="${SSH_PUBKEY:-}"
APP_DIR="/opt/brainxp"

[[ $EUID -eq 0 ]] || { echo "Jalankan sebagai root atau lewat sudo."; exit 1; }

add_key() {
  local user="$1" home="$2" key="$3"
  [[ -n "$key" ]] || return 0
  install -d -m 700 -o "$user" -g "$user" "$home/.ssh"
  touch "$home/.ssh/authorized_keys"
  grep -qxF "$key" "$home/.ssh/authorized_keys" || echo "$key" >> "$home/.ssh/authorized_keys"
  chown "$user:$user" "$home/.ssh/authorized_keys"
  chmod 600 "$home/.ssh/authorized_keys"
}

existing_keys() {
  local home="$1"
  [[ -s "$home/.ssh/authorized_keys" ]] && wc -l < "$home/.ssh/authorized_keys" || echo 0
}

echo "==> Memperbarui paket sistem"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban unattended-upgrades openssl jq

echo "==> Pengguna deploy: $DEPLOY_USER"
if id -u "$DEPLOY_USER" &>/dev/null; then
  echo "    sudah ada, kunci yang terpasang tidak diubah"
else
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
add_key "$DEPLOY_USER" "$DEPLOY_HOME" "$SSH_PUBKEY"
echo "    kunci terpasang: $(existing_keys "$DEPLOY_HOME")"

if [[ "$(existing_keys "$DEPLOY_HOME")" -eq 0 ]]; then
  echo "    TIDAK ADA kunci SSH untuk $DEPLOY_USER. Login password akan dimatikan"
  echo "    dan kamu akan terkunci keluar. Isi SSH_PUBKEY lalu ulangi."
  exit 1
fi

echo "==> Memasang Docker"
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc 2>/dev/null \
    || curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$DEPLOY_USER"
systemctl enable --now docker

echo "==> Menyiapkan direktori aplikasi"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR" "$APP_DIR/deploy" "$APP_DIR/migrations"

echo "==> Firewall"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status verbose | sed 's/^/    /'

echo "==> fail2ban"
cat > /etc/fail2ban/jail.local <<'JAIL'
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 5
backend = systemd

[sshd]
enabled = true
JAIL
systemctl enable --now fail2ban
systemctl restart fail2ban

echo "==> Pengerasan SSH"
echo "    memverifikasi kunci berfungsi sebelum mematikan login password"
rm -f /etc/ssh/sshd_config.d/99-brainxp.conf
cat > /etc/ssh/sshd_config.d/01-brainxp.conf <<'SSHD'
PasswordAuthentication no
PermitRootLogin prohibit-password
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
X11Forwarding no
MaxAuthTries 3
SSHD
if sshd -t; then
  systemctl reload ssh 2>/dev/null || systemctl reload sshd
  EFFECTIVE="$(sshd -T 2>/dev/null | awk '/^passwordauthentication/ {print $2}')"
  if [[ "$EFFECTIVE" == "no" ]]; then
    echo "    login password dimatikan, hanya kunci SSH yang diterima"
  else
    echo "    PERINGATAN: sshd masih melaporkan passwordauthentication=$EFFECTIVE"
    echo "    Ada berkas lain di /etc/ssh/sshd_config.d/ yang dibaca lebih dulu:"
    grep -rln '^PasswordAuthentication' /etc/ssh/sshd_config.d/ | sed 's/^/      /'
    exit 1
  fi
else
  echo "    konfigurasi sshd tidak valid, perubahan TIDAK diterapkan"; exit 1
fi

echo "==> Pembaruan keamanan otomatis"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo
echo "Provisioning selesai."
echo "  pengguna deploy : $DEPLOY_USER"
echo "  direktori       : $APP_DIR"
echo "  docker          : $(docker --version)"
echo
echo "Langkah berikutnya: salin .env ke $APP_DIR/.env lalu jalankan deploy/bootstrap.sh"
