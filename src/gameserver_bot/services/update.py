"""Validated update progress shared by the controller, monitor, and Discord UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class UpdatePhase(Enum):
    QUEUED = "queued"
    CHECKING = "checking"
    STOPPING = "stopping"
    BACKUP = "backup"
    DOWNLOADING = "downloading"
    STARTING = "starting"
    SUCCEEDED = "succeeded"
    REFUSED_PLAYERS = "refused_players"
    FAILED_STOP = "failed_stop"
    FAILED_BACKUP = "failed_backup"
    FAILED_DOWNLOAD = "failed_download"
    FAILED_START = "failed_start"
    INTERRUPTED = "interrupted"

    @property
    def active(self) -> bool:
        return self in {
            self.QUEUED, self.CHECKING, self.STOPPING,
            self.BACKUP, self.DOWNLOADING, self.STARTING,
        }


UPDATE_MESSAGES = {
    UpdatePhase.QUEUED: "更新を受け付けた。順番を待ちな。",
    UpdatePhase.CHECKING: "更新前の接続人数を確認している。",
    UpdatePhase.STOPPING: "更新のため、世界を保存して店を閉めている。",
    UpdatePhase.BACKUP: "更新前の世界の写しを取っている。",
    UpdatePhase.DOWNLOADING: "Steam から更新を取り寄せている。しばらく待ちな。",
    UpdatePhase.STARTING: "更新を適用した。ゲームが応答するのを待っている。",
    UpdatePhase.SUCCEEDED: "更新を終え、ゲームの応答も確認した。開店だ。",
    UpdatePhase.REFUSED_PLAYERS: "更新を中止した。接続者がいるか、人数を確認できなかった。",
    UpdatePhase.FAILED_STOP: (
        "保存・停止を確認できず、更新を中止した。Maintainer がログを確認しな。"
    ),
    UpdatePhase.FAILED_BACKUP: "バックアップに失敗し、更新を中止した。ゲームは停止したままだ。",
    UpdatePhase.FAILED_DOWNLOAD: "更新の取得に失敗した。ゲームは起動せずに残してある。",
    UpdatePhase.FAILED_START: "更新後のゲーム応答を確認できなかった。Maintainer がログを確認しな。",
    UpdatePhase.INTERRUPTED: "更新処理が中断された。自動で再開せず、Maintainer がログを確認しな。",
}


@dataclass(frozen=True, slots=True)
class UpdateReport:
    job_id: str
    phase: UpdatePhase


def parse_update(stdout: str) -> UpdateReport | None:
    values = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    job_id = values.get("update_id", "")
    if not re.fullmatch(r"[0-9]{1,24}", job_id):
        return None
    try:
        phase = UpdatePhase(values.get("update_phase", ""))
    except ValueError:
        return None
    return UpdateReport(job_id, phase)
