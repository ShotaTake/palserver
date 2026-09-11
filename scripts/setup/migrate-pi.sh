#!/usr/bin/env bash
# Raspberry Pi: move the Discord bot from the Palworld layout to the
# game-neutral one, reusing the existing token and SSH key.
#
#   sudo bash scripts/setup/migrate-pi.sh --dry-run     # 確認だけ
#   sudo bash scripts/setup/migrate-pi.sh               # 本番
#
# Run migrate-server.sh on the server PC FIRST. The self-check at the end
# expects that machine to already accept the Valheim forced command.
#
# Safe to run repeatedly. The bot token is never printed.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/setup/lib.sh
. "$SCRIPT_DIR/lib.sh"

trap on_error ERR

BOT_USER=gameserver-bot
BOT_HOME=/var/lib/gameserver-bot
REPO_DIR=/opt/gameserver-ops
REPO_URL=https://github.com/ShotaTake/palserver.git
BOT_ENV=/etc/gameserver-bot/bot.env
BOT_SERVICE=gameserver-bot.service
BOT_UNIT=/etc/systemd/system/gameserver-bot.service

OLD_BOT_USER=palworld-bot
OLD_BOT_HOME=/var/lib/palworld-bot
OLD_REPO_DIR=/opt/palworld-server-ops
OLD_BOT_ENV=/etc/palworld-bot/bot.env
OLD_BOT_SERVICE=palworld-bot.service

GAME_PORT=''
usage_extra=' [--game-port N]'
parse_common_args "$@"
set -- "${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"}"
while [ $# -gt 0 ]; do
  case "$1" in
    --game-port)
      GAME_PORT="${2:-}"
      [ -n "$GAME_PORT" ] || fail "--game-port に番号を指定してください。"
      shift 2
      ;;
    *) fail "不明な引数: $1  (--help で使い方)" ;;
  esac
done

banner "ラズパイ: Discord Bot を Valheim 構成へ"

# Value only, first match. Never sources the file, so a stray line in it can
# never run — and we only ever ask for non-secret keys.
read_value() {
  sed -n "s/^$2=//p" "$1" | head -n 1
}

# ---------------------------------------------------------------- 1. preflight

step "事前確認"

require_root
need_cmd systemctl "systemd の無い環境はこのスクリプトの対象外です。"
need_cmd git "sudo apt install -y git"
need_cmd python3 "sudo apt install -y python3"
need_cmd ssh "sudo apt install -y openssh-client"
python3 -c 'import venv' 2> /dev/null || fail "python3-venv がありません: sudo apt install -y python3-venv"

OWNER="${SUDO_USER:-root}"

# Everything under the clone belongs to whoever invoked sudo, so they can
# `git pull` later without it. When the script is run as root outright there
# is nobody to drop to.
as_owner() {
  if [ "$OWNER" = "root" ]; then
    run "$@"
  else
    run sudo -u "$OWNER" "$@"
  fi
}

as_owner_ok() {
  as_owner "$@" || true
}

[ -f "$REPO_ROOT/systemd/gameserver-bot.service.example" ] ||
  fail "systemd/gameserver-bot.service.example が見つかりません。リポジトリの中で実行してください。"

say "検出した状態:"
note "旧 Bot サービス: $(unit_exists "$OLD_BOT_SERVICE" && svc_state is-active "$OLD_BOT_SERVICE" || echo なし)"
note "旧設定 $OLD_BOT_ENV: $([ -e "$OLD_BOT_ENV" ] && echo あり || echo なし)"
note "旧 SSH 鍵 $OLD_BOT_HOME/.ssh: $([ -d "$OLD_BOT_HOME/.ssh" ] && echo あり || echo なし)"
note "新設定 $BOT_ENV: $([ -e "$BOT_ENV" ] && echo 'あり（キーだけ直します）' || echo なし)"
note "clone 先 $REPO_DIR: $([ -d "$REPO_DIR/.git" ] && echo あり || echo なし)"
note "実行ユーザー（clone の所有者にします）: $OWNER"

if [ ! -e "$OLD_BOT_ENV" ] && [ ! -e "$BOT_ENV" ]; then
  fail "設定ファイルが見つかりません。移行元の $OLD_BOT_ENV が必要です。"
fi

say ""
say "これから行うこと:"
say "  1. 旧 Bot を停止して自動起動を切る"
say "  2. $BOT_USER ユーザーと $REPO_DIR を用意する"
say "  3. SSH 鍵と設定を引き継ぐ（トークンは表示しません）"
say "  4. 新しいサービスを起動して、サーバー PC との疎通を確認する"
say ""
say "旧環境は消しません（片付けは cleanup-palworld.sh）。"

confirm "ラズパイの Bot を Valheim 構成に切り替えます。よろしいですか？"

# --------------------------------------------------------------- 2. stop old

step "旧 Bot の停止"

if unit_exists "$OLD_BOT_SERVICE"; then
  run_ok systemctl disable --now "$OLD_BOT_SERVICE"
  ok "旧 Bot を停止しました。"
else
  note "旧 Bot サービスはありません。"
fi

# ------------------------------------------------------------ 3. user + code

step "ユーザーとコードの配置"

if ! user_exists "$BOT_USER"; then
  run useradd -r -m -d "$BOT_HOME" -s /usr/sbin/nologin "$BOT_USER"
else
  note "$BOT_USER ユーザーは既にあります。"
fi
run install -d -o "$BOT_USER" -g "$BOT_USER" -m 0750 "$BOT_HOME"

if [ "$REPO_ROOT" = "$REPO_DIR" ]; then
  note "既に $REPO_DIR で実行しているので clone は不要です。"
  as_owner_ok git -C "$REPO_DIR" pull --ff-only
elif [ -d "$REPO_DIR/.git" ]; then
  as_owner git -C "$REPO_DIR" pull --ff-only
else
  # /opt rather than a home directory: the service runs with ProtectHome=true
  # and would not be able to see its own code under /home.
  run install -d -o "$OWNER" -m 0755 "$REPO_DIR"
  as_owner git clone "$REPO_URL" "$REPO_DIR"
fi

if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  as_owner python3 -m venv "$REPO_DIR/.venv"
fi
as_owner "$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
as_owner "$REPO_DIR/.venv/bin/pip" install --quiet -e "$REPO_DIR"

if ! dry_run && [ ! -x "$REPO_DIR/.venv/bin/gameserver-bot" ]; then
  fail "$REPO_DIR/.venv/bin/gameserver-bot が作られていません。pip の出力を確認してください。"
fi

# --------------------------------------------------------------- 4. ssh keys

step "SSH 鍵の引き継ぎ"

if [ -f "$BOT_HOME/.ssh/id_ed25519" ]; then
  ok "$BOT_HOME/.ssh に鍵が既にあります。"
elif [ -f "$OLD_BOT_HOME/.ssh/id_ed25519" ]; then
  run cp -a "$OLD_BOT_HOME/.ssh" "$BOT_HOME/.ssh"
  run chown -R "$BOT_USER:$BOT_USER" "$BOT_HOME/.ssh"
  ok "旧 Bot の鍵と known_hosts を引き継ぎました。"
else
  warn "引き継げる鍵がありません。新しく作ります。"
  run install -d -o "$BOT_USER" -g "$BOT_USER" -m 0700 "$BOT_HOME/.ssh"
  run sudo -u "$BOT_USER" ssh-keygen -t ed25519 \
    -f "$BOT_HOME/.ssh/id_ed25519" -N '' -C "$BOT_USER@$(hostname)"
  say ""
  say "この公開鍵をサーバー PC に登録してください:"
  if ! dry_run; then
    show_file "$BOT_HOME/.ssh/id_ed25519.pub"
  fi
  say '登録する行（1行）:'
  say '  restrict,command="/usr/local/sbin/valheim-control-ssh" <上の内容>'
  say ""
  fail "鍵の登録が済んだら、このスクリプトをもう一度実行してください。"
fi

KEY_PATH="$BOT_HOME/.ssh/id_ed25519"
KNOWN_HOSTS="$BOT_HOME/.ssh/known_hosts"

# ----------------------------------------------------------------- 5. config

step "設定の引き継ぎ"

if [ -e "$BOT_ENV" ]; then
  note "$BOT_ENV は既にあります。必要なキーだけ直します。"
else
  run install -d -m 0755 /etc/gameserver-bot
  run cp -a "$OLD_BOT_ENV" "$BOT_ENV"
  ok "$OLD_BOT_ENV を引き継ぎました（中身は表示していません）。"
fi
run chown root:root "$BOT_ENV"
run chmod 600 "$BOT_ENV"

# Rewrite one key without ever printing the file: it holds the Discord token.
set_env_key() {
  local key="$1" value="$2"
  printf '%s  → %s=%s%s\n' "$_C_DIM" "$key" "$value" "$_C_OFF"
  if dry_run; then
    return 0
  fi
  if grep -q "^$key=" "$BOT_ENV"; then
    sed -i "s|^$key=.*|$key=$value|" "$BOT_ENV"
  else
    printf '%s=%s\n' "$key" "$value" >> "$BOT_ENV"
  fi
}

# The game port is decided once, in the repository, so both machines agree
# without anyone having to remember a number. GAME_PORT is what /server
# address tells people to connect to.
if [ -z "$GAME_PORT" ]; then
  GAME_PORT="$(read_value "$REPO_ROOT/config/valheim.env.example" VALHEIM_PORT)"
fi
GAME_PORT="${GAME_PORT:-2456}"
case "$GAME_PORT" in '' | *[!0-9]*) fail "ゲームポートが数値ではありません: $GAME_PORT" ;; esac

set_env_key SERVER_SSH_KEY_PATH "$KEY_PATH"
set_env_key SERVER_SSH_KNOWN_HOSTS_PATH "$KNOWN_HOSTS"
set_env_key GAME_PORT "$GAME_PORT"
set_env_key GAME_NAME Valheim

if ! dry_run; then
  SSH_HOST="$(read_value "$BOT_ENV" SERVER_TAILSCALE_HOST)"
  SSH_USER="$(read_value "$BOT_ENV" SERVER_SSH_USER)"
  [ -n "$SSH_HOST" ] || fail "$BOT_ENV に SERVER_TAILSCALE_HOST がありません。"
  [ -n "$SSH_USER" ] || fail "$BOT_ENV に SERVER_SSH_USER がありません。"
  note "接続先: $SSH_USER@$SSH_HOST"
fi

# ------------------------------------------------------------- 6. pal images

step "/取引 の画像"

IMG_DIR=''
if ! dry_run; then
  IMG_DIR="$(read_value "$BOT_ENV" PAL_IMAGE_DIR)"
fi
NEW_IMG_DIR="$REPO_DIR/src/gameserver_bot/assets/pals"
OLD_IMG_DIR="$OLD_REPO_DIR/src/palworld_bot/assets/pals"

if [ -n "$IMG_DIR" ] && [ -d "$IMG_DIR" ]; then
  ok "PAL_IMAGE_DIR=$IMG_DIR をそのまま使います。"
elif [ -d "$OLD_IMG_DIR" ] && [ -n "$(ls -A "$OLD_IMG_DIR" 2>/dev/null | grep -v '^\.gitkeep$' || true)" ]; then
  run install -d -m 0755 "$NEW_IMG_DIR"
  run cp -a "$OLD_IMG_DIR/." "$NEW_IMG_DIR/"
  ok "旧クローンから画像を移しました。"
else
  note "移す画像はありません。/取引 を使うなら $NEW_IMG_DIR に置いてください。"
fi

# ---------------------------------------------------------------- 7. service

step "サービスの設置"

if [ -e "$BOT_UNIT" ]; then
  backup_file "$BOT_UNIT"
fi
run install -m 0644 -o root -g root \
  "$REPO_ROOT/systemd/gameserver-bot.service.example" "$BOT_UNIT"
run systemctl daemon-reload
run systemctl enable "$BOT_SERVICE"
run systemctl restart "$BOT_SERVICE"

if dry_run; then
  skipped "起動確認"
else
  sleep 5
  if ! unit_active "$BOT_SERVICE"; then
    say ""
    journalctl -u "$BOT_SERVICE" -n 40 --no-pager || true
    fail "Bot が起動しませんでした。上のログを送ってください。"
  fi
  ok "$BOT_SERVICE は active です。"
fi

# ------------------------------------------------------------ 8. self checks

step "サーバー PC との疎通確認"

if dry_run; then
  skipped "SSH 疎通確認"
else
  ssh_probe() {
    sudo -u "$BOT_USER" ssh \
      -i "$KEY_PATH" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=yes \
      -o UserKnownHostsFile="$KNOWN_HOSTS" \
      -o ConnectTimeout=10 \
      "$SSH_USER@$SSH_HOST" "$1" 2>&1 || true
  }

  out="$(ssh_probe status)"
  case "$out" in
    *valheim=*) ok "status: $out" ;;
    *"Permission denied"*)
      say "$out"
      fail "鍵が受け付けられていません。サーバー PC 側で sshd -T の authorizedkeysfile と、登録先ファイルを確認してください。"
      ;;
    *)
      say "$out"
      fail "想定外の応答です。サーバー PC 側の migrate-server.sh が済んでいるか確認してください。"
      ;;
  esac

  # The forced command must reject anything outside its allowlist. If this
  # ever succeeds, the bot has more reach than it should.
  out="$(ssh_probe ls)"
  case "$out" in
    *"command denied"*) ok "制限も効いています（ls は command denied）。" ;;
    *)
      say "$out"
      remember_warning "固定コマンド制限が効いていない可能性があります。authorized_keys の restrict,command= を確認してください。"
      ;;
  esac
fi

print_final_warnings

say ""
ok "ラズパイ側は完了です。"
say ""
say "残っている手作業:"
say "  ルーター: UDP $GAME_PORT がサーバー PC へ転送されていることを確認"
say ""
say "Discord で確認してください:"
say "  /server status → Valheim が running"
say "  /server stop → 保存・バックアップ・電源オフ"
say "  /server start → WOL で起動"
say "  もう一度入って、ワールドの進行が残っていること"
say ""
say "全部動いたら、両方のマシンで片付けを実行できます:"
say "  sudo bash scripts/setup/cleanup-palworld.sh"
