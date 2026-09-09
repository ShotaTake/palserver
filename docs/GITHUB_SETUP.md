# GitHub 運用（main直接運用）

## 1. 方針

このプロジェクトは短期・少人数開発のため、feature branchやPull Requestを必須にせず、`main`へ直接pushする。

ただし、次の最低限のルールは守る。

1. 作業前に必ず`git pull --ff-only`する
2. 同じファイルを複数人で同時編集しない
3. 1回の変更を小さくする
4. push前に`ruff`、`mypy`、`pytest`を実行する（シェルスクリプトを触ったら`bash -n`も）
5. `git diff`を人間が確認してからcommitする
6. `git push --force`は使用しない
7. 動作確認済みの時点でGit tagを付ける

## 2. リポジトリ

- <https://github.com/ShotaTake/palserver>
- Visibility: **public**（クローンに認証は不要。その代わり秘密情報の混入に注意する）

コードを編集できる人数と、Discordからサーバーを操作できる人数は一致させる必要はない。前者はGitHubのCollaborator、後者はDiscordのロールで決まる。

## 3. cloneとPython環境

```powershell
git clone https://github.com/ShotaTake/palserver.git
cd palserver
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

確認:

```powershell
ruff check .
mypy src
pytest
```

## 4. 通常の開発手順

```powershell
git switch main
git pull --ff-only
claude
```

実装した後:

```powershell
git status
git diff
ruff check .
mypy src
pytest
git add .
git commit -m "feat: add server status command"
git push origin main
```

他のメンバーが先にpushしていた場合は、再度次を実行する。

```powershell
git pull --rebase
```

競合が発生した場合、内容を理解せずに解消したり、force pushしたりしない。

## 5. 安定版を残す

動作確認済みの区切りでtagを付ける。

```powershell
git tag -a v0.1.0 -m "status and start commands working"
git push origin v0.1.0
```

問題が起きた場合に、どの版まで正常だったか判断しやすくなる。Palworldを運用していた版は `v1.0-palworld` に残してある。

## 6. GitHub Actions

`main`へpushされると、GitHub Actionsで次を確認する。

- Ruff
- Mypy
- Pytest

main直接運用では、Actionsは壊れたpushを防ぐものではなく、push後に検出するものになる。したがってローカル確認を省略しない。

## 7. Gitへ入れないもの

- `.env`
- Discord Bot Token
- SSH秘密鍵
- ゲームのサーバーパスワード
- 実際のセーブデータ
- バックアップ
- ログ
- ゲームの著作物（`/取引`用の画像）

秘密情報を誤ってpushした場合は、履歴から消すだけでなくTokenや鍵を失効・再発行する。**publicリポジトリなので、pushした時点で第三者に取得されたものとして扱う。**
