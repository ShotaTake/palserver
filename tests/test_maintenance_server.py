"""Restore tests use only temporary worlds and mocked OS/service operations."""

import importlib.machinery
import importlib.util
import io
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def maintenance(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader(
        "maintenance_server", str(ROOT / "scripts/server/gameserver-maintenance")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    for name, directory in (("WORLD", "worlds_local"), ("BACKUPS", "backups"), ("STATE", "state")):
        path = tmp_path / directory
        path.mkdir()
        monkeypatch.setattr(module, name, path)
    (module.WORLD / "Test.fwl").write_bytes(b"metadata now")
    (module.WORLD / "Test.db").write_bytes(b"progress now")
    config = tmp_path / "valheim.env"
    config.write_text('VALHEIM_WORLD="Test"\n', encoding="utf-8")
    monkeypatch.setattr(module, "WORLD_ENV", config)
    monkeypatch.setattr(module, "assign_world_owner", lambda path: None)
    monkeypatch.setattr(module, "operation_lock", lambda **kwargs: nullcontext())
    return module


def archive(module, extras=(), *, database=True):
    import tarfile

    target = module.BACKUPS / "valheim-world-20260924-120000.tar.gz"
    with tarfile.open(target, "w:gz") as stream:
        files = [("worlds_local/Test.fwl", b"metadata old")]
        if database:
            files.append(("worlds_local/Test.db", b"progress old"))
        for name, content in files:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            stream.addfile(member, io.BytesIO(content))
        for member in extras:
            stream.addfile(member, io.BytesIO(b"x" * member.size) if member.isfile() else None)
    return {"name": target.name, "fingerprint": module.fingerprint(target.stat())}


def test_listing_is_bounded_and_ignores_partial_and_unknown_files(maintenance):
    module = maintenance
    archive(module)
    (module.BACKUPS / "private.env").write_bytes(b"not listed")
    (module.BACKUPS / "valheim-world-20260924-120001.tar.partial").write_bytes(b"partial")
    entries = module.backup_list()
    assert len(entries) == 1
    assert entries[0]["size"] > 0
    assert len(entries[0]["fingerprint"]) == 64


@pytest.mark.parametrize("payload", [
    {"name": "../../etc/passwd", "fingerprint": "a" * 64},
    {"name": "valheim-world-20260924-120000.tar.gz; poweroff", "fingerprint": "a" * 64},
    {"name": "valheim-world-20260924-120000.tar.gz", "fingerprint": "bad"},
    {"name": "valheim-world-20260924-120000.tar.gz", "fingerprint": "a" * 64, "path": "/etc"},
])
def test_request_rejects_paths_and_extra_fields(maintenance, payload):
    with pytest.raises(ValueError):
        maintenance.validate_request(payload)


@pytest.mark.parametrize("name,kind", [
    ("../outside", "file"), ("/etc/passwd", "file"),
    ("worlds_local/../../outside", "file"), ("worlds_local/link", "symlink"),
    ("worlds_local/hard", "hardlink"), ("worlds_local/device", "device"),
    ("worlds_local/Test.db", "file"), ("worlds_local\\outside", "file"),
])
def test_malicious_archives_leave_live_world_untouched(maintenance, tmp_path, name, kind):
    import tarfile

    member = tarfile.TarInfo(name)
    member.type = {"file": tarfile.REGTYPE, "symlink": tarfile.SYMTYPE,
                   "hardlink": tarfile.LNKTYPE, "device": tarfile.CHRTYPE}[kind]
    member.linkname = "/etc/passwd"
    selection = archive(maintenance, [member])
    staging = tmp_path / "stage"
    staging.mkdir()
    with pytest.raises((ValueError, OSError, tarfile.TarError)):
        maintenance.prepare_archive(selection, staging)
    assert (maintenance.WORLD / "Test.db").read_bytes() == b"progress now"
    assert not (tmp_path / "outside").exists()


def test_missing_database_is_not_restored(maintenance, tmp_path):
    selection = archive(maintenance, database=False)
    staging = tmp_path / "stage"
    staging.mkdir()
    with pytest.raises(ValueError, match="database"):
        maintenance.prepare_archive(selection, staging)


def test_restore_can_repair_missing_current_metadata(maintenance, tmp_path):
    selection = archive(maintenance)
    (maintenance.WORLD / "Test.fwl").unlink()
    staging = tmp_path / "stage"
    staging.mkdir()
    maintenance.prepare_archive(selection, staging)
    maintenance.safety_backup("123")
    maintenance.switch_world(staging, "123")
    assert (maintenance.WORLD / "Test.fwl").read_bytes() == b"metadata old"


def test_snapshot_change_after_confirmation_is_rejected(maintenance, tmp_path):
    selection = archive(maintenance)
    with (maintenance.BACKUPS / selection["name"]).open("ab") as stream:
        stream.write(b"changed")
    staging = tmp_path / "stage"
    staging.mkdir()
    with pytest.raises(ValueError, match="changed"):
        maintenance.prepare_archive(selection, staging)


def test_truncated_archive_is_rejected(maintenance, tmp_path):
    selection = archive(maintenance)
    path = maintenance.BACKUPS / selection["name"]
    path.write_bytes(path.read_bytes()[:-8])
    selection["fingerprint"] = maintenance.fingerprint(path.stat())
    staging = tmp_path / "stage"
    staging.mkdir()
    with pytest.raises(EOFError):
        maintenance.prepare_archive(selection, staging)


def test_insufficient_space_does_not_touch_live_world(maintenance, tmp_path, monkeypatch):
    selection = archive(maintenance)
    staging = tmp_path / "stage"
    staging.mkdir()
    monkeypatch.setattr(maintenance.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    with pytest.raises(ValueError, match="space"):
        maintenance.prepare_archive(selection, staging)
    assert (maintenance.WORLD / "Test.db").read_bytes() == b"progress now"


def test_diagnosis_preserves_permission_failure_as_a_result(maintenance, monkeypatch):
    def denied(path):
        raise PermissionError("not readable")
    monkeypatch.setattr(Path, "stat", denied)
    assert maintenance.directory_check(maintenance.WORLD) == "denied"


def test_changed_selection_never_enqueues_a_job(maintenance, monkeypatch):
    selection = archive(maintenance)
    (maintenance.BACKUPS / selection["name"]).write_bytes(b"changed")
    monkeypatch.setattr(maintenance, "service_state", lambda service: "inactive")
    launched = []
    monkeypatch.setattr(maintenance, "run", lambda *args, **kw: launched.append(args))
    with pytest.raises(ValueError, match="changed"):
        maintenance.request_restore(selection)
    assert launched == []


def test_verified_replacement_keeps_current_backup_and_original_directory(maintenance, tmp_path):
    selection = archive(maintenance)
    staging = tmp_path / "stage"
    staging.mkdir()
    maintenance.prepare_archive(selection, staging)
    saved = maintenance.safety_backup("123")
    assert saved.name.startswith("valheim-pre-restore-")
    maintenance.switch_world(staging, "123")
    assert (maintenance.WORLD / "Test.db").read_bytes() == b"progress old"
    original = maintenance.WORLD.parent / ".before-restore-123/Test.db"
    assert original.read_bytes() == b"progress now"
    assert saved.exists()
    assert not (maintenance.STATE / "restore-block").exists()


def test_failed_rename_restores_current_directory(maintenance, tmp_path, monkeypatch):
    selection = archive(maintenance)
    staging = tmp_path / "stage"
    staging.mkdir()
    maintenance.prepare_archive(selection, staging)
    rename = Path.rename

    def fail_replacement(path, destination):
        if path == staging / "worlds_local":
            raise OSError("simulated filesystem error")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_replacement)
    with pytest.raises(OSError):
        maintenance.switch_world(staging, "123")
    assert (maintenance.WORLD / "Test.db").read_bytes() == b"progress now"
    assert not (maintenance.STATE / "restore-block").exists()


def test_failed_rollback_keeps_persistent_inhibit_marker(maintenance, tmp_path, monkeypatch):
    selection = archive(maintenance)
    staging = tmp_path / "stage"
    staging.mkdir()
    maintenance.prepare_archive(selection, staging)
    rename = Path.rename

    def fail_after_first_rename(path, destination):
        if path != maintenance.WORLD:
            raise OSError("simulated failure")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_after_first_rename)
    with pytest.raises(OSError):
        maintenance.switch_world(staging, "123")
    assert (maintenance.STATE / "restore-block").exists()
    original = maintenance.WORLD.parent / ".before-restore-123/Test.db"
    assert original.read_bytes() == b"progress now"


@pytest.mark.parametrize("failure,expected", [
    ("none", "succeeded"), ("players", "refused_players"),
    ("joined", "refused_players"),
    ("stop", "failed_stop"), ("backup", "failed_backup"), ("start", "failed_start"),
])
def test_worker_stages_and_failures(maintenance, monkeypatch, failure, expected):
    selection = archive(maintenance)
    maintenance.atomic_json(maintenance.STATE / "restore-request", {**selection, "id": "123"})
    events = []
    state = {"game": "active"}
    queries = []

    def service_state(service):
        return state["game"] if service == maintenance.SERVICE else "inactive"

    def run(*args, **kwargs):
        if args[-1] == "players":
            queries.append(True)
            occupied = failure == "players" or (failure == "joined" and len(queries) > 1)
            return SimpleNamespace(returncode=0, stdout="players=1\n" if occupied
                                   else "players=0\n")
        action = args[1]
        events.append(action)
        if failure == action:
            return SimpleNamespace(returncode=1, stdout="")
        state["game"] = "inactive" if action == "stop" else "active"
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(maintenance, "service_state", service_state)
    monkeypatch.setattr(maintenance, "run", run)
    if failure == "backup":
        def failed_backup(job_id):
            raise OSError("no space")
        monkeypatch.setattr(maintenance, "safety_backup", failed_backup)
    result = maintenance.restore_worker()
    assert (result == 0) is (failure == "none")
    assert json.loads((maintenance.STATE / "restore-state").read_text())["phase"] == expected
    if failure in {"players", "joined", "stop", "backup"}:
        assert "start" not in events
        assert (maintenance.WORLD / "Test.db").read_bytes() == b"progress now"
