from unittest.mock import AsyncMock, Mock

import discord
import pytest

from gameserver_bot.discord_app import build_server_group
from gameserver_bot.services.server_manager import ServerManager, UpdateOutcome
from tests.test_server_manager import CONFIG


@pytest.mark.parametrize("guild,channel,role,allowed", [
    (100, 200, 500, True),
    (100, 200, 400, False),  # Player cannot update.
    (100, 200, 999, False),
    (999, 200, 500, False),
    (100, 999, 500, False),
    (None, 200, 500, False),
])
async def test_update_checks_context_and_maintainer_before_side_effects(
    guild: int | None, channel: int, role: int, allowed: bool,
) -> None:
    manager = Mock(spec=ServerManager)
    manager.update = AsyncMock(return_value=UpdateOutcome.ACCEPTED)
    interaction = Mock(spec=discord.Interaction)
    interaction.guild_id = guild
    interaction.channel_id = channel
    interaction.user = Mock(spec=discord.Member)
    interaction.user.id = 1234
    interaction.user.roles = [Mock(id=role)]
    interaction.response = Mock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup = Mock()
    interaction.followup.send = AsyncMock()
    command = build_server_group(CONFIG, manager).get_command("update")
    assert command is not None
    await command.callback(interaction)
    if allowed:
        manager.update.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
    else:
        manager.update.assert_not_awaited()
        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()
