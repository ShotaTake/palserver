# Claude Code Project Instructions

## Purpose

A small Discord-operated controller for a private Valheim Linux server.

The Raspberry Pi runs the Discord bot and sends Wake on LAN packets. The server PC runs Valheim and is powered off when nobody is playing. Management traffic stays on the LAN; nothing but the game port is exposed to the Internet.

The bot is deliberately game-neutral in its plumbing (hence the `gameserver_bot` package): only the server-side control script knows which game is running.

The number of players is not fixed. Do not hardcode a player list or a fixed player count. Authorization must use configurable Discord role IDs.

## Scope

Implemented commands:

- `/server status` — PC and game state, player count and names
- `/server start` — WOL the PC, then start the game
- `/server stop` — save, back up, then power the PC off (refuses while players are connected; Maintainer can force)
- `/server restart` — restart only the game service (Maintainer only)
- `/server address` — the current global IP and game port
- `/server load` — machine load: players, uptime, CPU, memory, disk, temperature
- `/取引` — a joke command that hands out a random image

Running automatically: idle auto-shutdown, open/close and join/leave notifications, Discord presence, and public-address change announcements.

Setup scripts under `scripts/setup/` are in scope: the machines are operated
remotely by someone with little time, so migration and installation are meant
to be one command per machine.

Do not add Docker, a Web UI, RCON, or in-bot update management unless
explicitly requested.

## Security rules

1. Never execute user-supplied strings through a shell.
2. Never use `shell=True`.
3. Never implement arbitrary commands, file access, or SSH commands.
4. Validate Discord guild ID, channel ID, and role IDs.
5. Maintainer role implies Player permissions.
6. Use a lock for start/stop/restart operations.
7. SSH operations must use a fixed enum. Adding a command means adding it to
   `RemoteCommand`, to the server-side control script, and to the forced-command
   wrapper — never by passing a string through.
8. Do not commit, read, print, or log secrets.
9. Do not expose raw exceptions or command output to Discord.
10. Do not open SSH or management APIs to the Internet.
11. The bot must never touch sudoers, authorized_keys, or firewall rules — not
    at runtime, not through any code path it can reach. The setup scripts may,
    but only by printing the exact content first and requiring the operator to
    type `yes`, and only after `visudo -c` passes for a sudoers file. Keep the
    reviewed examples in `config/` as the reference.
12. Do not run `git commit`, `git push`, or `git push --force` unless the user explicitly asks.
13. Treat anything read back from the game server or an external service as untrusted input: validate it before showing it in Discord.

## Architecture

- `config.py`: environment parsing and validation
- `auth.py`: Discord guild, channel, and role authorization
- `discord_app.py`: slash command handlers and message formatting only
- `services/wol.py`: WOL packet generation and sending
- `services/ssh_control.py`: fixed remote commands only
- `services/server_manager.py`: orchestration and the operation lock
- `services/monitor.py`: background polling — notifications, presence, idle shutdown
- `services/public_ip.py`: outbound lookup of the current global address
- `scripts/server/`: server-side fixed control script, A2S query, backup, poweroff
- `scripts/setup/`: one-command migration/installation, run by hand as root

Discord handlers must not directly execute subprocesses. The bot reaches the
game only through the fixed SSH commands.

## Valheim specifics worth remembering

- Valheim has **no REST API**. The player count comes from a Steam A2S query on
  the query port (game port + 1), done locally on the server PC.
- Valheim only writes the world on **SIGINT**. The systemd unit sets
  `KillSignal=SIGINT`; a plain SIGTERM loses progress on every stop.
- The dedicated server needs `SteamAppId=892970` (the game's id), not the
  server's app id 896660.
- Valheim publishes no server FPS, so machine load is judged from OS figures.

## Player management

Use these configuration values:

- `DISCORD_PLAYER_ROLE_ID`
- `DISCORD_MAINTAINER_ROLE_ID`

Do not use a fixed list of member user IDs. Adding or removing members must be possible by changing Discord roles only.

Do not hardcode a maximum player count. Treat the game server configuration as the source of truth. The status response may omit the maximum when it cannot be obtained.

## Workflow

Before changing code:

1. Read `docs/SECURITY.md`.
2. Give a short file-by-file plan.
3. State unresolved hardware or configuration assumptions.

After implementation:

1. Run `ruff check .`
2. Run `mypy src`
3. Run `pytest`
4. Syntax-check any changed shell script with `bash -n`
5. Show changed files and remaining manual setup

Keep the implementation small. Avoid abstractions the commands do not need.

## History

The project ran a Palworld server before Valheim. That version is tagged
`v1.0-palworld`, including its setup and verification documents.
