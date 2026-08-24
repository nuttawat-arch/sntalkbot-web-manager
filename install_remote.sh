#!/usr/bin/env bash
set -Eeuo pipefail
[[ "$EUID" -eq 0 ]] || exec sudo -E bash "$0" "$@"
REPO="${SNWEB_WEB_REPO:-https://github.com/nuttawat-arch/sntalkbot-web-manager.git}"
TARGET="${SNWEB_INSTALL_DIR:-/opt/sntalkbot-web-manager}"
KEEP_BACKUPS="${SNWEB_SOURCE_BACKUPS:-3}"
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

STAMP="$(date +%Y%m%d-%H%M%S)"
INCOMING="${TARGET}.incoming-${STAMP}-$$"
BACKUP="${TARGET}.backup-${STAMP}-$$"
FAILED="${TARGET}.failed-${STAMP}-$$"
cleanup(){ rm -rf -- "$INCOMING" 2>/dev/null || true; }
trap cleanup EXIT

# Never update the live tree with git pull. A dirty production checkout, CRLF
# conversion, or stray untracked file must not be able to block an upgrade.
echo "[STAGE] Cloning a clean Web Manager source tree before touching $TARGET"
git clone --depth 1 "$REPO" "$INCOMING"
[[ -d "$INCOMING/.git" && -f "$INCOMING/install.sh" ]] || { echo "Staged Web Manager checkout is incomplete; live source was left untouched." >&2; exit 1; }

had_previous=0
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  had_previous=1
  echo "[BACKUP] Preserving complete previous source: $TARGET -> $BACKUP"
  mv -- "$TARGET" "$BACKUP"
fi
mv -- "$INCOMING" "$TARGET"
trap - EXIT

if bash "$TARGET/install.sh"; then
  :
else
  rc=$?
  echo "[FAIL] New Web Manager installer failed; restoring the previous complete source tree." >&2
  if [[ -e "$TARGET" || -L "$TARGET" ]]; then mv -- "$TARGET" "$FAILED"; fi
  if ((had_previous)) && [[ -e "$BACKUP" || -L "$BACKUP" ]]; then
    mv -- "$BACKUP" "$TARGET"
    bash "$TARGET/install.sh" || true
    # The restored installer can itself be an older release that only used
    # `systemctl enable --now`; force-reload the restored source explicitly.
    systemctl restart sntalkbot-web-manager || true
  fi
  exit "$rc"
fi

# Keep a small rollback history. Persistent DB/session/config are outside TARGET.
if [[ "$KEEP_BACKUPS" =~ ^[0-9]+$ ]]; then
  mapfile -t old_backups < <(find "$(dirname "$TARGET")" -maxdepth 1 -mindepth 1 -name "$(basename "$TARGET").backup-*" -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk '{print $2}')
  for ((i=KEEP_BACKUPS; i<${#old_backups[@]}; i++)); do
    echo "[CLEANUP] Removing old source backup: ${old_backups[$i]}"
    rm -rf -- "${old_backups[$i]}"
  done
fi
