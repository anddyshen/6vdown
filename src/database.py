"""SQLite 数据访问层（线程安全，仅标准库）。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Optional

from . import constants
from .models import (
    DownloadHost,
    MagnetLink,
    MirrorSite,
    ParseItem,
    TaskRecord,
    host_from_row,
    mirror_from_row,
    now_ms,
    task_from_row,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS download_hosts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL, name TEXT, address TEXT, port INTEGER DEFAULT 0,
  username TEXT, password TEXT, is_active INTEGER DEFAULT 0,
  created_at INTEGER);
CREATE TABLE IF NOT EXISTS mirror_sites(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE, enabled INTEGER DEFAULT 1, is_current INTEGER DEFAULT 0,
  status TEXT DEFAULT '', checked_at INTEGER DEFAULT 0,
  created_at INTEGER DEFAULT 0, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS task_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER, title TEXT, link TEXT, source TEXT,
  host_name TEXT, host_type TEXT, status TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS parse_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_url TEXT, detail_url TEXT UNIQUE, title TEXT, date TEXT,
  block TEXT, is_red INTEGER DEFAULT 0, is_classic INTEGER DEFAULT 0,
  detail_ok INTEGER DEFAULT 0,
  desc TEXT, magnets_json TEXT DEFAULT '[]', first_seen INTEGER);
CREATE TABLE IF NOT EXISTS parse_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_url TEXT, started_at INTEGER, finished_at INTEGER,
  total INTEGER DEFAULT 0, new_count INTEGER DEFAULT 0, status TEXT);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT);
"""


class Database:
    def __init__(self, path: Optional[str] = None):
        self.path = path or constants.db_path()
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        """旧库迁移：为 parse_records 补充 detail_ok 列。"""
        try:
            with self._lock, self._conn() as c:
                cols = {r["name"] for r in
                        c.execute("PRAGMA table_info(parse_records)")}
                if cols and "detail_ok" not in cols:
                    c.execute(
                        "ALTER TABLE parse_records "
                        "ADD COLUMN detail_ok INTEGER DEFAULT 0")
        except Exception:
            pass

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    # ------------------------------------------------------------- hosts
    def list_hosts(self) -> list:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM download_hosts ORDER BY is_active DESC, id ASC"
            ).fetchall()
        return [host_from_row(r) for r in rows]

    def active_host(self) -> Optional[DownloadHost]:
        for h in self.list_hosts():
            if h.is_active:
                return h
        hosts = self.list_hosts()
        return hosts[0] if hosts else None

    def add_host(self, h: DownloadHost) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO download_hosts(type,name,address,port,username,password,"
                "is_active,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (h.type, h.name, h.address, h.port, h.username, h.password,
                 int(h.is_active), now_ms()),
            )
            return int(cur.lastrowid)

    def update_host(self, h: DownloadHost) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE download_hosts SET type=?,name=?,address=?,port=?,username=?,"
                "password=?,is_active=? WHERE id=?",
                (h.type, h.name, h.address, h.port, h.username, h.password,
                 int(h.is_active), h.id),
            )

    def delete_host(self, hid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM download_hosts WHERE id=?", (hid,))

    def set_active_host(self, hid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE download_hosts SET is_active=0")
            c.execute("UPDATE download_hosts SET is_active=1 WHERE id=?", (hid,))

    # ------------------------------------------------------------- mirrors
    def list_mirrors(self) -> list:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM mirror_sites ORDER BY is_current DESC, id ASC"
            ).fetchall()
        return [mirror_from_row(r) for r in rows]

    def current_mirror_url(self) -> str:
        for m in self.list_mirrors():
            if m.is_current:
                return m.url
        return ""

    def upsert_mirror(self, m: MirrorSite) -> int:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT id FROM mirror_sites WHERE url=?", (m.url,)).fetchone()
            if row:
                c.execute(
                    "UPDATE mirror_sites SET url=?,enabled=?,is_current=?,status=?,"
                    "checked_at=?,note=? WHERE id=?",
                    (m.url, int(m.enabled), int(m.is_current), m.status,
                     m.checked_at, m.note, row["id"]),
                )
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO mirror_sites(url,enabled,is_current,status,checked_at,"
                "created_at,note) VALUES(?,?,?,?,?,?,?)",
                (m.url, int(m.enabled), int(m.is_current), m.status,
                 m.checked_at, now_ms(), m.note),
            )
            return int(cur.lastrowid)

    def update_mirror(self, m: MirrorSite) -> None:
        """按 id 更新镜像（地址/备注/启用），current/status 保持不变。"""
        with self._lock, self._conn() as c:
            dup = c.execute(
                "SELECT id FROM mirror_sites WHERE url=? AND id<>?",
                (m.url, m.id)).fetchone()
            if dup:
                raise ValueError("该镜像地址已存在")
            c.execute(
                "UPDATE mirror_sites SET url=?, enabled=?, note=? WHERE id=?",
                (m.url, int(bool(m.enabled)), m.note or "", m.id))

    def delete_mirror(self, mid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM mirror_sites WHERE id=?", (mid,))

    def set_current_mirror(self, url: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE mirror_sites SET is_current=0")
            c.execute("UPDATE mirror_sites SET is_current=1 WHERE url=?", (url,))

    def mark_mirror(self, url: str, ok: bool, note: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE mirror_sites SET status=?, checked_at=?, note=? WHERE url=?",
                ("ok" if ok else "fail", now_ms(), note, url),
            )

    # ------------------------------------------------------------- task_log
    def add_task(self, t: TaskRecord) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO task_log(created_at,title,link,source,host_name,"
                "host_type,status,message) VALUES(?,?,?,?,?,?,?,?)",
                (t.created_at or now_ms(), t.title, t.link, t.source,
                 t.host_name, t.host_type, t.status, t.message),
            )
            return int(cur.lastrowid)

    def list_tasks(self, limit: int = 500, offset: int = 0, keyword: str = "") -> list:
        sql = "SELECT * FROM task_log"
        args: list = []
        if keyword:
            sql += " WHERE title LIKE ? OR link LIKE ? OR host_name LIKE ?"
            like = f"%{keyword}%"
            args += [like, like, like]
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        with self._lock, self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [task_from_row(r) for r in rows]

    def delete_task(self, tid: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM task_log WHERE id=?", (tid,))

    def task_count(self) -> int:
        with self._lock, self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM task_log").fetchone()[0])

    # ------------------------------------------------------------- parse
    def existing_detail_urls(self, site_url: str) -> set:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT detail_url FROM parse_records WHERE site_url=?", (site_url,)
            ).fetchall()
        return {r["detail_url"] for r in rows}

    def insert_parse_records(self, site_url: str, items: list) -> int:
        """写入新解析记录，返回新入库条数（按 detail_url 增量）。"""
        new_count = 0
        with self._lock, self._conn() as c:
            for it in items:
                if not it.detail_url:
                    continue
                exists = c.execute(
                    "SELECT 1 FROM parse_records WHERE site_url=? AND detail_url=?",
                    (site_url, it.detail_url),
                ).fetchone()
                if exists:
                    continue
                c.execute(
                    "INSERT INTO parse_records(site_url,detail_url,title,date,block,"
                    "is_red,is_classic,detail_ok,desc,magnets_json,first_seen) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (site_url, it.detail_url, it.title, it.date, it.block,
                     int(it.is_red), int(it.is_classic),
                     int(bool(it.magnets or it.detail_ok)), it.desc,
                     json.dumps([{"label": m.label, "url": m.url} for m in it.magnets],
                                ensure_ascii=False),
                     it.first_seen or now_ms()),
                )
                new_count += 1
        return new_count

    def update_parse_item(self, site_url: str, it: ParseItem) -> None:
        """更新已存在记录的磁力/简介/状态（用于失败补抓）。"""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE parse_records SET desc=?, detail_ok=?, magnets_json=? "
                "WHERE site_url=? AND detail_url=?",
                (it.desc or "", int(bool(it.magnets or it.detail_ok)),
                 json.dumps([{"label": m.label, "url": m.url} for m in it.magnets],
                            ensure_ascii=False),
                 site_url, it.detail_url),
            )

    def incomplete_parse_items(self, site_url: str) -> list:
        """曾抓取失败/无磁力的记录（下次解析时补抓）。"""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM parse_records WHERE site_url=? AND detail_ok=0",
                (site_url,),
            ).fetchall()
        return [self._row_to_parse_item(r) for r in rows]

    def list_parse_items(self, site_url: str) -> list:
        """读取某站全部缓存记录（第二次解析直接展示此缓存）。"""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM parse_records WHERE site_url=? "
                "ORDER BY id ASC",
                (site_url,),
            ).fetchall()
        return [self._row_to_parse_item(r) for r in rows]

    @staticmethod
    def _row_to_parse_item(r) -> ParseItem:
        magnets = []
        try:
            data = json.loads(r["magnets_json"] or "[]")
            magnets = [MagnetLink(label=str(x.get("label", "")),
                                  url=str(x.get("url", "")))
                       for x in data if x.get("url")]
        except Exception:
            magnets = []
        return ParseItem(
            title=r["title"] or "", date=r["date"] or "", block=r["block"] or "",
            detail_url=r["detail_url"] or "",
            is_red=bool(r["is_red"]), is_classic=bool(r["is_classic"]),
            desc=r["desc"] or "", magnets=magnets,
            detail_ok=bool(r["detail_ok"]) or bool(magnets),
            first_seen=r["first_seen"] or 0,
        )

    def clear_parse_data(self, site_url: str = "") -> None:
        """重置解析数据（回到首次解析前）。默认清空全部站点记录。"""
        with self._lock, self._conn() as c:
            if site_url:
                c.execute("DELETE FROM parse_records WHERE site_url=?", (site_url,))
                c.execute("DELETE FROM parse_runs WHERE site_url=?", (site_url,))
            else:
                c.execute("DELETE FROM parse_records")
                c.execute("DELETE FROM parse_runs")

    def start_run(self, site_url: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO parse_runs(site_url,started_at,status) VALUES(?,?,'running')",
                (site_url, now_ms()),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, total: int, new_count: int, ok: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE parse_runs SET finished_at=?, total=?, new_count=?, status=? WHERE id=?",
                (now_ms(), total, new_count, "ok" if ok else "fail", run_id),
            )

    def latest_new_count(self, site_url: str) -> int:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT new_count FROM parse_runs WHERE site_url=? ORDER BY id DESC LIMIT 1",
                (site_url,),
            ).fetchone()
        return int(row["new_count"]) if row else 0


