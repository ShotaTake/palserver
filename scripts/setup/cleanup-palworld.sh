#!/usr/bin/env bash
# Remove what is left of the Palworld setup, once Valheim is confirmed working.
# Run it on either machine — it only touches what it finds.
#
#   sudo bash scripts/setup/cleanup-palworld.sh --dry-run
#   sudo bash scripts/setup/cleanup-palworld.sh
#
# Save data and backups are never touched. Only the plumbing goes.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/setup/lib.sh
. "$SCRIPT_DIR/lib.sh"

trap on_error ERR

SBIN=/usr/local/sbin
OLD_SCRIPTS=(
  palworld-control
  palworld-control-ssh
  palworld-backup
  palworld-safe-poweroff
)
OLD_CONTROL_DIR=/etc/palworld-control
OLD_UNIT=/etc/systemd/system/palworld-server.service
OLD_BOT_UNIT=/etc/systemd/system/palworld-bot.service
OLD_BOT_ENV_DIR=/etc/palworld-bot
OLD_BOT_USER=palworld-bot
OLD_BOT_HOME=/var/lib/palworld-bot
OLD_REPO_DIR=/opt/palworld-server-ops
OLD_GAME_DIR=/opt/palworld-server
OLD_BACKUP_DIR=/var/lib/palworld-backups

parse_common_args "$@"
set -- "${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"}"
[ $# -eq 0 ] || fail "不明な引数: $1  (--help で使い方)"

banner "Palworld 環境の片付け"

step "事前確認"

require_root

FOUND=()
for s in "${OLD_SCRIPTS[@]}"; do
  if [ -e "$SBIN/$s" ]; then
    FOUND+=("$SBIN/$s")
  fi
done
for p in "$OLD_CONTROL_DIR" "$OLD_BOT_UNIT" "$OLD_BOT_ENV_DIR" "$OLD_REPO_DIR"; do
  if [ -e "$p" ]; then
    FOUND+=("$p")
  fi
done
if user_exists "$OLD_BOT_USER"; then
  FOUND+=("ユーザー $OLD_BOT_USER（ホーム $OLD_BOT_HOME ごと）")
fi

if [ "${#FOUND[@]}" -eq 0 ]; then
  ok "片付けるものはありません。"
  exit 0
fi

say "削除するもの:"
for f in "${FOUND[@]}"; do
  note "$f"
done

say ""
say "削除しないもの:"
note "$OLD_GAME_DIR（ゲーム本体とセーブデータ）"
note "$OLD_BACKUP_DIR（バックアップ）"
note "$OLD_UNIT.bak（退避したユニット。戻すときに使います）"

say ""
warn "先に Valheim が完全に動いていることを確認してください。"
warn "/server status /server stop /server start がすべて通り、ワールドの進行が残ること。"

confirm "上の一覧を削除します。よろしいですか？"

step "削除"

for s in "${OLD_SCRIPTS[@]}"; do
  if [ -e "$SBIN/$s" ]; then
    run rm -f "$SBIN/$s"
  fi
done

if [ -e "$OLD_CONTROL_DIR" ]; then
  run rm -rf "$OLD_CONTROL_DIR"
fi

if [ -e "$OLD_BOT_UNIT" ]; then
  run_ok systemctl disable --now palworld-bot.service
  run rm -f "$OLD_BOT_UNIT"
  run systemctl daemon-reload
fi

if [ -e "$OLD_BOT_ENV_DIR" ]; then
  run rm -rf "$OLD_BOT_ENV_DIR"
fi
if [ -e "$OLD_REPO_DIR" ]; then
  run rm -rf "$OLD_REPO_DIR"
fi

if user_exists "$OLD_BOT_USER"; then
  run_ok userdel -r "$OLD_BOT_USER"
fi

step "完了"

ok "片付けました。"
say ""
say "セーブデータを消してディスクを空けたくなったら、Valheim を数週間運用して"
say "戻す気が無いと確信してから、手で消してください:"
say "  sudo du -sh $OLD_GAME_DIR $OLD_BACKUP_DIR"
say "  sudo rm -rf $OLD_GAME_DIR $OLD_BACKUP_DIR"
say ""
say "ゲーム本体は SteamCMD で入れ直せるので、本当に惜しいのはセーブとバックアップだけです。"
