"""Exercise the real shell controller using isolated fake system services.

No real sudo, systemctl, SteamCMD, network calls or PC power operations run.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = (
    str(Path("C:/Program Files/Git/bin/bash.exe")) if os.name == "nt" else shutil.which("bash")
)
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason="Bash required")


@pytest.fixture
def server(tmp_path: Path) -> Path:
    (tmp_path / "bin").mkdir()
    (tmp_path / "game").write_text("active\n", newline="\n")
    (tmp_path / "unit").write_text("activating\n", newline="\n")
    (tmp_path / "update-state").write_text("update_id=123\nupdate_phase=queued\n", newline="\n")
    scripts = {
        "sudo": 'while [[ "$1" == -* ]]; do '
                'if [ "$1" = -u ]; then shift; fi; shift; done\nexec "$@"\n',
        "flock": 'exit "${LOCK_BUSY:-0}"\n',
        "sleep": "exit 0\n",
        "systemctl": '''
case "$*" in
  "show -p ActiveState --value valheim-server.service") cat "$TEST_DIR/game" ;;
  "show -p ActiveState --value valheim-update.service") cat "$TEST_DIR/unit" ;;
  "show -p ActiveState --value valheim-restore.service") echo "${RESTORE_STATE:-inactive}" ;;
  "show -p LoadState --value valheim-update.service") echo loaded ;;
  "is-active --quiet valheim-server.service") test "$(cat "$TEST_DIR/game")" = active ;;
  "stop valheim-server.service")
    echo stop >> "$TEST_DIR/events"
    [ "${STOP_FAIL:-0}" = 0 ] || exit 1
    echo inactive > "$TEST_DIR/game" ;;
  "start valheim-server.service")
    echo start >> "$TEST_DIR/events"
    [ "${START_FAIL:-0}" = 0 ] || exit 1
    echo active > "$TEST_DIR/game" ;;
  "start --no-block valheim-update.service")
    echo enqueue >> "$TEST_DIR/events"
    echo activating > "$TEST_DIR/unit" ;;
  *) echo "unexpected systemctl: $*" >&2; exit 99 ;;
esac
''',
        "query": '''
[ "${QUERY_FAIL:-0}" = 0 ] || exit 1
echo "players=${PLAYERS:-0}"
echo max_players=10
''',
        "backup": 'echo backup >> "$TEST_DIR/events"\nexit "${BACKUP_FAIL:-0}"\n',
        "steam": 'echo steam >> "$TEST_DIR/events"\nexit "${STEAM_FAIL:-0}"\n',
        "poweroff": 'echo poweroff >> "$TEST_DIR/events"\n',
    }
    for name, body in scripts.items():
        path = tmp_path / "bin" / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, newline="\n")
        path.chmod(0o755)
    source = (ROOT / "scripts/server/valheim-control").read_text(encoding="utf-8")
    # Only the test copy is redirected. Production paths cannot be selected by
    # Discord or by arguments to the fixed command.
    replacements = {
        "/var/lib/gameserver-control": str(tmp_path.as_posix()),
        "/usr/local/sbin/valheim-query": (tmp_path / "bin/query").as_posix(),
        "/usr/local/sbin/gameserver-backup": (tmp_path / "bin/backup").as_posix(),
        "/usr/local/sbin/gameserver-safe-poweroff": (tmp_path / "bin/poweroff").as_posix(),
        "/usr/local/sbin/valheim-steam-update": (tmp_path / "bin/steam").as_posix(),
    }
    for before, after in replacements.items():
        source = source.replace(before, after)
    (tmp_path / "control").write_text(source, newline="\n", encoding="utf-8")
    return tmp_path


def run(server: Path, command: str, **extra: str) -> subprocess.CompletedProcess[str]:
    shell_dir = server.as_posix()
    if os.name == "nt":
        shell_dir = "/" + shell_dir[0].lower() + shell_dir[2:]
    env = {
        **os.environ,
        "TEST_DIR": shell_dir,
        "TEST_COMMAND": command,
        "GAMESERVER_CONTROL_ENV": (server / "missing-config").as_posix(),
        **extra,
    }
    return subprocess.run(  # noqa: S603 - isolated test harness with fixed scripts
        [BASH, "-c", 'export PATH="$TEST_DIR/bin:/usr/bin:/bin:$PATH"; '
         'exec bash "$TEST_DIR/control" "$TEST_COMMAND"'],
        env=env, capture_output=True, text=True, timeout=30,
    )


def events(server: Path) -> list[str]:
    path = server / "events"
    return path.read_text().splitlines() if path.exists() else []


def test_worker_saves_backs_up_updates_and_verifies(server: Path) -> None:
    result = run(server, "update-run")
    assert result.returncode == 0, result.stderr
    assert events(server) == ["stop", "backup", "steam", "start"]
    assert "update_phase=succeeded" in (server / "update-state").read_text()


@pytest.mark.parametrize("env,phase,expected", [
    ({"PLAYERS": "1"}, "refused_players", []),
    ({"QUERY_FAIL": "1"}, "refused_players", []),
    ({"PLAYERS": "-1"}, "refused_players", []),
    ({"STOP_FAIL": "1"}, "failed_stop", ["stop"]),
    ({"BACKUP_FAIL": "1"}, "failed_backup", ["stop", "backup"]),
    ({"STEAM_FAIL": "1"}, "failed_download", ["stop", "backup", "steam"]),
    ({"START_FAIL": "1"}, "failed_start", ["stop", "backup", "steam", "start"]),
])
def test_worker_stops_on_each_failure(
    server: Path, env: dict[str, str], phase: str, expected: list[str]
) -> None:
    result = run(server, "update-run", **env)
    assert result.returncode != 0
    assert events(server) == expected
    assert f"update_phase={phase}" in (server / "update-state").read_text()


@pytest.mark.parametrize(
    "command", ["start", "restart", "shutdown", "backup", "poweroff", "update"]
)
def test_update_blocks_all_other_mutations(server: Path, command: str) -> None:
    result = run(server, command)
    assert result.returncode == 75
    assert events(server) == []


def test_lock_contention_blocks_mutation(server: Path) -> None:
    (server / "unit").write_text("inactive\n", newline="\n")
    assert run(server, "start", LOCK_BUSY="1").returncode == 75
    assert events(server) == []


@pytest.mark.parametrize("command", ["start", "shutdown", "poweroff", "update", "update-run"])
@pytest.mark.parametrize("blocked", [False, True])
def test_restore_blocks_mutations_across_bot_restarts(server: Path, command: str, blocked: bool):
    (server / "unit").write_text("inactive\n", newline="\n")
    if blocked:
        (server / "restore-block").write_text("incomplete switch", newline="\n")
    result = run(server, command, RESTORE_STATE="inactive" if blocked else "activating")
    assert result.returncode == 75
    assert events(server) == []


def test_enqueue_returns_without_running_worker(server: Path) -> None:
    (server / "unit").write_text("inactive\n", newline="\n")
    result = run(server, "update")
    assert result.returncode == 0, result.stderr
    assert events(server) == ["enqueue"]
    assert "update_phase=queued" in result.stdout


def test_status_detects_interrupted_worker(server: Path) -> None:
    (server / "unit").write_text("failed\n", newline="\n")
    result = run(server, "status")
    assert result.returncode == 0, result.stderr
    assert "update_phase=interrupted" in result.stdout


@pytest.mark.parametrize("command", [
    "update-run", "update anything", "update; poweroff", "bash",
    "restore-run", "restore-status", "restore anything", "restore; poweroff",
])
def test_ssh_wrapper_denies_non_allowlisted_commands(command: str) -> None:
    result = subprocess.run(  # noqa: S603 - denial cases, no allowed command can execute
        [BASH, str(ROOT / "scripts/server/valheim-control-ssh")],
        env={**os.environ, "SSH_ORIGINAL_COMMAND": command},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 64


@pytest.mark.skipif(os.name == "nt", reason="Real flock is verified on Linux CI")
def test_real_lock_blocks_another_process(server: Path) -> None:
    import fcntl

    (server / "bin/flock").unlink()  # Use util-linux flock on the CI host.
    (server / "unit").write_text("inactive\n", newline="\n")
    with (server / "operation.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert run(server, "start").returncode == 75
    assert events(server) == []


@pytest.mark.parametrize("exit_code,success_line,executable,success", [
    ("0", "1", True, True),
    ("1", "1", True, False),
    ("0", "0", True, False),
    ("0", "1", False, False),
])
def test_steam_helper_requires_exit_success_marker_and_binary(
    server: Path, exit_code: str, success_line: str, executable: bool, success: bool,
) -> None:
    steam = server / "bin/steamcmd"
    steam.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$@" > "$TEST_DIR/steam-args"\n'
        'if [ "$SUCCESS_LINE" = 1 ]; then '
        'echo "Success! App \'896660\' fully installed."; fi\n'
        'exit "$STEAM_EXIT"\n', newline="\n",
    )
    steam.chmod(0o755)
    if executable:
        binary = server / "valheim_server.x86_64"
        binary.write_text("#!/usr/bin/env bash\n", newline="\n")
        binary.chmod(0o755)
    helper = (ROOT / "scripts/server/valheim-steam-update").read_text(encoding="utf-8")
    helper = helper.replace("/usr/games/steamcmd", steam.as_posix())
    helper = helper.replace("/opt/valheim-server", server.as_posix())
    # The helper must be called without arguments; run() supplies one, so use
    # a tiny test launcher that calls the copied helper with no arguments.
    (server / "helper").write_text(helper, encoding="utf-8", newline="\n")
    (server / "control").write_text('exec bash "$TEST_DIR/helper"\n', newline="\n")
    result = run(server, "unused", STEAM_EXIT=exit_code, SUCCESS_LINE=success_line)
    assert (result.returncode == 0) is success, result.stderr
    args = (server / "steam-args").read_text().splitlines()
    assert args[args.index("+app_update") + 1] == "896660"
    assert args[args.index("+login") + 1] == "anonymous"


def test_steam_helper_denies_extra_arguments() -> None:
    result = subprocess.run(  # noqa: S603 - rejects before touching any installation paths
        [BASH, str(ROOT / "scripts/server/valheim-steam-update"), "extra"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 64
