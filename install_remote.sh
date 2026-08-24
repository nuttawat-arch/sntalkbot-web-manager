#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || exec sudo -E bash "$0" "$@"
REPO="${SNWEB_WEB_REPO:-https://github.com/nuttawat-arch/sntalkbot-web-manager.git}"
TARGET="${SNWEB_INSTALL_DIR:-/opt/sntalkbot-web-manager}"
has(){ command -v "$1" >/dev/null 2>&1; }
missing=()
has git || missing+=(git)
[[ -s /etc/ssl/certs/ca-certificates.crt ]] || missing+=(ca-certificates)
if ((${#missing[@]})); then
  echo "[MISSING] ${missing[*]}"
  apt-get update
  apt-get install -y "${missing[@]}"
else
  echo "[OK] git and CA certificates already available; skipping APT install."
fi
if [[ -d "$TARGET/.git" ]]; then
  echo "[GIT] Updating Web Manager source"
  git -C "$TARGET" pull --ff-only
elif [[ -e "$TARGET" ]]; then
  BACKUP="$TARGET.backup-$(date +%Y%m%d-%H%M%S)"
  echo "[BACKUP] $TARGET -> $BACKUP"
  mv "$TARGET" "$BACKUP"
  git clone "$REPO" "$TARGET"
else
  git clone "$REPO" "$TARGET"
fi
exec bash "$TARGET/install.sh"
