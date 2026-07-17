"""Slash command handlers only.

Handlers never run subprocesses directly and never expose raw exceptions or
command output to Discord.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from palworld_bot import auth
from palworld_bot.config import BotConfig
from palworld_bot.services.server_manager import (
    ServerManager,
    StartOutcome,
    StatusReport,
    StopOutcome,
    StopResult,
)

logger = logging.getLogger(__name__)

_GENERIC_ERROR_MESSAGE = "内部エラーが発生しました。Botのログを確認してください。"

_START_MESSAGES = {
    StartOutcome.STARTED: "Palworldサーバーを起動しました。",
    StartOutcome.ALREADY_RUNNING: "Palworldサーバーはすでに起動しています。",
    StartOutcome.BUSY: "別の操作が実行中です。完了を待ってから再実行してください。",
    StartOutcome.BOOT_TIMEOUT: (
        "WOLを送信しましたが、時間内にサーバーPCへ接続できませんでした。"
    ),
    StartOutcome.START_FAILED: "起動に失敗しました。Botのログを確認してください。",
}


def _format_status(report: StatusReport) -> str:
    lines = [
        f"サーバーPC: {report.pc.value}",
        f"Palworld: {report.palworld.value}",
    ]
    if report.players is not None:
        if report.max_players is not None:
            lines.append(f"接続人数: {report.players} / {report.max_players}")
        else:
            lines.append(f"接続人数: {report.players}")
    lines.append(f"確認時刻: {report.checked_at:%Y-%m-%d %H:%M:%S}")
    return "\n".join(lines)


def _format_stop(result: StopResult) -> str:
    outcome = result.outcome
    if outcome is StopOutcome.STOPPED:
        return "保存・停止・バックアップが完了しました。サーバーPCの電源を切ります。"
    if outcome is StopOutcome.REFUSED_PLAYERS_CONNECTED:
        if result.players is None:
            return (
                "接続人数を確認できないため停止しません。"
                "Maintainerは force:True で停止できます。"
            )
        return (
            f"接続中のプレイヤーがいるため停止しません（{result.players}人）。"
            "Maintainerは force:True で停止できます。"
        )
    if outcome is StopOutcome.BUSY:
        return "別の操作が実行中です。完了を待ってから再実行してください。"
    if outcome is StopOutcome.UNREACHABLE:
        return "サーバーPCへ接続できません。すでに停止している可能性があります。"
    if outcome is StopOutcome.SHUTDOWN_FAILED:
        return "Palworldの停止に失敗しました。Botのログを確認してください。"
    if outcome is StopOutcome.BACKUP_FAILED:
        return "バックアップに失敗したため、サーバーPCの電源は切りません。"
    return "停止とバックアップは完了しましたが、電源オフに失敗しました。"


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
        await _deny(interaction, "このチャンネルではコマンドを使用できません。")
        return False
    if not auth.has_player_access(config, _member_role_ids(interaction)):
        await _deny(interaction, "このコマンドを使用する権限がありません。")
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

    @group.command(name="stop", description="Palworldを安全に停止します")
    @app_commands.describe(force="接続者がいても停止します（Maintainer専用の確認操作）")
    async def stop_command(interaction: discord.Interaction, force: bool = False) -> None:
        if not await _ensure_player(interaction, config):
            return
        is_maintainer = auth.has_maintainer_access(config, _member_role_ids(interaction))
        if force and not is_maintainer:
            await _deny(interaction, "force はMaintainerロールのみ使用できます。")
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


class PalworldBotClient(discord.Client):
    """Discord client that registers the /server command group for one guild."""

    def __init__(self, config: BotConfig, manager: ServerManager) -> None:
        super().__init__(intents=discord.Intents.default())
        self._config = config
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(
            build_server_group(config, manager),
            guild=discord.Object(config.discord_guild_id),
        )

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=discord.Object(self._config.discord_guild_id))

    async def on_ready(self) -> None:
        logger.info("logged in as %s", self.user)
