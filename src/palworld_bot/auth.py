"""Discord guild, channel, and role authorization.

All checks use IDs from configuration, never names or hardcoded users.
"""

from __future__ import annotations

from collections.abc import Iterable

from palworld_bot.config import BotConfig


def is_allowed_context(config: BotConfig, guild_id: int | None, channel_id: int | None) -> bool:
    """Return True when the interaction happened in the configured guild and channel."""
    return (
        guild_id == config.discord_guild_id
        and channel_id == config.discord_command_channel_id
    )


def has_maintainer_access(config: BotConfig, role_ids: Iterable[int]) -> bool:
    """Return True when the member holds the maintainer role."""
    return config.discord_maintainer_role_id in set(role_ids)


def has_player_access(config: BotConfig, role_ids: Iterable[int]) -> bool:
    """Return True when the member holds the player or maintainer role."""
    roles = set(role_ids)
    return (
        config.discord_player_role_id in roles
        or config.discord_maintainer_role_id in roles
    )
