# Valheim サーバー構築手順（サーバー PC）

サーバー PC に Valheim 専用サーバーを構築する手順です。**Raspberry Pi では動きません**（Valheim は x86-64 専用）。Pi は Discord Bot の常駐ホストです。

まず手動で確実に動かしてから、Bot 側（[SETUP_PRODUCTION.md](SETUP_PRODUCTION.md)）を繋ぎます。

## 旧 Palworld サーバーがある場合

同じ PC で Palworld を動かしていたなら、先に止めて自動起動を切っておきます。リソースの食い合いと、ポートの取り合いを防ぐためです。

```bash
sudo systemctl disable --now palworld-server.service
```

> セーブデータは消さずに残しておけば、あとで戻すこともできます。

---

## 1. ユーザーとディレクトリ

ゲーム専用のユーザーを作り、他と分離しておくと権限事故が起きません。

```bash
sudo useradd -r -m -s /bin/bash valheim
sudo mkdir -p /opt/valheim-server
sudo chown valheim: /opt/valheim-server
```

## 2. SteamCMD で導入

SteamCMD が未導入なら `sudo apt install steamcmd` で入れます。Valheim 専用サーバーの App ID は **896660**。

```bash
sudo -u valheim /usr/games/steamcmd +force_install_dir /opt/valheim-server \
  +login anonymous +app_info_update 1 +app_info_print 896660 \
  +app_update 896660 validate +quit
```

`+app_info_update 1 +app_info_print 896660` を付けているのは、「古いマニフェストをキャッシュしたまま `Access Denied` になる」問題を避けるためです（過去に更新で実際にハマった箇所）。

最後に `Success! App '896660' fully installed.` が出れば成功です。

Steam SDK も配置しておきます:

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
VALHEIM_PORT=35520
VALHEIM_PUBLIC=1
VALHEIM_MODIFIERS=-modifier resources most -modifier deathpenalty casual -modifier portals casual
```

この内容は [config/valheim.env.example](../config/valheim.env.example) にそのまま入っています（パスワードだけ空）。`scripts/setup/migrate-server.sh` はそこから読むので、手で作る必要があるのはスクリプトを使わない場合だけです。

```bash
sudo chown root:valheim /etc/valheim/valheim.env
sudo chmod 640 /etc/valheim/valheim.env
```

制約と補足:

- **パスワードは5文字以上**。**ワールド名を含めることはできません**（含むと起動に失敗します）
- 値の後ろに `#` コメントを書かないでください（systemd が値の一部として読みます）
- **`VALHEIM_PUBLIC=1` は必須です。** 一覧公開の可否だけでなく、**Steam のクエリ応答そのもののスイッチ**を兼ねています。`0` にすると A2S が無応答になり、Bot の人数取得・プレイヤー名・presence 表示・無人時の自動シャットダウンがまとめて動かなくなります（実機の 1.0 サーバーで確認）
- ただし `1` にしても、クエリポートをルーターで転送しなければ一覧には実質載りません。この配備はその状態です。参加は IP 直接入力で、現在の接続先は `/server address` が案内します
- `VALHEIM_PORT=35520` は Palworld で使っていた番号の流用です。ルーターの転送ルールをそのまま使えます
- `VALHEIM_MODIFIERS` はワールド修飾子（後述）。空でも構いません

### ワールド修飾子（難易度）

Valheim には Palworld の `ExpRate 3` のような数値の倍率設定がありません。代わりに**段階指定のワールド修飾子**を起動引数として渡します。この配備で決めた値:

| キー | 値 | 効果 |
|---|---|---|
| `resources` | `most` | 採集・ドロップが約3倍 |
| `deathpenalty` | `casual` | スキルが下がらず、装備もその場に残る |
| `portals` | `casual` | 鉱石もポータルで運べる |
| `combat` | 指定なし | 敵の強さは素のまま |
| `raids` | 指定なし | 拠点襲撃の頻度も素のまま |

`resources` の段階はおおよそ `muchless`(0.5) / `less`(0.75) / `normal`(1) / `more`(1.5) / `muchmore`(2) / `most`(3) です。

死亡ペナルティを緩めたのは、少人数のサーバーで一番熱が冷めやすいのが死体回収の遠征だからです。ポータル制限も外してあるので、採集3倍と合わせて往復の時間がかなり減ります。戦闘と襲撃を素のままにしたのは、そこが Valheim の見せ場で、緩めると建築や探索の動機まで薄くなるためです。

修飾子は**後からいつでも変えられます**。`valheim.env` を編集して `systemctl restart valheim-server.service` するだけです。固定されるのはシード（`VALHEIM_WORLD` で決まる地形）だけ。

> **引数名は正式リリースの `-help` で未確認です。** サーバーが起動しない場合は、まずこの行を空にして切り分けてください。実際に使える引数は次で確認できます。
>
> ```bash
> /opt/valheim-server/valheim_server.x86_64 -help
> cat /opt/valheim-server/start_server.sh
> ```

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
  -password ${VALHEIM_PASSWORD} -public ${VALHEIM_PUBLIC} \
  $VALHEIM_MODIFIERS
Restart=on-failure
RestartSec=15

# Valheim はワールドを SIGINT で保存して終了する。既定の SIGTERM だと
# 保存されずに落ちるため、停止のたびに進行が巻き戻る。
KillSignal=SIGINT
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

**3つの落とし穴**:

- **`$VALHEIM_MODIFIERS` に波括弧を付けない**: systemd は `$VAR` を空白で分割して複数の引数にしますが、`${VAR}` は1つの引数として渡します。修飾子は複数の引数なので波括弧なし、サーバー名は空白を含みうるので `${VALHEIM_NAME}` のまま、という使い分けです
- **`KillSignal=SIGINT`**: これが無いと `systemctl stop` のたびにワールドが巻き戻ります。Valheim には保存用の API が無いため、Bot の `/server stop` もこの仕組みに乗って保存します
- **`SteamAppId=892970`**: サーバーの App ID（896660）ではなく**ゲーム本体の ID** を指定します。Valheim 付属の `start_server.sh` もこの値を使っています

反映:

```bash
sudo systemctl daemon-reload
sudo systemctl start valheim-server.service
systemctl status valheim-server.service
```

> `enable`（自動起動）は**付けません**。起動は Bot の `/server start` が担当します。自動起動にすると、WOL で PC が起きた時点でゲームまで立ち上がり、Bot 側の「PC はオン・ゲームは停止中」という状態が作れなくなります。

## 5. ネットワーク

ゲームポートは **35520**、クエリポートはその +1 の **35521** です。

**ファイアウォール**:

```bash
sudo ufw status | grep 3552
sudo ufw allow 35520:35521/udp
```

**ルーターのポート開放** — 転送が必要なのは **UDP 35520 だけ**です:

| 項目 | 値 |
|---|---|
| プロトコル | **UDP** |
| 外部/内部ポート | **35520**（両方とも同じ番号にすること） |
| 転送先 | **192.168.1.100**（サーバー PC） |

Palworld で同じ番号を転送していたなら、**ルーターは触らなくて済みます**。ただし外部ポートだけ 35520 で内部が 8211 のようなポート変換になっている場合は、内部側も 35520 に直してください。

クエリポート 35521 を転送しなくてよいのは、Bot の人数取得が `127.0.0.1` 宛だからです（[scripts/server/valheim-query](../scripts/server/valheim-query)）。外から届く必要があるのは、ゲーム内のサーバー一覧に実際に載せたいときだけです。

`VALHEIM_PUBLIC=1` と一覧公開は別物である点に注意してください。`1` は**クエリ応答を有効にするために必須**（`0` だと人数が取れない）で、実際に一覧へ載るかどうかは 35521 を転送するかどうかで決まります。

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
addr = ("127.0.0.1", 35521)
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

- `グローバルIP:35520` を直接指定して参加します。現在の接続先は Discord の `/server address` で確認できます（IP が変わったときは自動で通知されます）
- LAN 内からは `192.168.1.100:35520`
- `VALHEIM_PUBLIC=1` にした場合のみ、ゲーム内のサーバー一覧からサーバー名で探せます
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

Bot から `/server stop` した場合は、`scripts/server/gameserver-backup` が停止後に同じ内容を自動で固めます（設置は [SETUP_PRODUCTION.md](SETUP_PRODUCTION.md) の A-5）。手動バックアップが要るのは Bot を使わずに止めたときだけです。

## 9. アップデート手順

Discord から行う場合は、一度だけ [更新機能の導入](UPDATE_SETUP.md) を行い、以降は Maintainer が `/server update` を実行します。保存・バックアップ・更新・起動確認まで自動で行います。以下は所有者がターミナルで行う場合の手順です。Bot の更新処理と同時には実行しないでください。

**必ず停止してから**行ってください。

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
- [ ] `sudo -u <制御ユーザー> /usr/local/sbin/valheim-control status` が `valheim=running` を返す（Bot 連携の前提）

## 補足: リソースの確認

Valheim 稼働中に Discord で `/server load` を実行すると、CPU 使用率・メモリ・温度が確認できます。人数が増えたときの余力を見るのに使ってください。

## 補足: 正式リリース直後の注意

Valheim の正式リリース直後は、起動引数や必要要件が変わっている可能性があります。上記で起動しない場合は、`/opt/valheim-server/start_server.sh`（公式付属の起動スクリプト）を開いて、実際に使われている引数を確認してください。そこが最も確実な情報源です。
