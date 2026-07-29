from palworld_bot.config import load_config
from palworld_bot.services.ssh_control import RemoteCommand, SshResult, build_ssh_args
from tests.test_config import BASE_ENV

CONFIG = load_config(BASE_ENV)


def test_remote_commands_are_a_fixed_enum() -> None:
    assert {command.value for command in RemoteCommand} == {
        "status",
        "start",
        "players",
        "metrics",
        "restart",
        "shutdown",
        "backup",
        "poweroff",
    }


def test_ssh_args_end_with_fixed_command() -> None:
    args = build_ssh_args(CONFIG, RemoteCommand.STATUS, ssh_path="/usr/bin/ssh")
    assert args[0] == "/usr/bin/ssh"
    assert args[-1] == "status"
    assert args[-2] == "palbotctl@palworld-server"
    assert "BatchMode=yes" in args
    assert "StrictHostKeyChecking=yes" in args


def test_ssh_result_flags() -> None:
    assert SshResult(exit_code=0, stdout="").ok
    assert not SshResult(exit_code=1, stdout="").ok
    assert SshResult(exit_code=255, stdout="").connection_failed
    assert SshResult(exit_code=None, stdout="").connection_failed
    assert not SshResult(exit_code=1, stdout="").connection_failed
