from palworld_bot import auth
from palworld_bot.config import load_config
from tests.test_config import BASE_ENV

CONFIG = load_config(BASE_ENV)

PLAYER_ROLE = CONFIG.discord_player_role_id
MAINTAINER_ROLE = CONFIG.discord_maintainer_role_id


def test_allowed_context() -> None:
    assert auth.is_allowed_context(CONFIG, 100, 200)


def test_wrong_guild_rejected() -> None:
    assert not auth.is_allowed_context(CONFIG, 999, 200)


def test_wrong_channel_rejected() -> None:
    assert not auth.is_allowed_context(CONFIG, 100, 999)


def test_missing_ids_rejected() -> None:
    assert not auth.is_allowed_context(CONFIG, None, None)


def test_player_role_grants_player_access() -> None:
    assert auth.has_player_access(CONFIG, [PLAYER_ROLE])


def test_maintainer_role_grants_player_access() -> None:
    assert auth.has_player_access(CONFIG, [MAINTAINER_ROLE])


def test_no_role_denies_player_access() -> None:
    assert not auth.has_player_access(CONFIG, [123, 456])


def test_maintainer_access_requires_maintainer_role() -> None:
    assert auth.has_maintainer_access(CONFIG, [MAINTAINER_ROLE])
    assert not auth.has_maintainer_access(CONFIG, [PLAYER_ROLE])
