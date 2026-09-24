#!/usr/bin/env bash
# Add Discord update support to an existing standard Valheim installation.
# Run by the operator, never by the bot. Does not start/stop the game.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/setup/lib.sh
. "$SCRIPT_DIR/lib.sh"
trap on_error ERR
parse_common_args "$@"
[ "${#REMAINING_ARGS[@]}" -eq 0 ] || fail "不明な引数です。"
require_root
need_cmd visudo "sudo を導入してください。"
need_cmd flock "util-linux を導入してください。"
need_cmd systemctl "systemd が必要です。"
user_exists palbotctl || fail "先に既存の Bot 連携を導入してください。"
user_exists valheim || fail "valheim ユーザーがありません。"
[ -x /usr/games/steamcmd ] || fail "SteamCMD が /usr/games/steamcmd にありません。"
[ -d /opt/valheim-server ] || fail "Valheim が /opt/valheim-server にありません。"
case "$(systemctl show -p ActiveState --value valheim-update.service 2>/dev/null || true)" in
  active|activating|deactivating) fail "更新が進行中です。完了後に導入してください。" ;;
esac

banner "Discord の /server update を導入"
say "Pi 側の Bot を停止してから実行してください。ゲームの起動・停止・更新は行いません。"
say "標準構成（palbotctl / valheim / /opt/valheim-server）用です。"
sudoers_source="$REPO_ROOT/config/sudoers-gameserver-update.example"
visudo -c >/dev/null || fail "現在の sudoers にエラーがあります。"
visudo -cf "$sudoers_source" >/dev/null || fail "追加 sudoers の文法エラーです。"
say "/etc/sudoers.d/gameserver-update に追加する内容:"
show_file "$sudoers_source"
confirm "表示した限定権限と更新用ファイルを導入しますか？"

for script in valheim-control valheim-control-ssh valheim-steam-update; do
  backup_file "/usr/local/sbin/$script"
  run install -o root -g root -m 0755 "$REPO_ROOT/scripts/server/$script" "/usr/local/sbin/$script"
done
run install -d -o palbotctl -g palbotctl -m 0750 /var/lib/gameserver-control
backup_file /etc/systemd/system/valheim-update.service
run install -o root -g root -m 0644 "$REPO_ROOT/systemd/valheim-update.service.example" \
  /etc/systemd/system/valheim-update.service
backup_file /etc/sudoers.d/gameserver-update
run install -o root -g root -m 0440 "$sudoers_source" /etc/sudoers.d/gameserver-update
run visudo -c
run systemctl daemon-reload
ok "導入完了。Pi 側の Bot を更新して起動してください。"
