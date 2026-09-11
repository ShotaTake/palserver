#!/usr/bin/env bash
# Server PC: retire the Palworld server and bring up Valheim with the control
# scripts the Discord bot talks to.
#
#   sudo bash scripts/setup/migrate-server.sh --dry-run     # 確認だけ
#   sudo bash scripts/setup/migrate-server.sh               # 本番
#
# Run this BEFORE migrate-pi.sh: the Pi's self-check needs the SSH forced
# command on this machine to already point at the Valheim wrapper.
#
# Safe to run repeatedly. Nothing is deleted; anything replaced is backed up.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/setup/lib.sh
. "$SCRIPT_DIR/lib.sh"

trap on_error ERR

VALHEIM_USER=valheim
VALHEIM_DIR=/opt/valheim-server
VALHEIM_ENV=/etc/valheim/valheim.env
VALHEIM_UNIT=/etc/systemd/system/valheim-server.service
VALHEIM_SERVICE=valheim-server.service
CTL_USER=palbotctl
SBIN=/usr/local/sbin
BACKUP_DIR=/var/lib/gameserver-backups
CONTROL_ENV=/etc/gameserver-control/control.env
SUDOERS=/etc/sudoers.d/gameserver-control
OLD_UNIT=/etc/systemd/system/palworld-server.service
OLD_SERVICE=palworld-server.service
OLD_SUDOERS=/etc/sudoers.d/palworld-control
APPID=896660
CONTROL_SCRIPTS=(
  valheim-control
  valheim-control-ssh
  valheim-query
  gameserver-backup
  gameserver-safe-poweroff
)

VALUES_FILE=''
usage_extra=' [--values FILE]'
parse_common_args "$@"
set -- "${REMAINING_ARGS[@]+"${REMAINING_ARGS[@]}"}"
while [ $# -gt 0 ]; do
  case "$1" in
    --values)
      VALUES_FILE="${2:-}"
      [ -n "$VALUES_FILE" ] || fail "--values にファイルを指定してください。"
      shift 2
      ;;
    *) fail "不明な引数: $1  (--help で使い方)" ;;
  esac
done

banner "サーバー PC: Palworld → Valheim 移行"

# ---------------------------------------------------------------- 1. preflight

step "事前確認"

require_root
need_cmd systemctl "systemd の無い環境はこのスクリプトの対象外です。"
need_cmd install "coreutils を入れてください。"

[ "$(uname -m)" = "x86_64" ] || fail "Valheim 専用サーバーは x86-64 のみです（このマシン: $(uname -m)）。"

for s in "${CONTROL_SCRIPTS[@]}"; do
  [ -f "$REPO_ROOT/scripts/server/$s" ] || fail "$REPO_ROOT/scripts/server/$s が見つかりません。リポジトリの中で実行してください。"
done
[ -f "$REPO_ROOT/systemd/valheim-server.service.example" ] ||
  fail "systemd/valheim-server.service.example が見つかりません。"

say "検出した状態:"
if [ -e "$OLD_UNIT" ] || unit_exists "$OLD_SERVICE"; then
  note "Palworld: あり（$(svc_state is-active "$OLD_SERVICE") / $(svc_state is-enabled "$OLD_SERVICE")）"
else
  note "Palworld: なし（退役の手順は飛ばします）"
fi
note "Valheim ユニット: $([ -e "$VALHEIM_UNIT" ] && echo あり || echo なし)"
note "Valheim 設定 $VALHEIM_ENV: $([ -e "$VALHEIM_ENV" ] && echo 'あり（上書きしません）' || echo なし)"
note "$CTL_USER ユーザー: $(user_exists "$CTL_USER" && echo あり || echo なし)"
note "ufw: $(have_cmd ufw && ufw status 2>/dev/null | head -1 || echo なし)"

say ""
say "これから行うこと:"
say "  - Palworld を保存して停止し、二度と自動起動しないよう mask する"
say "  - Valheim を導入する（SteamCMD app $APPID）"
say "  - 制御スクリプト ${#CONTROL_SCRIPTS[@]} 本を $SBIN に置く"
say "  - Valheim を起動して、人数取得が通ることを確認する"
say "  - sudoers と SSH の受け口を更新する（内容を表示して確認します）"
say ""
say "Palworld のセーブデータとバックアップは削除しません。"

confirm "サーバー PC を Valheim 構成に切り替えます。よろしいですか？"

# ------------------------------------------------------- 2. retire Palworld

step "Palworld の退役"

if [ -e "$OLD_UNIT" ] || [ -e "$OLD_UNIT.bak" ] || unit_exists "$OLD_SERVICE"; then
  if unit_active "$OLD_SERVICE"; then
    if [ -x "$SBIN/palworld-control" ] && user_exists "$CTL_USER"; then
      say "REST 経由で保存して停止します。"
      run_ok sudo -u "$CTL_USER" "$SBIN/palworld-control" shutdown
    else
      run_ok systemctl stop "$OLD_SERVICE"
    fi
  else
    note "すでに停止しています。"
  fi

  if [ -x "$SBIN/palworld-backup" ] && user_exists "$CTL_USER"; then
    say "最後のバックアップを取ります。"
    run_ok sudo -u "$CTL_USER" "$SBIN/palworld-backup"
  fi

  run_ok systemctl disable --now "$OLD_SERVICE"

  # systemctl mask symlinks /etc/systemd/system/<unit> to /dev/null, so it
  # refuses to run while a real file sits at that exact path. Move it aside
  # first; keeping the copy means `unmask` + restore is still possible.
  if [ -f "$OLD_UNIT" ] && [ ! -L "$OLD_UNIT" ]; then
    say "ユニット実体を退避します（mask はこのパスを使うため）。"
    run mv "$OLD_UNIT" "$OLD_UNIT.bak"
    run systemctl daemon-reload
  fi

  run_ok systemctl mask "$OLD_SERVICE"

  if ! dry_run; then
    state="$(systemctl is-enabled "$OLD_SERVICE" 2>/dev/null || true)"
    if [ "$state" = "masked" ]; then
      ok "Palworld は masked です。手動でも依存でも起動しません。"
    else
      remember_warning "Palworld の mask に失敗しました（is-enabled=$state）。手動で起動できてしまう状態です。"
    fi
  fi
else
  note "Palworld のユニットが無いので何もしません。"
fi

# --------------------------------------------------------- 3. install Valheim

step "Valheim の導入"

if ! user_exists "$VALHEIM_USER"; then
  run useradd -r -m -s /bin/bash "$VALHEIM_USER"
else
  note "$VALHEIM_USER ユーザーは既にあります。"
fi

VALHEIM_HOME="$(getent passwd "$VALHEIM_USER" | cut -d: -f6)"
[ -n "$VALHEIM_HOME" ] || VALHEIM_HOME="/home/$VALHEIM_USER"

run install -d -o "$VALHEIM_USER" -g "$VALHEIM_USER" -m 0755 "$VALHEIM_DIR"

STEAMCMD=''
for candidate in /usr/games/steamcmd /usr/bin/steamcmd; do
  if [ -x "$candidate" ]; then
    STEAMCMD="$candidate"
    break
  fi
done
if [ -z "$STEAMCMD" ] && have_cmd steamcmd; then
  STEAMCMD="$(command -v steamcmd)"
fi
if [ -z "$STEAMCMD" ]; then
  say "SteamCMD が無いので導入します。"
  run dpkg --add-architecture i386
  run_ok add-apt-repository -y multiverse
  run apt-get update
  # The steamcmd package stops on a license prompt otherwise.
  if ! dry_run; then
    echo steam steam/question select "I AGREE" | debconf-set-selections
    echo steam steam/license note '' | debconf-set-selections
  fi
  run env DEBIAN_FRONTEND=noninteractive apt-get install -y steamcmd
  STEAMCMD=/usr/games/steamcmd
fi
note "SteamCMD: $STEAMCMD"

# +app_info_update/+app_info_print refreshes the cached manifest. Without it a
# stale cache turns into "Access Denied" on update, which cost a day once.
say "Valheim 専用サーバーを取得します（初回は数分かかります）。"
run sudo -H -u "$VALHEIM_USER" "$STEAMCMD" \
  +force_install_dir "$VALHEIM_DIR" \
  +login anonymous \
  +app_info_update 1 +app_info_print "$APPID" \
  +app_update "$APPID" validate \
  +quit

if ! dry_run && [ ! -x "$VALHEIM_DIR/valheim_server.x86_64" ]; then
  fail "$VALHEIM_DIR/valheim_server.x86_64 がありません。SteamCMD の出力を確認してください。"
fi

say "Steam SDK を配置します。"
run sudo -H -u "$VALHEIM_USER" mkdir -p "$VALHEIM_HOME/.steam/sdk64" "$VALHEIM_HOME/.steam/sdk32"
run_ok sudo -H -u "$VALHEIM_USER" cp \
  "$VALHEIM_HOME/.local/share/Steam/steamcmd/linux64/steamclient.so" \
  "$VALHEIM_HOME/.steam/sdk64/"
run_ok sudo -H -u "$VALHEIM_USER" cp \
  "$VALHEIM_HOME/.local/share/Steam/steamcmd/linux32/steamclient.so" \
  "$VALHEIM_HOME/.steam/sdk32/"

# --- server settings -----------------------------------------------------

read_value() {
  # read_value FILE KEY — first KEY=... line, value only. No sourcing, so a
  # stray line in the file can never execute.
  sed -n "s/^$2=//p" "$1" | head -n 1
}

if [ -e "$VALHEIM_ENV" ]; then
  ok "$VALHEIM_ENV は既にあります。中身はそのまま使います。"
  V_PORT="$(read_value "$VALHEIM_ENV" VALHEIM_PORT)"
  V_MODIFIERS="$(read_value "$VALHEIM_ENV" VALHEIM_MODIFIERS)"
else
  # Everything except the password is decided in the repository, so the usual
  # run reads it from there and only asks for what was left blank.
  [ -n "$VALUES_FILE" ] || VALUES_FILE="$REPO_ROOT/config/valheim.env.example"
  [ -r "$VALUES_FILE" ] || fail "$VALUES_FILE が読めません。"
  note "設定値の読み込み元: $VALUES_FILE"

  V_NAME="$(read_value "$VALUES_FILE" VALHEIM_NAME)"
  V_WORLD="$(read_value "$VALUES_FILE" VALHEIM_WORLD)"
  V_PASSWORD="$(read_value "$VALUES_FILE" VALHEIM_PASSWORD)"
  V_PORT="$(read_value "$VALUES_FILE" VALHEIM_PORT)"
  V_PUBLIC="$(read_value "$VALUES_FILE" VALHEIM_PUBLIC)"
  V_MODIFIERS="$(read_value "$VALUES_FILE" VALHEIM_MODIFIERS)"

  V_PORT="${V_PORT:-2456}"
  V_PUBLIC="${V_PUBLIC:-1}"

  [ -n "$V_NAME" ] || fail "$VALUES_FILE に VALHEIM_NAME がありません。"
  [ -n "$V_WORLD" ] || fail "$VALUES_FILE に VALHEIM_WORLD がありません。"
  case "$V_WORLD" in *[[:space:]]*) fail "ワールド名に空白は使えません。" ;; esac
  case "$V_PORT" in '' | *[!0-9]*) fail "VALHEIM_PORT が数値ではありません。" ;; esac

  say "サーバー名 $V_NAME / ワールド名 $V_WORLD / ポート $V_PORT / 一覧公開 $V_PUBLIC"

  if [ -z "$V_PASSWORD" ]; then
    if dry_run; then
      V_PASSWORD='(dry-run のためプロンプトは出しません)'
      note "本番実行ではここでサーバーパスワードを聞きます。"
    else
      printf 'サーバーパスワード（5文字以上・「%s」を含めない・入力は表示されません）: ' "$V_WORLD"
      read -rs V_PASSWORD < /dev/tty
      printf '\n'
    fi
  fi

  if ! dry_run; then
    [ "${#V_PASSWORD}" -ge 5 ] || fail "パスワードは5文字以上にしてください。"
    # The server refuses to start when the password contains the world name.
    pw_lower="${V_PASSWORD,,}"
    world_lower="${V_WORLD,,}"
    case "$pw_lower" in
      *"$world_lower"*)
        fail "パスワードにワールド名を含めることはできません（起動に失敗します）。"
        ;;
    esac
  fi

  write_file "$VALHEIM_ENV" 0640 "root:$VALHEIM_USER" <<EOF
VALHEIM_NAME=$V_NAME
VALHEIM_WORLD=$V_WORLD
VALHEIM_PASSWORD=$V_PASSWORD
VALHEIM_PORT=$V_PORT
VALHEIM_PUBLIC=$V_PUBLIC
VALHEIM_MODIFIERS=$V_MODIFIERS
EOF
  ok "$VALHEIM_ENV を作成しました（パスワードは表示していません）。"
fi

V_PORT="${V_PORT:-2456}"
QUERY_PORT=$((V_PORT + 1))
note "ゲームポート $V_PORT / クエリポート $QUERY_PORT"
if [ -n "${V_MODIFIERS:-}" ]; then
  note "ワールド修飾子: $V_MODIFIERS"
fi

# --- unit ----------------------------------------------------------------

if [ -e "$VALHEIM_UNIT" ]; then
  note "$VALHEIM_UNIT は既にあります。退避してから置き換えます。"
  backup_file "$VALHEIM_UNIT"
fi
sed '1s|.*|# Installed by scripts/setup/migrate-server.sh — edit, then systemctl daemon-reload.|' \
  "$REPO_ROOT/systemd/valheim-server.service.example" |
  write_file "$VALHEIM_UNIT" 0644 root:root

if ! dry_run; then
  grep -q '^KillSignal=SIGINT$' "$VALHEIM_UNIT" ||
    fail "ユニットに KillSignal=SIGINT がありません。これが無いと停止のたびにワールドが巻き戻ります。"
  grep -q '^Environment=SteamAppId=892970$' "$VALHEIM_UNIT" ||
    fail "ユニットに SteamAppId=892970 がありません。サーバーが起動しません。"
  ok "KillSignal=SIGINT と SteamAppId=892970 を確認しました。"
fi

run systemctl daemon-reload

# The bot starts the game; auto-start would make "PC on, game stopped"
# unreachable as a state.
run_ok systemctl disable "$VALHEIM_SERVICE"

# ------------------------------------------------ 4. control scripts + user

step "制御スクリプトと $CTL_USER"

if ! user_exists "$CTL_USER"; then
  run useradd -m -s /bin/bash "$CTL_USER"
else
  note "$CTL_USER ユーザーは既にあります。"
fi

for s in "${CONTROL_SCRIPTS[@]}"; do
  run install -m 0755 -o root -g root "$REPO_ROOT/scripts/server/$s" "$SBIN/$s"
done

# The backup script runs as palbotctl without sudo, so a root-owned directory
# here makes every backup fail — and a failed backup blocks the poweroff.
run install -d -o "$CTL_USER" -g "$CTL_USER" -m 0750 "$BACKUP_DIR"

# valheim-control defaults to query port 2457. On any other game port the
# player count would quietly come back empty while the running/stopped state
# still looked right, so pin it here rather than relying on the default.
run install -d -m 0755 /etc/gameserver-control
if [ -e "$CONTROL_ENV" ]; then
  printf '%s  → %s の VALHEIM_QUERY_PORT を %s に%s\n' \
    "$_C_DIM" "$CONTROL_ENV" "$QUERY_PORT" "$_C_OFF"
  if ! dry_run; then
    backup_file "$CONTROL_ENV"
    if grep -q '^VALHEIM_QUERY_PORT=' "$CONTROL_ENV"; then
      sed -i "s|^VALHEIM_QUERY_PORT=.*|VALHEIM_QUERY_PORT=\"$QUERY_PORT\"|" "$CONTROL_ENV"
    else
      printf 'VALHEIM_QUERY_PORT="%s"\n' "$QUERY_PORT" >> "$CONTROL_ENV"
    fi
  fi
else
  write_file "$CONTROL_ENV" 0640 "root:$CTL_USER" <<EOF
# Installed by scripts/setup/migrate-server.sh.
# Overrides for the control scripts. Must not be group/world writable — they
# refuse to read it otherwise, because it names the paths they trust.
VALHEIM_QUERY_PORT="$QUERY_PORT"
EOF
fi

ufw_state=''
if have_cmd ufw; then
  ufw_state="$(ufw status 2>/dev/null | head -n 1 || true)"
fi
case "$ufw_state" in
  *active*) run_ok ufw allow "$V_PORT:$QUERY_PORT/udp" ;;
  *) note "ufw が有効ではないので何もしません。" ;;
esac

# ------------------------------------------------------- 5. start and verify

step "Valheim の起動と応答確認"

run systemctl start "$VALHEIM_SERVICE"

# The modifier argument names are the least certain thing here: a game update
# can rename them, and the server then refuses to start. Say so at the point
# of failure, where it is actionable.
modifier_hint() {
  if [ -n "${V_MODIFIERS:-}" ]; then
    say ""
    warn "ワールド修飾子を渡しています: $V_MODIFIERS"
    say "  引数名がこのビルドで通らない可能性があります。切り分けるには"
    say "  $VALHEIM_ENV の VALHEIM_MODIFIERS を空にして、"
    say "  systemctl restart $VALHEIM_SERVICE を試してください。"
    say "  正しい引数は /opt/valheim-server/valheim_server.x86_64 -help で分かります。"
  fi
}

if dry_run; then
  skipped "起動確認"
else
  say "サーバーの応答を待ちます（初回のワールド生成は数分かかります）。"
  answered=0
  for _ in $(seq 1 60); do
    if "$SBIN/valheim-query" "$QUERY_PORT" > /dev/null 2>&1; then
      answered=1
      break
    fi
    if ! unit_active "$VALHEIM_SERVICE"; then
      say ""
      journalctl -u "$VALHEIM_SERVICE" -n 40 --no-pager || true
      modifier_hint
      fail "Valheim が落ちました。上のログを送ってください。"
    fi
    sleep 5
  done
  if [ "$answered" -ne 1 ]; then
    say ""
    journalctl -u "$VALHEIM_SERVICE" -n 40 --no-pager || true
    modifier_hint
    fail "5分待っても人数取得に応答がありません。上のログを送ってください。"
  fi
  ok "応答あり: $("$SBIN/valheim-query" "$QUERY_PORT" | tr '\n' ' ')"
fi

# ------------------------------------------------------- 6. privileged files

step "sudoers（内容を確認してから書き込みます）"

SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
# Installed by scripts/setup/migrate-server.sh.
# Only starting, stopping, and powering off need privileges; querying state
# does not, so systemctl is-active is deliberately absent.
Cmnd_Alias GAMESERVER_START = /usr/bin/systemctl start $VALHEIM_SERVICE
Cmnd_Alias GAMESERVER_STOP = /usr/bin/systemctl stop $VALHEIM_SERVICE
Cmnd_Alias GAMESERVER_POWER = $SBIN/gameserver-safe-poweroff

$CTL_USER ALL=(root) NOPASSWD: GAMESERVER_START, GAMESERVER_STOP, GAMESERVER_POWER
EOF

visudo -cf "$SUDOERS_TMP" > /dev/null || {
  rm -f "$SUDOERS_TMP"
  fail "生成した sudoers が文法エラーです（バグです。この出力を送ってください）。"
}
ok "文法チェック（visudo -c）を通りました。"
say "$SUDOERS に次の内容を書き込みます:"
show_file "$SUDOERS_TMP"

confirm "この sudoers を適用しますか？"
if dry_run; then
  skipped "sudoers の書き込み"
else
  backup_file "$SUDOERS"
  install -m 0440 -o root -g root "$SUDOERS_TMP" "$SUDOERS"
  ok "$SUDOERS を設置しました。"
fi
rm -f "$SUDOERS_TMP"

if [ -e "$OLD_SUDOERS" ]; then
  say ""
  say "旧 Palworld 用の sudoers が残っています:"
  show_file "$OLD_SUDOERS"
  confirm "これを削除しますか？（Bot から Palworld を起動する権限が消えます）"
  run rm -f "$OLD_SUDOERS"
fi

step "SSH の受け口（内容を確認してから書き込みます）"

CTL_HOME="$(getent passwd "$CTL_USER" | cut -d: -f6)"
[ -n "$CTL_HOME" ] || CTL_HOME="/home/$CTL_USER"

# sshd can be pointed at a non-default file, and assuming authorized_keys is
# what once caused a long "Permission denied (publickey)" hunt. Ask sshd
# instead of guessing.
AKF_SETTING="$(sshd -T 2>/dev/null | awk 'tolower($1)=="authorizedkeysfile"{$1=""; sub(/^ /,""); print; exit}')"
[ -n "$AKF_SETTING" ] || AKF_SETTING=".ssh/authorized_keys"
note "sshd の AuthorizedKeysFile: $AKF_SETTING"

AK_CANDIDATES=()
for entry in $AKF_SETTING; do
  path="${entry//\%h/$CTL_HOME}"
  path="${path//\%u/$CTL_USER}"
  case "$path" in
    /*) ;;
    *) path="$CTL_HOME/$path" ;;
  esac
  AK_CANDIDATES+=("$path")
done

AK_FILE=''
AK_STATE='missing'
for path in "${AK_CANDIDATES[@]}"; do
  [ -f "$path" ] || continue
  if grep -q 'valheim-control-ssh' "$path"; then
    AK_FILE="$path"
    AK_STATE='current'
    break
  fi
  if grep -q 'palworld-control-ssh' "$path"; then
    AK_FILE="$path"
    AK_STATE='old'
    break
  fi
done

case "$AK_STATE" in
  current)
    ok "$AK_FILE は既に valheim-control-ssh を指しています。変更は不要です。"
    ;;
  old)
    AK_NEW="$(mktemp)"
    sed "s#$SBIN/palworld-control-ssh#$SBIN/valheim-control-ssh#g" "$AK_FILE" > "$AK_NEW"
    say "$AK_FILE の forced command を差し替えます。"
    say ""
    say "変更前:"
    show_file "$AK_FILE"
    say "変更後:"
    show_file "$AK_NEW"
    confirm "この内容で書き換えますか？（公開鍵そのものは変わりません）"
    if dry_run; then
      skipped "authorized_keys の書き換え"
    else
      backup_file "$AK_FILE"
      # Keep the original owner and mode; sshd refuses a loose key file.
      cat "$AK_NEW" > "$AK_FILE"
      chown "$CTL_USER:$CTL_USER" "$AK_FILE"
      chmod 600 "$AK_FILE"
      ok "$AK_FILE を更新しました。"
    fi
    rm -f "$AK_NEW"
    ;;
  missing)
    remember_warning "Bot 用の公開鍵が見つかりませんでした。ラズパイ側の手順で登録が必要です。"
    say ""
    say "ラズパイの公開鍵を、次のファイルに1行で登録してください:"
    say "  ${AK_CANDIDATES[0]}"
    say ""
    say '  restrict,command="'"$SBIN"'/valheim-control-ssh" ssh-ed25519 AAAA... gameserver-bot@raspberrypi'
    say ""
    say "所有者 $CTL_USER、パーミッション 600、ディレクトリは 700 にしてください。"
    ;;
esac

# ------------------------------------------------------------ 7. self checks

step "最終確認"

if dry_run; then
  skipped "動作確認"
else
  out="$(sudo -u "$CTL_USER" "$SBIN/valheim-control" status || true)"
  case "$out" in
    *valheim=running*) ok "status: $out" ;;
    *) fail "status が想定外です: $out" ;;
  esac

  out="$(sudo -u "$CTL_USER" "$SBIN/valheim-control" players || true)"
  case "$out" in
    *players=*) ok "players: $(printf '%s' "$out" | tr '\n' ' ')" ;;
    *) remember_warning "人数取得に失敗しました（クエリポート $QUERY_PORT を確認してください）。" ;;
  esac

  say "sudo 権限の確認のため、ゲームを一度再起動します。"
  out="$(sudo -u "$CTL_USER" "$SBIN/valheim-control" restart || true)"
  case "$out" in
    *restarted*) ok "restart: $out" ;;
    *) fail "restart に失敗しました。sudoers を確認してください: $out" ;;
  esac
fi

print_final_warnings

say ""
ok "サーバー PC 側は完了です。"
say ""
say "次にやること:"
say "  1. ラズパイで:  sudo bash scripts/setup/migrate-pi.sh --dry-run"
say "     問題なければ --dry-run を外して本番実行"
say "  2. ルーター: UDP $V_PORT がこの PC へ転送されていることを確認"
say "     クエリポート $QUERY_PORT は loopback でしか使わないので転送不要です"
say "     （一覧公開を有効にする場合だけ $QUERY_PORT も開けてください）"
say ""
say "全部動いたあとに、旧 Palworld 環境を片付けるスクリプトがあります:"
say "  sudo bash scripts/setup/cleanup-palworld.sh"
