# 本番セットアップ手順書（サーバー管理者向け）

この手順書だけで、**現地作業者（サーバー PC と Raspberry Pi を設置する人）が一人で**セットアップを完了できるように書かれています。リモートの協力者は Discord 側の作業（Bot 作成・ロール管理）だけ分担できます。

ゲーム本体（Valheim）の導入は **[VALHEIM_SETUP.md](VALHEIM_SETUP.md)** に分けてあります。こちらは Bot・WOL・SSH・Discord・ルーターの手順です。

## 全体像

```
[設置場所（自宅）]
  Raspberry Pi ── 常時起動。Discord Bot + Wake on LAN 送信
  サーバー PC  ── Ubuntu + Valheim。普段は電源オフ、遊ぶときだけ Bot が起こす
  ルーター     ── ゲームポート UDP 35520 だけ開放（SSH や管理ポートは開放しない）
[インターネット]
  Discord ⇔ Pi（Bot が外向きに接続。着信ポート開放は不要）
```

動作の流れ: Discord で `/server start` → Pi の Bot が WOL でサーバー PC を起動 → SSH（固定コマンドのみ）で Valheim を起動。`/server stop` → 保存して停止 → バックアップ → 電源オフ。

管理接続（SSH）は **LAN 内だけ**で行い、インターネットには出しません。宅外から保守したい場合だけ Tailscale などの VPN を足してください（必須ではありません）。

## 必要なもの

- [ ] サーバー PC（x86-64。Valheim 専用サーバーはメモリ 4GB 程度から動くが 8GB 以上推奨）
- [ ] **サーバー PC は有線 LAN 接続**（Wake on LAN は Wi-Fi では動かない）
- [ ] Raspberry Pi（3 以降、64bit 推奨）+ SD カード + 電源。**可能なら有線 LAN**
- [ ] Ubuntu Server 24.04 LTS のインストール USB
- [ ] Discord の Bot トークンと各種 ID（→「Part C」参照。リモート協力者が用意して安全な手段で共有しても良い）

> このリポジトリは **public** なので、クローンに GitHub アカウントや認証は不要です。以降の `git clone https://github.com/ShotaTake/palserver.git` はそのまま実行できます。

---

# Part A: サーバー PC

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

# WOL に必要な MAC アドレスをメモしておく（後で Pi の bot.env に書く）
ip link show enp3s0 | grep ether
```

**ここで一度 WOL テストをする**（これが通らないと全部無意味なので最初に確認）:

```bash
sudo poweroff
```

→ 同じ LAN 内の別マシン（Pi のセットアップ後なら Pi、スマホの WOL アプリでも可）からマジックパケットを送って**電源が入るか確認**。入らなければ BIOS 設定を見直す。

## A-3. Valheim の導入

**[VALHEIM_SETUP.md](VALHEIM_SETUP.md)** に従って、次まで済ませてください。

- `valheim` ユーザーと `/opt/valheim-server`
- SteamCMD で App ID **896660** を導入
- `/etc/valheim/valheim.env`（サーバー名・ワールド名・パスワード）
- `valheim-server.service`（**`KillSignal=SIGINT` と `SteamAppId=892970` が必須**）
- `sudo ufw allow 35520:35521/udp`

`systemctl status valheim-server.service` が `active (running)` になり、**一度停止して再起動してもワールドの進行が残る**ことまで確認してから先へ進みます。

## A-4. 制御用ユーザー

```bash
sudo useradd -m -s /bin/bash palbotctl
```

ゲームを動かす `valheim` ユーザーとは別にします。Bot が入ってくる口を、ゲームの権限から切り離しておくためです。

## A-5. 制御スクリプトの設置

```bash
sudo apt install -y git
git clone https://github.com/ShotaTake/palserver.git ~/palserver
cd ~/palserver

sudo install -m 0755 scripts/server/valheim-control          /usr/local/sbin/valheim-control
sudo install -m 0755 scripts/server/valheim-control-ssh      /usr/local/sbin/valheim-control-ssh
sudo install -m 0755 scripts/server/valheim-query            /usr/local/sbin/valheim-query
sudo install -m 0755 scripts/server/gameserver-backup        /usr/local/sbin/gameserver-backup
sudo install -m 0755 scripts/server/gameserver-safe-poweroff /usr/local/sbin/gameserver-safe-poweroff
```

バックアップ先を用意します（**`palbotctl` 所有にすること**。root のままだとバックアップに失敗し、安全設計により電源も切れません）:

```bash
sudo install -d -o palbotctl -g palbotctl -m 0750 /var/lib/gameserver-backups
```

クエリポートを設定します。`valheim-control` の既定は 2457 なので、**ゲームポートを 35520 にしている以上ここは必須**です。書かないと起動状態は正しく出るのに人数だけ取れません。

```bash
sudo mkdir -p /etc/gameserver-control
sudo nano /etc/gameserver-control/control.env
```

```bash
VALHEIM_QUERY_PORT="35521"
```

```bash
sudo chown root:palbotctl /etc/gameserver-control/control.env
sudo chmod 640 /etc/gameserver-control/control.env
```

サービス名やワールドの場所も同じファイルで上書きできます。**group/world 書き込み可だとスクリプトが読み込みを拒否する**ので 640 を守ってください。

> Valheim には管理パスワードの類が要りません。control.env に秘密情報を書く必要はありません。

動作確認:

```bash
sudo -u palbotctl /usr/local/sbin/valheim-control status    # valheim=running
sudo -u palbotctl /usr/local/sbin/valheim-control players   # players=0 / max_players=N
```

## A-6. sudoers（palbotctl に固定コマンドだけ許可）

```bash
sudo visudo -f /etc/sudoers.d/gameserver-control
```

```
palbotctl ALL=(root) NOPASSWD: /usr/bin/systemctl start valheim-server.service, /usr/bin/systemctl stop valheim-server.service, /usr/local/sbin/gameserver-safe-poweroff
```

保存後に検証: `sudo visudo -cf /etc/sudoers.d/gameserver-control` → `parsed OK`

`systemctl is-active`（状態確認）は意図的に含めていません。特権が要るのは起動・停止・電源断だけです。

## A-7. Bot 用 SSH 受け口

**Pi 側で作った公開鍵**（→ B-4。`ssh-ed25519 AAAA...` の1行）を登録:

```bash
sudo install -d -m 0700 -o palbotctl -g palbotctl /home/palbotctl/.ssh
sudo nano /home/palbotctl/.ssh/authorized_keys
```

次の**1行**を書く（`ssh-ed25519 AAAA...` 部分を Pi の公開鍵に置き換え）:

```
restrict,command="/usr/local/sbin/valheim-control-ssh" ssh-ed25519 AAAA... gameserver-bot@raspberrypi
```

```bash
sudo chown palbotctl:palbotctl /home/palbotctl/.ssh/authorized_keys
sudo chmod 600 /home/palbotctl/.ssh/authorized_keys
```

> `restrict,command="..."` が付いていることを必ず確認してください。これが Bot に「決められたコマンドしか実行させない」仕組みそのものです。

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
```

## B-3. Bot のデプロイ

```bash
sudo useradd -r -m -d /var/lib/gameserver-bot -s /usr/sbin/nologin gameserver-bot

# クローン先を自分（ログインユーザー）所有で用意し、sudo なしで clone/pull できるようにする
sudo install -d -o "$USER" /opt/gameserver-ops
git clone https://github.com/ShotaTake/palserver.git /opt/gameserver-ops
cd /opt/gameserver-ops
python3 -m venv .venv
.venv/bin/pip install -e .
```

> `/opt` に置くのは、Bot のサービスが `ProtectHome=true` で動く（`/home` が見えない）ためです。ホーム配下に置くと起動しません。

## B-4. SSH 鍵の生成と登録

```bash
sudo -u gameserver-bot mkdir -p /var/lib/gameserver-bot/.ssh
sudo -u gameserver-bot ssh-keygen -t ed25519 \
  -f /var/lib/gameserver-bot/.ssh/id_ed25519 -N "" -C gameserver-bot@raspberrypi

# 公開鍵を表示 → この1行をサーバー PC の A-7 に登録する
sudo cat /var/lib/gameserver-bot/.ssh/id_ed25519.pub
```

> 秘密鍵（`id_ed25519`）は Pi の外に持ち出さない。登録するのは `.pub` の方だけ。

サーバー PC 側の A-7 が済んだら疎通確認（初回は `yes` と答える。これで known_hosts に固定される）:

```bash
sudo -u gameserver-bot ssh -i /var/lib/gameserver-bot/.ssh/id_ed25519 palbotctl@<サーバーのIP> status
# → valheim=running (または stopped) が返れば成功
sudo -u gameserver-bot ssh -i /var/lib/gameserver-bot/.ssh/id_ed25519 palbotctl@<同上> ls
# → command denied が返れば制限も正常
```

## B-5. Bot の設定

```bash
sudo mkdir -p /etc/gameserver-bot
sudo cp /opt/gameserver-ops/config/bot.env.example /etc/gameserver-bot/bot.env
sudo nano /etc/gameserver-bot/bot.env
sudo chmod 600 /etc/gameserver-bot/bot.env
```

記入内容:

| キー | 値 |
|---|---|
| `DISCORD_BOT_TOKEN` | Bot のトークン（Part C。**チャットや Git に貼らない**） |
| `DISCORD_GUILD_ID` ほか ID 系 | Part C で取得した各 ID |
| `SERVER_MAC_ADDRESS` | サーバー PC の有線 NIC の MAC（A-2 でメモした値） |
| `SERVER_LAN_BROADCAST` | LAN のブロードキャスト（例: `192.168.1.255`） |
| `SERVER_TAILSCALE_HOST` | サーバーの **固定 LAN IP**（例: `192.168.1.100`）。Tailscale を使うならそのホスト名 |
| `SERVER_SSH_USER` | `palbotctl` |
| `SERVER_SSH_KEY_PATH` | `/var/lib/gameserver-bot/.ssh/id_ed25519` |
| `SERVER_SSH_KNOWN_HOSTS_PATH` | `/var/lib/gameserver-bot/.ssh/known_hosts` |
| `GAME_PORT` | `35520` |

> 値の後ろに `# コメント` を書かないこと。systemd の `EnvironmentFile` はコメントごと値として読みます。

`/取引` を使う場合は、画像を Pi 上に置いて `PAL_IMAGE_DIR` にそのパスを指定します（画像は Git に含めていません）。

## B-6. Bot の systemd 化

```bash
sudo cp /opt/gameserver-ops/systemd/gameserver-bot.service.example /etc/systemd/system/gameserver-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now gameserver-bot.service
systemctl status gameserver-bot.service     # active (running) を確認
journalctl -u gameserver-bot.service -n 20  # 「logged in as ...」が出ていれば OK
```

---

# Part C: Discord（リモート協力者が分担可能）

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application → 左メニュー **Bot** → **Reset Token** でトークン取得
   - Privileged Gateway Intents は**すべて OFF のまま**
   - PUBLIC BOT は OFF 推奨
2. 遊ぶ用の Discord サーバーに、コマンド用チャンネル（例: `#server-control`）、通知用チャンネル（任意）、ロール **Player** / **Maintainer** を作成
3. OAuth2 → URL Generator で `bot` + `applications.commands`（権限は Send Messages / Attach Files）→ 生成 URL からサーバーに招待
4. ユーザー設定 → 詳細設定 → **開発者モード ON** → 右クリックで各 ID をコピー:
   - サーバー ID / チャンネル ID / 各ロール ID
5. メンバーにロールを付与（Maintainer は Player を兼ねる。全コマンドはロール保持者のみ使用可）
6. トークンと ID を**安全な手段で**現地作業者へ共有（公開チャンネルに貼らない）

> メンバーの追加・削除は以後 **Discord のロール付け外しだけ**で完結する。コードや設定の変更は不要。

---

# Part D: ルーター設定

| 設定 | 内容 |
|---|---|
| ポート開放 | **UDP 35520 → サーバー PC** だけ。外部・内部とも同じ番号にすること。クエリポート 35521 は人数取得が loopback 経由なので転送不要（サーバー一覧に載せる場合のみ必要） |
| 開放しないもの | SSH(22) / Bot 関連。管理接続は LAN 内だけで行う |
| DHCP 固定 | サーバー PC と Pi の IP を DHCP 予約で固定しておくと安定する |

グローバル IP が変わる回線の場合、現在の接続先は Discord の `/server address` で確認できます（変わったときは自動で通知されます）。

---

# Part E: 動作確認チェックリスト（この順で）

1. [ ] **SSH 単体**: Pi から `... palbotctl@サーバー status` → `valheim=running/stopped`（B-4）
2. [ ] **Discord status**: `/server status` → online / running が返る
3. [ ] **停止**: `/server stop` → 「保存・停止・バックアップが完了しました。」→ **サーバー PC が実際に電源オフになる**
   - 初回は安全のため、サーバー PC の `/etc/gameserver-control/control.env` に `GAMESERVER_POWEROFF_DRYRUN="1"` を入れて試し、問題なければ行を消して本番挙動にするのも可
4. [ ] **セーブ確認**: 上の停止のあと起動し直して、**ワールドの進行が残っている**（SIGINT が効いている証拠。ここが一番重要）
5. [ ] **WOL 起動**: PC が電源オフの状態で `/server start` → PC が起動 → 「サーバーを起動しました。」（数分かかる。タイムアウトする場合は A-2 を見直し）
6. [ ] **ゲーム参加**: Valheim クライアントから「グローバル IP:35520」または LAN 内なら「192.168.1.100:35520」+ サーバーパスワードで参加
7. [ ] **人数表示**: 誰かが入った状態で `/server status` → `接続人数: 1 / N`
8. [ ] **停止拒否**: 誰かが入った状態で `/server stop` → 拒否される。Maintainer の `/server stop force:True` でのみ停止できる
9. [ ] **自動復帰**: Pi を再起動 → Bot が自動起動する（B-6 の enable）

---

# Part F: Palworld 版からの移行

すでに Palworld 版を運用していた場合の差し替えです。新規構築なら読み飛ばしてください。

**各マシンでスクリプトを1本実行するだけ**で済みます。手で追いたい場合は末尾の付録に同じ内容の手順があります。

## 順番

サーバー PC が先です。ラズパイ側の最後の疎通確認が、サーバー PC の SSH 受け口が更新済みであることを前提にしています。

### 1. サーバー PC

```bash
sudo apt install -y git
git clone https://github.com/ShotaTake/palserver.git ~/palserver
cd ~/palserver
sudo bash scripts/setup/migrate-server.sh --dry-run
```

`--dry-run` は**何も変更せず、実行する内容をすべて表示するだけ**です。この出力をそのまま管理者に送り、確認してもらってから本番を実行します。

```bash
sudo bash scripts/setup/migrate-server.sh
```

途中で Valheim のサーバー名・ワールド名・パスワードを聞かれます。事前に用意した値ファイルがあるなら、聞かれずに済みます。

```bash
sudo bash scripts/setup/migrate-server.sh --values ~/valheim-values.env
```

値ファイルの雛形は [config/valheim.env.example](../config/valheim.env.example) です。

### 2. ラズパイ

```bash
sudo apt install -y git python3-venv
git clone https://github.com/ShotaTake/palserver.git ~/palserver
cd ~/palserver
sudo bash scripts/setup/migrate-pi.sh --dry-run
sudo bash scripts/setup/migrate-pi.sh
```

Discord トークンも SSH 鍵も**既存の設定から引き継ぐ**ので、入力するものはありません。

### 3. ルーター

ここだけは手作業です。ゲームポートは Palworld と同じ **35520** を使うので、既存の転送ルールが `35520 → 35520` になっていれば**何もしなくて済みます**。

確認してほしいのは 1 点だけ: 外部ポートが 35520 で内部ポートが 8211 のような**ポート変換になっていないか**。なっていたら内部側も 35520 に直してください。

### 4. 確認と片付け

Discord で Part E のチェックリストを流します。全部通ったら、両方のマシンで旧環境を片付けます。

```bash
sudo bash scripts/setup/cleanup-palworld.sh --dry-run
sudo bash scripts/setup/cleanup-palworld.sh
```

## スクリプトが何をするか

| | サーバー PC (`migrate-server.sh`) | ラズパイ (`migrate-pi.sh`) |
|---|---|---|
| 旧環境 | 保存して停止 → 最終バックアップ → `disable` → ユニットを退避して `mask` | 旧 Bot を `disable --now` |
| 導入 | SteamCMD で Valheim、`valheim.env`、ユニット（`KillSignal=SIGINT` を検証） | `gameserver-bot` ユーザー、`/opt/gameserver-ops`、venv |
| 引き継ぎ | — | SSH 鍵・known_hosts・`bot.env`（4キーだけ書き換え） |
| 権限 | 制御スクリプト5本、バックアップ先、ufw、sudoers、`authorized_keys` | — |
| 確認 | 起動 → A2S 応答 → `status`/`players`/`restart` | サービス起動 → SSH で `status` と `command denied` の両方 |

`mask` の前にユニット実体を退避するのは、`systemctl mask` が `/etc/systemd/system/<ユニット名>` に `/dev/null` へのリンクを張る仕組みで、同じパスに実ファイルがあると失敗するためです。

`authorized_keys` の場所は決め打ちせず、`sshd -T` に聞いて実際の参照先を使います。既定以外のファイル名を設定している sshd は珍しくなく、決め打ちで書いて動かなかったことが実際にあります。

## 安全のための設計

- **何度実行しても同じ結果**になります。途中で失敗したら、直して頭から再実行できます
- 置き換えるファイルには必ず `.bak.<日時>` を残します
- **Palworld のセーブデータとバックアップは削除しません**。`cleanup-palworld.sh` も触りません
- sudoers と `authorized_keys` は、**中身を全文表示して `yes` を打たせてから**書きます。sudoers は `visudo -c` を通してからでないと適用しません
- Discord トークンは一度も画面に出しません

途中で止まったときは、出力をそのまま送ってください。

---

# 付録: 手作業で移行する

スクリプトを使わずに手で移行する場合の手順です。スクリプトが途中で失敗したときの参照用でもあります。

**サーバー PC:**

```bash
# 1. 旧サーバーを止めて自動起動を切る
sudo systemctl disable --now palworld-server.service

# 2. Valheim を構築（VALHEIM_SETUP.md）してから、制御スクリプトを入れ替え
cd ~/palserver && git pull --ff-only
sudo install -m 0755 scripts/server/valheim-control          /usr/local/sbin/valheim-control
sudo install -m 0755 scripts/server/valheim-control-ssh      /usr/local/sbin/valheim-control-ssh
sudo install -m 0755 scripts/server/valheim-query            /usr/local/sbin/valheim-query
sudo install -m 0755 scripts/server/gameserver-backup        /usr/local/sbin/gameserver-backup
sudo install -m 0755 scripts/server/gameserver-safe-poweroff /usr/local/sbin/gameserver-safe-poweroff

# 3. バックアップ先
sudo install -d -o palbotctl -g palbotctl -m 0750 /var/lib/gameserver-backups

# 4. クエリポート（ゲームポート 35520 に対して +1）。既定の 2457 のままだと人数が取れない
sudo mkdir -p /etc/gameserver-control
echo 'VALHEIM_QUERY_PORT="35521"' | sudo tee /etc/gameserver-control/control.env
sudo chown root:palbotctl /etc/gameserver-control/control.env
sudo chmod 640 /etc/gameserver-control/control.env
```

`authorized_keys` の forced command を新しいラッパーへ向けます。**手で開いて 1 行を書き換えてください**（この行は Bot の権限そのものなので、目で確認してから直します）:

```bash
sudo nano /home/palbotctl/.ssh/authorized_keys
# command="/usr/local/sbin/palworld-control-ssh"
#   ↓
# command="/usr/local/sbin/valheim-control-ssh"
```

sudoers も張り替えます（A-6 の 1 行を書いてから旧ファイルを消す）:

```bash
sudo visudo -f /etc/sudoers.d/gameserver-control
sudo visudo -cf /etc/sudoers.d/gameserver-control     # parsed OK を確認
sudo rm /etc/sudoers.d/palworld-control
```

Valheim 側の疎通確認（`valheim-control status` と Discord の `/server status`）が通ってから、旧スクリプトと旧設定を撤去します:

```bash
sudo rm -f /usr/local/sbin/palworld-control /usr/local/sbin/palworld-control-ssh \
  /usr/local/sbin/palworld-backup /usr/local/sbin/palworld-safe-poweroff
sudo rm -rf /etc/palworld-control
```

**Raspberry Pi:**

```bash
# 1. 旧 Bot を止める
sudo systemctl disable --now palworld-bot.service

# 2. 新しいユーザーとクローン先
sudo useradd -r -m -d /var/lib/gameserver-bot -s /usr/sbin/nologin gameserver-bot
sudo install -d -o "$USER" /opt/gameserver-ops
git clone https://github.com/ShotaTake/palserver.git /opt/gameserver-ops
cd /opt/gameserver-ops && python3 -m venv .venv && .venv/bin/pip install -e .

# 3. SSH 鍵と known_hosts を引き継ぐ（作り直して A-7 に再登録しても良い）
sudo cp -a /var/lib/palworld-bot/.ssh /var/lib/gameserver-bot/.ssh
sudo chown -R gameserver-bot:gameserver-bot /var/lib/gameserver-bot/.ssh

# 4. 設定を引き継いで、パスと新項目を直す
sudo mkdir -p /etc/gameserver-bot
sudo cp /etc/palworld-bot/bot.env /etc/gameserver-bot/bot.env
sudo nano /etc/gameserver-bot/bot.env
sudo chmod 600 /etc/gameserver-bot/bot.env
```

`bot.env` で直すのは次の 4 か所です:

| キー | 新しい値 |
|---|---|
| `SERVER_SSH_KEY_PATH` | `/var/lib/gameserver-bot/.ssh/id_ed25519` |
| `SERVER_SSH_KNOWN_HOSTS_PATH` | `/var/lib/gameserver-bot/.ssh/known_hosts` |
| `GAME_PORT` | `35520` |
| `GAME_NAME` | `Valheim`（無ければ追記） |

サーバー PC 側で `/etc/gameserver-control/control.env` に `VALHEIM_QUERY_PORT="35521"` を書くのも忘れないでください（A-5）。ここを飛ばすと `/server status` の人数だけが空になります。

```bash
# 5. サービスを入れ替え
sudo cp /opt/gameserver-ops/systemd/gameserver-bot.service.example /etc/systemd/system/gameserver-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now gameserver-bot.service
journalctl -u gameserver-bot.service -n 30

# 6. 動いたら旧環境を撤去
sudo rm /etc/systemd/system/palworld-bot.service
sudo systemctl daemon-reload
sudo rm -rf /etc/palworld-bot /opt/palworld-server-ops
sudo userdel -r palworld-bot
```

`/取引` の画像を旧クローンに置いていた場合は、消す前に新しい場所へ移してください。

**ルーター:** ゲームポートは 35520 のままなので、既存の転送が `35520 → 35520` なら変更不要です。ポート変換になっている場合だけ内部側を 35520 に直します。
---

# トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| Bot 応答「アプリケーションが応答しませんでした」 | Discord の 3 秒制限に通信遅延で間に合わなかった。**もう一度実行すれば OK** |
| `/server start` がタイムアウト | WOL が効いていない。A-2 の BIOS 設定（特に ErP）と `ethtool` の `Wake-on: g` を確認。サーバーが Wi-Fi 接続になっていないか確認。冷間起動が遅いだけなら `SERVER_BOOT_TIMEOUT_SECONDS` を伸ばす |
| SSH が `Permission denied (publickey)` | 鍵も権限も正しいのに通らない場合、sshd が既定以外の `AuthorizedKeysFile` を見ていることがある。`sudo sshd -T` の出力から `authorizedkeysfile` の行を探して実際の参照先を確認する |
| 「バックアップに失敗したため、サーバーPCの電源は切りません。」 | バックアップ先の権限不足が典型。`ls -ld /var/lib/gameserver-backups` が `palbotctl` 所有か確認（A-5）。※電源が切れないのは安全設計どおり |
| 停止のたびにワールドが巻き戻る | `valheim-server.service` に `KillSignal=SIGINT` が無い。VALHEIM_SETUP.md の 4 章 |
| SSH で `bash\r: No such file or directory` | スクリプトが Windows 改行(CRLF)になっている。`sudo sed -i 's/\r$//' /usr/local/sbin/valheim-*` で修正 |
| `players` が取れない（状態は出るのに人数だけ空） | `/etc/gameserver-control/control.env` の `VALHEIM_QUERY_PORT` がゲームポート+1（35521）になっているか確認。既定の 2457 のままだとこうなる |
| Bot のログを見たい | Pi で `journalctl -u gameserver-bot.service -f` |
| サーバーのログを見たい | サーバー PC で `journalctl -u valheim-server.service -f` |

# 日常運用

- **起動**: Discord で `/server start`（Player ロール以上）
- **停止**: 遊び終わったら `/server stop`（0人なら誰でも。バックアップまで自動）。放置しても無人が続けば自動で落ちる
- **メンバー追加**: Discord でロールを付けるだけ
- **ゲーム本体の更新**: サーバー PC で VALHEIM_SETUP.md の 9 章（停止 → `steamcmd +app_update 896660 validate` → 起動）
- **Bot の更新**: Pi で `cd /opt/gameserver-ops && git pull --ff-only && .venv/bin/pip install -e . && sudo systemctl restart gameserver-bot.service`
- **サーバー側スクリプトの更新**: サーバー PC で `cd ~/palserver && git pull --ff-only` してから A-5 の `install` を再実行
