# 運用方針

## コード変更

```bash
git switch main
git pull --ff-only
# Claude Codeまたは手作業で変更
git diff
ruff check .
mypy src
pytest
bash -n scripts/server/*        # シェルスクリプトを触ったとき
git add .
git commit -m "feat: describe the change"
git push origin main
```

複数人が同時に同じ機能を触らない。作業開始前にDiscord等で担当を宣言する。

## 本番反映

追加した更新・診断・バックアップ一覧・復元・ヘルプを既存環境へ反映する場合は、[本番反映手順書](DEPLOY_UPDATE.md) に沿って作業する。Bot だけを更新する手順も同じ手順書に記載している。

### Bot（Raspberry Pi）

```bash
cd /opt/gameserver-ops
git pull --ff-only
.venv/bin/pip install -e .
sudo systemctl restart gameserver-bot.service
systemctl status gameserver-bot.service
journalctl -u gameserver-bot.service -n 30
```

### サーバー側の制御スクリプト（サーバーPC）

`scripts/server/` を変更したときは、サーバーPCでも入れ直す。

```bash
cd ~/palserver
git pull --ff-only
sudo install -m 0755 scripts/server/valheim-control          /usr/local/sbin/valheim-control
sudo install -m 0755 scripts/server/valheim-control-ssh      /usr/local/sbin/valheim-control-ssh
sudo install -m 0755 scripts/server/valheim-query            /usr/local/sbin/valheim-query
sudo install -m 0755 scripts/server/gameserver-backup        /usr/local/sbin/gameserver-backup
sudo install -m 0755 scripts/server/gameserver-safe-poweroff /usr/local/sbin/gameserver-safe-poweroff
sudo -u palbotctl /usr/local/sbin/valheim-control status
```

sudoers・authorized_keys・ファイアウォールは自動で書き換えない。変更が要るときは `config/` の例を見ながら人間が編集する。

本番反映はMaintainerに限定する。

## メンバーの追加・削除

コードを変更しない。

- 追加: DiscordでPlayerロールを付与
- 管理者追加: Maintainerロールを付与
- 削除: 該当ロールを外す

サーバーの最大人数を変えるときは、ゲームサーバー側の設定を変更して安全に再起動する。Botに人数の固定値を持たせない。

## ゲーム本体の更新

診断・バックアップ一覧・ワールド復元は [MAINTENANCE_SETUP.md](MAINTENANCE_SETUP.md) を参照してください。復元には対象選択と確認があり、成功後はゲームを起動します。

通常は Maintainer が Discord で `/server update` を実行する。初回だけ [UPDATE_SETUP.md](UPDATE_SETUP.md) の導入が必要。進行と直近の結果は `/server status` で確認する。

手動の場合は停止してから更新する。手順は [VALHEIM_SETUP.md](VALHEIM_SETUP.md) の「アップデート手順」。Bot の更新と同時には実行しない。

## 安定版

動作確認できた区切りでtagを付ける。

```bash
git tag -a v0.1.0 -m "MVP working"
git push origin v0.1.0
```

Palworldを運用していた版は `v1.0-palworld` に残してある。
