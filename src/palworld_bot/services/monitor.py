"""Background monitor: open/close notifications and idle auto-shutdown.

Polls ServerManager.status() on a fixed interval. Two responsibilities:

- Notify (via an injected callback) when Palworld transitions between
  running and not-running — the single source of "open/close" messages.
- Track how long the server has been running with zero players and trigger
  the normal safe-stop flow once the idle threshold is reached.

Sleeping is injectable so tests can drive ticks synchronously.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from palworld_bot.config import BotConfig
from palworld_bot.services.server_manager import (
    PalworldState,
    ServerManager,
    StatusReport,
    StopOutcome,
)

logger = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]
Reporter = Callable[[StatusReport], Awaitable[None]]
Sleeper = Callable[[float], Awaitable[None]]
PublicIpProvider = Callable[[], Awaitable[str | None]]

_OPENED_MESSAGE = "……灯が入った。開店だ。(Palworld: running)"
_CLOSED_MESSAGE = "灯が落ちた。店じまいだ。(Palworld: stopped)"
_AUTO_STOP_DONE_MESSAGE = "世界を封じ、写しを取って、灯を落とした。また声をかけな。"
_AUTO_STOP_FAILED_MESSAGE = "……自動の店じまいをしくじった。様子を見てくれ。"


class ServerMonitor:
    """Periodic status watcher; owns no Discord objects, only a notify callback."""

    def __init__(
        self,
        config: BotConfig,
        manager: ServerManager,
        notify: Notifier,
        *,
        on_report: Reporter | None = None,
        public_ip_provider: PublicIpProvider | None = None,
        sleep: Sleeper | None = None,
    ) -> None:
        self._config = config
        self._manager = manager
        self._notify = notify
        self._on_report = on_report
        self._public_ip_provider = public_ip_provider
        self._sleep: Sleeper = sleep if sleep is not None else self._asyncio_sleep
        self._last_running: bool | None = None
        self._idle_seconds = 0.0
        self._known_players: frozenset[str] = frozenset()
        self._players_tracked = False
        self._public_ip: str | None = None
        # Start due so the first tick establishes the baseline address.
        self._seconds_since_ip_check = float("inf")

    @staticmethod
    async def _asyncio_sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def run(self) -> None:
        while True:
            await self._sleep(self._config.status_poll_interval_seconds)
            try:
                await self.tick()
            except Exception:
                logger.exception("monitor tick failed")

    async def tick(self) -> None:
        # Refresh the address first so an "opened" notice can carry it.
        await self._handle_public_ip()
        report = await self._manager.status()
        running = report.palworld is PalworldState.RUNNING
        await self._handle_transition(running)
        await self._handle_players(report, running)
        await self._handle_idle(report, running)
        if self._on_report is not None:
            try:
                await self._on_report(report)
            except Exception:
                logger.warning("failed to report status for presence")

    @property
    def public_ip(self) -> str | None:
        """Most recent successfully looked-up public address, if any."""
        return self._public_ip

    def address_line(self) -> str | None:
        """`ip:port` for players to connect to, when the address is known."""
        if self._public_ip is None:
            return None
        return f"{self._public_ip}:{self._config.game_port}"

    async def _handle_public_ip(self) -> None:
        interval = self._config.public_ip_check_interval_seconds
        if self._public_ip_provider is None or interval <= 0:
            return
        self._seconds_since_ip_check += self._config.status_poll_interval_seconds
        if self._seconds_since_ip_check < interval:
            return
        self._seconds_since_ip_check = 0.0
        try:
            address = await self._public_ip_provider()
        except Exception:
            logger.warning("public IP lookup raised")
            return
        # A failed lookup keeps the last known value: never announce on flapping.
        if address is None or address == self._public_ip:
            return
        previous = self._public_ip
        self._public_ip = address
        if previous is None:
            return  # First successful read is the baseline.
        await self._safe_notify(
            f"店の場所が変わった。今度からはこっちだ……{address}:{self._config.game_port}"
        )

    async def _handle_transition(self, running: bool) -> None:
        previous = self._last_running
        self._last_running = running
        if previous is None or previous == running:
            return
        if not running:
            await self._safe_notify(_CLOSED_MESSAGE)
            return
        message = _OPENED_MESSAGE
        address = self.address_line()
        if address is not None:
            message = f"{message}\n場所はここだ……{address}"
        await self._safe_notify(message)

    async def _handle_players(self, report: StatusReport, running: bool) -> None:
        if not running or report.players is None:
            # No reliable roster: forget it so the next running tick re-baselines
            # (and don't announce departures — the close notification covers that).
            self._known_players = frozenset()
            self._players_tracked = False
            return
        # Trust the name list only when it matches the count; the names lookup
        # can fail independently of the count.
        if len(report.player_names) != report.players:
            return
        current = frozenset(report.player_names)
        if not self._players_tracked:
            # First roster after (re)start becomes the baseline, no announcements.
            self._known_players = current
            self._players_tracked = True
            return
        for name in sorted(current - self._known_players):
            await self._safe_notify(f"{name} が暖簾をくぐった。")
        for name in sorted(self._known_players - current):
            await self._safe_notify(f"{name} が去っていった。")
        self._known_players = current

    async def _handle_idle(self, report: StatusReport, running: bool) -> None:
        threshold_minutes = self._config.idle_shutdown_minutes
        if threshold_minutes <= 0:
            return
        if not (running and report.players == 0):
            # Not running, players connected, or count unknown: no idle credit.
            self._idle_seconds = 0.0
            return
        self._idle_seconds += self._config.status_poll_interval_seconds
        if self._idle_seconds < threshold_minutes * 60:
            return
        self._idle_seconds = 0.0
        await self._safe_notify(
            f"客足が {threshold_minutes} 分途絶えた。店を閉めさせてもらうぜ。"
        )
        result = await self._manager.stop(allow_with_players=False)
        if result.outcome is StopOutcome.STOPPED:
            # Suppress the redundant "closed" transition message next tick.
            self._last_running = False
            await self._safe_notify(_AUTO_STOP_DONE_MESSAGE)
        else:
            logger.warning("idle auto-shutdown did not complete: %s", result.outcome.name)
            await self._safe_notify(_AUTO_STOP_FAILED_MESSAGE)

    async def _safe_notify(self, message: str) -> None:
        try:
            await self._notify(message)
        except Exception:
            logger.warning("failed to deliver a monitor notification")
