# Palworld Server Operations 簡易実装設計書

- 対象: Raspberry Pi上のDiscord Bot、LinuxサーバーPC
- 非対象: Docker、Web管理画面、クラウド、自動デプロイ

## 1. 目的

DiscordからPalworld専用サーバーを起動、状態確認、安全停止できるようにする。

利用人数は固定しない。Discordのロール付与・削除によって参加メンバーを増減できる構成にする。

## 2. 構成

```text
Discordメンバー
    ↓ slash command
Discord Bot（Raspberry Pi）
    ├─ 権限確認
    ├─ Wake on LAN
    └─ Tailscale経由の制限付きSSH
             ↓
LinuxサーバーPC
    ├─ Palworld Dedicated Server
    ├─ systemd
    ├─ 固定コマンド用の制御スクリプト
    └─ バックアップ
```

SSH、管理API、Bot用ポートはルーターで公開しない。

## 3. メンバー管理

人数やユーザーIDをコードへ固定しない。

Discordサーバーに次のロールを作成する。

- `Palworld Player`: status、start、空き状態でのstop
- `Palworld Maintainer`: Playerの権限に加え、接続者がいる状態での停止や保守

`.env`にはロールIDを保存する。

```env
DISCORD_PLAYER_ROLE_ID=
DISCORD_MAINTAINER_ROLE_ID=
```

新しいメンバーを追加するときはDiscord上でPlayerロールを付与する。削除するときはロールを外す。コードや`.env`のユーザー一覧は変更しない。

Botは次を確認する。

1. 指定Guildで実行されたか
2. 指定Channelで実行されたか
3. 実行者がPlayerまたはMaintainerロールを持つか
4. 管理操作ではMaintainerロールを持つか

ロール名ではなくロールIDで判定する。

## 4. サーバー最大人数

Bot側で「4人」を固定値として持たない。

Palworldの最大参加人数はPalworldサーバー設定を正とする。Botは現在の接続人数を取得し、最大人数を取得できる場合だけ`現在人数 / 最大人数`として表示する。

最大人数を取得できない場合でも、起動・停止機能は正常に動作すること。

## 5. MVPコマンド

### `/server status`

Player以上。

表示:

- サーバーPC: offline / online / unknown
- Palworld: stopped / running / unknown
- 現在の接続人数
- 最大人数（取得可能な場合）
- 確認時刻

### `/server start`

Player以上。

1. 既に起動しているか確認
2. offlineならWOLを送信
3. SSH接続可能になるまで待機
4. Palworldサービスを起動
5. runningを確認してDiscordへ通知

同時に複数回実行されても二重起動しないよう、Bot内で操作用Lockを使用する。

### `/server stop`

Player以上。

1. 接続人数を確認
2. 0人なら安全停止を実行
3. 1人以上ならPlayerの停止を拒否
4. Maintainerだけが確認付きで停止可能
5. ワールド保存
6. Palworld終了
7. バックアップ
8. バックアップ成功後にLinuxをpoweroff

バックアップに失敗した場合はOSをpoweroffしない。

## 6. SSH制御

Discordの入力をそのままシェルへ渡さない。

Botから実行できるリモート操作は次の固定値だけにする。

```text
status
start
stop
```

禁止:

- `/run`
- 任意のSSHコマンド
- `shell=True`
- Discord入力の文字列連結

サーバーPC側でも固定コマンド以外を拒否する。

## 7. ファイル構成

```text
palworld-server-ops/
├─ src/palworld_bot/
│  ├─ main.py
│  ├─ config.py
│  ├─ auth.py
│  ├─ discord_app.py
│  └─ services/
│     ├─ wol.py
│     ├─ ssh_control.py
│     └─ server_manager.py
├─ scripts/server/
│  ├─ palworld-control
│  └─ backup.sh
├─ systemd/
│  ├─ palworld-bot.service.example
│  └─ palworld-server.service.example
├─ tests/
├─ .env.example
├─ CLAUDE.md
└─ README.md
```

## 8. 実装順序

### Phase 1

- 設定読み込み
- Discordロール認証
- `/server status`
- モックを用いたテスト

### Phase 2

- WOL
- `/server start`
- 起動待機とタイムアウト

### Phase 3

- 接続人数確認
- `/server stop`
- 保存、バックアップ、poweroff

この3段階で完成とする。restart、update、Web UIは必要になった時だけ追加する。

## 9. 完了条件

- Playerロールの人数を変更してもコード変更が不要
- 4人という固定値がソースコードに存在しない
- status、start、stopが動作する
- 接続者がいる状態で一般Playerが停止できない
- SSHや管理APIを公開していない
- 秘密情報がGitに含まれていない
- `ruff check .`、`mypy src`、`pytest`が成功する
