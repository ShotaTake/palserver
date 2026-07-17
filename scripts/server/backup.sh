#!/usr/bin/env bash
set -euo pipefail

# Archive the Palworld save data. Intended to run after the server has stopped
# so the archive is consistent. Prints "backup ok" and exits 0 on success; the
# orchestrator only powers the machine off when this succeeds.
#
# Configuration comes from a root-owned env file, never from arguments.
CONFIG_FILE="${PALWORLD_CONTROL_ENV:-/etc/palworld-control/control.env}"

PALWORLD_SAVE_DIR="/opt/palworld-server/Pal/Saved/SaveGames"
PALWORLD_BACKUP_DIR="/var/lib/palworld-backups"
PALWORLD_BACKUP_KEEP="10"

if [ -e "$CONFIG_FILE" ]; then
  if find "$CONFIG_FILE" -maxdepth 0 -perm /022 | grep -q .; then
    printf '%s\n' 'config file must not be group/world writable' >&2
    exit 77
  fi
  # shellcheck source=/dev/null
  . "$CONFIG_FILE"
fi

if [ ! -d "$PALWORLD_SAVE_DIR" ]; then
  printf '%s\n' 'save directory not found' >&2
  exit 1
fi

mkdir -p "$PALWORLD_BACKUP_DIR"
timestamp="$(date '+%Y%m%d-%H%M%S')"
archive="${PALWORLD_BACKUP_DIR}/palworld-save-${timestamp}.tar.gz"
tmp_archive="${archive}.partial"

# Build into a temp name first so a crash never leaves a truncated archive that
# later looks like a valid backup.
tar -czf "$tmp_archive" -C "$(dirname "$PALWORLD_SAVE_DIR")" "$(basename "$PALWORLD_SAVE_DIR")"
mv "$tmp_archive" "$archive"

# Verify the archive is readable before reporting success.
if ! tar -tzf "$archive" >/dev/null 2>&1; then
  printf '%s\n' 'backup verification failed' >&2
  rm -f "$archive"
  exit 1
fi

# Retention: keep the newest N archives.
if [ "$PALWORLD_BACKUP_KEEP" -gt 0 ] 2>/dev/null; then
  mapfile -t old < <(ls -1t "${PALWORLD_BACKUP_DIR}"/palworld-save-*.tar.gz 2>/dev/null \
    | tail -n +"$((PALWORLD_BACKUP_KEEP + 1))")
  if [ "${#old[@]}" -gt 0 ]; then
    rm -f "${old[@]}"
  fi
fi

printf 'backup ok: %s\n' "$(basename "$archive")"
