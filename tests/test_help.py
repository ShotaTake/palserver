import re
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from gameserver_bot.discord_app import build_server_group
from gameserver_bot.services.server_manager import ServerManager
from tests.test_server_manager import CONFIG


def make_interaction(
    role: int, guild: int | None = 100, channel: int | None = 200,
) -> Mock:
    interaction = Mock(spec=discord.Interaction)
    interaction.guild_id = guild
    interaction.channel_id = channel
    interaction.user = Mock(spec=discord.Member)
    interaction.user.roles = [Mock(id=role)]
    interaction.response = Mock()
    interaction.response.send_message = AsyncMock()
    return interaction


@pytest.mark.parametrize("role", [999, 400, 500])
async def test_help_shows_available_commands_privately_without_server_access(role: int) -> None:
    manager = Mock(spec=ServerManager)
    group = build_server_group(CONFIG, manager)
    command = group.get_command("help")
    assert command is not None
    interaction = make_interaction(role)

    await command.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    call = interaction.response.send_message.await_args
    assert call.kwargs == {"ephemeral": True}
    message = call.args[0]
    shown = set(re.findall(r"`/server (\w+)", message))
    if role == 500:
        # Maintainer inherits Player access; every registered command is covered.
        assert shown == {item.name for item in group.commands}
        assert "force:True" in message
    elif role == 400:
        assert shown == {"help", "status", "start", "address", "load", "stop"}
        assert "force:True" not in message
    else:
        assert shown == {"help"}
        assert "管理者に相談" in message
    assert "`/取引`" in message
    assert len(message) <= 2000
    assert manager.mock_calls == []


@pytest.mark.parametrize("guild,channel", [(999, 200), (100, 999), (None, None)])
async def test_help_rejects_wrong_context(guild: int | None, channel: int | None) -> None:
    manager = Mock(spec=ServerManager)
    command = build_server_group(CONFIG, manager).get_command("help")
    assert command is not None
    interaction = make_interaction(500, guild, channel)

    await command.callback(interaction)

    interaction.response.send_message.assert_awaited_once()
    call = interaction.response.send_message.await_args
    assert call.kwargs == {"ephemeral": True}
    assert "指定の場所" in call.args[0]
    assert "/server" not in call.args[0]
    assert manager.mock_calls == []
