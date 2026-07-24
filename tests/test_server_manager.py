from palworld_bot.config import load_config
from palworld_bot.services.server_manager import (
    PalworldState,
    PcState,
    RestartOutcome,
    ServerManager,
    StartOutcome,
    StopOutcome,
)
from palworld_bot.services.ssh_control import RemoteCommand, SshResult
from tests.test_config import BASE_ENV

CONFIG = load_config(BASE_ENV)

OK_RUNNING = SshResult(exit_code=0, stdout="palworld=running\n")
OK_STOPPED = SshResult(exit_code=0, stdout="palworld=stopped\n")
CONNECTION_FAILED = SshResult(exit_code=255, stdout="")
OK_EMPTY = SshResult(exit_code=0, stdout="")
FAILED = SshResult(exit_code=1, stdout="")


class FakeSsh:
    """Returns queued results per command; the last result repeats."""

    def __init__(self, responses: dict[RemoteCommand, list[SshResult]]) -> None:
        self._responses = {command: list(results) for command, results in responses.items()}
        self.calls: list[RemoteCommand] = []

    async def __call__(self, command: RemoteCommand) -> SshResult:
        self.calls.append(command)
        queue = self._responses[command]
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]


def make_manager(ssh: FakeSsh) -> tuple[ServerManager, list[str]]:
    events: list[str] = []

    async def wol_sender() -> int:
        events.append("wol")
        return CONFIG.wol_repeat_count

    async def instant_sleep(_seconds: float) -> None:
        events.append("sleep")

    manager = ServerManager(CONFIG, ssh_runner=ssh, wol_sender=wol_sender, sleep=instant_sleep)
    return manager, events


async def test_status_offline_when_connection_fails() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [CONNECTION_FAILED]})
    manager, _ = make_manager(ssh)
    report = await manager.status()
    assert report.pc is PcState.OFFLINE
    assert report.palworld is PalworldState.UNKNOWN
    assert report.players is None


async def test_status_running_reports_players() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_RUNNING],
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=2\nmax_players=8\n")],
        }
    )
    manager, _ = make_manager(ssh)
    report = await manager.status()
    assert report.pc is PcState.ONLINE
    assert report.palworld is PalworldState.RUNNING
    assert report.players == 2
    assert report.max_players == 8


async def test_status_running_without_max_players() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_RUNNING],
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=1\n")],
        }
    )
    manager, _ = make_manager(ssh)
    report = await manager.status()
    assert report.players == 1
    assert report.max_players is None


async def test_status_stopped_reports_zero_players() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [OK_STOPPED]})
    manager, _ = make_manager(ssh)
    report = await manager.status()
    assert report.palworld is PalworldState.STOPPED
    assert report.players == 0


async def test_status_reports_player_names() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_RUNNING],
            RemoteCommand.PLAYERS: [
                SshResult(
                    exit_code=0,
                    stdout="players=2\nmax_players=8\nplayer=Alice\nplayer=Bob\n",
                )
            ],
        }
    )
    manager, _ = make_manager(ssh)
    report = await manager.status()
    assert report.players == 2
    assert report.player_names == ("Alice", "Bob")


async def test_restart_success() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_RUNNING, OK_RUNNING],
            RemoteCommand.RESTART: [SshResult(exit_code=0, stdout="restarted\n")],
        }
    )
    manager, _ = make_manager(ssh)
    assert await manager.restart() is RestartOutcome.RESTARTED
    assert RemoteCommand.RESTART in ssh.calls


async def test_restart_unreachable() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [CONNECTION_FAILED]})
    manager, _ = make_manager(ssh)
    assert await manager.restart() is RestartOutcome.UNREACHABLE
    assert RemoteCommand.RESTART not in ssh.calls


async def test_restart_failure_when_not_running_after() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_RUNNING, OK_STOPPED],
            RemoteCommand.RESTART: [OK_EMPTY],
        }
    )
    manager, _ = make_manager(ssh)
    assert await manager.restart() is RestartOutcome.RESTART_FAILED


async def test_start_when_already_running() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [OK_RUNNING]})
    manager, events = make_manager(ssh)
    assert await manager.start() is StartOutcome.ALREADY_RUNNING
    assert "wol" not in events


async def test_start_from_offline_sends_wol_then_starts() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [CONNECTION_FAILED, OK_STOPPED, OK_RUNNING],
            RemoteCommand.START: [OK_EMPTY],
        }
    )
    manager, events = make_manager(ssh)
    assert await manager.start() is StartOutcome.STARTED
    assert events.count("wol") == 1
    assert RemoteCommand.START in ssh.calls


async def test_start_boot_timeout() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [CONNECTION_FAILED]})
    manager, events = make_manager(ssh)
    assert await manager.start() is StartOutcome.BOOT_TIMEOUT
    assert events.count("wol") == 1
    assert RemoteCommand.START not in ssh.calls


async def test_start_failure_when_not_running_after_start() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.STATUS: [OK_STOPPED, OK_STOPPED],
            RemoteCommand.START: [OK_EMPTY],
        }
    )
    manager, _ = make_manager(ssh)
    assert await manager.start() is StartOutcome.START_FAILED


async def test_stop_refused_when_players_connected() -> None:
    ssh = FakeSsh({RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=3\n")]})
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=False)
    assert result.outcome is StopOutcome.REFUSED_PLAYERS_CONNECTED
    assert result.players == 3
    assert RemoteCommand.SHUTDOWN not in ssh.calls


async def test_stop_refused_when_players_unknown() -> None:
    ssh = FakeSsh({RemoteCommand.PLAYERS: [FAILED]})
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=False)
    assert result.outcome is StopOutcome.REFUSED_PLAYERS_CONNECTED
    assert result.players is None


async def test_stop_success_runs_shutdown_backup_poweroff_in_order() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=0\n")],
            RemoteCommand.SHUTDOWN: [OK_EMPTY],
            RemoteCommand.BACKUP: [OK_EMPTY],
            RemoteCommand.POWEROFF: [OK_EMPTY],
        }
    )
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=False)
    assert result.outcome is StopOutcome.STOPPED
    assert ssh.calls == [
        RemoteCommand.PLAYERS,
        RemoteCommand.SHUTDOWN,
        RemoteCommand.BACKUP,
        RemoteCommand.POWEROFF,
    ]


async def test_stop_with_players_allowed_for_maintainer() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=2\n")],
            RemoteCommand.SHUTDOWN: [OK_EMPTY],
            RemoteCommand.BACKUP: [OK_EMPTY],
            RemoteCommand.POWEROFF: [OK_EMPTY],
        }
    )
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=True)
    assert result.outcome is StopOutcome.STOPPED


async def test_backup_failure_prevents_poweroff() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=0\n")],
            RemoteCommand.SHUTDOWN: [OK_EMPTY],
            RemoteCommand.BACKUP: [FAILED],
        }
    )
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=False)
    assert result.outcome is StopOutcome.BACKUP_FAILED
    assert RemoteCommand.POWEROFF not in ssh.calls


async def test_poweroff_connection_drop_counts_as_stopped() -> None:
    ssh = FakeSsh(
        {
            RemoteCommand.PLAYERS: [SshResult(exit_code=0, stdout="players=0\n")],
            RemoteCommand.SHUTDOWN: [OK_EMPTY],
            RemoteCommand.BACKUP: [OK_EMPTY],
            RemoteCommand.POWEROFF: [CONNECTION_FAILED],
        }
    )
    manager, _ = make_manager(ssh)
    result = await manager.stop(allow_with_players=False)
    assert result.outcome is StopOutcome.STOPPED


async def test_operations_report_busy_while_lock_is_held() -> None:
    ssh = FakeSsh({RemoteCommand.STATUS: [OK_STOPPED]})
    manager, _ = make_manager(ssh)
    async with manager._lock:  # noqa: SLF001 - simulate an in-flight operation
        assert await manager.start() is StartOutcome.BUSY
        assert await manager.restart() is RestartOutcome.BUSY
        stop_result = await manager.stop(allow_with_players=False)
        assert stop_result.outcome is StopOutcome.BUSY
