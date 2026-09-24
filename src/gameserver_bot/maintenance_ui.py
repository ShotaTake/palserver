"""Maintainer-only diagnostic, backup listing, and confirmed restore UI."""

from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord import app_commands

from gameserver_bot import auth
from gameserver_bot.config import BotConfig
from gameserver_bot.services.maintenance import (
    DIAGNOSE_LABELS,
    DIAGNOSE_VALUES,
    BackupEntry,
)
from gameserver_bot.services.server_manager import RestoreOutcome, ServerManager

logger = logging.getLogger(__name__)
RESTORE_RESULTS = {
    RestoreOutcome.ACCEPTED: "復元を受け付けた。/server status で進行を確認しな。結果も通知する。",
    RestoreOutcome.BUSY: "別の操作か復元の手動確認が必要な状態だ。/server diagnose を確認しな。",
    RestoreOutcome.UNREACHABLE: "PC と通信できない。電源状態は断定できない。",
    RestoreOutcome.REFUSED_PLAYERS: "接続者がいるか人数が不明だ。復元は始めていない。",
    RestoreOutcome.FAILED: "復元を受け付けられなかった。バックアップ一覧と導入設定を確認しな。",
    RestoreOutcome.UNKNOWN: "受付結果が不明だ。再実行する前に /server status を確認しな。",
}


async def ensure_maintainer(interaction: discord.Interaction, config: BotConfig) -> bool:
    roles = [role.id for role in interaction.user.roles] if isinstance(
        interaction.user, discord.Member
    ) else []
    if (not auth.is_allowed_context(config, interaction.guild_id, interaction.channel_id)
            or not auth.has_maintainer_access(config, roles)):
        await interaction.response.send_message(
            "指定チャンネルの Maintainer だけが使える操作だ。", ephemeral=True
        )
        return False
    return True


def backup_embed(entries: tuple[BackupEntry, ...]) -> discord.Embed:
    embed = discord.Embed(title="バックアップ一覧（新しい順・最大20件）")
    if not entries:
        embed.description = "バックアップはまだない。"
    for entry in entries:
        embed.add_field(
            name=entry.name,
            value=f"<t:{entry.modified}:f> · {entry.size / 1024**2:.1f} MiB\n"
                  "アーカイブの内容は復元時に検証",
            inline=False,
        )
    embed.set_footer(text="日時はファイルの更新日時。復元は /server restore から選択。")
    return embed


def diagnose_text(checks: dict[str, str]) -> str:
    if checks.get("ssh") == "unreachable":
        return "SSH: 接続できない。電源・ネットワーク・認証などに問題が考えられるが、状態は不明だ。"
    lines = ["SSH: 接続成功"]
    if checks.get("diagnose") == "unavailable":
        lines.append("診断処理: 利用できない。サーバー側の導入設定を確認しな。")
    for key, label in DIAGNOSE_LABELS.items():
        if checks.get(key) in DIAGNOSE_VALUES:
            lines.append(f"{label}: {DIAGNOSE_VALUES[checks[key]]}")
    return "\n".join(lines)


class MaintainerView(discord.ui.View):
    def __init__(self, config: BotConfig, actor_id: int) -> None:
        super().__init__(timeout=90)
        self.config = config
        self.actor_id = actor_id
        self.expires = time.monotonic() + 90
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.used or time.monotonic() >= self.expires or interaction.user.id != self.actor_id:
            await interaction.response.send_message(
                "この確認は期限切れ・使用済み、または別の人のものだ。コマンドからやり直しな。",
                ephemeral=True,
            )
            return False
        return await ensure_maintainer(interaction, self.config)


class RestoreConfirm(MaintainerView):
    def __init__(self, config: BotConfig, actor_id: int, manager: ServerManager,
                 entry: BackupEntry) -> None:
        super().__init__(config, actor_id)
        self.manager, self.entry = manager, entry

    @discord.ui.button(label="このバックアップへ復元", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        # Repeat the guard here as well: it must run immediately before the
        # one-use claim, even if component dispatch changes or calls overlap.
        if not await self.interaction_check(interaction):
            return
        if self.used:
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="復元の受付を確認している。", view=None)
        logger.info("restore requested user_id=%s backup=%s", interaction.user.id, self.entry.name)
        try:
            outcome = await self.manager.restore(self.entry)
            message = RESTORE_RESULTS[outcome]
            logger.info("restore result=%s user_id=%s", outcome.name, interaction.user.id)
        except Exception:
            logger.exception("restore request failed")
            message = "復元要求で問題が起きた。再実行する前に /server status を確認しな。"
        await interaction.edit_original_response(content=message, view=None)

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="復元は取りやめた。", view=None)


class BackupSelect(discord.ui.Select["RestoreSelection"]):
    def __init__(self, entries: tuple[BackupEntry, ...]) -> None:
        super().__init__(placeholder="復元するバックアップを選択", options=[
            discord.SelectOption(label=entry.name, value=entry.name,
                                 description=f"{entry.size / 1024**2:.1f} MiB")
            for entry in entries
        ])

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None or not await view.interaction_check(interaction):
            return
        entry = next((item for item in view.entries if item.name == self.values[0]), None)
        if entry is None or view.used:
            return
        view.used = True
        view.stop()
        confirmation = RestoreConfirm(view.config, view.actor_id, view.manager, entry)
        await interaction.response.edit_message(
            content=f"**復元対象: {entry.name}**\nバックアップ日時: <t:{entry.modified}:f>\n"
                    "ワールド保存フォルダー全体をこの時点へ戻す。以降の進行は巻き戻る。\n"
                    "現在のワールドを別途バックアップしてから復元し、成功後はゲームを起動する。\n"
                    "接続者あり・人数不明なら中止する。90秒以内に確認しな。",
            embed=None, view=confirmation,
        )


class RestoreSelection(MaintainerView):
    def __init__(self, config: BotConfig, actor_id: int, manager: ServerManager,
                 entries: tuple[BackupEntry, ...]) -> None:
        super().__init__(config, actor_id)
        self.manager, self.entries = manager, entries
        self.add_item(BackupSelect(entries))


def register_maintenance(
    group: app_commands.Group, config: BotConfig, manager: ServerManager
) -> None:
    @group.command(name="diagnose", description="運用上の問題を診断します（Maintainer専用）")
    async def diagnose(interaction: discord.Interaction) -> None:
        if not await ensure_maintainer(interaction, config):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            text = diagnose_text(await manager.diagnose())
        except Exception:
            logger.exception("diagnose failed")
            text = "診断結果を取得できなかった。所有者がログを確認しな。"
        await interaction.followup.send(text, ephemeral=True)

    @group.command(name="backups", description="バックアップ一覧を表示します（Maintainer専用）")
    async def backups(interaction: discord.Interaction) -> None:
        if not await ensure_maintainer(interaction, config):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            entries = await manager.backups()
            if entries is not None:
                await interaction.followup.send(embed=backup_embed(entries), ephemeral=True)
                return
        except Exception:
            logger.exception("backup listing failed")
        await interaction.followup.send("一覧を取得できない。PCとの接続と導入設定を確認しな。",
                                        ephemeral=True)

    @group.command(
        name="restore", description="バックアップを選んでワールドを復元（Maintainer専用）"
    )
    async def restore(interaction: discord.Interaction) -> None:
        if not await ensure_maintainer(interaction, config):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            entries = await manager.backups()
            if entries:
                await interaction.followup.send(
                    content="復元候補を選びな。次の画面で内容を確認してから実行する。",
                    embed=backup_embed(entries),
                    view=RestoreSelection(config, interaction.user.id, manager, entries),
                    ephemeral=True,
                )
                return
        except Exception:
            logger.exception("restore selection failed")
        await interaction.followup.send(
            "復元候補がないか、一覧を取得できなかった。", ephemeral=True
        )
