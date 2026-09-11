# Game Server Operations

Discord から Valheim 専用サーバーを操作する小規模プロジェクトです。使わないときはサーバー PC の電源を落としておき、遊ぶときだけ Discord から Wake on LAN で起こします。

## できること

### コマンド

| コマンド | 権限 | 内容 |
|---|---|---|
| `/server status` | Player | サーバー PC とゲームの状態、接続人数とプレイヤー名 |
| `/server start` | Player | WOL で PC を起動し、ゲームを立ち上げる |
| `/server stop` | Player | 保存 → 停止 → バックアップ → PC の電源オフ（接続者がいると拒否。Maintainer は `force:True` で強制可） |
| `/server restart` | Maintainer | ゲームだけ再起動（PC は落とさない） |
| `/server address` | Player | 今の接続先（グローバル IP:ポート）を表示 |
| `/server load` | Player | サーバー PC の負荷（接続人数・稼働時間・CPU・メモリ・ディスク・温度） |
| `/取引` | 全員 | ランダムで画像を1枚渡す（おまけ） |

Bot は Palworld の「闇商人」の口調で応答します（前身プロジェクトからの名残）。

### 自動で動くもの

- **無人時の自動シャットダウン** — 誰もいない状態が続くと、保存・バックアップ・電源オフまで自動実行（既定 30 分、`0` で無効）
- **状態の通知** — サーバーの開店・閉店、プレイヤーの参加・退出を Discord に自動投稿
- **オンライン表示** — Bot の Discord 上の表示が「N/M人 プレイ中」「サーバー停止中」に追従
- **アドレス変化の通知** — 動的グローバル IP が変わったら自動で新しい接続先を投稿

## 構成

```text
Discord
  ↓
Raspberry Pi: Bot + Wake on LAN（常時起動）
  ↓ SSH（LAN 内・固定コマンドのみ）
Linux Server PC: Valheim + systemd + backup（普段は電源オフ）
```

ルーターで開放するのは**ゲーム用の UDP ポートだけ**です。SSH と管理系はインターネットへ公開しません。

## 方針

- Discord ロール（Player / Maintainer）で権限を管理する。メンバーの増減はロールの付け外しだけで完結し、コードや設定は変更しない
- Bot がサーバーへ送れるのは固定コマンドのみ。任意コマンドの実行や文字列の埋め込みは行わない
- SSH と管理系をインターネットへ公開しない
- 最大人数などはゲームサーバー側の設定を正とし、Bot に固定値を持たせない
- 配管（WOL・SSH・監視・通知）はゲームに依存しない。ゲーム固有の知識はサーバー側の制御スクリプトに閉じ込める

## セットアップ

- **[docs/VALHEIM_SETUP.md](docs/VALHEIM_SETUP.md)** — サーバー PC に Valheim を構築する手順（SteamCMD、systemd、ポート、バックアップ）
- **[docs/SETUP_PRODUCTION.md](docs/SETUP_PRODUCTION.md)** — Bot 側（Raspberry Pi / Discord / ルーター）の構築と動作確認

Palworld 版から移行する場合は、各マシンでスクリプトを1本実行するだけです。

```bash
sudo bash scripts/setup/migrate-server.sh --dry-run    # サーバー PC（先）
sudo bash scripts/setup/migrate-pi.sh --dry-run        # ラズパイ（後）
```

`--dry-run` は何も変更せず実行内容を表示するだけなので、まずこれを流して確認してから外してください。詳細は SETUP_PRODUCTION.md の Part F。

## 設定

Bot の設定は `config/bot.env.example` を元に作ります（本番では `/etc/gameserver-bot/bot.env`）。主な任意項目:

| キー | 既定 | 内容 |
|---|---|---|
| `GAME_NAME` | `Valheim` | status に表示するゲーム名 |
| `GAME_PORT` | `35520` | `/server address` が表示するポート。`config/valheim.env.example` の `VALHEIM_PORT` と揃える |
| `IDLE_SHUTDOWN_MINUTES` | `30` | 無人がこの分数続くと自動シャットダウン。`0` で無効 |
| `STATUS_POLL_INTERVAL_SECONDS` | `60` | 状態を確認する間隔。通知や表示の更新間隔にもなる |
| `PUBLIC_IP_CHECK_INTERVAL_SECONDS` | `300` | グローバル IP を確認する間隔。`0` で無効 |
| `DISCORD_AUDIT_CHANNEL_ID` | 空 | 自動通知の投稿先。空ならコマンド用チャンネル |

`SERVER_TAILSCALE_HOST` には Tailscale のホスト名だけでなく、**LAN の固定 IP** も指定できます。

> 設定値はコメントを行末に書かず、独立した行に置いてください（systemd の `EnvironmentFile` は行末コメントを値の一部として読むことがあります）。

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

## 詳しい資料

- [CLAUDE.md](CLAUDE.md) — 実装方針とアーキテクチャの制約
- [docs/SECURITY.md](docs/SECURITY.md) — セキュリティ設計
- [docs/OPERATIONS.md](docs/OPERATIONS.md) — 運用方針
- [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md) — リポジトリの初期設定

## Git に含めないもの

`.env`、Discord Bot Token、SSH 秘密鍵、ゲームの管理者パスワード、セーブデータ、バックアップは追加しません。

`/取引` 用の画像（`src/gameserver_bot/assets/pals/`）もゲームの著作物のため Git に含めていません。Bot を動かすマシンごとに手元で配置してください。

## 履歴

このプロジェクトは Valheim の前に Palworld サーバーを運用していました。その版は **`v1.0-palworld`** タグに、当時のセットアップ手順と検証記録ごと保存されています。
