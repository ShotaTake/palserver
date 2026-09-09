from datetime import datetime

import discord

from gameserver_bot.discord_app import (
    _format_address,
    _format_load,
    _format_presence,
    _format_status,
    _format_stop,
)
from gameserver_bot.services.server_manager import (
    GameState,
    LoadReport,
    PcState,
    StatusReport,
    StopOutcome,
    StopResult,
)

_NOW = datetime(2026, 7, 25, 12, 0, 0)


def test_status_keeps_data_readable_under_persona() -> None:
    report = StatusReport(
        PcState.ONLINE, GameState.RUNNING, 1, 8, datetime(2026, 7, 18, 5, 37, 11)
    )
    text = _format_status(report, "Valheim")
    # The flavour text must not hide the actual status data.
    assert "サーバーPC: online" in text
    assert "Valheim: running" in text
    assert "接続人数: 1 / 8" in text
    assert "2026-07-18 05:37:11" in text


def test_status_without_max_players() -> None:
    report = StatusReport(
        PcState.ONLINE, GameState.RUNNING, 1, None, datetime(2026, 7, 18, 5, 37, 11)
    )
    assert "接続人数: 1" in _format_status(report, "Valheim")


def test_status_shows_player_names_when_present() -> None:
    base = StatusReport(
        PcState.ONLINE,
        GameState.RUNNING,
        2,
        8,
        datetime(2026, 7, 25, 12, 0, 0),
        ("Alice", "Bob"),
    )
    text = _format_status(base, "Valheim")
    assert "客: Alice, Bob" in text


def test_status_omits_player_names_when_empty() -> None:
    base = StatusReport(
        PcState.ONLINE, GameState.RUNNING, 0, 8, datetime(2026, 7, 25, 12, 0, 0)
    )
    assert "客:" not in _format_status(base, "Valheim")


def test_stop_refused_still_reports_count_and_force_hint() -> None:
    text = _format_stop(StopResult(StopOutcome.REFUSED_PLAYERS_CONNECTED, players=2))
    assert "2" in text
    assert "force:True" in text


def test_address_shows_ip_and_port() -> None:
    text = _format_address("203.0.113.5", 8211)
    assert "203.0.113.5:8211" in text


def test_address_unknown_is_explained() -> None:
    text = _format_address(None, 8211)
    assert "8211" not in text
    assert "掴めねえ" in text


def test_load_shows_game_and_os_figures() -> None:
    report = LoadReport(
        players=2,
        max_players=10,
        uptime_seconds=3725,
        loadavg=1.35,
        cpu_cores=8,
        mem_used_mb=5200,
        mem_total_mb=16000,
        disk_use_pct=23,
        disk_avail_gb=812,
        cpu_temp=52,
    )
    text = _format_load(report, "Valheim")
    assert "接続人数: 2 / 10" in text
    assert "1時間2分" in text  # uptime formatted
    assert "1.35" in text  # load average
    assert "8コア" in text  # core count gives the load meaning
    assert "17%" in text  # 1.35 / 8 cores
    assert "812" in text  # disk
    assert "52" in text  # temperature


def test_load_without_core_count_says_so() -> None:
    text = _format_load(LoadReport(loadavg=1.35), "Valheim")
    assert "1.35" in text
    assert "コア数不明" in text


def test_cpu_usage_verdicts() -> None:
    assert "余裕あり" in _format_load(LoadReport(loadavg=1.0, cpu_cores=8), "Valheim")  # 12%
    assert "やや高い" in _format_load(LoadReport(loadavg=5.0, cpu_cores=8), "Valheim")  # 62%
    assert "高い" in _format_load(LoadReport(loadavg=7.5, cpu_cores=8), "Valheim")  # 94%


def test_load_omits_game_block_when_stopped() -> None:
    report = LoadReport(loadavg=0.08, mem_used_mb=900, mem_total_mb=16000)
    text = _format_load(report, "Valheim")
    assert "接続人数" not in text
    assert "Valheim: stopped" in text
    assert "0.08" in text


def test_load_unreachable_is_explained() -> None:
    assert "届かねえ" in _format_load(None, "Valheim")


def test_presence_running_shows_count_and_online() -> None:
    report = StatusReport(PcState.ONLINE, GameState.RUNNING, 3, 8, _NOW)
    text, status = _format_presence(report)
    assert "3" in text and "8" in text
    assert status is discord.Status.online


def test_presence_stopped_is_idle() -> None:
    report = StatusReport(PcState.ONLINE, GameState.STOPPED, 0, 8, _NOW)
    text, status = _format_presence(report)
    assert "停止" in text
    assert status is discord.Status.idle


def test_presence_offline_is_idle() -> None:
    report = StatusReport(PcState.OFFLINE, GameState.UNKNOWN, None, None, _NOW)
    _text, status = _format_presence(report)
    assert status is discord.Status.idle
