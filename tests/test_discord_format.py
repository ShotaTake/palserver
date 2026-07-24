from datetime import datetime

from palworld_bot.discord_app import _format_status, _format_stop
from palworld_bot.services.server_manager import (
    PalworldState,
    PcState,
    StatusReport,
    StopOutcome,
    StopResult,
)


def test_status_keeps_data_readable_under_persona() -> None:
    report = StatusReport(
        PcState.ONLINE, PalworldState.RUNNING, 1, 8, datetime(2026, 7, 18, 5, 37, 11)
    )
    text = _format_status(report)
    # The flavour text must not hide the actual status data.
    assert "サーバーPC: online" in text
    assert "Palworld: running" in text
    assert "接続人数: 1 / 8" in text
    assert "2026-07-18 05:37:11" in text


def test_status_without_max_players() -> None:
    report = StatusReport(
        PcState.ONLINE, PalworldState.RUNNING, 1, None, datetime(2026, 7, 18, 5, 37, 11)
    )
    assert "接続人数: 1" in _format_status(report)


def test_status_shows_player_names_when_present() -> None:
    base = StatusReport(
        PcState.ONLINE,
        PalworldState.RUNNING,
        2,
        8,
        datetime(2026, 7, 25, 12, 0, 0),
        ("Alice", "Bob"),
    )
    text = _format_status(base)
    assert "客: Alice, Bob" in text


def test_status_omits_player_names_when_empty() -> None:
    base = StatusReport(
        PcState.ONLINE, PalworldState.RUNNING, 0, 8, datetime(2026, 7, 25, 12, 0, 0)
    )
    assert "客:" not in _format_status(base)


def test_stop_refused_still_reports_count_and_force_hint() -> None:
    text = _format_stop(StopResult(StopOutcome.REFUSED_PLAYERS_CONNECTED, players=2))
    assert "2" in text
    assert "force:True" in text
