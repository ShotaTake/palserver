# 追加コマンドを本番環境へ反映する手順

対象は、すでに Valheim と Discord Bot が動いている環境です。
`/server update`・`/server diagnose`・`/server backups`・`/server restore`・`/server help` を反映します。
この手順は GitHub の `main` に変更が push された後に実施します。

## どこで実行するか

| 端末 | リポジトリ | 作業 |
|---|---|---|
| Raspberry Pi | `/opt/gameserver-ops` | Bot の停止、コード更新、起動 |
| サーバー PC（Linux） | `~/palserver` | 制御スクリプトと更新・復元用サービスの導入 |
| Discord | 設定済みのコマンド用チャンネル | コマンドの確認 |

以下のコマンドは SSH などで各端末のターミナルに入り、そこで実行してください。
リポジトリの場所が異なる場合は `cd` のパスを読み替えます。

初回は「全機能の反映」を順番に実施します。
更新・診断・復元機能を導入済みで、`/server help` など Bot 側だけの変更を取り込む場合は、後半の「Bot だけを更新する」を使えます。

## 全機能の反映

### 1. 作業前の確認

- プレイヤーがいない時間に作業し、作業中は接続を控えてもらいます。
- サーバー PC を起動し、管理用 SSH で接続できる状態にします。必要なら Bot を停止する前に `/server start` を使います。
- 更新・復元が実行中でないことを `/server status` で確認します。
- サーバー PC の標準構成は `valheim` / `palbotctl` ユーザー、ゲーム本体 `/opt/valheim-server`、SteamCMD `/usr/games/steamcmd` です。保守機能には `/usr/bin/python3` が Python 3.10 以上であることが必要です。Pi の Bot 本体は Python 3.11 以上が必要です。
- ワールドは `/home/valheim/.config/unity3d/IronGate/Valheim/worlds_local`、バックアップは `/var/lib/gameserver-backups` を前提にしています。独自構成は [更新機能の導入](UPDATE_SETUP.md) と [保守機能の導入](MAINTENANCE_SETUP.md) を先に確認してください。

各コマンドが成功してから次へ進んでください。エラーが出た場合は、その段階で止めて「うまくいかない場合」を参照します。

### 2. Raspberry Pi：Bot を止めてコードを更新

```bash
sudo systemctl stop gameserver-bot.service
cd /opt/gameserver-ops
git status --short --branch
```

`main` ブランチで、ローカル変更がないことを確認してから実行します。

```bash
git pull --ff-only origin main
.venv/bin/pip install -e .
git log -1 --oneline
```

最後に出たコミット ID を控えてください。Bot はまだ起動しません。
Bot を停止することで、導入中のコマンド受付や無人時の自動シャットダウンを止めます。

### 3. サーバー PC：同じコードを取得

サーバー PC のターミナルへ切り替えます。

```bash
cd ~/palserver
git status --short --branch
```

こちらも `main` ブランチで、ローカル変更がないことを確認してから実行します。

```bash
git pull --ff-only origin main
git log -1 --oneline
```

Pi と同じコミット ID であることを確認してください。

### 4. サーバー PC：導入内容を確認して適用

まず、変更を行わない確認モードで実行します。

```bash
sudo bash scripts/setup/install-update.sh --dry-run
sudo bash scripts/setup/install-maintenance.sh --dry-run
```

エラーがなければ、順に適用します。

```bash
sudo bash scripts/setup/install-update.sh
sudo bash scripts/setup/install-maintenance.sh
```

各スクリプトは sudoers の文法を検証し、追加する限定権限を表示します。
内容を確認し、適用する場合は確認入力に `yes` と入力してください。
既存の導入先ファイルはスクリプトが退避します。

この段階では制御スクリプト・サービス・権限設定を導入するだけで、ゲーム本体の更新やワールド復元は実行しません。
通常の機能追加では、移行用の `migrate-server.sh` を実行する必要はありません。

### 5. Raspberry Pi：Bot を起動

Raspberry Pi のターミナルへ戻ります。

```bash
sudo systemctl start gameserver-bot.service
systemctl status gameserver-bot.service --no-pager
journalctl -u gameserver-bot.service -n 50 --no-pager
```

`active (running)` になり、ログに起動や Discord 接続のエラーがないことを確認します。
Bot は起動時に、設定された Discord サーバーへスラッシュコマンドを同期します。

### 6. Discord：反映を確認

設定済みのコマンド用チャンネルで、次を順に確認します。

| コマンド | 確認内容 |
|---|---|
| `/server help` | 自分だけにヘルプが表示される。Player と Maintainer で案内が切り替わる |
| `/server status` | PC・ゲームの状態と接続人数を取得できる |
| `/server diagnose` | Maintainer で診断できる。問題が表示された項目を確認する |
| `/server backups` | Maintainer で一覧を取得できる。保存済みアーカイブがなければ空で正常 |

確認のためだけに本番ワールドを復元する必要はありません。
復元の実機テストは、失って困らないテスト用ワールドとバックアップで行ってください。

## 以降のゲーム本体の更新

プレイヤーがいない時間に、Maintainer が指定チャンネルで実行します。

```text
/server update
```

PC がオフなら WOL で起動し、無人を確認して、保存・停止 → バックアップ → SteamCMD による更新 → ゲーム起動を行います。
ゲームが稼働中で接続者がいる、または人数を確認できない場合は更新を拒否します。

`/server status` で進行を確認し、完了通知後にゲームから接続してください。
失敗・通信切断時は、再実行する前に状態を確認します。
詳しい動作と制限は [UPDATE_SETUP.md](UPDATE_SETUP.md) に記載しています。

`/server update` が更新するのはゲーム本体です。Bot・OS・MOD の更新は含みません。

## Bot だけを更新する

サーバー側の更新・保守機能を導入済みで、Bot 側だけを変更した場合の手順です。
GitHub の `main` への push が完了し、ゲームの更新・復元や起動・停止操作が進行中でない状態で行います。

Raspberry Pi で実行します。

```bash
cd /opt/gameserver-ops
git status --short --branch
```

`main` ブランチでローカル変更がないことを確認したら、次へ進みます。

```bash
sudo systemctl stop gameserver-bot.service
git pull --ff-only origin main
.venv/bin/pip install -e .
sudo systemctl start gameserver-bot.service
systemctl status gameserver-bot.service --no-pager
journalctl -u gameserver-bot.service -n 50 --no-pager
```

途中でエラーが出たら後続のコマンドは実行せず、原因を確認してください。
`/server help` のみの変更なら、サーバー PC 側の再導入は不要です。

## うまくいかない場合

### git pull が失敗した

ローカル変更やブランチの分岐があれば、更新は止めます。
`git status` で状況を確認し、変更を退避・整理してからやり直してください。
作業内容を確認せず `git reset --hard` やリポジトリ削除で解消しないでください。

### 導入スクリプトが失敗した

Python 3.10.x なのに「Python 3.11 以上が必要」と表示される場合は、古い導入スクリプトを使っています。サーバー PC で `git pull --ff-only origin main` を実行し、`sudo bash scripts/setup/install-maintenance.sh --dry-run` から再開してください。サーバー PC 側の保守機能のために Python を3.11へ入れ替える必要はありません。判定対象は `/usr/bin/python3 --version` で確認できます。

Bot を停止したまま、表示された不足条件を確認します。
Python のバージョン、ユーザー、保存先、SteamCMD の場所、進行中の更新・復元が主な確認項目です。
原因を解消してから該当スクリプトを再実行し、両方の導入が成功してから Bot を起動します。

### コマンドが出ない／使えない

- Pi のサービスが `active (running)` か、起動ログに同期エラーがないかを確認します。
- Bot を登録した Discord サーバーと、設定済みのチャンネルで実行しているか確認します。
- サーバー操作には Player または Maintainer、保守操作には Maintainer が必要です。`/server help` は指定チャンネルならロールなしでも利用できます。
- 同期が成功している場合は Discord を再読み込みし、コマンド候補を確認します。

### 更新・復元で問題が出た

まず `/server status` と `/server diagnose` を確認します。
詳細が必要ならサーバー PC でログを確認してください。

```bash
sudo journalctl -u valheim-update.service -n 100 --no-pager
sudo journalctl -u valheim-restore.service -n 100 --no-pager
sudo journalctl -u valheim-server.service -n 100 --no-pager
```

復元の手動確認が必要と表示された場合は、保護を解除する前に [MAINTENANCE_SETUP.md の中断・失敗時](MAINTENANCE_SETUP.md#中断失敗時) を参照してください。
ログや設定を共有する場合は、トークン・パスワード・秘密鍵を含めないでください。
