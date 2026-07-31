from datetime import datetime

import discord

from palworld_bot.discord_app import (
    _format_address,
    _format_load,
    _format_presence,
    _format_status,
    _format_stop,
)
from palworld_bot.services.server_manager import (
    LoadReport,
    PalworldState,
    PcState,
    StatusReport,
    StopOutcome,
    StopResult,
)

_NOW = datetime(2026, 7, 25, 12, 0, 0)


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


def test_address_shows_ip_and_port() -> None:
    text = _format_address("203.0.113.5", 8211)
    assert "203.0.113.5:8211" in text


def test_address_unknown_is_explained() -> None:
    text = _format_address(None, 8211)
    assert "8211" not in text
    assert "掴めねえ" in text


def test_load_shows_game_and_os_figures() -> None:
    report = LoadReport(
        fps=57,
        fps_avg=58.4,
        uptime_seconds=3725,
        basecamps=3,
        players=2,
        loadavg=1.35,
        cpu_cores=8,
        mem_used_mb=5200,
        mem_total_mb=16000,
        disk_use_pct=23,
        disk_avail_gb=812,
        cpu_temp=52,
        game_backups=418,
    )
    text = _format_load(report)
    assert "57 / 60" in text  # fps against the target
    assert "58.4" in text  # average
    assert "1時間2分" in text  # uptime formatted
    assert "1.35" in text  # load average
    assert "8コア" in text  # core count gives the load meaning
    assert "17%" in text  # 1.35 / 8 cores
    assert "812" in text  # disk
    assert "52" in text  # temperature
    assert "418" in text  # backup generations


def test_load_without_core_count_says_so() -> None:
    text = _format_load(LoadReport(loadavg=1.35))
    assert "1.35" in text
    assert "コア数不明" in text


def test_cpu_usage_verdicts() -> None:
    assert "余裕あり" in _format_load(LoadReport(loadavg=1.0, cpu_cores=8))  # 12%
    assert "やや高い" in _format_load(LoadReport(loadavg=5.0, cpu_cores=8))  # 62%
    assert "高い" in _format_load(LoadReport(loadavg=7.5, cpu_cores=8))  # 94%


def test_load_omits_game_block_when_stopped() -> None:
    report = LoadReport(loadavg=0.08, mem_used_mb=900, mem_total_mb=16000)
    text = _format_load(report)
    assert "サーバーFPS" not in text
    assert "stopped" in text
    assert "0.08" in text


def test_load_unreachable_is_explained() -> None:
    assert "届かねえ" in _format_load(None)


def test_load_flags_heavy_server() -> None:
    assert "余裕あり" in _format_load(LoadReport(fps=58))
    assert "やや重い" in _format_load(LoadReport(fps=35))
    assert "重い" in _format_load(LoadReport(fps=18))


def test_presence_running_shows_count_and_online() -> None:
    report = StatusReport(PcState.ONLINE, PalworldState.RUNNING, 3, 8, _NOW)
    text, status = _format_presence(report)
    assert "3" in text and "8" in text
    assert status is discord.Status.online


def test_presence_stopped_is_idle() -> None:
    report = StatusReport(PcState.ONLINE, PalworldState.STOPPED, 0, 8, _NOW)
    text, status = _format_presence(report)
    assert "停止" in text
    assert status is discord.Status.idle


def test_presence_offline_is_idle() -> None:
    report = StatusReport(PcState.OFFLINE, PalworldState.UNKNOWN, None, None, _NOW)
    _text, status = _format_presence(report)
    assert status is discord.Status.idle
