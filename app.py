"""
芒果催熟排程管理 — Flask 後端
- 資料庫：有環境變數 DATABASE_URL（Railway 的 PostgreSQL）就用 Postgres；
          沒有就退回本機 SQLite（方便本地開發）。
- 支援多個排程計畫（plan），每個計畫底下有多顆芒果（mango）。
- 熟成/賞味計算都在前端做，後端只負責存取（避免時區問題）。
"""
import os
import base64
import sqlite3
from flask import Flask, request, jsonify, send_from_directory, Response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
IS_PG = DATABASE_URL.startswith("postgres")
SQLITE_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "mango.db"))

if IS_PG:
    import psycopg2
    import psycopg2.extras

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 照片已在前端壓縮，上限給寬一點


@app.after_request
def _no_cache_html(resp):
    # HTML 頁面不快取，確保部署後使用者一定載到最新的程式（避免舊 JS 造成照片更新失效）
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ---------- 資料庫抽象層（同時支援 Postgres 與 SQLite）----------
def get_conn():
    if IS_PG:
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _adapt(sql):
    # SQL 一律用 %s 佔位符；SQLite 需要換成 ?
    return sql if IS_PG else sql.replace("%s", "?")


def _cursor(conn):
    if IS_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def q_all(conn, sql, params=()):
    cur = _cursor(conn)
    cur.execute(_adapt(sql), params)
    rows = cur.fetchall()
    cur.close()
    return [dict(r) for r in rows]


def q_one(conn, sql, params=()):
    rows = q_all(conn, sql, params)
    return rows[0] if rows else None


def execute(conn, sql, params=()):
    cur = _cursor(conn)
    cur.execute(_adapt(sql), params)
    cur.close()


def db_binary(raw):
    return psycopg2.Binary(raw) if IS_PG else sqlite3.Binary(raw)


def init_db():
    conn = get_conn()
    if IS_PG:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS plan (
                id                  SERIAL PRIMARY KEY,
                name                TEXT NOT NULL,
                received_date       TEXT,
                target_date         TEXT,
                count               INTEGER DEFAULT 0,
                fridge_life_days    INTEGER DEFAULT 6,
                room_ripe_life_days INTEGER DEFAULT 2,
                frozen_life_days    INTEGER DEFAULT 60,
                variety             TEXT DEFAULT '愛文'
            )""")
        execute(conn, """
            CREATE TABLE IF NOT EXISTS mango (
                id          SERIAL PRIMARY KEY,
                plan_id     INTEGER NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
                seq         INTEGER NOT NULL,
                status      TEXT DEFAULT 'hard',
                ripe_date   TEXT,
                fridge_date TEXT,
                note        TEXT DEFAULT '',
                photo       BYTEA,
                photo_mime  TEXT
            )""")
        execute(conn, """
            CREATE TABLE IF NOT EXISTS photo (
                id       SERIAL PRIMARY KEY,
                mango_id INTEGER NOT NULL REFERENCES mango(id) ON DELETE CASCADE,
                seq      INTEGER NOT NULL,
                data     BYTEA NOT NULL,
                mime     TEXT
            )""")
    else:
        execute(conn, """
            CREATE TABLE IF NOT EXISTS plan (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT NOT NULL,
                received_date       TEXT,
                target_date         TEXT,
                count               INTEGER DEFAULT 0,
                fridge_life_days    INTEGER DEFAULT 6,
                room_ripe_life_days INTEGER DEFAULT 2,
                frozen_life_days    INTEGER DEFAULT 60,
                variety             TEXT DEFAULT '愛文'
            )""")
        execute(conn, """
            CREATE TABLE IF NOT EXISTS mango (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id     INTEGER NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
                seq         INTEGER NOT NULL,
                status      TEXT DEFAULT 'hard',
                ripe_date   TEXT,
                fridge_date TEXT,
                note        TEXT DEFAULT '',
                photo       BLOB,
                photo_mime  TEXT
            )""")
        execute(conn, """
            CREATE TABLE IF NOT EXISTS photo (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                mango_id INTEGER NOT NULL REFERENCES mango(id) ON DELETE CASCADE,
                seq      INTEGER NOT NULL,
                data     BLOB NOT NULL,
                mime     TEXT
            )""")
    conn.commit()
    # 一次性搬移：把舊版的單張照片（mango.photo）移進新的 photo 表，然後清空來源避免重複搬移
    legacy = q_all(conn, "SELECT id, photo, photo_mime FROM mango WHERE photo IS NOT NULL")
    for m in legacy:
        execute(conn, "INSERT INTO photo (mango_id, seq, data, mime) VALUES (%s, 1, %s, %s)",
                (m["id"], db_binary(bytes(m["photo"])), m["photo_mime"] or "image/jpeg"))
    if legacy:
        execute(conn, "UPDATE mango SET photo=NULL, photo_mime=NULL WHERE photo IS NOT NULL")
        conn.commit()
    conn.close()


def insert_plan(conn, d):
    cols = ("name", "received_date", "target_date", "count",
            "fridge_life_days", "room_ripe_life_days", "frozen_life_days", "variety")
    vals = (
        d.get("name") or "未命名計畫",
        d.get("received_date"),
        d.get("target_date"),
        int(d.get("count", 0) or 0),
        int(d.get("fridge_life_days", 6) or 6),
        int(d.get("room_ripe_life_days", 2) or 2),
        int(d.get("frozen_life_days", 60) or 60),
        d.get("variety", "愛文"),
    )
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO plan ({', '.join(cols)}) VALUES ({placeholders})"
    if IS_PG:
        row = q_one(conn, sql + " RETURNING id", vals)
        return row["id"]
    cur = conn.cursor()
    cur.execute(_adapt(sql), vals)
    return cur.lastrowid


def sync_mango_count(conn, plan_id, count):
    """依 count 增減芒果：不足補 hard（seq 接續），過多刪除 seq 較大的。"""
    rows = q_all(conn, "SELECT seq FROM mango WHERE plan_id = %s ORDER BY seq", (plan_id,))
    current = len(rows)
    if count > current:
        for s in range(current + 1, count + 1):
            execute(conn,
                    "INSERT INTO mango (plan_id, seq, status) VALUES (%s, %s, 'hard')",
                    (plan_id, s))
    elif count < current:
        execute(conn, "DELETE FROM photo WHERE mango_id IN "
                      "(SELECT id FROM mango WHERE plan_id = %s AND seq > %s)", (plan_id, count))
        execute(conn, "DELETE FROM mango WHERE plan_id = %s AND seq > %s", (plan_id, count))


def read_plan_state(conn, plan_id):
    plan = q_one(conn, "SELECT * FROM plan WHERE id = %s", (plan_id,))
    if plan is None:
        return None
    mangoes = q_all(conn,
        "SELECT id, plan_id, seq, status, ripe_date, fridge_date, note "
        "FROM mango WHERE plan_id = %s ORDER BY seq", (plan_id,))
    # 一次撈出這個計畫所有芒果的照片 id，依 seq 排好再分組掛到各芒果上
    photos = q_all(conn,
        "SELECT ph.id, ph.mango_id FROM photo ph "
        "JOIN mango m ON ph.mango_id = m.id "
        "WHERE m.plan_id = %s ORDER BY ph.mango_id, ph.seq", (plan_id,))
    by_mango = {}
    for ph in photos:
        by_mango.setdefault(ph["mango_id"], []).append(ph["id"])
    for m in mangoes:
        m["photos"] = by_mango.get(m["id"], [])
    return {"plan": plan, "mangoes": mangoes}


# ---------- 計畫 API ----------
@app.route("/api/plans", methods=["GET"])
def api_plans():
    conn = get_conn()
    plans = q_all(conn,
        "SELECT p.*, "
        "(SELECT COUNT(*) FROM mango m WHERE m.plan_id = p.id) AS mango_total, "
        "(SELECT COUNT(*) FROM mango m WHERE m.plan_id = p.id AND m.status = 'eaten') AS eaten "
        "FROM plan p ORDER BY p.id")
    conn.close()
    return jsonify({"plans": plans})


@app.route("/api/plans", methods=["POST"])
def api_plan_create():
    d = request.get_json(force=True) or {}
    conn = get_conn()
    plan_id = insert_plan(conn, d)
    sync_mango_count(conn, plan_id, int(d.get("count", 0) or 0))
    conn.commit()
    state = read_plan_state(conn, plan_id)
    conn.close()
    return jsonify(state), 201


@app.route("/api/plans/<int:plan_id>/state", methods=["GET"])
def api_plan_state(plan_id):
    conn = get_conn()
    state = read_plan_state(conn, plan_id)
    conn.close()
    if state is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(state)


@app.route("/api/plans/<int:plan_id>", methods=["PUT"])
def api_plan_update(plan_id):
    d = request.get_json(force=True) or {}
    conn = get_conn()
    exists = q_one(conn, "SELECT id FROM plan WHERE id = %s", (plan_id,))
    if exists is None:
        conn.close()
        return jsonify({"error": "not found"}), 404
    execute(conn, """
        UPDATE plan SET name=%s, received_date=%s, target_date=%s, count=%s,
            fridge_life_days=%s, room_ripe_life_days=%s, frozen_life_days=%s, variety=%s
        WHERE id=%s
        """, (
        d.get("name") or "未命名計畫",
        d.get("received_date"),
        d.get("target_date"),
        int(d.get("count", 0) or 0),
        int(d.get("fridge_life_days", 6) or 6),
        int(d.get("room_ripe_life_days", 2) or 2),
        int(d.get("frozen_life_days", 60) or 60),
        d.get("variety", "愛文"),
        plan_id,
    ))
    sync_mango_count(conn, plan_id, int(d.get("count", 0) or 0))
    conn.commit()
    state = read_plan_state(conn, plan_id)
    conn.close()
    return jsonify(state)


@app.route("/api/plans/<int:plan_id>", methods=["DELETE"])
def api_plan_delete(plan_id):
    conn = get_conn()
    execute(conn, "DELETE FROM photo WHERE mango_id IN (SELECT id FROM mango WHERE plan_id = %s)", (plan_id,))
    execute(conn, "DELETE FROM mango WHERE plan_id = %s", (plan_id,))  # 保險：不依賴 cascade
    execute(conn, "DELETE FROM plan WHERE id = %s", (plan_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": plan_id})


@app.route("/api/plans/<int:plan_id>/reset", methods=["POST"])
def api_plan_reset(plan_id):
    conn = get_conn()
    execute(conn, "DELETE FROM photo WHERE mango_id IN (SELECT id FROM mango WHERE plan_id = %s)", (plan_id,))
    execute(conn,
        "UPDATE mango SET status='hard', ripe_date=NULL, fridge_date=NULL, note='' "
        "WHERE plan_id=%s", (plan_id,))
    conn.commit()
    state = read_plan_state(conn, plan_id)
    conn.close()
    if state is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(state)


# ---------- 芒果 API ----------
@app.route("/api/mango/<int:mango_id>", methods=["PUT"])
def api_mango(mango_id):
    d = request.get_json(force=True) or {}
    conn = get_conn()
    exists = q_one(conn, "SELECT id FROM mango WHERE id = %s", (mango_id,))
    if exists is None:
        conn.close()
        return jsonify({"error": "not found"}), 404
    execute(conn,
        "UPDATE mango SET status=%s, ripe_date=%s, fridge_date=%s, note=%s WHERE id=%s",
        (d.get("status", "hard"), d.get("ripe_date") or None,
         d.get("fridge_date") or None, d.get("note", "") or "", mango_id))
    conn.commit()
    row = q_one(conn,
        "SELECT id, plan_id, seq, status, ripe_date, fridge_date, note "
        "FROM mango WHERE id = %s", (mango_id,))
    photos = q_all(conn, "SELECT id FROM photo WHERE mango_id = %s ORDER BY seq", (mango_id,))
    row["photos"] = [p["id"] for p in photos]
    conn.close()
    return jsonify(row)


# ---------- 照片 API（一顆芒果多張）----------
@app.route("/api/mango/<int:mango_id>/photos", methods=["POST"])
def api_photo_add(mango_id):
    d = request.get_json(force=True) or {}
    data = d.get("data", "")
    mime = d.get("mime", "image/jpeg")
    if "," in data and data.strip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
    except Exception:
        return jsonify({"error": "invalid image data"}), 400
    conn = get_conn()
    exists = q_one(conn, "SELECT id FROM mango WHERE id = %s", (mango_id,))
    if exists is None:
        conn.close()
        return jsonify({"error": "not found"}), 404
    nxt = q_one(conn, "SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM photo WHERE mango_id = %s", (mango_id,))
    seq = nxt["s"]
    sql = "INSERT INTO photo (mango_id, seq, data, mime) VALUES (%s, %s, %s, %s)"
    params = (mango_id, seq, db_binary(raw), mime)
    if IS_PG:
        new = q_one(conn, sql + " RETURNING id", params)
        photo_id = new["id"]
    else:
        cur = conn.cursor()
        cur.execute(_adapt(sql), params)
        photo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": photo_id, "seq": seq}), 201


@app.route("/api/photo/<int:photo_id>", methods=["GET"])
def api_photo_get(photo_id):
    conn = get_conn()
    row = q_one(conn, "SELECT data, mime FROM photo WHERE id = %s", (photo_id,))
    conn.close()
    if row is None:
        return "", 404
    data = bytes(row["data"])  # sqlite 回 bytes、psycopg2 回 memoryview，都轉成 bytes
    mime = row["mime"] or "image/jpeg"
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if request.args.get("dl"):
        ext = "png" if "png" in mime else "jpg"
        resp.headers["Content-Disposition"] = f'attachment; filename="mango-photo-{photo_id}.{ext}"'
    return resp


@app.route("/api/photo/<int:photo_id>", methods=["DELETE"])
def api_photo_delete(photo_id):
    conn = get_conn()
    execute(conn, "DELETE FROM photo WHERE id = %s", (photo_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": photo_id})


# ---------- 前端 ----------
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/demo")
def demo():
    return send_from_directory(BASE_DIR, "demo.html")


@app.route("/guide")
def guide():
    return send_from_directory(BASE_DIR, "guide.html")


@app.route("/health")
def health():
    return "ok (pg)" if IS_PG else "ok (sqlite)"


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
