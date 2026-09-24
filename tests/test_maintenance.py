import json
from dataclasses import asdict, replace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from gameserver_bot.discord_app import build_server_group
from gameserver_bot.maintenance_ui import RestoreConfirm, diagnose_text
from gameserver_bot.services import ssh_control
from gameserver_bot.services.maintenance import (
    BackupEntry,
    RestorePhase,
    RestoreReport,
    parse_backups,
    parse_diagnose,
    restore_payload,
)
from gameserver_bot.services.server_manager import RestoreOutcome, ServerManager
from gameserver_bot.services.ssh_control import RemoteCommand, SshResult
from tests.test_monitor import FakeManager, make_monitor, report
from tests.test_server_manager import CONFIG, CONNECTION_FAILED, OK_RUNNING, OK_STOPPED, FakeSsh

ENTRY = BackupEntry("valheim-world-20260924-120000.tar.gz", 1234, 1790200000, "a" * 64)
QUEUED = SshResult(0, "restore_id=123\nrestore_phase=queued\n")


def interaction(role=500, guild=100, channel=200, actor=1234):
    item = Mock(spec=discord.Interaction)
    item.guild_id, item.channel_id = guild, channel
    item.user = Mock(spec=discord.Member)
    item.user.id, item.user.roles = actor, [Mock(id=role)]
    item.response = Mock()
    item.response.defer = AsyncMock()
    item.response.edit_message = AsyncMock()
    item.response.send_message = AsyncMock()
    item.followup = Mock()
    item.followup.send = AsyncMock()
    item.edit_original_response = AsyncMock()
    return item


@pytest.mark.parametrize("command", ["diagnose", "backups", "restore"])
@pytest.mark.parametrize("role,guild,channel,allowed", [
    (500, 100, 200, True), (400, 100, 200, False),
    (500, 999, 200, False), (500, 100, 999, False), (500, None, 200, False),
])
async def test_maintenance_commands_authorize_before_querying(
    command, role, guild, channel, allowed
):
    manager = Mock(spec=ServerManager)
    manager.diagnose = AsyncMock(return_value={"ssh": "ok"})
    manager.backups = AsyncMock(return_value=(ENTRY,))
    manager.restore = AsyncMock()
    item = interaction(role=role, guild=guild, channel=channel)
    handler = build_server_group(CONFIG, manager).get_command(command)
    await handler.callback(item)
    manager.restore.assert_not_awaited()  # /restore only offers a selection.
    method = manager.diagnose if command == "diagnose" else manager.backups
    if allowed:
        method.assert_awaited_once()
    else:
        method.assert_not_awaited()
        item.response.send_message.assert_awaited_once()


@pytest.mark.parametrize("change", ["role", "guild", "channel", "actor", "expired"])
async def test_confirmation_rechecks_authorization_and_expiry(change):
    manager = Mock(spec=ServerManager)
    manager.restore = AsyncMock(return_value=RestoreOutcome.ACCEPTED)
    view = RestoreConfirm(CONFIG, 1234, manager, ENTRY)
    item = interaction()
    if change == "role":
        item.user.roles = [Mock(id=400)]
    elif change == "guild":
        item.guild_id = 999
    elif change == "channel":
        item.channel_id = 999
    elif change == "actor":
        item.user.id = 999
    else:
        view.expires = 0
    await view.confirm.callback(item)
    manager.restore.assert_not_awaited()


async def test_confirmation_only_once_and_exact_selected_entry():
    manager = Mock(spec=ServerManager)
    manager.restore = AsyncMock(return_value=RestoreOutcome.ACCEPTED)
    view = RestoreConfirm(CONFIG, 1234, manager, ENTRY)
    await view.confirm.callback(interaction())
    await view.confirm.callback(interaction())
    manager.restore.assert_awaited_once_with(ENTRY)


async def test_cancel_does_not_restore():
    manager = Mock(spec=ServerManager)
    manager.restore = AsyncMock()
    view = RestoreConfirm(CONFIG, 1234, manager, ENTRY)
    await view.cancel.callback(interaction())
    await view.confirm.callback(interaction())
    manager.restore.assert_not_awaited()


@pytest.mark.parametrize("change", [
    {"name": "../../world"}, {"name": "@everyone"}, {"size": -1},
    {"modified": 99999999999999999}, {"fingerprint": "not-a-fingerprint"},
])
def test_backup_parser_rejects_untrusted_fields(change):
    with pytest.raises(ValueError):
        parse_backups(json.dumps({"backups": [{**asdict(ENTRY), **change}]}))


def test_diagnosis_drops_raw_text_and_does_not_claim_poweroff():
    checks = parse_diagnose(json.dumps({"checks": {"game": "running", "world": "@everyone",
                                                   "secret": "private"}}))
    assert checks == {"game": "running"}
    assert "不明" in diagnose_text({"ssh": "unreachable"})


async def test_restore_refuses_players_and_unknown_counts():
    for count in ["1", "-1", "unknown"]:
        sender = AsyncMock(return_value=QUEUED)
        ssh = FakeSsh({RemoteCommand.STATUS: [OK_RUNNING],
                       RemoteCommand.PLAYERS: [SshResult(0, f"players={count}\n")]})
        manager = ServerManager(CONFIG, ssh_runner=ssh, restore_sender=sender)
        assert await manager.restore(ENTRY) is RestoreOutcome.REFUSED_PLAYERS
        sender.assert_not_awaited()


@pytest.mark.parametrize("result,outcome", [
    (QUEUED, RestoreOutcome.ACCEPTED), (CONNECTION_FAILED, RestoreOutcome.UNKNOWN),
    (SshResult(75, ""), RestoreOutcome.BUSY), (SshResult(1, ""), RestoreOutcome.FAILED),
])
async def test_restore_request_outcomes(result, outcome):
    manager = ServerManager(CONFIG, ssh_runner=FakeSsh({RemoteCommand.STATUS: [OK_STOPPED]}),
                            restore_sender=AsyncMock(return_value=result))
    assert await manager.restore(ENTRY) is outcome


async def test_restore_payload_uses_stdin_and_fixed_command(monkeypatch):
    process = Mock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"restore_id=123\nrestore_phase=queued\n", b""))
    launch = AsyncMock(return_value=process)
    monkeypatch.setattr(ssh_control.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(ssh_control.shutil, "which", lambda name: "/usr/bin/ssh")
    payload = restore_payload(ENTRY)
    await ssh_control.run_remote(CONFIG, RemoteCommand.RESTORE, input_data=payload)
    assert launch.call_args.args[-1] == "restore"
    assert ENTRY.name not in launch.call_args.args
    process.communicate.assert_awaited_once_with(payload)


async def test_restore_monitor_suppresses_idle_and_announces_completion_once():
    running = report(running=True, players=0)
    active = replace(running, restore=RestoreReport("123", RestorePhase.VALIDATING))
    done = replace(running, restore=RestoreReport("123", RestorePhase.SUCCEEDED))
    manager = FakeManager([active, active, done])
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()
    assert manager.stop_calls == []
    await monitor.tick()
    assert sum("復元を終え" in text for text in sent) == 1
