# Valheim サーバー構築手順（サーバー PC）

Palworld と同じサーバー PC に Valheim 専用サーバーを追加する手順です。**Raspberry Pi では動きません**（Valheim も x86-64 専用）。Pi は今までどおり Discord Bot の常駐ホストのままです。

現時点では **Bot には統合していません**。まず手動で確実に動かし、そのあと Bot に組み込みます。

## 運用方針: 片方ずつ

Palworld と Valheim は**同時に起動しません**。リソースを食い合わないよう、遊ぶ方だけを起動します。

```bash
# Valheim で遊ぶとき
sudo systemctl stop palworld-server.service
sudo systemctl start valheim-server.service

# Palworld で遊ぶとき
sudo systemctl stop valheim-server.service
sudo systemctl start palworld-server.service
```

> どちらも「誰も接続していないこと」を確認してから止めてください。

---

## 1. ユーザーとディレクトリ

Palworld と分離しておくと、権限事故が起きません。

```bash
sudo useradd -r -m -s /bin/bash valheim
sudo mkdir -p /opt/valheim-server
sudo chown valheim: /opt/valheim-server
```

## 2. SteamCMD で導入

SteamCMD は Palworld のときに導入済みです。Valheim 専用サーバーの App ID は **896660**。

```bash
sudo -u valheim /usr/games/steamcmd +force_install_dir /opt/valheim-server \
  +login anonymous +app_info_update 1 +app_info_print 896660 \
  +app_update 896660 validate +quit
```

`+app_info_update 1 +app_info_print 896660` を付けているのは、Palworld の更新でハマった「古いマニフェストをキャッシュしたまま `Access Denied` になる」問題を最初から避けるためです。

最後に `Success! App '896660' fully installed.` が出れば成功です。

Steam SDK も配置しておきます（Palworld と同じ対策）:

```bash
sudo -u valheim bash -c '
  mkdir -p ~/.steam/sdk64 ~/.steam/sdk32
  cp ~/.local/share/Steam/steamcmd/linux64/steamclient.so ~/.steam/sdk64/ 2>/dev/null || true
  cp ~/.local/share/Steam/steamcmd/linux32/steamclient.so ~/.steam/sdk32/ 2>/dev/null || true
'
```

## 3. 設定ファイル（パスワードを systemd ユニットに直書きしない）

サーバー名やパスワードをユニットファイルに書くと `systemctl show` や `ps` から見えてしまいます。環境ファイルに分離します。

```bash
sudo mkdir -p /etc/valheim
sudo nano /etc/valheim/valheim.env
```

```env
VALHEIM_NAME=kgyValheim
VALHEIM_WORLD=kgyWorld
VALHEIM_PASSWORD=ここに5文字以上
VALHEIM_PORT=2456
VALHEIM_PUBLIC=1
```

```bash
sudo chown root:valheim /etc/valheim/valheim.env
sudo chmod 640 /etc/valheim/valheim.env
```

制約と補足:

- **パスワードは5文字以上**。**ワールド名を含めることはできません**（含むと起動に失敗します）
- 値の後ろに `#` コメントを書かないでください（systemd が値の一部として読みます）
- `VALHEIM_PUBLIC=1` にするとコミュニティのサーバー一覧に名前で載ります。**自宅がグローバル IP 変動制なので、名前で探してもらえるこの設定は相性が良い**です（IP を毎回共有しなくて済む）。一覧に出したくなければ `0` にして、IP 直接接続にします

## 4. systemd ユニット（`KillSignal=SIGINT` が最重要）

```bash
sudo nano /etc/systemd/system/valheim-server.service
```

```ini
[Unit]
Description=Valheim Dedicated Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=valheim
Group=valheim
WorkingDirectory=/opt/valheim-server
EnvironmentFile=/etc/valheim/valheim.env
Environment=LD_LIBRARY_PATH=/opt/valheim-server/linux64
Environment=SteamAppId=892970
ExecStart=/opt/valheim-server/valheim_server.x86_64 -nographics -batchmode \
  -name ${VALHEIM_NAME} -port ${VALHEIM_PORT} -world ${VALHEIM_WORLD} \
  -password ${VALHEIM_PASSWORD} -public ${VALHEIM_PUBLIC}
Restart=on-failure
RestartSec=15

# Valheim はワールドを SIGINT で保存して終了する。既定の SIGTERM だと
# 保存されずに落ちるため、停止のたびに進行が巻き戻る。
KillSignal=SIGINT
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

**2つの落とし穴**:

- **`KillSignal=SIGINT`**: これが無いと `systemctl stop` のたびにワールドが巻き戻ります。Palworld で REST の `shutdown` を使っているのと同じ役割です
- **`SteamAppId=892970`**: サーバーの App ID（896660）ではなく**ゲーム本体の ID** を指定します。Valheim 付属の `start_server.sh` もこの値を使っています

反映:

```bash
sudo systemctl daemon-reload
sudo systemctl start valheim-server.service
systemctl status valheim-server.service
```

> `enable`（自動起動）は**付けません**。片方ずつ運用なので、起動は手動または Bot からにします。

## 5. ネットワーク

**ファイアウォール** — 以前確認したとき `2456:2458` は既に開いていました。念のため確認:

```bash
sudo ufw status | grep 245
```

出ていなければ:

```bash
sudo ufw allow 2456:2457/udp
```

**ルーターのポート開放** — Palworld 用（UDP 35520）とは別に、Valheim 用の転送を追加します:

| 項目 | 値 |
|---|---|
| プロトコル | **UDP** |
| 外部/内部ポート | **2456-2457** |
| 転送先 | **192.168.1.100**（サーバー PC） |

2456 がゲーム本体、2457 がクエリ（サーバー一覧や人数取得に使用）です。

## 6. 起動確認

```bash
journalctl -u valheim-server.service -f
```

`Game server connected` や `DungeonDB Start` などが出れば起動しています。初回はワールド生成で少し時間がかかります。

**接続人数の確認**（Valheim には REST API が無いので、Steam のクエリで取得します）:

```bash
python3 - <<'PY'
import socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
addr = ("127.0.0.1", 2457)
req = b"\xff\xff\xff\xffTSource Engine Query\x00"
s.sendto(req, addr); data, _ = s.recvfrom(4096)
if data[4:5] == b"A":                      # チャレンジ応答なら付け直して再送
    s.sendto(req + data[5:9], addr); data, _ = s.recvfrom(4096)
b = data[6:]                                # ヘッダとプロトコルを飛ばす
def take(buf):                              # ヌル終端文字列を1つ取り出す
    i = buf.index(b"\x00"); return buf[:i].decode("utf-8", "replace"), buf[i+1:]
name, b = take(b); mapname, b = take(b); folder, b = take(b); game, b = take(b)
b = b[2:]                                   # AppID
print(f"server={name!r} players={b[0]} max={b[1]}")
PY
```

`players=0 max=10` のように出れば成功です。**この仕組みを Bot の人数取得にも使います。**

## 7. クライアントから参加

- `VALHEIM_PUBLIC=1` の場合: ゲーム内のサーバー一覧で**サーバー名で検索**
- 直接指定の場合: `グローバルIP:2456`（現在の IP は Discord の `/server address` で確認できます）
- どちらもサーバーパスワードが必要です

## 8. バックアップ

Valheim のワールドデータはここにあります:

```
/home/valheim/.config/unity3d/IronGate/Valheim/worlds_local/
```

`<ワールド名>.db`（本体）と `<ワールド名>.fwl`（メタ情報）の**両方**が必要です。手動バックアップの例:

```bash
sudo tar -czf ~/valheim-backup-$(date +%Y%m%d-%H%M%S).tar.gz \
  -C /home/valheim/.config/unity3d/IronGate/Valheim worlds_local
```

> 現在の `palworld-backup` は Palworld 専用です。Valheim の自動バックアップは Bot 統合のときに合わせて用意します。

## 9. アップデート手順

Palworld と同じ形です。**必ず停止してから**行ってください。

```bash
sudo systemctl stop valheim-server.service
sudo -u valheim /usr/games/steamcmd +force_install_dir /opt/valheim-server \
  +login anonymous +app_info_update 1 +app_info_print 896660 \
  +app_update 896660 validate +quit
sudo systemctl start valheim-server.service
```

## 10. 動作確認チェックリスト

- [ ] `systemctl status valheim-server.service` が `active (running)`
- [ ] 上記の Python スクリプトで `players=` が取得できる
- [ ] LAN 内のクライアントから参加できる
- [ ] 外（スマホのモバイル通信や友達）から参加できる
- [ ] `sudo systemctl stop valheim-server.service` で停止 → **再起動してワールドの進行が保持されている**（SIGINT 設定の確認。ここが一番重要）
- [ ] Palworld を起動する前に Valheim を停止できる（片方ずつ運用）

## 補足: リソースの確認

Palworld と比べた重さは `/server load` で測れます。Valheim 稼働中に Discord で `/server load` を実行し、CPU 使用率とメモリを確認しておくと、将来「同時稼働できるか」を判断する材料になります。

## 補足: 正式リリース直後の注意

Valheim の正式リリース直後は、起動引数や必要要件が変わっている可能性があります。上記で起動しない場合は、`/opt/valheim-server/start_server.sh`（公式付属の起動スクリプト）を開いて、実際に使われている引数を確認してください。そこが最も確実な情報源です。
