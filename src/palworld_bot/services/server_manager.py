"""Status/start/stop orchestration.

Holds the single asyncio.Lock that prevents concurrent start/stop operations.
Network side effects (SSH, WOL) are injectable for testing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
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
    player_names: tuple[str, ...] = ()


class StartOutcome(Enum):
    STARTED = auto()
    ALREADY_RUNNING = auto()
    BUSY = auto()
    BOOT_TIMEOUT = auto()
    START_FAILED = auto()


@dataclass(frozen=True, slots=True)
class LoadReport:
    """How hard the machine is working. Every field is None when unavailable."""

    fps: int | None = None
    fps_avg: float | None = None
    frametime: float | None = None
    uptime_seconds: int | None = None
    game_days: int | None = None
    basecamps: int | None = None
    players: int | None = None
    loadavg: float | None = None
    mem_used_mb: int | None = None
    mem_total_mb: int | None = None
    disk_use_pct: int | None = None
    disk_avail_gb: int | None = None
    cpu_temp: int | None = None
    game_backups: int | None = None

    @property
    def has_game_metrics(self) -> bool:
        return self.fps is not None


class RestartOutcome(Enum):
    RESTARTED = auto()
    BUSY = auto()
    UNREACHABLE = auto()
    RESTART_FAILED = auto()


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


def _parse_key_values(stdout: str) -> dict[str, str]:
    """Read the `key=value` lines the server-side script emits."""
    values: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key:
            values[key] = value.strip()
    return values


def _as_int(values: Mapping[str, str], key: str) -> int | None:
    try:
        return int(values[key])
    except (KeyError, ValueError):
        return None


def _as_float(values: Mapping[str, str], key: str) -> float | None:
    try:
        return float(values[key])
    except (KeyError, ValueError):
        return None


def _parse_player_names(stdout: str) -> tuple[str, ...]:
    names = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("player="):
            name = line.removeprefix("player=").strip()
            if name:
                names.append(name)
    return tuple(names)


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
        # Shutdown, restart, and backup can take longer than a status probe.
        if command in (RemoteCommand.SHUTDOWN, RemoteCommand.RESTART, RemoteCommand.BACKUP):
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
        player_names: tuple[str, ...] = ()
        if palworld is PalworldState.RUNNING:
            players_result = await self._ssh_runner(RemoteCommand.PLAYERS)
            if players_result.ok:
                players, max_players = _parse_players(players_result.stdout)
                player_names = _parse_player_names(players_result.stdout)
        elif palworld is PalworldState.STOPPED:
            players = 0
        return StatusReport(
            PcState.ONLINE, palworld, players, max_players, checked_at, player_names
        )

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

    async def load(self) -> LoadReport | None:
        """Current load figures, or None when the machine cannot be reached."""
        result = await self._ssh_runner(RemoteCommand.METRICS)
        if not result.ok:
            return None
        values = _parse_key_values(result.stdout)
        return LoadReport(
            fps=_as_int(values, "fps"),
            fps_avg=_as_float(values, "fps_avg"),
            frametime=_as_float(values, "frametime"),
            uptime_seconds=_as_int(values, "uptime"),
            game_days=_as_int(values, "game_days"),
            basecamps=_as_int(values, "basecamps"),
            players=_as_int(values, "players"),
            loadavg=_as_float(values, "loadavg"),
            mem_used_mb=_as_int(values, "mem_used_mb"),
            mem_total_mb=_as_int(values, "mem_total_mb"),
            disk_use_pct=_as_int(values, "disk_use_pct"),
            disk_avail_gb=_as_int(values, "disk_avail_gb"),
            cpu_temp=_as_int(values, "cpu_temp"),
            game_backups=_as_int(values, "game_backups"),
        )

    async def restart(self) -> RestartOutcome:
        """Save the world and restart only the Palworld service (no poweroff)."""
        if self._lock.locked():
            return RestartOutcome.BUSY
        async with self._lock:
            probe = await self._ssh_runner(RemoteCommand.STATUS)
            if probe.connection_failed:
                return RestartOutcome.UNREACHABLE
            result = await self._ssh_runner(RemoteCommand.RESTART)
            if not result.ok:
                return RestartOutcome.RESTART_FAILED
            verify = await self._ssh_runner(RemoteCommand.STATUS)
            if verify.ok and _parse_palworld_state(verify.stdout) is PalworldState.RUNNING:
                return RestartOutcome.RESTARTED
            return RestartOutcome.RESTART_FAILED

    async def _wait_for_ssh(self) -> bool:
        # Count each attempt's real cost — the poll interval *and* the probe's
        # own timeout — so server_boot_timeout_seconds reflects wall-clock time.
        # (An unreachable host makes each probe take ssh_command_timeout_seconds,
        # which would otherwise not be counted at all.)
        waited = 0.0
        per_attempt = _BOOT_POLL_INTERVAL_SECONDS + self._config.ssh_command_timeout_seconds
        while waited < self._config.server_boot_timeout_seconds:
            await self._sleep(_BOOT_POLL_INTERVAL_SECONDS)
            probe = await self._ssh_runner(RemoteCommand.STATUS)
            if not probe.connection_failed:
                return True
            waited += per_attempt
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
