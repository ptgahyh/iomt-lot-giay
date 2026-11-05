"""Lưu trữ SQLite: số liệu, sự kiện, trạng thái bảo mật của node, hàng đợi gửi bù.

Một kết nối duy nhất, mọi truy cập đi qua một khóa (lock), nên các luồng
không bao giờ ghi cùng lúc. Bảng readings/events có cột sent: 0 = chưa đẩy lên
cloud. Mất mạng thì dữ liệu nằm chờ ở đây, có mạng lại thì luồng cloud gửi bù.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms     INTEGER NOT NULL,
    node_id   INTEGER NOT NULL,
    source    TEXT    NOT NULL,      -- lora | mqtt | modbus
    kind      TEXT    NOT NULL,      -- insole | wrist | bed
    data      TEXT    NOT NULL,      -- JSON
    sent      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_readings_unsent ON readings(sent, id);
CREATE INDEX IF NOT EXISTS idx_readings_node ON readings(node_id, ts_ms);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms     INTEGER NOT NULL,
    node_id   INTEGER,               -- NULL = sự kiện của gateway
    level     TEXT    NOT NULL,      -- INFO | WARN | ALARM | SECURITY
    code      TEXT    NOT NULL,
    message   TEXT    NOT NULL,
    sent      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_unsent ON events(sent, id);

CREATE TABLE IF NOT EXISTS node_state (
    node_id     INTEGER PRIMARY KEY,
    last_fcnt   INTEGER,
    last_frame  BLOB,
    last_nonce  INTEGER,
    updated_ms  INTEGER
);

CREATE TABLE IF NOT EXISTS seen_nonces (
    node_id   INTEGER NOT NULL,
    nonce     INTEGER NOT NULL,
    ts_ms     INTEGER NOT NULL,
    PRIMARY KEY (node_id, nonce)
);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class NodeSecState:
    last_fcnt: int | None = None
    last_frame: bytes | None = None
    last_nonce: int | None = None


@dataclass
class Row:
    id: int
    ts_ms: int
    node_id: int | None
    payload: dict


class Storage:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------ ghi
    def add_reading(self, node_id: int, source: str, kind: str, data: dict,
                    ts_ms: int | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO readings(ts_ms,node_id,source,kind,data) VALUES(?,?,?,?,?)",
                (ts_ms or now_ms(), node_id, source, kind,
                 json.dumps(data, ensure_ascii=False)))
            return cur.lastrowid

    def add_event(self, level: str, code: str, message: str, node_id: int | None = None,
                  ts_ms: int | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO events(ts_ms,node_id,level,code,message) VALUES(?,?,?,?,?)",
                (ts_ms or now_ms(), node_id, level, code, message))
            return cur.lastrowid

    # ------------------------------------------------------------ hàng đợi gửi bù
    def unsent_readings(self, limit: int) -> list[Row]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id,ts_ms,node_id,data FROM readings WHERE sent=0 ORDER BY id LIMIT ?",
                (limit,)).fetchall()
        return [Row(r[0], r[1], r[2], json.loads(r[3])) for r in rows]

    def unsent_events(self, limit: int) -> list[Row]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id,ts_ms,node_id,level,code,message FROM events "
                "WHERE sent=0 ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [Row(r[0], r[1], r[2], {"level": r[3], "code": r[4], "message": r[5]})
                for r in rows]

    def mark_sent(self, table: str, ids: list[int]) -> None:
        if table not in ("readings", "events"):
            raise ValueError(table)
        if not ids:
            return
        with self._lock:
            self._db.executemany(f"UPDATE {table} SET sent=1 WHERE id=?", [(i,) for i in ids])

    def count_unsent(self) -> int:
        with self._lock:
            a = self._db.execute("SELECT COUNT(*) FROM readings WHERE sent=0").fetchone()[0]
            b = self._db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]
        return a + b

    # ------------------------------------------------------------ trạng thái bảo mật
    def load_sec_state(self, node_id: int) -> NodeSecState:
        with self._lock:
            r = self._db.execute(
                "SELECT last_fcnt,last_frame,last_nonce FROM node_state WHERE node_id=?",
                (node_id,)).fetchone()
        return NodeSecState(*r) if r else NodeSecState()

    def save_sec_state(self, node_id: int, st: NodeSecState) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO node_state(node_id,last_fcnt,last_frame,last_nonce,updated_ms) "
                "VALUES(?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET "
                "last_fcnt=excluded.last_fcnt,last_frame=excluded.last_frame,"
                "last_nonce=excluded.last_nonce,updated_ms=excluded.updated_ms",
                (node_id, st.last_fcnt, st.last_frame, st.last_nonce, now_ms()))

    def nonce_seen(self, node_id: int, nonce: int) -> bool:
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM seen_nonces WHERE node_id=? AND nonce=?",
                (node_id, nonce)).fetchone() is not None

    def add_nonce(self, node_id: int, nonce: int) -> None:
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO seen_nonces VALUES(?,?,?)",
                             (node_id, nonce, now_ms()))

    # ------------------------------------------------------------ xuất CSV (báo cáo)
    def export_csv(self, path: str) -> int:
        import csv
        with self._lock:
            rows = self._db.execute(
                "SELECT id,ts_ms,node_id,source,kind,data FROM readings ORDER BY id").fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "ts_ms", "node_id", "source", "kind", "data"])
            w.writerows(rows)
        return len(rows)
