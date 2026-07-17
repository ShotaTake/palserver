# Palworld Server Operations

Raspberry Pi上のDiscord Botから、LinuxのPalworldサーバーを起動・状態確認・安全停止する小規模プロジェクトです。

## 方針

- Dockerは使用しない
- mainへ直接pushする
- 利用者数は固定しない
- DiscordロールでPlayer/Maintainerを管理する
- SSHと管理APIはインターネットへ公開しない
- MVPは`status`、`start`、`stop`だけ

## 構成

```text
Discord
  ↓
Raspberry Pi: Bot + Wake on LAN
  ↓ Tailscale SSH
Linux Server PC: Palworld + systemd + backup
```

## 最初に読むもの

1. `docs/GITHUB_SETUP.md`
2. `docs/IMPLEMENTATION_SPEC.md`
3. `CLAUDE.md`
4. `docs/SECURITY.md`

## 開発環境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

## Claude Codeへの最初の指示

```text
CLAUDE.md、docs/IMPLEMENTATION_SPEC.md、docs/SECURITY.mdを読んでください。
Phase 1だけを対象に、まだコードを変更せず、短い実装計画と変更予定ファイルを示してください。
利用人数を4人に固定せず、DiscordのPlayerロールとMaintainerロールで認証してください。
不要な抽象化や追加機能は作らないでください。
```

計画確認後:

```text
Phase 1を実装してください。
実装後にruff check .、mypy src、pytestを実行してください。
git commitとgit pushは実行しないでください。
```

## 秘密情報

`.env`、Discord Bot Token、SSH秘密鍵、Tailscale認証キー、Palworld管理者パスワード、セーブデータ、バックアップはGitへ追加しません。
