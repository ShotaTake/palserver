#!/usr/bin/env bash
# Operator-only installation of diagnose/backups/confirmed restore.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/setup/lib.sh
. "$SCRIPT_DIR/lib.sh"
trap on_error ERR
parse_common_args "$@"
[ "${#REMAINING_ARGS[@]}" -eq 0 ] || fail "不明な引数です。"
require_root
need_cmd python3 "Python 3.11 以上が必要です。"
need_cmd visudo "sudo が必要です。"
need_cmd flock "util-linux が必要です。"
need_cmd systemctl "systemd が必要です。"
user_exists valheim || fail "既存の Valheim 導入が必要です。"
user_exists palbotctl || fail "既存の Bot 連携が必要です。"
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 11)' || fail "Python 3.11 以上が必要です。"

for service in valheim-update.service valheim-restore.service; do
  case "$(systemctl show -p ActiveState --value "$service" 2>/dev/null || true)" in
    active|activating|deactivating) fail "更新・復元の完了後に導入してください。" ;;
  esac
done
[ ! -e /var/lib/gameserver-control/restore-block ] || fail "中断した復元を先に確認してください。"

# Fail closed for nonstandard world layouts. The worker and systemd write
# allowlist must be adjusted together by the owner for custom installations.
VALHEIM_WORLD_DIR=/home/valheim/.config/unity3d/IronGate/Valheim/worlds_local
GAMESERVER_BACKUP_DIR=/var/lib/gameserver-backups
VALHEIM_SERVICE=valheim-server.service
if [ -e /etc/gameserver-control/control.env ]; then
  [ "$(stat -c %u /etc/gameserver-control/control.env)" = 0 ] || fail "control.env は root 所有が必要です。"
  if find /etc/gameserver-control/control.env -maxdepth 0 -perm /022 | grep -q .; then
    fail "control.env の書き込み権限を確認してください。"
  fi
  # shellcheck source=/dev/null
  . /etc/gameserver-control/control.env
fi
[ "$VALHEIM_WORLD_DIR" = /home/valheim/.config/unity3d/IronGate/Valheim/worlds_local ] || fail "独自ワールド配置には個別調整が必要です。"
[ "$GAMESERVER_BACKUP_DIR" = /var/lib/gameserver-backups ] || fail "独自バックアップ配置には個別調整が必要です。"
[ "$VALHEIM_SERVICE" = valheim-server.service ] || fail "独自サービス名には個別調整が必要です。"
[ -d "$VALHEIM_WORLD_DIR" ] || fail "ワールド保存先がありません。"

banner "診断・バックアップ一覧・復元機能を導入"
say "Pi の Bot を停止してから実行してください。ここでは復元は実行しません。"
sudoers_source="$REPO_ROOT/config/sudoers-gameserver-maintenance.example"
visudo -c >/dev/null
visudo -cf "$sudoers_source" >/dev/null
say "/etc/sudoers.d/gameserver-maintenance に追加する内容:"
show_file "$sudoers_source"
confirm "表示した限定権限と保守用サービスを導入しますか？"

for script in valheim-control valheim-control-ssh gameserver-maintenance; do
  backup_file "/usr/local/sbin/$script"
  run install -o root -g root -m 0755 "$REPO_ROOT/scripts/server/$script" "/usr/local/sbin/$script"
done
run install -d -o palbotctl -g palbotctl -m 0750 /var/lib/gameserver-control
run install -d -o palbotctl -g palbotctl -m 0750 /var/lib/gameserver-backups
backup_file /etc/systemd/system/valheim-restore.service
run install -o root -g root -m 0644 "$REPO_ROOT/systemd/valheim-restore.service.example" \
  /etc/systemd/system/valheim-restore.service
backup_file /etc/sudoers.d/gameserver-maintenance
run install -o root -g root -m 0440 "$sudoers_source" /etc/sudoers.d/gameserver-maintenance
run visudo -c
run systemctl daemon-reload
ok "導入完了。Pi の Bot を更新して起動してください。"
