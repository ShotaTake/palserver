# セキュリティ設計（簡易版）

## 1. 公開範囲

ルーターで開放するのは**ゲームポート（UDP 35520）だけ**。クエリポート（35521）は人数取得が `127.0.0.1` 宛なので開ける必要がない。

公開しないもの:

- Raspberry PiのSSH
- サーバーPCのSSH
- Bot用の独自ポート（そもそも待ち受けない。BotはDiscordへ外向きに接続するだけ）

管理接続はLAN内だけで行う。宅外から保守したい場合はVPN（Tailscale等）を足す。ポート転送で代用しない。

## 2. Discord権限

メンバー数を固定しないため、User ID一覧ではなくDiscordロールIDで管理する。

- Playerロール: status、start、address、load、0人時のstop
- Maintainerロール: Player権限に加えて、restartと強制stop

BotはGuild ID、Channel ID、Role IDをすべて検証する。

Discordサーバーでロールを付与できる権限は、信頼できる管理者だけに与える。誰でもPlayer/Maintainerロールを付けられる設定では、Bot側の認証が無意味になる。

## 3. 任意コマンドを禁止

Botがサーバーへ送信できるのは固定の名前だけ: `status`、`start`、`players`、`metrics`、`restart`、`shutdown`、`backup`、`poweroff`。

- `shell=True`禁止
- `/run`のような汎用実行コマンドを作らない
- Discord入力をシェル文字列へ埋め込まない
- サーバーPC側でも、SSHの強制コマンド（`restrict,command="..."`）で固定名以外を拒否する

二重にしているのは、片方の設定ミスだけでは任意実行にならないようにするため。

## 4. 停止時の保護

- 接続人数0人: Playerが停止可能
- 接続人数1人以上: Playerは停止不可
- Maintainerのみ確認後に停止可能
- 保存とバックアップが成功してからpoweroff
- バックアップ失敗時はpoweroffしない

人数の上限は固定しない。判定は常に実際の現在接続人数を使う。

Valheimは`SIGINT`を受けたときにワールドを書き出す。保存はsystemdユニットの`KillSignal=SIGINT`に依存しているので、この設定を消さない。

## 5. サーバーから返る値の扱い

プレイヤー名などゲーム側の文字列は**信頼しない**。Discordへ出す前に長さを切り、メンションやコードブロックとして解釈されない形にする。ゲームに入れる人は必ずしもDiscordの参加者と同じではない。

例外やコマンド出力をそのままDiscordへ流さない。ユーザーには短い日本語のメッセージを返し、詳細はログに残す。

## 6. GitHub

このリポジトリは**public**。push前に秘密情報が混ざっていないか必ず確認する。

main直接pushを採用するが、次は禁止する。

- force push
- 秘密情報のcommit
- テスト未実行でのpush
- 本番サーバー上だけを直接編集してGitと差を作ること

Gitに入れないもの: `.env`、Discord Bot Token、SSH秘密鍵、ゲームのパスワード、セーブデータ、バックアップ、ゲームの著作物（`/取引`用の画像）。

秘密情報を誤ってpushした場合は、履歴から消すだけでなくTokenや鍵を失効・再発行する。
