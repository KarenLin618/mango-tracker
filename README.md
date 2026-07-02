# 🥭 芒果催熟排程管理

追蹤每一顆芒果從「硬 → 熟 → 冷藏 → 吃」的流程，自動算出冷藏剩餘天數、
在快到期時標紅，並排出「目標日該吃哪幾顆」。支援多個排程計畫，分批管理。

- 後端：Flask（`app.py`）
- 前端：Vue 3（CDN，免打包，`index.html`）
  - `demo.html`：靜態展示版（用示範資料呈現實際畫面，可試玩、不接後端）
  - `guide.html`：操作說明頁
- 資料庫：**Railway 上用 PostgreSQL**；本機開發自動退回 SQLite
- 熟成/賞味計算全在瀏覽器端，用本地時區的日曆日，不受伺服器時區影響

## 功能

- 多個排程計畫：新增 / 切換 / 刪除，每批（或每次採買）獨立管理
- 設定：計畫名稱、收到日、目標日、數量、品種、冷藏可放天數、室溫熟後可放天數
- 看板：每顆芒果的狀態、熟成日、進冰箱日、最佳賞味日、倒數天數（快到期紅框）
- 照片：每顆可拍照/上傳，瀏覽器端先壓縮（長邊 900px、JPEG 0.7）再存資料庫，點縮圖看大圖
- 建議：即將到期清單、完整食用順序、目標日可吃顆數統計
- 所有操作即時存進資料庫，手機／電腦看到的進度一致

## 資料庫：本機 SQLite、線上 PostgreSQL

程式用環境變數 `DATABASE_URL` 判斷：

- **有** `DATABASE_URL`（且以 `postgres` 開頭）→ 用 PostgreSQL（Railway 會自動注入）。
- **沒有** → 退回本機 SQLite（檔案預設 `mango.db`，可用 `DATABASE_PATH` 指定路徑）。

同一份 SQL 兩邊共用，照片在 Postgres 存 `BYTEA`、SQLite 存 `BLOB`，程式已處理差異。

## 本機測試

```bash
pip install -r requirements.txt
python app.py          # 沒設 DATABASE_URL → 自動用 SQLite
# 主畫面 http://localhost:5000  ·  展示 /demo  ·  操作說明 /guide
```

## 用 GitHub 管理

```bash
git init
git add .
git commit -m "postgres + multi-plan"
git branch -M main
git remote add origin https://github.com/<你的帳號>/mango-tracker.git
git push -u origin main
```

## 部署到 Railway（含 PostgreSQL）

1. Railway → New Project → **Deploy from GitHub repo** → 選這個 repo。
2. 在同一個 Project 按 **New → Database → Add PostgreSQL**。
3. Railway 會自動把 `DATABASE_URL` 注入到你的服務，程式偵測到就會用 Postgres。
   （不需要另外掛 Volume，資料存在 Postgres 裡本來就會持久化。）
4. 部署完成後在 Settings → Networking 產生 public domain 即可打開。

> 若服務先於資料庫啟動、第一次連線失敗，重新部署一次（Deploy）即可。

## API 一覽

- `GET  /api/plans`                    列出所有計畫（含每計畫的總數/已吃數）
- `POST /api/plans`                    新增計畫（body 含 name/日期/count/品種…）
- `GET  /api/plans/<id>/state`         取某計畫的設定與所有芒果
- `PUT  /api/plans/<id>`               修改計畫設定（含依 count 增減芒果）
- `DELETE /api/plans/<id>`             刪除計畫（連同芒果與照片）
- `POST /api/plans/<id>/reset`         把該計畫所有芒果重設為「硬」
- `PUT  /api/mango/<id>`               更新單顆芒果狀態/日期/備註（用全域 id）
- `GET/PUT/DELETE /api/mango/<id>/photo`  照片取得/上傳/刪除

## 三個頁面

- `/`（index.html）：正式版，資料存資料庫。
- `/demo`（demo.html）：**靜態展示版**，用內建示範資料呈現和正式版一模一樣的介面，可以隨意點按試玩，但不會儲存、也不連後端。適合給別人看「長怎樣」。
- `/guide`（guide.html）：**操作說明**，圖解怎麼用，含一張可互動的狀態示範卡。

> `demo.html` 是由 `index.html` 自動產生的（見 `_gen_demo.py`）：把正式版的資料存取換成記憶體示範資料。若你改了正式版的畫面，執行 `python _gen_demo.py` 就能重新產生同步的展示版。

## 熟成邏輯備忘

- 硬：不算賞味期，提醒別冰（愛文寒害會熟不透）。
- 熟：最佳賞味 = 熟成日 + 室溫可放天數（愛文預設 2 天）。
- 已冷藏：最佳賞味 = 進冰箱日 + 冷藏可放天數（愛文預設 6 天）。
- 已冷凍：進冰箱日 + 60 天，適合太早熟、撐不到目標日的那幾顆。
- 剩餘 ≤ 2 天會標紅並列入「盡快吃」。
