#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || { echo "กรุณารันด้วย sudo: sudo ./install.sh" >&2; exit 1; }
. /etc/os-release 2>/dev/null || true
case "${ID:-}" in ubuntu|debian) ;; *) echo "ตัวติดตั้งอัตโนมัติรองรับ Ubuntu/Debian" >&2; exit 1 ;; esac

SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${SNWEB_INSTALL_DIR:-/opt/sntalkbot-web-manager}"
BIND="${SNWEB_BIND:-127.0.0.1}"
PORT="${SNWEB_PORT:-28765}"
SERVICE_USER="${SNWEB_SERVICE_USER:-sntalkweb}"
DATA_DIR="/var/lib/sntalkbot-web-manager"
ETC_DIR="/etc/sntalkbot-web-manager"
ROOT_BRIDGE="/usr/local/lib/sntalkbot-web-manager/snweb-root"

has(){ command -v "$1" >/dev/null 2>&1; }
echo "SNTalkBot Web Manager installer preflight"
missing=()
has python3 || missing+=(python3)
has git || missing+=(git)
has curl || missing+=(curl)
has sudo || missing+=(sudo)
python3 -m venv --help >/dev/null 2>&1 || missing+=(python3-venv)
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || missing+=(ca-certificates)
if ((${#missing[@]})); then
  echo "Missing packages: ${missing[*]}"
  apt-get update
  apt-get install -y "${missing[@]}"
else
  echo "[OK] python/git/curl/sudo/venv/CA certificates already available; skipping APT dependency install."
fi
if has docker; then echo "[OK] Docker already installed"; else echo "[INFO] Docker not installed yet; Web Manager can install it later through Core Stack preflight."; fi

# Create the service group explicitly. useradd --system does not guarantee a
# same-name private group on every Debian/Ubuntu configuration.
if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
  groupadd --system "$SERVICE_USER"
  echo "Created system group: $SERVICE_USER"
else
  echo "[OK] system group $SERVICE_USER already exists"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_USER" --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "Created system user: $SERVICE_USER"
else
  usermod -g "$SERVICE_USER" "$SERVICE_USER"
  echo "[OK] system user $SERVICE_USER already exists"
fi
# SNTalkBot containers use UID/GID 10001. Join that group so the dashboard can
# read/write config files without running its whole service as root.
data_group="$(getent group 10001 | cut -d: -f1 || true)"
if [[ -z "$data_group" ]]; then
  groupadd -g 10001 sntalkbot-data
  data_group="sntalkbot-data"
fi
usermod -a -G "$data_group" "$SERVICE_USER"

mkdir -p "$TARGET"
if [[ "$SOURCE_DIR" != "$TARGET" ]]; then cp -a "$SOURCE_DIR"/. "$TARGET"/; fi
chown -R root:root "$TARGET"
chmod -R a+rX "$TARGET"
python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/pip" install --upgrade pip
"$TARGET/.venv/bin/pip" install -r "$TARGET/requirements.txt"

install -d -o root -g "$SERVICE_USER" -m 0750 "$ETC_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$DATA_DIR" "$DATA_DIR/jobs"
if [[ ! -s "$ETC_DIR/session_secret" ]]; then
  python3 - <<PY > "$ETC_DIR/session_secret"
import secrets
print(secrets.token_urlsafe(64))
PY
fi
chown root:"$SERVICE_USER" "$ETC_DIR/session_secret"; chmod 0640 "$ETC_DIR/session_secret"

install -d -m 0755 /usr/local/lib/sntalkbot-web-manager
install -o root -g root -m 0755 "$TARGET/webmanager/root_bridge.py" "$ROOT_BRIDGE"
cat > /etc/sudoers.d/sntalkbot-web-manager <<EOF
$SERVICE_USER ALL=(root) NOPASSWD: $ROOT_BRIDGE *
EOF
chmod 0440 /etc/sudoers.d/sntalkbot-web-manager
visudo -cf /etc/sudoers.d/sntalkbot-web-manager >/dev/null

# Make existing helper data readable/editable by the data group while preserving
# UID 10001 ownership expected inside SNTalkBot containers.
BOTS_ROOT="/opt/sntalkbot-bots"
if [[ -r /etc/default/ttuhelper ]]; then
  # shellcheck disable=SC1091
  . /etc/default/ttuhelper
  BOTS_ROOT="${TTU_BOTS_ROOT:-$BOTS_ROOT}"
fi
if [[ -d "$BOTS_ROOT" ]]; then
  chgrp "$data_group" "$BOTS_ROOT" 2>/dev/null || true
  chmod 2770 "$BOTS_ROOT" 2>/dev/null || true
  find "$BOTS_ROOT" -mindepth 1 -maxdepth 1 -type d -exec chgrp "$data_group" {} \; -exec chmod 2770 {} \; 2>/dev/null || true
  find "$BOTS_ROOT" -mindepth 2 -maxdepth 2 -type f \( -name config.ini -o -name limits.conf \) -exec chgrp "$data_group" {} \; -exec chmod 0660 {} \; 2>/dev/null || true
  find "$BOTS_ROOT" -mindepth 2 -maxdepth 2 -type f \( -name instance.conf -o -name runtime_status.json \) -exec chgrp "$data_group" {} \; -exec chmod 0640 {} \; 2>/dev/null || true
fi

ENV_FILE="/etc/default/sntalkbot-web-manager"
write_default(){
  local key="$1" value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    printf '%s="%s"\n' "$key" "$value" >> "$ENV_FILE"
  fi
}
if [[ ! -e "$ENV_FILE" ]]; then
  : > "$ENV_FILE"
  echo "Created $ENV_FILE"
else
  echo "[OK] Keeping existing Web Manager settings; adding only missing defaults."
fi
write_default SNWEB_BIND "$BIND"
write_default SNWEB_PORT "$PORT"
write_default SNWEB_DATA_DIR "$DATA_DIR"
write_default SNWEB_SESSION_SECRET_FILE "$ETC_DIR/session_secret"
write_default SNWEB_DB_FILE "$DATA_DIR/webmanager.db"
write_default SNWEB_ROOT_BRIDGE "$ROOT_BRIDGE"
write_default SNWEB_COOKIE_SECURE "false"
write_default SNWEB_FORWARDED_ALLOW_IPS "127.0.0.1"
write_default SNWEB_TTU_SOURCE "/opt/ttuhelper"
write_default SNWEB_INSTALL_DIR "$TARGET"
write_default SNWEB_TTU_REPO "https://github.com/nuttawat-arch/ttuhelper.git"
write_default SNWEB_WEB_REPO "https://github.com/nuttawat-arch/sntalkbot-web-manager.git"
# Read the effective persisted bind/port for the final status message.
# shellcheck disable=SC1091
. "$ENV_FILE"
BIND="${SNWEB_BIND:-$BIND}"
PORT="${SNWEB_PORT:-$PORT}"

chown root:"$SERVICE_USER" /etc/default/sntalkbot-web-manager; chmod 0640 /etc/default/sntalkbot-web-manager

cat > /etc/systemd/system/sntalkbot-web-manager.service <<EOF
[Unit]
Description=SNTalkBot Web Manager
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
SupplementaryGroups=$data_group
WorkingDirectory=$TARGET
EnvironmentFile=-/etc/default/sntalkbot-web-manager
ExecStart=$TARGET/.venv/bin/python -m webmanager
Restart=on-failure
RestartSec=3
UMask=0027
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable sntalkbot-web-manager >/dev/null

EXPECTED_VERSION="$(tr -d '\r\n' < "$TARGET/VERSION")"
health_host="$BIND"
case "$health_host" in
  0.0.0.0|::|\[::\]|"") health_host="127.0.0.1" ;;
esac
health_url="http://${health_host}:${PORT}/healthz"

if [[ "${SNWEB_DEFER_RESTART:-0}" == "1" ]]; then
  # Self-update is invoked by the running Web Manager itself.  Restarting here
  # would kill the caller before the job can report success, so root_bridge.py
  # schedules the restart from a separate transient systemd unit after exit.
  echo "[INFO] Web Manager restart deferred to the self-update controller."
  if ! systemctl is-active --quiet sntalkbot-web-manager; then
    systemctl start sntalkbot-web-manager
  fi
else
  # Manual/ZIP/bootstrap upgrades must reload the new source immediately.
  # `enable --now` alone does not restart an already-active service.
  systemctl restart sntalkbot-web-manager
  ok=0
  health=""
  for _ in {1..20}; do
    if systemctl is-active --quiet sntalkbot-web-manager; then
      health="$(curl -fsS "$health_url" 2>/dev/null || true)"
      if [[ "$health" == *"\"version\":\"${EXPECTED_VERSION}\""* || "$health" == *"\"version\": \"${EXPECTED_VERSION}\""* ]]; then
        ok=1
        break
      fi
    fi
    sleep 0.5
  done
  if (( ! ok )); then
    echo "[FAIL] Web Manager did not come back on $health_url with expected version $EXPECTED_VERSION." >&2
    [[ -n "$health" ]] && echo "Last health response: $health" >&2
    systemctl --no-pager --full status sntalkbot-web-manager >&2 || true
    journalctl -u sntalkbot-web-manager -n 40 --no-pager >&2 || true
    exit 1
  fi
  echo "[OK] Web Manager restarted and health reports version $EXPECTED_VERSION."
fi

systemctl --no-pager --full status sntalkbot-web-manager | sed -n '1,18p' || true

echo
echo "ติดตั้ง Web Manager เสร็จแล้ว"
echo "ครั้งแรก: เปิด http://127.0.0.1:$PORT/ ผ่าน reverse proxy แล้วสร้าง Super Admin บนหน้า Setup"
echo "CloudPanel: สร้าง Reverse Proxy Site -> http://127.0.0.1:$PORT"
echo "หลังเปิด HTTPS ให้แก้ SNWEB_COOKIE_SECURE=\"true\" ใน /etc/default/sntalkbot-web-manager แล้ว restart service"
