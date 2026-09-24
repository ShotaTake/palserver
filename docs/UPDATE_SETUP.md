# Discord から Valheim を更新する

Maintainer が指定チャンネルで `/server update` を実行すると、PC が停止中なら WOL で起動し、接続人数を確認して更新を受け付けます。

サーバー PC 上の独立した systemd ジョブが次の順に実行します。

1. 接続人数を再確認（接続者あり・人数不明なら拒否。ゲームが停止済みなら人数取得不要）
2. SIGINT による保存・停止
3. ワールドのバックアップ
4. `valheim` ユーザーで SteamCMD による公開版の更新・検証
5. ゲームを起動し、A2S の応答を確認

`/server status` に進行と直近の結果が表示されます。結果は通常の監視通知先（`DISCORD_AUDIT_CHANNEL_ID`、未指定ならコマンド用チャンネル）にも送信します。通知間隔は既存の `STATUS_POLL_INTERVAL_SECONDS` に従います。更新は Discord の応答期限や SSH の切断に依存せず継続します。

## 初回だけ必要な導入

このリポジトリの標準構成（`palbotctl`、`valheim`、`/opt/valheim-server`、`/usr/games/steamcmd`）向けです。独自のユーザー名・配置先を使っている場合は、サービス・固定ヘルパー・sudoers を所有者が調整してください。

変更済みコードを両マシンのリポジトリに反映してから、プレイヤーがいない時間に行います。

1. Raspberry Pi で Bot を停止する（導入中の起動・停止要求と自動停止を防ぐ）。

   ```bash
   sudo systemctl stop gameserver-bot.service
   ```

2. サーバー PC のリポジトリで、まず実行内容を確認する。

   ```bash
   sudo bash scripts/setup/install-update.sh --dry-run
   ```

3. 問題がなければ適用する。

   ```bash
   sudo bash scripts/setup/install-update.sh
   ```

   更新用サービス・制御スクリプト・状態保存先を導入します。sudoers は文法検証後に内容を表示し、所有者が `yes` と入力した場合だけ追加します。ゲームの更新はこの導入では実行しません。既存の sudoers や authorized_keys を書き換えません。通常の Palworld → Valheim 移行スクリプトからも、この導入処理を呼びます。

4. Raspberry Pi のリポジトリで Bot を入れ直して起動する。

   ```bash
   .venv/bin/pip install -e .
   sudo systemctl start gameserver-bot.service
   ```

5. Discord の Maintainer ロールで `/server update` を実行し、`/server status` と完了通知を確認する。最後にゲームクライアントから接続する。

以降の通常のゲーム更新は `/server update` だけで実行できます。OS 更新・MOD 更新・Bot 自身の更新は対象外です。

## 制限と復旧

- 更新中は、他の起動・再起動・停止・バックアップ・電源オフ・重複更新をサーバー側でも拒否します。Bot 再起動後も有効です。所有者が別の管理用 SSH で直接操作する場合も、更新中は操作を重ねないでください。
- 更新前に人数を再確認しますが、確認と停止の間にゲームへ接続することまで排除できません。利用者がいない時間に実行してください。
- 保存・停止・バックアップ・ダウンロードのどこかで失敗したら、後続の処理は実行しません。更新失敗後に自動で旧版を起動したり、ワールドを巻き戻したりはしません。
- バックアップはワールド用です。ゲーム本体の旧バージョンを保存する機能ではありません。SteamCMD の `validate` は配布ファイルへの独自変更を上書きする場合があります。
- 更新後の起動確認は最大 60 回、各回の間隔は 5 秒です（クエリの処理時間は別途かかります）。応答がなければ確認失敗を通知します。この場合、ゲームが起動処理中または再起動中の可能性があるため `/server status` とログを確認してください。
- ジョブ全体は最大 1 時間です。時間超過やサーバー再起動で中断したら、その状態を表示します。処理の自動再開はしません。
- 更新要求直後に通信が切れた場合は、受け付け済みの可能性があります。再実行する前に `/server status` を確認してください。
- 過去の完了結果は Bot 起動直後には再通知しません。Bot 停止中に完了した更新は `/server status` から確認できます。

詳細ログはサーバー PC の所有者が確認します。

```bash
sudo journalctl -u valheim-update.service -n 100 --no-pager
sudo journalctl -u valheim-server.service -n 100 --no-pager
```

Discord には固定の進行・結果メッセージだけを出します。任意のターミナル操作や、生ログの転送は提供しません。
