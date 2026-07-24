"""Fixed remote commands over SSH.

Only the exact enum values below are ever sent to the server. Discord input
never reaches this module, and no shell is involved on the client side.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from enum import Enum

from palworld_bot.config import BotConfig

logger = logging.getLogger(__name__)

_SSH_CONNECTION_FAILURE_EXIT = 255


class RemoteCommand(Enum):
    """The only values the bot may execute remotely."""

    STATUS = "status"
    START = "start"
    PLAYERS = "players"
    RESTART = "restart"
    SHUTDOWN = "shutdown"
    BACKUP = "backup"
    POWEROFF = "poweroff"


@dataclass(frozen=True, slots=True)
class SshResult:
    """Outcome of one remote command. ``exit_code`` is None on timeout."""

    exit_code: int | None
    stdout: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def connection_failed(self) -> bool:
        return self.exit_code is None or self.exit_code == _SSH_CONNECTION_FAILURE_EXIT


def build_ssh_args(
    config: BotConfig,
    command: RemoteCommand,
    *,
    ssh_path: str | None = None,
) -> list[str]:
    """Build the fixed ssh argument list for one remote command."""
    if ssh_path is None:
        ssh_path = shutil.which("ssh")
    if ssh_path is None:
        raise FileNotFoundError("ssh executable not found on PATH")
    return [
        ssh_path,
        "-i",
        config.server_ssh_key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        f"UserKnownHostsFile={config.server_ssh_known_hosts_path}",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        f"{config.server_ssh_user}@{config.server_ssh_host}",
        command.value,
    ]


async def run_remote(
    config: BotConfig,
    command: RemoteCommand,
    *,
    timeout_seconds: float | None = None,
) -> SshResult:
    """Run one fixed remote command and capture its output."""
    if timeout_seconds is None:
        timeout_seconds = config.ssh_command_timeout_seconds
    args = build_ssh_args(config, command)
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("ssh %s timed out after %ss", command.value, timeout_seconds)
        return SshResult(exit_code=None, stdout="")
    if process.returncode != 0:
        logger.warning(
            "ssh %s exited %s: %s",
            command.value,
            process.returncode,
            stderr.decode(errors="replace").strip(),
        )
    return SshResult(exit_code=process.returncode, stdout=stdout.decode(errors="replace"))
