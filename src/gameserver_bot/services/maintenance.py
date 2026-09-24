"""Small, validated maintenance responses. Remote text is never rendered raw."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import Enum

BACKUP_ID = re.compile(r"valheim-(?:world|pre-restore)-[0-9]{8}-[0-9]{6}(?:-[0-9]{1,20})?\.tar\.gz")


@dataclass(frozen=True, slots=True)
class BackupEntry:
    name: str
    size: int
    modified: int
    fingerprint: str


def parse_backups(raw: str) -> tuple[BackupEntry, ...]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("backups"), list):
        raise ValueError("invalid backup response")
    if len(data["backups"]) > 20:
        raise ValueError("too many backups")
    entries = []
    for item in data["backups"]:
        if not isinstance(item, dict):
            raise ValueError("invalid backup")
        name, size, modified, fingerprint = (
            item.get("name"), item.get("size"), item.get("modified"), item.get("fingerprint")
        )
        if not isinstance(name, str) or not BACKUP_ID.fullmatch(name):
            raise ValueError("invalid backup ID")
        if type(size) is not int or not 0 < size < 2**50:
            raise ValueError("invalid size")
        if type(modified) is not int or not 0 <= modified <= 253402300799:
            raise ValueError("invalid timestamp")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise ValueError("invalid fingerprint")
        entries.append(BackupEntry(name, size, modified, fingerprint))
    if len({entry.name for entry in entries}) != len(entries):
        raise ValueError("duplicate backup ID")
    return tuple(entries)


def restore_payload(entry: BackupEntry) -> bytes:
    # Validate again at the transport boundary, even for a caller-built entry.
    parse_backups(json.dumps({"backups": [asdict(entry)]}))
    return json.dumps({"name": entry.name, "fingerprint": entry.fingerprint}).encode("ascii")


class RestorePhase(Enum):
    QUEUED = "queued"
    CHECKING = "checking"
    VALIDATING = "validating"
    STOPPING = "stopping"
    BACKUP = "backup"
    RESTORING = "restoring"
    STARTING = "starting"
    SUCCEEDED = "succeeded"
    REFUSED_PLAYERS = "refused_players"
    INVALID_BACKUP = "invalid_backup"
    FAILED_STOP = "failed_stop"
    FAILED_BACKUP = "failed_backup"
    FAILED_RESTORE = "failed_restore"
    FAILED_START = "failed_start"
    INTERRUPTED = "interrupted"

    @property
    def active(self) -> bool:
        return self in {self.QUEUED, self.CHECKING, self.VALIDATING, self.STOPPING,
                        self.BACKUP, self.RESTORING, self.STARTING}


RESTORE_MESSAGES = {
    RestorePhase.QUEUED: "復元を受け付けた。",
    RestorePhase.CHECKING: "復元前の人数を確認している。",
    RestorePhase.VALIDATING: "復元候補を展開・検証している。",
    RestorePhase.STOPPING: "現在の世界を保存して停止している。",
    RestorePhase.BACKUP: "復元前の世界を別のバックアップに保管している。",
    RestorePhase.RESTORING: "検証したワールドへ切り替えている。",
    RestorePhase.STARTING: "復元したゲームの応答を待っている。",
    RestorePhase.SUCCEEDED: "ワールドの復元を終え、ゲームの応答を確認した。開店だ。",
    RestorePhase.REFUSED_PLAYERS: "接続者がいるか人数が不明なため、復元を中止した。",
    RestorePhase.INVALID_BACKUP: "バックアップの変更・破損・容量不足などで検証できず中止した。",
    RestorePhase.FAILED_STOP: "保存・停止を確認できず、復元を中止した。",
    RestorePhase.FAILED_BACKUP: "復元前バックアップに失敗した。ワールドは切り替えていない。",
    RestorePhase.FAILED_RESTORE: "復元に失敗した。起動せずに残してある。所有者が確認しな。",
    RestorePhase.FAILED_START: "復元後のゲーム応答を確認できなかった。所有者が確認しな。",
    RestorePhase.INTERRUPTED: "復元が中断された。再操作の前に所有者が診断とログを確認しな。",
}


@dataclass(frozen=True, slots=True)
class RestoreReport:
    job_id: str
    phase: RestorePhase


def parse_restore(raw: str) -> RestoreReport | None:
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    job_id = values.get("restore_id", "")
    if not re.fullmatch(r"[0-9]{1,24}", job_id):
        return None
    try:
        return RestoreReport(job_id, RestorePhase(values.get("restore_phase", "")))
    except ValueError:
        return None


DIAGNOSE_LABELS = {
    "game": "ゲームサービス", "query": "ゲーム応答", "world": "ワールド読み取り",
    "backup_dir": "バックアップ先", "world_space": "ワールド用空き容量",
    "backup_space": "バックアップ用空き容量", "last_stop": "直近の停止結果",
    "restore_block": "復元の手動確認", "update": "更新処理", "restore": "復元処理",
}
DIAGNOSE_VALUES = {
    "ok": "正常", "running": "稼働中", "stopped": "停止中", "unknown": "不明",
    "unavailable": "取得できない", "low": "不足の可能性あり（1 GiB未満）",
    "missing": "見つからない", "denied": "権限不足", "not_needed": "ゲーム停止中",
    "required": "所有者による確認が必要", "clear": "不要", "idle": "待機中",
    "failed": "失敗", "requested": "電源オフ要求済み（電源断は未確認）",
    "shutdown_failed": "ゲーム停止に失敗", "backup_failed": "バックアップに失敗",
    "poweroff_failed": "電源オフ要求に失敗",
}


def parse_diagnose(raw: str) -> dict[str, str]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("checks"), dict):
        raise ValueError("invalid diagnostic response")
    return {key: value for key, value in data["checks"].items()
            if key in DIAGNOSE_LABELS and isinstance(value, str) and value in DIAGNOSE_VALUES}
