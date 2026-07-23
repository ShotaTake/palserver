import pytest

from palworld_bot.config import ConfigError, load_config

BASE_ENV = {
    "DISCORD_BOT_TOKEN": "dummy-token",  # noqa: S106 - test fixture, not a real secret
    "DISCORD_GUILD_ID": "100",
    "DISCORD_COMMAND_CHANNEL_ID": "200",
    "DISCORD_AUDIT_CHANNEL_ID": "300",
    "DISCORD_PLAYER_ROLE_ID": "400",
    "DISCORD_MAINTAINER_ROLE_ID": "500",
    "SERVER_MAC_ADDRESS": "AA:BB:CC:DD:EE:FF",
    "SERVER_LAN_BROADCAST": "192.168.1.255",
    "SERVER_TAILSCALE_HOST": "palworld-server",
    "SERVER_SSH_USER": "palbotctl",
    "SERVER_SSH_KEY_PATH": "/keys/id_ed25519",
    "SERVER_SSH_KNOWN_HOSTS_PATH": "/keys/known_hosts",
}


def test_load_config_success() -> None:
    config = load_config(BASE_ENV)
    assert config.discord_guild_id == 100
    assert config.discord_command_channel_id == 200
    assert config.discord_audit_channel_id == 300
    assert config.discord_player_role_id == 400
    assert config.discord_maintainer_role_id == 500
    assert config.server_ssh_host == "palworld-server"
    assert config.wol_repeat_count == 3
    assert config.server_boot_timeout_seconds == 240
    assert config.log_level == "INFO"


def test_audit_channel_is_optional() -> None:
    env = {**BASE_ENV, "DISCORD_AUDIT_CHANNEL_ID": ""}
    assert load_config(env).discord_audit_channel_id is None


def test_pal_image_dir_is_optional() -> None:
    assert load_config(BASE_ENV).pal_image_dir is None
    env = {**BASE_ENV, "PAL_IMAGE_DIR": "/var/lib/palworld-bot/pals"}
    assert load_config(env).pal_image_dir == "/var/lib/palworld-bot/pals"


def test_missing_token_raises() -> None:
    env = {**BASE_ENV, "DISCORD_BOT_TOKEN": ""}
    with pytest.raises(ConfigError, match="DISCORD_BOT_TOKEN"):
        load_config(env)


def test_non_integer_guild_id_raises() -> None:
    env = {**BASE_ENV, "DISCORD_GUILD_ID": "not-a-number"}
    with pytest.raises(ConfigError, match="DISCORD_GUILD_ID"):
        load_config(env)


def test_invalid_mac_address_raises() -> None:
    env = {**BASE_ENV, "SERVER_MAC_ADDRESS": "AA:BB:CC:DD:EE"}
    with pytest.raises(ConfigError, match="SERVER_MAC_ADDRESS"):
        load_config(env)


def test_invalid_log_level_raises() -> None:
    env = {**BASE_ENV, "LOG_LEVEL": "VERBOSE"}
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_config(env)


def test_non_positive_timeout_raises() -> None:
    env = {**BASE_ENV, "SSH_COMMAND_TIMEOUT_SECONDS": "0"}
    with pytest.raises(ConfigError, match="SSH_COMMAND_TIMEOUT_SECONDS"):
        load_config(env)


def test_token_not_in_repr() -> None:
    config = load_config(BASE_ENV)
    assert "dummy-token" not in repr(config)
