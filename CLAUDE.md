# Claude Code Project Instructions

## Purpose

Implement a small Discord-operated controller for a private Palworld Linux server.

The Raspberry Pi runs the Discord bot and sends Wake on LAN packets. The server PC runs Palworld. Management traffic uses Tailscale.

The number of players is not fixed. Do not hardcode four users, A/B/C/D, or a fixed player count. Authorization must use configurable Discord role IDs.

## Scope

Implement only:

1. `/server status`
2. `/server start`
3. `/server stop`

Do not add Docker, a Web UI, automatic deployment, RCON, update management, or unrelated features unless explicitly requested.

## Security rules

1. Never execute user-supplied strings through a shell.
2. Never use `shell=True`.
3. Never implement arbitrary commands, file access, or SSH commands.
4. Validate Discord guild ID, channel ID, and role IDs.
5. Maintainer role implies Player permissions.
6. Use a lock for start/stop operations.
7. SSH operations must use a fixed enum: `status`, `start`, `stop`.
8. Do not commit, read, print, or log secrets.
9. Do not expose raw exceptions or command output to Discord.
10. Do not open SSH or management APIs to the Internet.
11. Do not edit sudoers, authorized_keys, firewall, or Tailscale policy automatically. Provide human-reviewed examples only.
12. Do not run `git commit`, `git push`, or `git push --force` unless the user explicitly asks.

## Simple architecture

- `config.py`: environment parsing and validation
- `auth.py`: Discord guild, channel, and role authorization
- `discord_app.py`: slash command handlers only
- `services/wol.py`: WOL packet generation and sending
- `services/ssh_control.py`: fixed remote commands only
- `services/server_manager.py`: status/start/stop orchestration
- `scripts/server/`: server-side fixed control script and backup

Discord handlers must not directly execute subprocesses.

## Player management

Use these configuration values:

- `DISCORD_PLAYER_ROLE_ID`
- `DISCORD_MAINTAINER_ROLE_ID`

Do not use a fixed list of member user IDs. Adding or removing members must be possible by changing Discord roles only.

Do not hardcode a maximum Palworld player count. Treat the Palworld server configuration as the source of truth. The status response may omit the maximum when it cannot be obtained.

## Workflow

Before changing code:

1. Read `docs/IMPLEMENTATION_SPEC.md` and `docs/SECURITY.md`.
2. Give a short file-by-file plan.
3. State unresolved hardware or configuration assumptions.

After implementation:

1. Run `ruff check .`
2. Run `mypy src`
3. Run `pytest`
4. Show changed files and remaining manual setup

Keep the implementation small. Avoid abstractions that are not required by the three MVP commands.
