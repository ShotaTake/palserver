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
git add .
git commit -m "feat: describe the change"
git push origin main
```

複数人が同時に同じ機能を触らない。作業開始前にDiscord等で担当を宣言する。

## 本番反映

Raspberry Piで次を実行する。

```bash
cd /opt/palworld-server-ops
git pull --ff-only
source .venv/bin/activate
pip install -e .
sudo systemctl restart palworld-bot.service
sudo systemctl status palworld-bot.service
```

本番反映はAまたはMaintainerに限定する。

## メンバーの追加・削除

コードを変更しない。

- 追加: Discordで`Palworld Player`ロールを付与
- 管理者追加: `Palworld Maintainer`ロールを付与
- 削除: 該当ロールを外す

Palworldサーバー自体の最大人数を変更する場合は、Palworldの設定を変更してサーバーを安全に再起動する。Botには4人固定の設定を持たせない。

## 安定版

動作確認できた区切りでtagを付ける。

```bash
git tag -a v0.1.0 -m "MVP working"
git push origin v0.1.0
```
