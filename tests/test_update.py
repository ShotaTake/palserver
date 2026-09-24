from dataclasses import replace

import pytest

from gameserver_bot.services.server_manager import (
    StartOutcome,
    UpdateOutcome,
)
from gameserver_bot.services.ssh_control import RemoteCommand, SshResult
from gameserver_bot.services.update import UpdatePhase, UpdateReport, parse_update
from tests.test_monitor import FakeManager, make_monitor, report
from tests.test_server_manager import (
    CONNECTION_FAILED,
    FAILED,
    OK_RUNNING,
    OK_STOPPED,
    FakeSsh,
    make_manager,
)

QUEUED = SshResult(0, "update_id=123\nupdate_phase=queued\n")


@pytest.mark.parametrize("players", ["1", "-1", "unknown", ""])
async def test_update_refuses_players_or_unknown_count(players: str) -> None:
    ssh = FakeSsh({
        RemoteCommand.STATUS: [OK_RUNNING],
        RemoteCommand.PLAYERS: [SshResult(0, f"players={players}\n")],
    })
    manager, _ = make_manager(ssh)
    assert await manager.update() is UpdateOutcome.REFUSED_PLAYERS
    assert RemoteCommand.UPDATE not in ssh.calls


async def test_update_wakes_pc_without_starting_old_game() -> None:
    ssh = FakeSsh({
        RemoteCommand.STATUS: [CONNECTION_FAILED, OK_STOPPED, OK_STOPPED],
        RemoteCommand.UPDATE: [QUEUED],
    })
    manager, events = make_manager(ssh)
    assert await manager.update() is UpdateOutcome.ACCEPTED
    assert manager.requested_update_id == "123"
    assert events.count("wol") == 1
    assert RemoteCommand.START not in ssh.calls


async def test_update_running_empty_server() -> None:
    ssh = FakeSsh({
        RemoteCommand.STATUS: [OK_RUNNING],
        RemoteCommand.PLAYERS: [SshResult(0, "players=0\n")],
        RemoteCommand.UPDATE: [QUEUED],
    })
    manager, _ = make_manager(ssh)
    assert await manager.update() is UpdateOutcome.ACCEPTED


async def test_update_boot_timeout_does_not_enqueue() -> None:
    manager, _ = make_manager(FakeSsh({RemoteCommand.STATUS: [CONNECTION_FAILED]}))
    assert await manager.update() is UpdateOutcome.BOOT_TIMEOUT


@pytest.mark.parametrize("result,outcome", [
    (FAILED, UpdateOutcome.FAILED),
    (SshResult(75, ""), UpdateOutcome.BUSY),
    (CONNECTION_FAILED, UpdateOutcome.UNKNOWN),
    (SshResult(None, ""), UpdateOutcome.UNKNOWN),
    (SshResult(0, "arbitrary output"), UpdateOutcome.FAILED),
    (SshResult(0, "update_id=123\nupdate_phase=failed_download\n"), UpdateOutcome.FAILED),
])
async def test_update_request_failures(result: SshResult, outcome: UpdateOutcome) -> None:
    manager, _ = make_manager(FakeSsh({
        RemoteCommand.STATUS: [OK_STOPPED], RemoteCommand.UPDATE: [result],
    }))
    assert await manager.update() is outcome


async def test_update_respects_local_and_remote_locks() -> None:
    manager, _ = make_manager(FakeSsh({RemoteCommand.STATUS: [
        SshResult(0, "valheim=running\n" + QUEUED.stdout),
    ]}))
    assert await manager.update() is UpdateOutcome.BUSY
    assert await manager.start() is StartOutcome.BUSY
    async with manager._lock:
        assert await manager.update() is UpdateOutcome.BUSY


@pytest.mark.parametrize("payload", [
    "update_id=@everyone\nupdate_phase=succeeded",
    "update_id=123\nupdate_phase=@everyone",
    "update_id=123\nupdate_phase=unknown",
    "update_phase=succeeded",
])
def test_update_report_rejects_untrusted_fields(payload: str) -> None:
    assert parse_update(payload) is None


async def test_status_parses_update_without_extra_ssh_commands() -> None:
    manager, _ = make_manager(FakeSsh({RemoteCommand.STATUS: [
        SshResult(0, "valheim=stopped\n" + QUEUED.stdout),
    ]}))
    assert (await manager.status()).update == UpdateReport("123", UpdatePhase.QUEUED)


async def test_monitor_blocks_idle_during_update_and_announces_once() -> None:
    running = report(running=True, players=0)
    downloading = replace(running, update=UpdateReport("123", UpdatePhase.DOWNLOADING))
    done = replace(running, update=UpdateReport("123", UpdatePhase.SUCCEEDED))
    manager = FakeManager([downloading, downloading, done])
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()
    assert manager.stop_calls == []
    await monitor.tick()
    assert sum("更新を終え" in message for message in sent) == 1


async def test_monitor_reports_fast_update_and_does_not_repeat_old_result() -> None:
    done = replace(report(running=False, players=0),
                   update=UpdateReport("123", UpdatePhase.SUCCEEDED))
    manager = FakeManager([done])
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    assert sent == []  # Historical result when the bot starts.
    manager = FakeManager([done])
    manager.requested_update_id = "123"
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()
    assert len(sent) == 1
    assert manager.requested_update_id is None
