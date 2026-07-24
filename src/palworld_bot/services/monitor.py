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
Sleeper = Callable[[float], Awaitable[None]]

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
        sleep: Sleeper | None = None,
    ) -> None:
        self._config = config
        self._manager = manager
        self._notify = notify
        self._sleep: Sleeper = sleep if sleep is not None else self._asyncio_sleep
        self._last_running: bool | None = None
        self._idle_seconds = 0.0

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
        report = await self._manager.status()
        running = report.palworld is PalworldState.RUNNING
        await self._handle_transition(running)
        await self._handle_idle(report, running)

    async def _handle_transition(self, running: bool) -> None:
        previous = self._last_running
        self._last_running = running
        if previous is None or previous == running:
            return
        await self._safe_notify(_OPENED_MESSAGE if running else _CLOSED_MESSAGE)

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
