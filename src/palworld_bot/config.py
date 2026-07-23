"""Environment parsing and validation.

Secrets (the Discord bot token) must never be logged or echoed back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_MAC_ADDRESS_RE = re.compile(r"^[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}$")
_ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


class ConfigError(ValueError):
    """Raised when the environment configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class BotConfig:
    """Validated bot configuration."""

    # repr=False keeps the token out of accidental repr()/logging output.
    discord_bot_token: str = field(repr=False)
    discord_guild_id: int
    discord_command_channel_id: int
    discord_audit_channel_id: int | None
    discord_player_role_id: int
    discord_maintainer_role_id: int
    server_mac_address: str
    server_lan_broadcast: str
    server_ssh_host: str
    server_ssh_user: str
    server_ssh_key_path: str
    server_ssh_known_hosts_path: str
    wol_repeat_count: int
    wol_repeat_interval_seconds: float
    server_boot_timeout_seconds: int
    ssh_command_timeout_seconds: int
    stop_wait_seconds: int
    log_level: str
    pal_image_dir: str | None


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _require_int(env: Mapping[str, str], key: str) -> int:
    raw = _require(env, key)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None


def _optional_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None


def _positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def _positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number") from None
    if value <= 0:
        raise ConfigError(f"{key} must be positive")
    return value


def load_config(env: Mapping[str, str]) -> BotConfig:
    """Build a validated :class:`BotConfig` from an environment mapping."""
    mac_address = _require(env, "SERVER_MAC_ADDRESS")
    if not _MAC_ADDRESS_RE.match(mac_address):
        raise ConfigError("SERVER_MAC_ADDRESS must look like AA:BB:CC:DD:EE:FF")

    log_level = env.get("LOG_LEVEL", "").strip().upper() or "INFO"
    if log_level not in _ALLOWED_LOG_LEVELS:
        raise ConfigError("LOG_LEVEL must be one of DEBUG, INFO, WARNING, ERROR")

    return BotConfig(
        discord_bot_token=_require(env, "DISCORD_BOT_TOKEN"),
        discord_guild_id=_require_int(env, "DISCORD_GUILD_ID"),
        discord_command_channel_id=_require_int(env, "DISCORD_COMMAND_CHANNEL_ID"),
        discord_audit_channel_id=_optional_int(env, "DISCORD_AUDIT_CHANNEL_ID"),
        discord_player_role_id=_require_int(env, "DISCORD_PLAYER_ROLE_ID"),
        discord_maintainer_role_id=_require_int(env, "DISCORD_MAINTAINER_ROLE_ID"),
        server_mac_address=mac_address,
        server_lan_broadcast=_require(env, "SERVER_LAN_BROADCAST"),
        server_ssh_host=_require(env, "SERVER_TAILSCALE_HOST"),
        server_ssh_user=_require(env, "SERVER_SSH_USER"),
        server_ssh_key_path=_require(env, "SERVER_SSH_KEY_PATH"),
        server_ssh_known_hosts_path=_require(env, "SERVER_SSH_KNOWN_HOSTS_PATH"),
        wol_repeat_count=_positive_int(env, "WOL_REPEAT_COUNT", 3),
        wol_repeat_interval_seconds=_positive_float(env, "WOL_REPEAT_INTERVAL_SECONDS", 1.0),
        server_boot_timeout_seconds=_positive_int(env, "SERVER_BOOT_TIMEOUT_SECONDS", 240),
        ssh_command_timeout_seconds=_positive_int(env, "SSH_COMMAND_TIMEOUT_SECONDS", 20),
        stop_wait_seconds=_positive_int(env, "STOP_WAIT_SECONDS", 60),
        log_level=log_level,
        pal_image_dir=env.get("PAL_IMAGE_DIR", "").strip() or None,
    )
