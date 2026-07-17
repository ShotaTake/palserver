# サーバー側の検証（WSL + 実 Palworld サーバー）

Mac ダミー検証（[VERIFICATION.md](VERIFICATION.md)）では Bot のフローを確認した。ここでは **実際の Palworld 専用サーバー**を WSL2(Ubuntu）で動かし、サーバー側スクリプト（[palworld-control](../scripts/server/palworld-control) / [backup.sh](../scripts/server/backup.sh) / [palworld-safe-poweroff](../scripts/server/palworld-safe-poweroff)）を本番同等の systemd 構成で検証する。

本番の Linux サーバー PC でも同じ手順が使える（WSL 固有なのはインストール場所くらい）。

## 検証範囲

| 項目 | ここで検証 | 本番でのみ検証 |
|---|---|---|
| REST API の挙動（人数・保存・終了） | ✅ | |
| 終了時のワールド保存（save-on-shutdown） | ✅ | |
| `palworld-control` 全コマンド（systemd 経由） | ✅ | |
| バックアップ生成と検証 | ✅ | |
| poweroff ガード（稼働中は拒否） | ✅（dry-run） | |
| 実際の電源断・WOL 実起床・Tailscale SSH | | ✅ |

## 1. WSL の準備

```bash
# /etc/wsl.conf に以下を入れて systemd を有効化（未設定なら）
# [boot]
# systemd=true
# → PowerShell で wsl --shutdown 後に再起動

# 依存
sudo apt update
sudo dpkg --add-architecture i386
sudo add-apt-repository -y multiverse
sudo apt install -y steamcmd curl
```

## 2. Palworld 専用サーバーのインストール

```bash
sudo useradd -r -m -s /bin/bash palworld
sudo mkdir -p /opt/palworld-server && sudo chown palworld: /opt/palworld-server
sudo -u palworld /usr/games/steamcmd +force_install_dir /opt/palworld-server \
  +login anonymous +app_update 2394010 validate +quit
```

インストール直後、`~/.steam` のシンボリックリンク作成に失敗する警告が出る。これを放置すると `steamclient.so` が見つからず起動に失敗するので、先に用意する：

```bash
sudo -u palworld bash -c '
  mkdir -p ~/.steam/sdk64 ~/.steam/sdk32
  cp ~/.local/share/Steam/steamcmd/linux64/steamclient.so ~/.steam/sdk64/
  cp ~/.local/share/Steam/steamcmd/linux32/steamclient.so ~/.steam/sdk32/
  ln -sfn ~/.local/share/Steam ~/.steam/steam
  ln -sfn ~/.local/share/Steam ~/.steam/root
'
sudo locale-gen en_US.UTF-8   # setlocale 警告対策
```

初回起動で設定ファイルを生成 → 停止：

```bash
cd /opt/palworld-server
sudo -u palworld env LANG=en_US.UTF-8 ./PalServer.sh &
sleep 30 && pkill -f PalServer-Linux
```

## 3. REST API の有効化

```bash
CFG=/opt/palworld-server/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini
sudo -u palworld cp /opt/palworld-server/DefaultPalWorldSettings.ini "$CFG"
# OptionSettings=(...) 内を編集
sudo -u palworld sed -i \
  -e 's/RESTAPIEnabled=False/RESTAPIEnabled=True/' \
  -e 's/AdminPassword=""/AdminPassword="<強いパスワード>"/' \
  "$CFG"
```

REST API は 127.0.0.1 からのみ使用する。**ルーターで 8212 を開けない。**

## 4. REST API の実測結果（palworld-control 実装の根拠）

サーバー v1.0.1.100619 で確認した事実：

- **認証**: HTTP Basic 認証。ユーザー名は `admin` 固定、パスワードは `AdminPassword`。
- **人数取得は `/v1/api/metrics` が最適**: `currentplayernum` と `maxplayernum` を **1 リクエストで両方** JSON で返す。
  ```json
  { "currentplayernum": 0, "maxplayernum": 8, "uptime": 17, ... }
  ```
- **POST 系はボディなしでも `Content-Length` ヘッダが必須**。付けないと `HTTP 411 (missing_content_length_header)` になる。空 POST は `-H 'Content-Length: 0'`、JSON ボディありは通常どおり。
- **`/v1/api/save`**（POST）→ 実行後 `Level.sav` の mtime が進む＝保存される。
- **`/v1/api/shutdown`**（POST, `{"waittime":N,"message":"..."}`）→ **終了直前にワールドを保存してからプロセス終了**。これが「安全停止」の核心。SIGTERM/kill では確実に保存されないため、必ず REST の save→shutdown を使う。

セーブデータの場所: `Pal/Saved/SaveGames/0/<WorldGUID>/Level.sav`

## 5. サーバー側スクリプトのデプロイ

```bash
sudo install -m 0755 scripts/server/palworld-control       /usr/local/sbin/palworld-control
sudo install -m 0755 scripts/server/backup.sh              /usr/local/sbin/palworld-backup
sudo install -m 0755 scripts/server/palworld-safe-poweroff /usr/local/sbin/palworld-safe-poweroff

# 設定（REST パスワードを含むため root 所有 0600）
sudo mkdir -p /etc/palworld-control
sudo tee /etc/palworld-control/control.env >/dev/null <<'ENV'
PALWORLD_REST_PASSWORD="<強いパスワード>"
PALWORLD_SAVE_DIR="/opt/palworld-server/Pal/Saved/SaveGames"
PALWORLD_BACKUP_DIR="/var/lib/palworld-backups"
# 検証時のみ: 実際に電源を切らない
PALWORLD_POWEROFF_DRYRUN="1"
ENV
sudo chmod 600 /etc/palworld-control/control.env
```

systemd ユニットは [palworld-server.service.example](../systemd/palworld-server.service.example) を `/etc/systemd/system/palworld-server.service` に配置（ExecStart を実パスに合わせる）→ `sudo systemctl daemon-reload`。

`palworld-control` は `systemctl start/stop` と poweroff に `sudo -n` を使う。本番では [sudoers-palworld-control.example](../config/sudoers-palworld-control.example) で bot 用アカウントに固定コマンドだけを NOPASSWD 許可する。

## 6. エンドツーエンド検証結果

`palworld-control` を systemd 管理下の実サーバーに対して実行し、全項目パス：

| # | コマンド | 期待 | 結果 |
|---|---|---|---|
| 1 | `status`（停止時） | `palworld=stopped` | ✅ |
| 2 | 不正コマンド | exit 64 | ✅ |
| 3 | `start` | サービス起動＋REST 応答 | ✅（~9s） |
| 4 | `status`（起動時） | `palworld=running` | ✅ |
| 5 | `players` | `players=0` / `max_players=8` | ✅ |
| 6 | `shutdown` | 保存してから停止（mtime 前進） | ✅ |
| 7 | `backup` | tar.gz 生成＋検証 | ✅ |
| 8 | `poweroff`（dry-run） | 停止時はスキップ | ✅ |
| 9 | `poweroff`（稼働中） | **拒否**（データ保護） | ✅ |

出力形式（`palworld=...` / `players=N` / `max_players=M`）は Bot 側 [server_manager.py](../src/palworld_bot/services/server_manager.py) のパーサと一致する。

## 7. 本番に残る差分

- WOL による実起床（有線 LAN + BIOS 設定）
- `PALWORLD_POWEROFF_DRYRUN` を外した実際の電源断
- Tailscale 経由の SSH 強制コマンド（[ssh_authorized_keys.example](../config/ssh_authorized_keys.example)）
- Bot（Pi）→ SSH → palworld-control の結合（各半分は検証済み: Mac ダミーで Bot→SSH、ここで control→実サーバー）
