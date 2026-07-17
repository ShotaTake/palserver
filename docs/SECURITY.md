# セキュリティ設計（簡易版）

## 1. 公開範囲

ルーターで公開しないもの:

- Raspberry PiのSSH
- サーバーPCのSSH
- Palworld REST API
- Discord Bot用の独自ポート

管理接続はTailscale内だけで行う。

## 2. Discord権限

メンバー数を固定しないため、User ID一覧ではなくDiscordロールIDで管理する。

- Playerロール: status、start、0人時のstop
- Maintainerロール: Player権限と管理停止

BotはGuild ID、Channel ID、Role IDをすべて検証する。

Discordサーバーでロールを付与できる権限は、信頼できる管理者だけに与える。誰でもPlayer/Maintainerロールを付けられる設定では、Bot側の認証が無意味になる。

## 3. 任意コマンドを禁止

Botがサーバーへ送信できる値は`status`、`start`、`stop`だけとする。

- `shell=True`禁止
- `/run`禁止
- Discord入力をシェル文字列へ埋め込まない
- サーバーPC側でも固定コマンド以外を拒否する

## 4. 停止時の保護

- 接続人数0人: Playerが停止可能
- 接続人数1人以上: Playerは停止不可
- Maintainerのみ確認後に停止可能
- 保存とバックアップが成功してからpoweroff
- バックアップ失敗時はpoweroffしない

人数の上限は固定しない。判定は常に実際の現在接続人数を使う。

## 5. GitHub

main直接pushを採用するが、次は禁止する。

- force push
- 秘密情報のcommit
- テスト未実行でのpush
- 本番サーバー上だけを直接編集してGitと差を作ること

main直接運用では誤変更をレビューで防げないため、push前の`git diff`確認と小さなcommitが必須になる。
