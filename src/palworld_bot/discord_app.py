"""Slash command handlers only.

Handlers never run subprocesses directly and never expose raw exceptions or
command output to Discord.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from palworld_bot import auth, pals
from palworld_bot.config import BotConfig
from palworld_bot.services.monitor import ServerMonitor
from palworld_bot.services.server_manager import (
    PalworldState,
    PcState,
    RestartOutcome,
    ServerManager,
    StartOutcome,
    StatusReport,
    StopOutcome,
    StopResult,
)

logger = logging.getLogger(__name__)

# The bot speaks as Palworld's Black Marketeer (闇商人): a gruff, shady dealer.
# The flavour is prose only — the actual status data stays plain and readable.
_GENERIC_ERROR_MESSAGE = "……ちっ、裏で厄介事だ。番人（ログ）に聞いてくれ。"

_START_MESSAGES = {
    StartOutcome.STARTED: "……よかろう、灯を入れてやった。せいぜい楽しむがいい。",
    StartOutcome.ALREADY_RUNNING: "はっ、とっくに開いてるぜ。目ん玉ついてんのか？",
    StartOutcome.BUSY: "今は別の商いの最中でな。少し待ちな。",
    StartOutcome.BOOT_TIMEOUT: (
        "起こしの狼煙（WOL）は上げたが……あの箱、うんともすんとも言わねえ。出直しな。"
    ),
    StartOutcome.START_FAILED: "……しくじった。番人（ログ）に事情を聞きな。",
}

_RESTART_MESSAGES = {
    RestartOutcome.RESTARTED: "一度店を畳んで、開け直した。……文句はねえな？",
    RestartOutcome.BUSY: "今は別の商いの最中でな。少し待ちな。",
    RestartOutcome.UNREACHABLE: "……箱に手が届かねえ。店が開いてるかも怪しいぜ。",
    RestartOutcome.RESTART_FAILED: "建て直しにしくじった。番人（ログ）に聞きな。",
}


def _format_status(report: StatusReport) -> str:
    lines = [
        "……様子が知りたいってのかい。ほらよ、目を通しな。",
        "",
        f"サーバーPC: {report.pc.value}",
        f"Palworld: {report.palworld.value}",
    ]
    if report.players is not None:
        if report.max_players is not None:
            lines.append(f"接続人数: {report.players} / {report.max_players}")
        else:
            lines.append(f"接続人数: {report.players}")
    if report.player_names:
        lines.append("客: " + ", ".join(report.player_names))
    lines.append(f"確認時刻: {report.checked_at:%Y-%m-%d %H:%M:%S}")
    return "\n".join(lines)


def _format_stop(result: StopResult) -> str:
    outcome = result.outcome
    if outcome is StopOutcome.STOPPED:
        return "商いは仕舞いだ。世界を封じ、写しを取って、灯を落とした。またおいで。"
    if outcome is StopOutcome.REFUSED_PLAYERS_CONNECTED:
        if result.players is None:
            return (
                "客がいるかどうかも分からねえ。うかつに店は閉められねえな。"
                "……Maintainer なら force:True で押し通せるがよ。"
            )
        return (
            f"客がまだ {result.players} 人ばかり残ってら。無粋な真似はよせ。"
            "……どうしてもってなら、Maintainer の力を見せてみな（force:True）。"
        )
    if outcome is StopOutcome.BUSY:
        return "今は別の商いの最中でな。少し待ちな。"
    if outcome is StopOutcome.UNREACHABLE:
        return "……箱に手が届かねえ。とっくに閉まってるのかもな。"
    if outcome is StopOutcome.SHUTDOWN_FAILED:
        return "店じまいにしくじった。番人（ログ）に聞きな。"
    if outcome is StopOutcome.BACKUP_FAILED:
        return "写し（バックアップ）を取り損ねた。こんなときに灯は落とせねえ。"
    return "店は畳んで写しも取った。だが灯が落ちきらねえ……妙だな。"


def _format_presence(report: StatusReport) -> tuple[str, discord.Status]:
    """Bot activity text + status dot reflecting the current server state."""
    if report.pc is PcState.OFFLINE or report.palworld is PalworldState.STOPPED:
        return "サーバー停止中", discord.Status.idle
    if report.palworld is PalworldState.RUNNING:
        if report.players is None:
            return "起動中", discord.Status.online
        if report.max_players is not None:
            return f"{report.players}/{report.max_players}人 プレイ中", discord.Status.online
        return f"{report.players}人 プレイ中", discord.Status.online
    return "状態確認中", discord.Status.idle


def _member_role_ids(interaction: discord.Interaction) -> list[int]:
    user = interaction.user
    if isinstance(user, discord.Member):
        return [role.id for role in user.roles]
    return []


async def _deny(interaction: discord.Interaction, message: str) -> None:
    try:
        await interaction.response.send_message(message, ephemeral=True)
    except discord.NotFound:
        logger.warning("interaction expired before the denial could be sent")


async def _acknowledge(interaction: discord.Interaction) -> bool:
    """Defer the response; False when Discord already expired the interaction.

    Discord invalidates an interaction that is not acknowledged within
    3 seconds, which surfaces as NotFound (10062) under network latency.
    """
    try:
        await interaction.response.defer(thinking=True)
    except discord.NotFound:
        logger.warning("interaction expired before it could be acknowledged; ask to retry")
        return False
    return True


async def _reply(interaction: discord.Interaction, message: str) -> None:
    try:
        await interaction.followup.send(message)
    except discord.HTTPException:
        logger.warning("failed to deliver the command response")


async def _ensure_player(interaction: discord.Interaction, config: BotConfig) -> bool:
    if not auth.is_allowed_context(config, interaction.guild_id, interaction.channel_id):
        await _deny(interaction, "ここは商いの場じゃねえ。指定の場所で声をかけな。")
        return False
    if not auth.has_player_access(config, _member_role_ids(interaction)):
        await _deny(interaction, "……お前さんにゃ、この商いはまだ早いな。出直しな。")
        return False
    return True


def build_server_group(config: BotConfig, manager: ServerManager) -> app_commands.Group:
    group = app_commands.Group(name="server", description="Palworldサーバー操作")

    @group.command(name="status", description="サーバーの状態を確認します")
    async def status_command(interaction: discord.Interaction) -> None:
        if not await _ensure_player(interaction, config):
            return
        if not await _acknowledge(interaction):
            return
        try:
            report = await manager.status()
        except Exception:
            logger.exception("status command failed")
            await _reply(interaction, _GENERIC_ERROR_MESSAGE)
            return
        await _reply(interaction, _format_status(report))

    @group.command(name="start", description="サーバーPCとPalworldを起動します")
    async def start_command(interaction: discord.Interaction) -> None:
        if not await _ensure_player(interaction, config):
            return
        if not await _acknowledge(interaction):
            return
        try:
            outcome = await manager.start()
        except Exception:
            logger.exception("start command failed")
            await _reply(interaction, _GENERIC_ERROR_MESSAGE)
            return
        await _reply(interaction, _START_MESSAGES[outcome])

    @group.command(
        name="restart", description="保存してからPalworldのみ再起動します（Maintainer専用）"
    )
    async def restart_command(interaction: discord.Interaction) -> None:
        if not await _ensure_player(interaction, config):
            return
        if not auth.has_maintainer_access(config, _member_role_ids(interaction)):
            await _deny(interaction, "店の建て直しは Maintainer だけの仕事だ。")
            return
        if not await _acknowledge(interaction):
            return
        try:
            outcome = await manager.restart()
        except Exception:
            logger.exception("restart command failed")
            await _reply(interaction, _GENERIC_ERROR_MESSAGE)
            return
        await _reply(interaction, _RESTART_MESSAGES[outcome])

    @group.command(name="stop", description="Palworldを安全に停止します")
    @app_commands.describe(force="接続者がいても停止します（Maintainer専用の確認操作）")
    async def stop_command(interaction: discord.Interaction, force: bool = False) -> None:
        if not await _ensure_player(interaction, config):
            return
        is_maintainer = auth.has_maintainer_access(config, _member_role_ids(interaction))
        if force and not is_maintainer:
            await _deny(interaction, "その力（force）は Maintainer だけのもんだ。身の程を知りな。")
            return
        if not await _acknowledge(interaction):
            return
        try:
            result = await manager.stop(allow_with_players=force and is_maintainer)
        except Exception:
            logger.exception("stop command failed")
            await _reply(interaction, _GENERIC_ERROR_MESSAGE)
            return
        await _reply(interaction, _format_stop(result))

    return group


def build_trade_command(config: BotConfig) -> app_commands.Command[Any, ..., None]:
    """The ``/取引`` command: hand over one random Pal image. No role/channel gate."""
    image_dir = Path(config.pal_image_dir) if config.pal_image_dir else pals.DEFAULT_PAL_IMAGE_DIR

    async def trade_command(interaction: discord.Interaction) -> None:
        if not await _acknowledge(interaction):
            return
        image = pals.draw_pal_image(image_dir)
        if image is None:
            await _reply(interaction, "……あいにく品切れだ。またおいで。")
            return
        message = "これはまずいな……" if pals.is_mystery_pal(image) else "ほらよ。"
        try:
            await interaction.followup.send(message, file=discord.File(image))
        except discord.HTTPException:
            logger.warning("failed to deliver the trade image")

    return app_commands.Command(
        name="取引",
        description="闇商人からパルを引き取る",
        callback=trade_command,
    )


class PalworldBotClient(discord.Client):
    """Discord client that registers the /server command group for one guild."""

    def __init__(self, config: BotConfig, manager: ServerManager) -> None:
        super().__init__(intents=discord.Intents.default())
        self._config = config
        self._manager = manager
        self._monitor_task: asyncio.Task[None] | None = None
        self._last_presence: tuple[str, discord.Status] | None = None
        self.tree = app_commands.CommandTree(self)
        guild = discord.Object(config.discord_guild_id)
        self.tree.add_command(build_server_group(config, manager), guild=guild)
        self.tree.add_command(build_trade_command(config), guild=guild)

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=discord.Object(self._config.discord_guild_id))
        self._monitor_task = asyncio.create_task(self._run_monitor())

    async def _run_monitor(self) -> None:
        await self.wait_until_ready()
        monitor = ServerMonitor(
            self._config,
            self._manager,
            self._send_notification,
            on_report=self._update_presence,
        )
        await monitor.run()

    async def _update_presence(self, report: StatusReport) -> None:
        text, status = _format_presence(report)
        if (text, status) == self._last_presence:
            return
        self._last_presence = (text, status)
        try:
            await self.change_presence(status=status, activity=discord.Game(name=text))
        except discord.HTTPException:
            logger.warning("failed to update presence")

    async def _send_notification(self, message: str) -> None:
        channel_id = (
            self._config.discord_audit_channel_id or self._config.discord_command_channel_id
        )
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException:
                logger.warning("could not fetch the notification channel")
                return
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("notification channel does not accept messages")
            return
        await channel.send(message)

    async def on_ready(self) -> None:
        logger.info("logged in as %s", self.user)
        if self._last_presence is None:
            try:
                await self.change_presence(
                    status=discord.Status.idle, activity=discord.Game(name="状態確認中…")
                )
            except discord.HTTPException:
                logger.warning("failed to set the initial presence")
