# 本番セットアップ手順書（サーバー管理者向け）

この手順書だけで、**現地作業者（サーバー PC と Raspberry Pi を設置する人）が一人で**セットアップを完了できるように書かれています。リモートの協力者は Discord 側の作業（Bot 作成・ロール管理）だけ分担できます。

## 全体像

```
[設置場所（自宅）]
  Raspberry Pi ── 常時起動。Discord Bot + Wake on LAN 送信
  サーバー PC  ── Ubuntu + Palworld。普段は電源オフ、遊ぶときだけ Bot が起こす
  ルーター     ── ゲームポート UDP 8211 だけ開放（SSH や管理ポートは開放しない）
[インターネット]
  Discord ⇔ Pi（Bot が外向きに接続。着信ポート開放は不要）
  Tailscale ── 保守用のリモートアクセス（任意だが推奨）
```

動作の流れ: Discord で `/server start` → Pi の Bot が WOL でサーバー PC を起動 → SSH（固定コマンドのみ）で Palworld を起動。`/server stop` → 保存 → 停止 → バックアップ → 電源オフ。

## 必要なもの

- [ ] サーバー PC（Palworld 動作要件を満たすもの。メモリ 16GB 推奨）
- [ ] **サーバー PC は有線 LAN 接続**（Wake on LAN は Wi-Fi では動かない）
- [ ] Raspberry Pi（3 以降、64bit 推奨）+ SD カード + 電源。**可能なら有線 LAN**
- [ ] Ubuntu Server 24.04 LTS のインストール USB
- [ ] GitHub アカウント（リポジトリは private のため。→ 下記「リポジトリへのアクセス準備」）
- [ ] Discord の Bot トークンと各種 ID（→「Part C」参照。リモート協力者が用意して安全な手段で共有しても良い）

## リポジトリへのアクセス準備（最初に一度だけ）

このリポジトリは private なので、クローンする前に次の準備をする。

1. **（リポジトリ所有者の作業）** GitHub の リポジトリページ → Settings → Collaborators → **Add people** で現地作業者のアカウントを招待（Read 権限で十分）
2. **（現地作業者の作業）** 招待メールを承認したら、クローン用のトークンを作る:
   - GitHub → 右上アイコン → Settings → Developer settings → **Personal access tokens → Fine-grained tokens → Generate new token**
   - Repository access: **Only select repositories** → このリポジトリを選択
   - Permissions: **Contents: Read-only** だけ
   - 有効期限は長め（90日〜）に設定し、表示されたトークン（`github_pat_...`）を控える
3. サーバー PC / Pi で `git clone` するとき、ユーザー名は GitHub のユーザー名、**パスワード欄にこのトークン**を入力する。毎回聞かれないようにするには、クローン前に一度だけ:

   ```bash
   git config --global credential.helper store   # 初回入力後、そのマシンに保存される
   ```

---

# Part A: サーバー PC（Ubuntu + Palworld）

## A-1. OS インストール

1. Ubuntu Server 24.04 LTS をインストール（インストーラーの指示どおりで OK）
2. インストール時に **OpenSSH Server を有効化**
3. ユーザー名は任意（以下 `admin` と表記。sudo 可能なユーザーであること）

## A-2. Wake on LAN の有効化（最重要・最初にやる）

**BIOS/UEFI 設定**（起動時に F2/DEL 等で入る）:

- 「Wake on LAN」「Power On By PCI-E/PCI」「Resume by LAN」等の名前の項目を **Enabled** に
- 「ErP」「EuP」という省電力項目があれば **Disabled** に（有効だと電源オフ時に NIC まで電源が切れて WOL が効かない）

**OS 側**（Ubuntu にログインして）:

```bash
# インターフェース名を確認（enp3s0 等をメモ）
ip -o link show | grep -v lo

# netplan 設定に wakeonlan を追加（ファイル名・IF名は環境に合わせる）
sudo nano /etc/netplan/50-cloud-init.yaml
```

```yaml
network:
  ethernets:
    enp3s0:            # ← 実際のインターフェース名に置き換え
      dhcp4: true
      wakeonlan: true
```

```bash
sudo netplan apply
sudo apt install -y ethtool
sudo ethtool enp3s0 | grep Wake-on    # 「Wake-on: g」なら OK

# WOL に必要な MAC アドレスをメモしておく（後で Pi の .env に書く）
ip link show enp3s0 | grep ether
```

**ここで一度 WOL テストをする**（これが通らないと全部無意味なので最初に確認）:

```bash
sudo poweroff
```

→ 同じ LAN 内の別マシン（Pi のセットアップ後なら Pi、スマホの WOL アプリでも可）からマジックパケットを送って**電源が入るか確認**。入らなければ BIOS 設定を見直す。

## A-3. Tailscale（保守用・推奨）

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up    # 表示された URL をブラウザで開いて認証
tailscale status     # このマシンの Tailscale ホスト名をメモ（例: palworld-server）
```

## A-4. ユーザー作成

```bash
sudo useradd -r -m -s /bin/bash palworld     # ゲーム実行用
sudo useradd -m -s /bin/bash palbotctl       # Bot の SSH 接続受け用
```

## A-5. SteamCMD と Palworld のインストール

```bash
sudo dpkg --add-architecture i386
sudo add-apt-repository -y multiverse
sudo apt update
sudo apt install -y steamcmd curl

sudo mkdir -p /opt/palworld-server
sudo chown palworld: /opt/palworld-server
sudo -u palworld /usr/games/steamcmd +force_install_dir /opt/palworld-server \
  +login anonymous +app_update 2394010 validate +quit
```

`Success! App '2394010' fully installed.` が出ること。**続けて steamclient.so の配置**（やらないと起動に失敗する）:

```bash
sudo -u palworld bash -c '
  mkdir -p ~/.steam/sdk64 ~/.steam/sdk32
  cp ~/.local/share/Steam/steamcmd/linux64/steamclient.so ~/.steam/sdk64/
  cp ~/.local/share/Steam/steamcmd/linux32/steamclient.so ~/.steam/sdk32/
  ln -sfn ~/.local/share/Steam ~/.steam/steam
  ln -sfn ~/.local/share/Steam ~/.steam/root
'
sudo locale-gen en_US.UTF-8
```

## A-6. 初回起動と設定

```bash
# 初回起動で設定ファイルを生成（30秒ほど待って Ctrl+C で止める）
cd /opt/palworld-server
sudo -u palworld env LANG=en_US.UTF-8 ./PalServer.sh
# 「Running Palworld dedicated server on :8211」が出たら Ctrl+C
```

設定ファイルを作って編集:

```bash
CFG=/opt/palworld-server/Pal/Saved/Config/LinuxServer/PalWorldSettings.ini
sudo -u palworld cp /opt/palworld-server/DefaultPalWorldSettings.ini "$CFG"
sudo -u palworld nano "$CFG"
```

`OptionSettings=(...)` の中の以下を変更（カンマ区切りの長い1行の中にある）:

| 項目 | 値 | 意味 |
|---|---|---|
| `ServerName="..."` | 好きな名前 | サーバー名 |
| `ServerPassword="..."` | 参加パスワード | 友達に共有する |
| `AdminPassword="..."` | **強いパスワード** | REST API 管理用（ゲーム参加者には教えない） |
| `ServerPlayerMaxNum=32` | 好きな人数 | 最大人数（Bot はこの値を自動表示する） |
| `RESTAPIEnabled=False` | **True** | 管理 API（ローカル専用） |

## A-7. systemd サービス化

リポジトリを取得して example を配置（初回はユーザー名と PAT トークンを聞かれる →「リポジトリへのアクセス準備」参照）:

```bash
cd ~ && git clone https://github.com/ShotaTake/palserver.git
sudo cp ~/palserver/systemd/palworld-server.service.example /etc/systemd/system/palworld-server.service
sudo nano /etc/systemd/system/palworld-server.service
```

`ExecStart` を実際の起動コマンドに変更:

```ini
ExecStart=/opt/palworld-server/PalServer.sh -useperfthreads -NoAsyncLoadingThread -UseMultithreadForDS
```

`Environment=LANG=en_US.UTF-8` の行も `[Service]` 内に追加。反映と動作確認:

```bash
sudo systemctl daemon-reload
sudo systemctl enable palworld-server.service   # PC 起動時に自動起動
sudo systemctl start palworld-server.service
systemctl status palworld-server.service        # active (running) を確認
```

## A-8. 制御スクリプトの設置

```bash
cd ~/palserver
sudo install -m 0755 scripts/server/palworld-control        /usr/local/sbin/palworld-control
sudo install -m 0755 scripts/server/palworld-control-ssh    /usr/local/sbin/palworld-control-ssh
sudo install -m 0755 scripts/server/backup.sh               /usr/local/sbin/palworld-backup
sudo install -m 0755 scripts/server/palworld-safe-poweroff  /usr/local/sbin/palworld-safe-poweroff
```

設定ファイル（**A-6 で決めた AdminPassword を書く**）:

```bash
sudo mkdir -p /etc/palworld-control
sudo nano /etc/palworld-control/control.env
```

```bash
PALWORLD_REST_PASSWORD="<A-6のAdminPasswordと同じ値>"
```

```bash
sudo chown root:palbotctl /etc/palworld-control/control.env
sudo chmod 640 /etc/palworld-control/control.env

# バックアップ先（palbotctl 所有にすること。root のままだと backup が失敗する）
sudo install -d -o palbotctl -g palbotctl -m 0750 /var/lib/palworld-backups
```

動作確認:

```bash
sudo -u palbotctl /usr/local/sbin/palworld-control status    # palworld=running
sudo -u palbotctl /usr/local/sbin/palworld-control players   # players=0 / max_players=N
```

## A-9. sudoers（palbotctl に固定コマンドだけ許可）

```bash
sudo visudo -f /etc/sudoers.d/palworld-control
```

```
palbotctl ALL=(root) NOPASSWD: /usr/bin/systemctl start palworld-server.service, /usr/bin/systemctl stop palworld-server.service, /usr/local/sbin/palworld-safe-poweroff
```

保存後に検証: `sudo visudo -cf /etc/sudoers.d/palworld-control` → `parsed OK`

## A-10. Bot 用 SSH 受け口

**Pi 側で作った公開鍵**（→ B-4。`ssh-ed25519 AAAA...` の1行）を登録:

```bash
sudo install -d -m 0700 -o palbotctl -g palbotctl /home/palbotctl/.ssh
sudo nano /home/palbotctl/.ssh/authorized_keys
```

次の**1行**を書く（`ssh-ed25519 AAAA...` 部分を Pi の公開鍵に置き換え）:

```
restrict,command="/usr/local/sbin/palworld-control-ssh" ssh-ed25519 AAAA... palworld-bot@raspberrypi
```

```bash
sudo chown palbotctl:palbotctl /home/palbotctl/.ssh/authorized_keys
sudo chmod 600 /home/palbotctl/.ssh/authorized_keys
```

---

# Part B: Raspberry Pi（Discord Bot）

## B-1. OS

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/) で **Raspberry Pi OS Lite (64-bit)** を SD に書き込み
2. Imager の設定（歯車）で: ホスト名、ユーザー（以下 `pi` と表記）、SSH 有効化、（Wi-Fi なら）Wi-Fi 設定
3. 起動して SSH またはモニタでログイン

## B-2. 基本セットアップ

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-venv python3-pip openssh-client
# Tailscale（推奨）
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

## B-3. Bot のデプロイ

```bash
sudo useradd -r -m -d /var/lib/palworld-bot -s /usr/sbin/nologin palworld-bot

# クローン先を自分（ログインユーザー）所有で用意し、sudo なしで clone/pull できるようにする
sudo install -d -o "$USER" /opt/palworld-server-ops
git clone https://github.com/ShotaTake/palserver.git /opt/palworld-server-ops
cd /opt/palworld-server-ops
python3 -m venv .venv
.venv/bin/pip install -e .
```

## B-4. SSH 鍵の生成と登録

```bash
sudo -u palworld-bot mkdir -p /var/lib/palworld-bot/.ssh
sudo -u palworld-bot ssh-keygen -t ed25519 \
  -f /var/lib/palworld-bot/.ssh/id_ed25519 -N "" -C palworld-bot@raspberrypi

# 公開鍵を表示 → この1行をサーバー PC の A-10 に登録する
sudo cat /var/lib/palworld-bot/.ssh/id_ed25519.pub
```

> 秘密鍵（`id_ed25519`）は Pi の外に持ち出さない。登録するのは `.pub` の方だけ。

サーバー PC 側の A-10 が済んだら疎通確認（初回は `yes` と答える。これで known_hosts に固定される）:

```bash
sudo -u palworld-bot ssh -i /var/lib/palworld-bot/.ssh/id_ed25519 palbotctl@<サーバーのIPまたはTailscale名> status
# → palworld=running (または stopped) が返れば成功
sudo -u palworld-bot ssh -i /var/lib/palworld-bot/.ssh/id_ed25519 palbotctl@<同上> ls
# → command denied が返れば制限も正常
```

## B-5. Bot の設定（.env）

```bash
sudo mkdir -p /etc/palworld-bot
sudo cp /opt/palworld-server-ops/config/bot.env.example /etc/palworld-bot/bot.env
sudo nano /etc/palworld-bot/bot.env
sudo chmod 600 /etc/palworld-bot/bot.env
```

記入内容:

| キー | 値 |
|---|---|
| `DISCORD_BOT_TOKEN` | Bot のトークン（Part C。**チャットや Git に貼らない**） |
| `DISCORD_GUILD_ID` ほか ID 系 | Part C で取得した各 ID |
| `SERVER_MAC_ADDRESS` | サーバー PC の有線 NIC の MAC（A-2 でメモした値） |
| `SERVER_LAN_BROADCAST` | LAN のブロードキャスト（例: `192.168.1.255`） |
| `SERVER_TAILSCALE_HOST` | サーバーの Tailscale ホスト名（無ければ固定 LAN IP） |
| `SERVER_SSH_USER` | `palbotctl` |
| `SERVER_SSH_KEY_PATH` | `/var/lib/palworld-bot/.ssh/id_ed25519` |
| `SERVER_SSH_KNOWN_HOSTS_PATH` | `/var/lib/palworld-bot/.ssh/known_hosts` |

## B-6. Bot の systemd 化

```bash
sudo cp /opt/palworld-server-ops/systemd/palworld-bot.service.example /etc/systemd/system/palworld-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now palworld-bot.service
systemctl status palworld-bot.service     # active (running) を確認
journalctl -u palworld-bot.service -n 20  # 「logged in as ...」が出ていれば OK
```

---

# Part C: Discord（リモート協力者が分担可能）

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application → 左メニュー **Bot** → **Reset Token** でトークン取得
   - Privileged Gateway Intents は**すべて OFF のまま**
   - PUBLIC BOT は OFF 推奨
2. 遊ぶ用の Discord サーバーに、コマンド用チャンネル（例: `#server-control`）とロール **`Palworld Player`** / **`Palworld Maintainer`** を作成
3. OAuth2 → URL Generator で `bot` + `applications.commands`（権限は Send Messages）→ 生成 URL からサーバーに招待
4. ユーザー設定 → 詳細設定 → **開発者モード ON** → 右クリックで各 ID をコピー:
   - サーバー ID / チャンネル ID / 各ロール ID
5. メンバーにロールを付与（Maintainer は Player を兼ねる。全コマンドはロール保持者のみ使用可）
6. トークンと ID を**安全な手段で**現地作業者へ共有（公開チャンネルに貼らない）

> メンバーの追加・削除は以後 **Discord のロール付け外しだけ**で完結する。コードや設定の変更は不要。

---

# Part D: ルーター設定

| 設定 | 内容 |
|---|---|
| ポート開放 | **UDP 8211 → サーバー PC** だけ。外部の友達がゲーム参加するのに必要なのはこれのみ |
| 開放しないもの | SSH(22) / REST(8212) / Bot 関連。保守は Tailscale 経由で行う |
| DHCP 固定 | サーバー PC と Pi の IP を DHCP 予約で固定しておくと安定する |

---

# Part E: 動作確認チェックリスト（この順で）

1. [ ] **SSH 単体**: Pi から `... palbotctl@サーバー status` → `palworld=running/stopped`（B-4）
2. [ ] **Discord status**: `/server status` → online / running が返る
3. [ ] **停止**: `/server stop` → 「保存・停止・バックアップが完了しました。サーバーPCの電源を切ります。」→ **サーバー PC が実際に電源オフになる**
   - 初回は安全のため、サーバー PC で `/etc/palworld-control/control.env` に `PALWORLD_POWEROFF_DRYRUN="1"` を入れて試し、問題なければ行を消して本番挙動にするのも可
4. [ ] **WOL 起動**: PC が電源オフの状態で `/server start` → PC が起動 → 「Palworldサーバーを起動しました。」（数分かかる。タイムアウトする場合は A-2 を見直し）
5. [ ] **ゲーム参加**: Palworld クライアントから「グローバル IP:8211」または LAN 内なら「サーバーPCのIP:8211」+ サーバーパスワードで参加
6. [ ] **人数表示**: 誰かが入った状態で `/server status` → `接続人数: 1 / N`
7. [ ] **停止拒否**: 誰かが入った状態で `/server stop` → 拒否される。Maintainer の `/server stop force:True` でのみ停止できる
8. [ ] **自動復帰**: Pi を再起動 → Bot が自動起動する（B-6 の enable）

---

# トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| Bot 応答「アプリケーションが応答しませんでした」 | Discord の 3 秒制限に通信遅延で間に合わなかった。**もう一度実行すれば OK** |
| `/server start` がタイムアウト | WOL が効いていない。A-2 の BIOS 設定（特に ErP）と `ethtool` の `Wake-on: g` を確認。サーバーが Wi-Fi 接続になっていないか確認 |
| 「バックアップに失敗したため、サーバーPCの電源は切りません。」 | バックアップ先の権限不足が典型。`ls -ld /var/lib/palworld-backups` が `palbotctl` 所有か確認（A-8）。※電源が切れないのは安全設計どおり |
| SSH で `bash\r: No such file or directory` | スクリプトが Windows 改行(CRLF)になっている。`sudo sed -i 's/\r$//' /usr/local/sbin/palworld-control*` で修正 |
| サーバーが起動しない（steamclient.so エラー） | A-5 の steamclient.so 配置をやり直す |
| `players` が失敗する | REST API 設定（A-6 の `RESTAPIEnabled=True` と AdminPassword が control.env と一致しているか）を確認 |
| Bot のログを見たい | Pi で `journalctl -u palworld-bot.service -f` |
| サーバーのログを見たい | サーバー PC で `journalctl -u palworld-server.service -f` |

# 日常運用

- **起動**: Discord で `/server start`（誰でも = Player ロール以上）
- **停止**: 遊び終わったら `/server stop`（0人なら誰でも。バックアップまで自動）
- **メンバー追加**: Discord でロールを付けるだけ
- **ゲーム本体の更新**: サーバー PC で A-5 の `steamcmd +app_update 2394010` を再実行（停止中に）
- **Bot の更新**: Pi で `cd /opt/palworld-server-ops && git pull --ff-only && .venv/bin/pip install -e . && sudo systemctl restart palworld-bot.service`
