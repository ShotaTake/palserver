#!/usr/bin/env bash
# Shared helpers for the setup scripts. Meant to be sourced, not executed.
#
# The scripts these back run as root on a machine we cannot reach, driven by
# someone who is not going to debug them. So everything here is built around
# two ideas: show exactly what is about to happen, and never destroy anything
# that cannot be put back.

if [ -t 1 ]; then
  _C_HEAD=$'\033[1;36m'
  _C_OK=$'\033[32m'
  _C_WARN=$'\033[33m'
  _C_ERR=$'\033[31m'
  _C_DIM=$'\033[2m'
  _C_OFF=$'\033[0m'
else
  _C_HEAD='' _C_OK='' _C_WARN='' _C_ERR='' _C_DIM='' _C_OFF=''
fi

DRY_RUN="${DRY_RUN:-0}"
_STEP_NO=0

say() { printf '%s\n' "$*"; }
ok() { printf '%s✓ %s%s\n' "$_C_OK" "$*" "$_C_OFF"; }
warn() { printf '%s! %s%s\n' "$_C_WARN" "$*" "$_C_OFF"; }
note() { printf '%s  %s%s\n' "$_C_DIM" "$*" "$_C_OFF"; }

fail() {
  printf '%s✗ %s%s\n' "$_C_ERR" "$*" "$_C_OFF" >&2
  exit 1
}

step() {
  _STEP_NO=$((_STEP_NO + 1))
  printf '\n%s[%d] %s%s\n' "$_C_HEAD" "$_STEP_NO" "$*" "$_C_OFF"
}

# Quote an argument for display only, so the echoed line can be pasted back.
_quote() {
  case "$1" in
    '' | *[!A-Za-z0-9_@%+=:,./-]*) printf "'%s'" "${1//\'/\'\\\'\'}" ;;
    *) printf '%s' "$1" ;;
  esac
}

_fmt_cmd() {
  local out='' arg
  for arg in "$@"; do
    out="$out $(_quote "$arg")"
  done
  printf '%s' "${out# }"
}

# run CMD ARGS... — show the command, then run it (or not, under --dry-run).
# Arguments are passed straight to the command; nothing is ever evaluated as
# shell text.
run() {
  printf '%s  $ %s%s\n' "$_C_DIM" "$(_fmt_cmd "$@")" "$_C_OFF"
  if [ "$DRY_RUN" = "1" ]; then
    return 0
  fi
  "$@"
}

# Same, but the command is expected to fail sometimes and that is not fatal.
run_ok() {
  run "$@" || true
}

# True while we are only pretending. Use it to skip verification that cannot
# work without the real changes having happened.
dry_run() {
  [ "$DRY_RUN" = "1" ]
}

skipped() {
  note "(dry-run: $* は実行しません)"
}

# confirm PROMPT — only an exact "yes" continues. Reads from the terminal, not
# stdin, so a piped invocation still asks a human.
confirm() {
  local prompt="$1" reply=''
  if dry_run; then
    printf '%s  [dry-run] ここで確認を求めます: %s%s\n' "$_C_DIM" "$prompt" "$_C_OFF"
    return 0
  fi
  printf '\n%s%s%s\n' "$_C_WARN" "$prompt" "$_C_OFF"
  printf '続けるなら yes と入力してください: '
  if [ -r /dev/tty ]; then
    read -r reply < /dev/tty
  else
    read -r reply
  fi
  if [ "$reply" = "yes" ]; then
    return 0
  fi
  # Says "so far" rather than "nothing", because a confirm partway through a
  # run has real changes behind it. Re-running is always safe.
  fail "中止しました。ここまでの変更はそのまま残っています（このスクリプトは何度でも実行できます）。"
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "root で実行してください:  sudo bash $0"
  fi
}

need_cmd() {
  command -v "$1" > /dev/null 2>&1 || fail "$1 が見つかりません。$2"
}

have_cmd() {
  command -v "$1" > /dev/null 2>&1
}

unit_exists() {
  systemctl list-unit-files "$1" > /dev/null 2>&1 &&
    [ -n "$(systemctl list-unit-files --no-legend "$1" 2>/dev/null)" ]
}

unit_active() {
  systemctl is-active --quiet "$1"
}

user_exists() {
  id -u "$1" > /dev/null 2>&1
}

# user_home USER — the home directory, or empty when there is no such user.
# getent exits 2 for a missing user, which set -e would otherwise take as a
# fatal error. That happens routinely during --dry-run, where the useradd was
# printed rather than run.
user_home() {
  getent passwd "$1" 2>/dev/null | cut -d: -f6 || true
}

# Copy a file to <path>.bak.<timestamp> before it is modified in place.
backup_file() {
  local path="$1"
  [ -e "$path" ] || return 0
  run cp -a "$path" "$path.bak.$(date +%Y%m%d-%H%M%S)"
}

# write_file DEST MODE OWNER:GROUP — content comes from stdin. Always goes
# through a temp file so a half-written config never lands in place.
write_file() {
  local dest="$1" mode="$2" owner="$3" tmp
  tmp="$(mktemp)"
  cat > "$tmp"
  printf '%s  → %s に書き込み (mode %s, %s)%s\n' "$_C_DIM" "$dest" "$mode" "$owner" "$_C_OFF"
  if dry_run; then
    rm -f "$tmp"
    return 0
  fi
  install -D -m "$mode" -o "${owner%%:*}" -g "${owner##*:}" "$tmp" "$dest"
  rm -f "$tmp"
}

# Print a file's content framed, so the operator can read what is about to be
# installed. Never use this on anything holding a secret.
#
# A failure to read must not abort a migration half way, so the error is shown
# in place of the content rather than raised.
show_file() {
  printf '%s\n' "----------------------------------------------------------------"
  cat "$1" 2>&1 || true
  printf '%s\n' "----------------------------------------------------------------"
}

# svc_state VERB UNIT — systemctl is-active/is-enabled exit non-zero for
# perfectly ordinary states, so ask without letting that count as an error.
svc_state() {
  local out
  out="$(systemctl "$1" "$2" 2>/dev/null || true)"
  printf '%s' "${out:-unknown}"
}

# Warnings worth repeating at the very end, where they will actually be read.
FINAL_WARNINGS=()

remember_warning() {
  FINAL_WARNINGS+=("$1")
  warn "$1"
}

print_final_warnings() {
  [ "${#FINAL_WARNINGS[@]}" -eq 0 ] && return 0
  printf '\n%s要確認:%s\n' "$_C_WARN" "$_C_OFF"
  local w
  for w in "${FINAL_WARNINGS[@]}"; do
    printf '  - %s\n' "$w"
  done
}

# Installed by each script so a mid-way failure tells the operator what to do.
on_error() {
  local code=$?
  printf '\n%s✗ 途中で失敗しました（終了コード %d）。%s\n' "$_C_ERR" "$code" "$_C_OFF" >&2
  printf '%s\n' "ここまでの出力をそのまま送ってください。原因を特定して手順を出し直します。" >&2
  printf '%s\n' "このスクリプトは何度実行しても大丈夫なので、直したあとは頭から再実行できます。" >&2
  exit "$code"
}

# parse_common_args "$@" — consumes --dry-run/-h and leaves the rest in
# REMAINING_ARGS. Each script handles its own extra options.
usage_extra=''
parse_common_args() {
  REMAINING_ARGS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h | --help)
        printf '使い方: sudo bash %s [--dry-run]%s\n' "$0" "$usage_extra"
        printf '\n  --dry-run  何も変更せず、実行する内容だけを表示します。\n'
        printf '             本番の前に必ず一度これを流して、出力を共有してください。\n'
        exit 0
        ;;
      *)
        REMAINING_ARGS+=("$1")
        shift
        ;;
    esac
  done
}

banner() {
  printf '%s\n' "=============================================================="
  printf '%s\n' " $1"
  printf '%s\n' "=============================================================="
  if dry_run; then
    printf '\n%s*** DRY RUN: 何も変更しません。実行内容の確認だけです。 ***%s\n' \
      "$_C_WARN" "$_C_OFF"
  fi
}
