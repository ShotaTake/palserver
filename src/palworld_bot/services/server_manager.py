"""Status/start/stop orchestration.

Holds the single asyncio.Lock that prevents concurrent start/stop operations.
Network side effects (SSH, WOL) are injectable for testing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from palworld_bot.config import BotConfig
from palworld_bot.services import ssh_control, wol
from palworld_bot.services.ssh_control import RemoteCommand, SshResult

SshRunner = Callable[[RemoteCommand], Awaitable[SshResult]]
WolSender = Callable[[], Awaitable[int]]
Sleeper = Callable[[float], Awaitable[None]]

_BOOT_POLL_INTERVAL_SECONDS = 5.0


class PcState(Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    UNKNOWN = "unknown"


class PalworldState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StatusReport:
    pc: PcState
    palworld: PalworldState
    players: int | None
    max_players: int | None
    checked_at: datetime


class StartOutcome(Enum):
    STARTED = auto()
    ALREADY_RUNNING = auto()
    BUSY = auto()
    BOOT_TIMEOUT = auto()
    START_FAILED = auto()


class StopOutcome(Enum):
    STOPPED = auto()
    REFUSED_PLAYERS_CONNECTED = auto()
    BUSY = auto()
    UNREACHABLE = auto()
    SHUTDOWN_FAILED = auto()
    BACKUP_FAILED = auto()
    POWEROFF_FAILED = auto()


@dataclass(frozen=True, slots=True)
class StopResult:
    outcome: StopOutcome
    players: int | None = None


def _parse_palworld_state(stdout: str) -> PalworldState:
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line == "palworld=running":
            return PalworldState.RUNNING
        if line == "palworld=stopped":
            return PalworldState.STOPPED
    return PalworldState.UNKNOWN


def _parse_players(stdout: str) -> tuple[int | None, int | None]:
    players: int | None = None
    max_players: int | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("players="):
            try:
                players = int(line.removeprefix("players="))
            except ValueError:
                players = None
        elif line.startswith("max_players="):
            try:
                max_players = int(line.removeprefix("max_players="))
            except ValueError:
                max_players = None
    return players, max_players


class ServerManager:
    """Orchestrates the three MVP operations against the remote server."""

    def __init__(
        self,
        config: BotConfig,
        *,
        ssh_runner: SshRunner | None = None,
        wol_sender: WolSender | None = None,
        sleep: Sleeper | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._ssh_runner: SshRunner = ssh_runner if ssh_runner is not None else self._run_ssh
        self._wol_sender: WolSender = wol_sender if wol_sender is not None else self._send_wol
        self._sleep: Sleeper = sleep if sleep is not None else self._asyncio_sleep
        self._now: Callable[[], datetime] = now if now is not None else datetime.now
        self._lock = asyncio.Lock()

    @staticmethod
    async def _asyncio_sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _run_ssh(self, command: RemoteCommand) -> SshResult:
        # Shutdown and backup can legitimately take longer than a status probe.
        if command in (RemoteCommand.SHUTDOWN, RemoteCommand.BACKUP):
            timeout: float = self._config.stop_wait_seconds
        else:
            timeout = self._config.ssh_command_timeout_seconds
        return await ssh_control.run_remote(self._config, command, timeout_seconds=timeout)

    async def _send_wol(self) -> int:
        return await asyncio.to_thread(
            wol.send_magic_packets,
            self._config.server_mac_address,
            self._config.server_lan_broadcast,
            count=self._config.wol_repeat_count,
            interval_seconds=self._config.wol_repeat_interval_seconds,
        )

    async def status(self) -> StatusReport:
        checked_at = self._now()
        result = await self._ssh_runner(RemoteCommand.STATUS)
        if result.connection_failed:
            return StatusReport(PcState.OFFLINE, PalworldState.UNKNOWN, None, None, checked_at)
        if not result.ok:
            return StatusReport(PcState.ONLINE, PalworldState.UNKNOWN, None, None, checked_at)
        palworld = _parse_palworld_state(result.stdout)
        players: int | None = None
        max_players: int | None = None
        if palworld is PalworldState.RUNNING:
            players_result = await self._ssh_runner(RemoteCommand.PLAYERS)
            if players_result.ok:
                players, max_players = _parse_players(players_result.stdout)
        elif palworld is PalworldState.STOPPED:
            players = 0
        return StatusReport(PcState.ONLINE, palworld, players, max_players, checked_at)

    async def start(self) -> StartOutcome:
        if self._lock.locked():
            return StartOutcome.BUSY
        async with self._lock:
            probe = await self._ssh_runner(RemoteCommand.STATUS)
            if probe.ok and _parse_palworld_state(probe.stdout) is PalworldState.RUNNING:
                return StartOutcome.ALREADY_RUNNING
            if probe.connection_failed:
                await self._wol_sender()
                if not await self._wait_for_ssh():
                    return StartOutcome.BOOT_TIMEOUT
            start_result = await self._ssh_runner(RemoteCommand.START)
            if not start_result.ok:
                return StartOutcome.START_FAILED
            verify = await self._ssh_runner(RemoteCommand.STATUS)
            if verify.ok and _parse_palworld_state(verify.stdout) is PalworldState.RUNNING:
                return StartOutcome.STARTED
            return StartOutcome.START_FAILED

    async def _wait_for_ssh(self) -> bool:
        waited = 0.0
        while waited < self._config.server_boot_timeout_seconds:
            await self._sleep(_BOOT_POLL_INTERVAL_SECONDS)
            waited += _BOOT_POLL_INTERVAL_SECONDS
            probe = await self._ssh_runner(RemoteCommand.STATUS)
            if not probe.connection_failed:
                return True
        return False

    async def stop(self, *, allow_with_players: bool) -> StopResult:
        if self._lock.locked():
            return StopResult(StopOutcome.BUSY)
        async with self._lock:
            players_result = await self._ssh_runner(RemoteCommand.PLAYERS)
            if players_result.connection_failed:
                return StopResult(StopOutcome.UNREACHABLE)
            players, _ = (
                _parse_players(players_result.stdout) if players_result.ok else (None, None)
            )
            if not allow_with_players and (players is None or players > 0):
                # Unknown player count is treated as "someone may be connected".
                return StopResult(StopOutcome.REFUSED_PLAYERS_CONNECTED, players=players)
            shutdown_result = await self._ssh_runner(RemoteCommand.SHUTDOWN)
            if not shutdown_result.ok:
                return StopResult(StopOutcome.SHUTDOWN_FAILED, players=players)
            backup_result = await self._ssh_runner(RemoteCommand.BACKUP)
            if not backup_result.ok:
                # Never power off when the backup did not succeed.
                return StopResult(StopOutcome.BACKUP_FAILED, players=players)
            poweroff_result = await self._ssh_runner(RemoteCommand.POWEROFF)
            # The connection dropping mid-poweroff means the machine went down.
            if poweroff_result.ok or poweroff_result.connection_failed:
                return StopResult(StopOutcome.STOPPED, players=players)
            return StopResult(StopOutcome.POWEROFF_FAILED, players=players)
