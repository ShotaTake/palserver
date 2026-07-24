from datetime import datetime

from palworld_bot.config import load_config
from palworld_bot.services.monitor import ServerMonitor
from palworld_bot.services.server_manager import (
    PalworldState,
    PcState,
    StatusReport,
    StopOutcome,
    StopResult,
)
from tests.test_config import BASE_ENV

# Poll every 60s, auto-shutdown after 2 idle minutes -> 2 consecutive idle ticks.
CONFIG = load_config(
    {**BASE_ENV, "STATUS_POLL_INTERVAL_SECONDS": "60", "IDLE_SHUTDOWN_MINUTES": "2"}
)


def report(
    *, running: bool, players: int | None, names: tuple[str, ...] = ()
) -> StatusReport:
    state = PalworldState.RUNNING if running else PalworldState.STOPPED
    pc = PcState.ONLINE if running or players is not None else PcState.OFFLINE
    return StatusReport(pc, state, players, None, datetime(2026, 7, 25, 12, 0, 0), names)


OFFLINE = StatusReport(
    PcState.OFFLINE, PalworldState.UNKNOWN, None, None, datetime(2026, 7, 25, 12, 0, 0)
)


class FakeManager:
    def __init__(self, reports: list[StatusReport]) -> None:
        self._reports = list(reports)
        self.stop_calls: list[bool] = []
        self.stop_result = StopResult(StopOutcome.STOPPED)

    async def status(self) -> StatusReport:
        if len(self._reports) > 1:
            return self._reports.pop(0)
        return self._reports[0]

    async def stop(self, *, allow_with_players: bool) -> StopResult:
        self.stop_calls.append(allow_with_players)
        return self.stop_result


def make_monitor(manager: FakeManager) -> tuple[ServerMonitor, list[str]]:
    sent: list[str] = []

    async def notify(message: str) -> None:
        sent.append(message)

    monitor = ServerMonitor(CONFIG, manager, notify)  # type: ignore[arg-type]
    return monitor, sent


async def test_idle_threshold_triggers_safe_stop() -> None:
    manager = FakeManager([report(running=True, players=0)])
    monitor, sent = make_monitor(manager)
    await monitor.tick()  # idle 60s
    assert manager.stop_calls == []
    await monitor.tick()  # idle 120s -> threshold
    assert manager.stop_calls == [False]  # never force through connected players
    assert any("店を閉め" in m for m in sent)
    assert any("灯を落とした" in m for m in sent)


async def test_connected_player_resets_idle_timer() -> None:
    manager = FakeManager(
        [
            report(running=True, players=0),
            report(running=True, players=1),
            report(running=True, players=0),
            report(running=True, players=0),
        ]
    )
    monitor, _ = make_monitor(manager)
    await monitor.tick()  # idle 60s
    await monitor.tick()  # player online -> reset
    await monitor.tick()  # idle 60s again
    assert manager.stop_calls == []
    await monitor.tick()  # idle 120s -> now it fires
    assert manager.stop_calls == [False]


async def test_transition_notifications() -> None:
    manager = FakeManager(
        [
            report(running=False, players=0),
            report(running=True, players=1),
            report(running=False, players=0),
        ]
    )
    monitor, sent = make_monitor(manager)
    await monitor.tick()  # baseline, no notification
    assert sent == []
    await monitor.tick()
    assert any("開店" in m for m in sent)
    await monitor.tick()
    assert any("店じまい" in m for m in sent)


async def test_auto_stop_suppresses_duplicate_close_notice() -> None:
    manager = FakeManager(
        [
            report(running=True, players=0),
            report(running=True, players=0),
            report(running=False, players=0),
        ]
    )
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()  # auto stop fires here
    await monitor.tick()  # server now stopped; no extra "closed" notice
    assert not any("店じまい" in m for m in sent)


async def test_disabled_when_threshold_zero() -> None:
    config = load_config({**BASE_ENV, "IDLE_SHUTDOWN_MINUTES": "0"})
    manager = FakeManager([report(running=True, players=0)])
    sent: list[str] = []

    async def notify(message: str) -> None:
        sent.append(message)

    monitor = ServerMonitor(config, manager, notify)  # type: ignore[arg-type]
    for _ in range(10):
        await monitor.tick()
    assert manager.stop_calls == []


async def test_offline_does_not_accumulate_idle() -> None:
    manager = FakeManager(
        [
            report(running=True, players=0),
            OFFLINE,
            report(running=True, players=0),
        ]
    )
    monitor, _ = make_monitor(manager)
    await monitor.tick()  # idle 60s
    await monitor.tick()  # offline -> reset
    await monitor.tick()  # idle 60s again; threshold (120s) not reached
    assert manager.stop_calls == []


async def test_join_and_leave_notifications() -> None:
    manager = FakeManager(
        [
            report(running=True, players=1, names=("Alice",)),  # baseline
            report(running=True, players=2, names=("Alice", "Bob")),  # Bob joins
            report(running=True, players=1, names=("Alice",)),  # Bob leaves
        ]
    )
    monitor, sent = make_monitor(manager)
    await monitor.tick()  # baseline: no per-player announcement
    assert not any("Alice" in m for m in sent)
    await monitor.tick()
    assert any("Bob" in m and "くぐった" in m for m in sent)
    await monitor.tick()
    assert any("Bob" in m and "去って" in m for m in sent)


async def test_missing_roster_does_not_emit_false_leaves() -> None:
    manager = FakeManager(
        [
            report(running=True, players=1, names=("Alice",)),  # baseline {Alice}
            report(running=True, players=2, names=()),  # names lookup failed -> skip
            report(running=True, players=1, names=("Alice",)),  # unchanged
        ]
    )
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()
    await monitor.tick()
    assert sent == []


async def test_stop_refusal_is_reported_not_fatal() -> None:
    manager = FakeManager([report(running=True, players=0)])
    manager.stop_result = StopResult(StopOutcome.REFUSED_PLAYERS_CONNECTED, players=1)
    monitor, sent = make_monitor(manager)
    await monitor.tick()
    await monitor.tick()  # fires, but stop refuses
    assert manager.stop_calls == [False]
    assert any("しくじった" in m for m in sent)