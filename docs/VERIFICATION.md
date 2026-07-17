# 自宅環境での検証手順（Windows Bot → macOS ダミーサーバー）

本番（Raspberry Pi → Linux サーバーPC）の前段検証として、自宅の 2 台で Discord Bot の起動フローを確認する手順です。

- **Windows PC**: Bot 実行役（本番の Raspberry Pi 相当）
- **Mac**: サーバー役（本番の Linux PC 相当）。Palworld の代わりにダミープロセスを起動する

## 検証の範囲と制限

| 項目 | 検証内容 |
|---|---|
| Discord 認証 | Guild / Channel / ロールID 検証を実機の Discord で確認 |
| `/server status` | SSH 経由でダミーサーバーの状態取得 |
| `/server start` | WOL 送信 → SSH 到達待ち → ダミープロセス起動 |
| `/server stop` | 人数確認 → 保存 → 停止 → バックアップ（poweroff は no-op） |
| WOL 実起床 | **対象外**。Mac（Wi-Fi ノート）はマジックパケットで確実に起床できないため、パケット送信のみ確認する。実起床の検証は本番の Linux PC（有線 + BIOS 設定）で行う |

Mac がスリープ中の挙動を試す場合は、`/server start` 実行後の SSH 到達待ち（最大 `SERVER_BOOT_TIMEOUT_SECONDS` 秒）の間に手動で Mac を開いて起こすことで、「WOL → 起動待ち → サービス起動」のフローを再現できます。

## 1. Discord 側の準備

1. [Discord Developer Portal](https://discord.com/developers/applications) で New Application → Bot を作成し、**Bot Token** を控える（特権 Intent は不要）
2. 検証用の Discord サーバー（Guild）を新規作成
3. コマンド実行用チャンネル（例: `#server-control`）を作成
4. ロールを 2 つ作成: `Palworld Player`、`Palworld Maintainer`
5. OAuth2 → URL Generator で `bot` と `applications.commands` スコープを選択し、生成 URL から Bot を検証サーバーへ招待
6. Discord の設定 → 詳細設定 → **開発者モード** を ON にし、右クリックで以下の ID をコピー:
   - サーバー ID（Guild ID）
   - チャンネル ID
   - 各ロール ID
7. 自分に `Palworld Maintainer` ロールを付与（Maintainer は Player 権限を含む）

## 2. Mac 側の準備（サーバー役）

1. **リモートログインを有効化**: システム設定 → 一般 → 共有 → リモートログイン ON
2. Mac の LAN IP を確認: システム設定 → Wi-Fi → 詳細、または `ipconfig getifaddr en0`
3. 作業ディレクトリを作成してスクリプトを配置:

   ```bash
   mkdir -p ~/palworld-verify
   # このリポジトリの scripts/verify/ から 2 ファイルをコピーして
   cp macos-control macos-control-ssh ~/palworld-verify/
   chmod 755 ~/palworld-verify/macos-control ~/palworld-verify/macos-control-ssh
   ```

4. 後述の Windows 側で生成した**公開鍵**を、固定コマンド付きで登録:

   ```bash
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   # <user> は Mac のユーザー名、鍵は Windows 側の id_ed25519.pub の内容
   echo 'command="/Users/<user>/palworld-verify/macos-control-ssh",restrict ssh-ed25519 AAAA... palworld-bot' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```

   `restrict` によりポート転送・PTY などが無効化され、`command=` により Bot の鍵ではラッパースクリプト経由の固定コマンドしか実行できません。

## 3. Windows 側の準備（Bot 役）

1. 依存関係のインストール:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -e ".[dev]"
   ```

2. 検証専用の SSH 鍵を作成（パスフレーズなし、既存の鍵とは分ける）:

   ```powershell
   ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\palworld_verify_ed25519 -C palworld-bot
   ```

   `palworld_verify_ed25519.pub` の内容を Mac の `authorized_keys` に登録する（上記 2-4）。

3. SSH 疎通確認と known_hosts 固定（初回のみ対話で yes）:

   ```powershell
   ssh -i $env:USERPROFILE\.ssh\palworld_verify_ed25519 <macuser>@<MacのIP> status
   ```

   `palworld=stopped` が返れば成功。このとき `~/.ssh/known_hosts` に Mac のホスト鍵が固定される。

4. リポジトリ直下に `.env` を作成（`config/bot.env.example` を参照）:

   ```env
   DISCORD_BOT_TOKEN=<Botトークン>
   DISCORD_GUILD_ID=<サーバーID>
   DISCORD_COMMAND_CHANNEL_ID=<チャンネルID>
   DISCORD_AUDIT_CHANNEL_ID=
   DISCORD_PLAYER_ROLE_ID=<PlayerロールID>
   DISCORD_MAINTAINER_ROLE_ID=<MaintainerロールID>

   SERVER_MAC_ADDRESS=<MacのWi-Fi MACアドレス>
   SERVER_LAN_BROADCAST=192.168.x.255
   SERVER_TAILSCALE_HOST=<MacのLAN IP>
   SERVER_SSH_USER=<Macのユーザー名>
   SERVER_SSH_KEY_PATH=C:\Users\<winuser>\.ssh\palworld_verify_ed25519
   SERVER_SSH_KNOWN_HOSTS_PATH=C:\Users\<winuser>\.ssh\known_hosts

   SERVER_BOOT_TIMEOUT_SECONDS=120
   ```

   検証では Tailscale を使わず LAN IP を直接指定する（キー名は本番と共通のため `SERVER_TAILSCALE_HOST` のまま）。

5. Bot を起動:

   ```powershell
   palworld-bot
   ```

   起動後、Discord の検証サーバーに `/server` コマンドが表示される（反映まで少し時間がかかることがある）。

## 4. 検証シナリオ

チェックリスト。すべて Discord のコマンドチャンネルから実行する。

1. **認可の拒否**
   - [ ] ロールなしのユーザー（または一時的に自分のロールを外して）→ 全コマンドが「権限がありません」で拒否される
   - [ ] 指定外のチャンネルで実行 → 拒否される
2. **status**
   - [ ] `/server status` → `サーバーPC: online` / `Palworld: stopped` が返る
   - [ ] Mac の Wi-Fi を切る（またはスリープ）→ `サーバーPC: offline`
3. **start**
   - [ ] `/server start` → ダミープロセスが起動し「起動しました」が返る。Mac 側で `curl -s localhost:18765` などで確認可
   - [ ] もう一度 `/server start` → 「すでに起動しています」
   - [ ] （任意）Mac をスリープさせて `/server start` → 待機中に手動で Mac を起こす → 起動まで到達する
4. **多重実行防止**
   - [ ] `/server start` を素早く 2 回実行 → 2 回目が「別の操作が実行中です」になる（タイミング依存。Mac スリープ状態で試すと待機時間が長く再現しやすい）
5. **stop**
   - [ ] `/server stop`（players=0）→ 保存 → 停止 → バックアップが実行され、Mac 側 `~/palworld-verify/backups/` に tar.gz が生成される。poweroff は no-op（Mac は落ちない）
   - [ ] Mac 側で `echo 2 > ~/palworld-verify/players_override` → `/server start` 後に `/server stop` → 「接続中のプレイヤーがいるため停止しません（2人）」
   - [ ] `/server stop force:True`（Maintainer）→ 停止できる
   - [ ] Maintainer ロールを外して `force:True` → 拒否される
   - [ ] 検証後は `rm ~/palworld-verify/players_override` で戻す
6. **WOL 送信**
   - [ ] Mac がオフライン状態で `/server start` → Bot ログに WOL 送信が記録される
   - [ ] （任意）Mac 側で `sudo tcpdump -i en0 -X udp port 9` を実行しておくと、マジックパケットの受信を確認できる

## 5. 本番との差分（このブランチで検証しないこと）

- WOL による実起床（Linux PC + 有線 + BIOS の Wake on LAN 設定で検証する）
- `poweroff` による実際の電源断
- Tailscale 経由の SSH（検証は同一 LAN 直結）
- systemd による Palworld サービス管理と実バックアップ

Bot 本体のコード（`src/palworld_bot/`）は本番用そのままで、Mac 固有なのは `scripts/verify/` の 2 スクリプトと本手順のみ。
