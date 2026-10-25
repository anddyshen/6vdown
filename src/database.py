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
    SiteInstance,
    Subscription,
    SubscriptionHistory,
    TaskRecord,
    host_from_row,
    mirror_from_row,
    now_ms,
    site_from_row,
    sub_from_row,
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
CREATE TABLE IF NOT EXISTS site_instances(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  module_id TEXT NOT NULL DEFAULT 'hao6v', name TEXT DEFAULT '',
  entry_urls TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1,
  is_current INTEGER DEFAULT 0,
  note TEXT DEFAULT '', created_at INTEGER);
CREATE TABLE IF NOT EXISTS task_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER, title TEXT, link TEXT, source TEXT,
  host_name TEXT, host_type TEXT, status TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS operation_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at INTEGER, category TEXT DEFAULT 'system',
  action TEXT DEFAULT '', detail TEXT DEFAULT '',
  status TEXT DEFAULT 'ok', operator TEXT DEFAULT 'admin');
CREATE TABLE IF NOT EXISTS parse_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_url TEXT, detail_url TEXT, title TEXT, date TEXT,
  block TEXT, is_red INTEGER DEFAULT 0, is_classic INTEGER DEFAULT 0,
  detail_ok INTEGER DEFAULT 0,
  desc TEXT, magnets_json TEXT DEFAULT '[]', first_seen INTEGER,
  last_seen INTEGER DEFAULT 0, prev_title TEXT DEFAULT '',
  site_key TEXT DEFAULT '',
  UNIQUE(site_url, detail_url));
CREATE TABLE IF NOT EXISTS parse_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_url TEXT, started_at INTEGER, finished_at INTEGER,
  total INTEGER DEFAULT 0, new_count INTEGER DEFAULT 0, status TEXT);
CREATE TABLE IF NOT EXISTS subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, detail_url TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'active', last_ep TEXT DEFAULT '',
  emby_series_id TEXT DEFAULT '', created_at INTEGER DEFAULT 0,
  updated_at INTEGER DEFAULT 0, site_key TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS subscription_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL, episode_label TEXT DEFAULT '',
  magnet_url TEXT NOT NULL, quality TEXT DEFAULT '',
  pushed_at INTEGER DEFAULT 0, UNIQUE(sub_id, magnet_url));
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS search_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL,
  site_ids TEXT DEFAULT '', result_count INTEGER DEFAULT 0,
  created_at INTEGER);
"""

# parse_records 重建迁移用的新表 DDL（联合唯一）
_SCHEMA_PARSE_RECORDS_NEW = """
CREATE TABLE parse_records(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site_url TEXT, detail_url TEXT, title TEXT, date TEXT,
  block TEXT, is_red INTEGER DEFAULT 0, is_classic INTEGER DEFAULT 0,
  detail_ok INTEGER DEFAULT 0,
  desc TEXT, magnets_json TEXT DEFAULT '[]', first_seen INTEGER,
  last_seen INTEGER DEFAULT 0, prev_title TEXT DEFAULT '',
  site_key TEXT DEFAULT '',
  UNIQUE(site_url, detail_url));
"""


class Database:
    def __init__(self, path: Optional[str] = None):
        self.path = path or constants.db_path()
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
        self._ensure_columns()
        self._migrate_parse_records_unique()
        self.ensure_builtin_sites()

    def _migrate_parse_records_unique(self) -> None:
        """旧库迁移：detail_url 全局唯一 → (site_url, detail_url) 联合唯一。

        多入口站点（如电影港新版的多个分类页）下，同一详情页会归属不同入口，
        全局唯一会导致 INSERT 冲突；重建表并原样拷贝数据。
        """
        try:
            with self._lock, self._conn() as c:
                row = c.execute(
                    "SELECT sql FROM sqlite_master WHERE type=? AND name=?",
                    ("table", "parse_records")).fetchone()
                sql = (row["sql"] or "") if row else ""
                compact = sql.replace(" ", "").lower()
                if "unique(site_url,detail_url)" in compact:
                    return
                if not compact:
                    return
                c.executescript(
                    "ALTER TABLE parse_records RENAME TO parse_records_old;"
                    + _SCHEMA_PARSE_RECORDS_NEW +
                    "INSERT OR IGNORE INTO parse_records(id,site_url,detail_url,"
                    "title,date,block,is_red,is_classic,detail_ok,desc,"
                    "magnets_json,first_seen,last_seen,prev_title,site_key) "
                    "SELECT id,site_url,detail_url,title,date,block,is_red,"
                    "is_classic,detail_ok,desc,magnets_json,first_seen,last_seen,"
                    "prev_title,site_key FROM parse_records_old;"
                    "DROP TABLE parse_records_old;")
        except Exception:
            # 迁移失败不阻断启动（下次打开会重试）；旧库仍可读
            pass

    def _ensure_columns(self) -> None:
        """旧库迁移：为后加的列自动补齐（parse_records / subscriptions）。"""
        added = {
            "parse_records": {
                "detail_ok": "INTEGER DEFAULT 0",
                "last_seen": "INTEGER DEFAULT 0",
                "prev_title": "TEXT DEFAULT ''",
                "site_key": "TEXT DEFAULT ''",
            },
            "subscriptions": {
                "site_key": "TEXT DEFAULT ''",
            },
            "site_instances": {
                "is_current": "INTEGER DEFAULT 0",
            },
        }
        try:
            with self._lock, self._conn() as c:
                for table, cols in added.items():
                    exist = {r["name"] for r in
                             c.execute(f"PRAGMA table_info({table})")}
                    if not exist:
                        continue
                    for name, ddl in cols.items():
                        if name not in exist:
                            c.execute(
                                f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
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

    # -------------------------------------------------------- 搜索历史
    def add_search_history(self, keyword: str, site_ids: Optional[list] = None,
                           result_count: int = 0, limit: int = 20) -> None:
        """记录一次搜索，并把总条数裁剪到 limit。"""
        kw = (keyword or "").strip()
        if not kw:
            return
        ids = ",".join(str(x) for x in (site_ids or []))
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO search_history(keyword, site_ids,"
                    " result_count, created_at) VALUES(?,?,?,?)",
                    (kw, ids, int(result_count or 0), now_ms()))
                c.execute(
                    "DELETE FROM search_history WHERE id NOT IN "
                    "(SELECT id FROM search_history ORDER BY created_at DESC"
                    " LIMIT ?)", (max(1, int(limit or 20)),))
        except Exception:
            pass

    def list_search_history(self, limit: int = 20) -> list:
        """最近搜索关键词（去重，按时间倒序）。"""
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT keyword, MAX(created_at) AS ts FROM"
                    " search_history GROUP BY keyword ORDER BY ts DESC"
                    " LIMIT ?", (max(1, int(limit or 20)),)).fetchall()
            return [r["keyword"] for r in rows]
        except Exception:
            return []

    def clear_search_history(self) -> None:
        """清空搜索历史。"""
        try:
            with self._lock, self._conn() as c:
                c.execute("DELETE FROM search_history")
        except Exception:
            pass

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

    # ------------------------------------------------------------- sites
    def ensure_default_site(self) -> int:
        """首次运行写入默认站点实例（hao6v 模块，入口为空=共享镜像池）。"""
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT id FROM site_instances ORDER BY id ASC LIMIT 1").fetchone()
            if row:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO site_instances(module_id,name,entry_urls,enabled,"
                "is_current,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (constants.DEFAULT_SITE_MODULE, constants.DEFAULT_SITE_NAME,
                 "[]", 1, 1, "系统默认站点；入口为空时使用镜像管理中的域名", now_ms()),
            )
            return int(cur.lastrowid)

    def ensure_builtin_sites(self) -> None:
        """按已注册的内置模块补写内置站点实例（幂等；用户删过的不再补）。"""
        self.ensure_default_site()
        try:
            from .site.modules.registry import list_modules

            metas = {m.module_id: m for m in list_modules()}
        except Exception:
            return
        have = {s.module_id for s in self.list_sites()}
        for mid, meta in metas.items():
            if mid == "hao6v" or mid in have:
                continue
            if not meta.default_entry_urls:
                continue
            if self.get_setting(f"site_dismissed:{mid}") == "1":
                continue
            self.upsert_site(SiteInstance(
                module_id=mid, name=meta.name,
                entry_urls=list(meta.default_entry_urls),
                enabled=True, note="内置站点，入口可自行增删（发布页域名可在备注中查）"))

    def list_sites(self, enabled_only: bool = False) -> list:
        sql = "SELECT * FROM site_instances"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id ASC"
        with self._lock, self._conn() as c:
            rows = c.execute(sql).fetchall()
        return [site_from_row(r) for r in rows]

    def get_site(self, site_id: int) -> Optional[SiteInstance]:
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT * FROM site_instances WHERE id=?", (site_id,)).fetchone()
        return site_from_row(r) if r else None

    def current_site(self) -> Optional[SiteInstance]:
        """当前解析站点（is_current=1）；未设置时取第一个启用的站点。"""
        sites = self.list_sites()
        for s in sites:
            if s.is_current:
                return s
        for s in sites:
            if s.enabled:
                return s
        return sites[0] if sites else None

    def set_current_site(self, site_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE site_instances SET is_current=0")
            c.execute("UPDATE site_instances SET is_current=1 WHERE id=?",
                      (site_id,))

    def upsert_site(self, s: SiteInstance) -> int:
        payload = json.dumps([u for u in (s.entry_urls or []) if u],
                             ensure_ascii=False)
        with self._lock, self._conn() as c:
            if s.id:
                c.execute(
                    "UPDATE site_instances SET module_id=?,name=?,entry_urls=?,"
                    "enabled=?,is_current=?,note=? WHERE id=?",
                    (s.module_id, s.name, payload, int(bool(s.enabled)),
                     int(bool(s.is_current)), s.note or "", s.id),
                )
                return int(s.id)
            cur = c.execute(
                "INSERT INTO site_instances(module_id,name,entry_urls,enabled,"
                "is_current,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (s.module_id, s.name, payload, int(bool(s.enabled)),
                 int(bool(s.is_current)), s.note or "", now_ms()),
            )
            return int(cur.lastrowid)

    def delete_site(self, site_id: int) -> None:
        site = self.get_site(site_id)
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM site_instances WHERE id=?", (site_id,))
        # 内置站点被用户主动删除 → 记录免打扰，重启不再自动补写
        if site is not None:
            try:
                from .site.modules.registry import list_modules

                builtin = {m.module_id: m for m in list_modules()}
                meta = builtin.get(site.module_id)
                if meta is not None and meta.default_entry_urls:
                    self.set_setting(f"site_dismissed:{site.module_id}", "1")
            except Exception:
                pass

    def set_site_enabled(self, site_id: int, enabled: bool) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE site_instances SET enabled=? WHERE id=?",
                      (int(bool(enabled)), site_id))

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

    # ------------------------------------------------------------- operation_logs
    def add_operation_log(
        self,
        category: str,
        action: str,
        detail: str,
        status: str = "ok",
        operator: str = "admin",
    ) -> int:
        """记录系统操作日志（下载、解析、追剧、配置变动等）。"""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO operation_logs(created_at, category, action, detail, status, operator) "
                "VALUES(?,?,?,?,?,?)",
                (now_ms(), category, action, detail, status, operator),
            )
            return int(cur.lastrowid)

    def list_operation_logs(
        self, limit: int = 200, category: str = "", keyword: str = ""
    ) -> list[dict]:
        """获取操作日志列表，支持按分类与关键词筛选。"""
        sql = "SELECT * FROM operation_logs"
        args: list = []
        conds: list[str] = []
        if category:
            conds.append("category=?")
            args.append(category)
        if keyword:
            conds.append("(action LIKE ? OR detail LIKE ? OR operator LIKE ?)")
            like = f"%{keyword}%"
            args.extend([like, like, like])
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def clear_operation_logs(self) -> None:
        """清空全部操作日志。"""
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM operation_logs")

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
                     json.dumps([{"label": m.label, "url": m.url,
                                  "kind": getattr(m, "kind", "magnet")}
                                 for m in it.magnets], ensure_ascii=False),
                     it.first_seen or now_ms()),
                )
                new_count += 1
        return new_count

    def existing_parse_map(self, site_url: str) -> dict:
        """{detail_url: ParseItem}（含 title/date，用于判定“同页更新”）。"""
        return {it.detail_url: it for it in self.list_parse_items(site_url)}

    def upsert_parse_records(self, site_url: str, items: list) -> tuple:
        """写入解析记录：已存在则更新（标题/日期/区块/标记/磁力）。

        返回 (新增条数, 更新条数)。判定“更新”的依据是标题或日期发生变化——
        连续剧/动画的“更新到第 N 集”“全集”就属于这一类（详情页 URL 不变）。
        详情页未抓取成功时保留库中已有的简介与磁力，避免被清空。
        """
        new_count = updated_count = 0
        with self._lock, self._conn() as c:
            for it in items:
                if not it.detail_url:
                    continue
                now = it.last_seen or now_ms()
                mags = json.dumps(
                    [{"label": m.label, "url": m.url,
                      "kind": getattr(m, "kind", "magnet")} for m in it.magnets],
                    ensure_ascii=False)
                row = c.execute(
                    "SELECT title,date,desc,detail_ok,magnets_json "
                    "FROM parse_records WHERE site_url=? AND detail_url=?",
                    (site_url, it.detail_url),
                ).fetchone()
                if row is None:
                    c.execute(
                        "INSERT INTO parse_records(site_url,detail_url,title,date,"
                        "block,is_red,is_classic,detail_ok,desc,magnets_json,"
                        "first_seen,last_seen,prev_title) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (site_url, it.detail_url, it.title, it.date, it.block,
                         int(it.is_red), int(it.is_classic),
                         int(bool(it.magnets or it.detail_ok)), it.desc, mags,
                         it.first_seen or now, now, it.prev_title or ""),
                    )
                    new_count += 1
                    continue
                changed = ((row["title"] or "") != (it.title or "")
                           or (row["date"] or "") != (it.date or ""))
                if it.detail_ok or it.magnets:
                    desc = it.desc
                    detail_ok = int(it.detail_ok)
                    mag_json = mags
                else:
                    desc = row["desc"] or ""
                    detail_ok = int(row["detail_ok"] or 0)
                    mag_json = row["magnets_json"] or "[]"
                prev_title = it.prev_title or (row["title"] if changed else "")
                c.execute(
                    "UPDATE parse_records SET title=?,date=?,block=?,is_red=?,"
                    "is_classic=?,detail_ok=?,desc=?,magnets_json=?,"
                    "last_seen=?,prev_title=? "
                    "WHERE site_url=? AND detail_url=?",
                    (it.title, it.date, it.block, int(it.is_red),
                     int(it.is_classic), detail_ok, desc, mag_json, now,
                     prev_title or "", site_url, it.detail_url),
                )
                if changed:
                    updated_count += 1
        return new_count, updated_count

    def update_parse_item(self, site_url: str, it: ParseItem) -> None:
        """更新已存在记录的磁力/简介/状态（用于失败补抓）。"""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE parse_records SET desc=?, detail_ok=?, magnets_json=? "
                "WHERE site_url=? AND detail_url=?",
                (it.desc or "", int(bool(it.magnets or it.detail_ok)),
                 json.dumps([{"label": m.label, "url": m.url,
                              "kind": getattr(m, "kind", "magnet")}
                             for m in it.magnets], ensure_ascii=False),
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

    def list_parse_items(self, site_url) -> list:
        """读取缓存记录（第二次解析直接展示此缓存）。

        site_url 可为单个地址或地址列表（多站点合并展示）。
        """
        if isinstance(site_url, (list, tuple, set)):
            urls = [u for u in site_url if u]
            if not urls:
                return []
            marks = ",".join("?" * len(urls))
            with self._lock, self._conn() as c:
                rows = c.execute(
                    f"SELECT * FROM parse_records WHERE site_url IN ({marks}) "
                    "ORDER BY id DESC", urls).fetchall()
            return [self._row_to_parse_item(r) for r in rows]
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM parse_records WHERE site_url=? "
                "ORDER BY id DESC",
                (site_url,),
            ).fetchall()
        return [self._row_to_parse_item(r) for r in rows]

    @staticmethod
    def _row_to_parse_item(r) -> ParseItem:
        magnets = []
        try:
            data = json.loads(r["magnets_json"] or "[]")
            magnets = [MagnetLink(label=str(x.get("label", "")),
                                  url=str(x.get("url", "")),
                                  kind=str(x.get("kind", "magnet") or "magnet"))
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
            prev_title=(r["prev_title"] if "prev_title" in r.keys() else "") or "",
            last_seen=(r["last_seen"] if "last_seen" in r.keys() else 0) or 0,
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

    # ------------------------------------------------------------ 订阅管理 (Subscriptions)
    def add_subscription(self, sub: Subscription) -> int:
        with self._lock, self._conn() as c:
            now = now_ms()
            site_key = getattr(sub, "site_key", "") or ""
            cur = c.execute(
                """INSERT INTO subscriptions(title, detail_url, status, last_ep, emby_series_id, created_at, updated_at, site_key)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(detail_url) DO UPDATE SET title=excluded.title, updated_at=excluded.updated_at, site_key=excluded.site_key""",
                (sub.title, sub.detail_url, sub.status or "active", sub.last_ep or "",
                 sub.emby_series_id or "", sub.created_at or now, now, site_key),
            )
            sub_id = int(cur.lastrowid or 0)
            if not sub_id:
                row = c.execute("SELECT id FROM subscriptions WHERE detail_url=?", (sub.detail_url,)).fetchone()
                sub_id = int(row["id"]) if row else 0
            return sub_id

    def list_subscriptions(self, status: str = "") -> list[Subscription]:
        with self._lock, self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM subscriptions WHERE status=? ORDER BY id DESC", (status,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM subscriptions ORDER BY id DESC").fetchall()
            return [sub_from_row(r) for r in rows]

    def get_subscription_by_url(self, detail_url: str) -> Optional[Subscription]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM subscriptions WHERE detail_url=? LIMIT 1", (detail_url,)).fetchone()
            return sub_from_row(r) if r else None

    def update_subscription(self, sub: Subscription) -> None:
        with self._lock, self._conn() as c:
            site_key = getattr(sub, "site_key", "") or ""
            c.execute(
                """UPDATE subscriptions SET title=?, status=?, last_ep=?, emby_series_id=?, updated_at=?, site_key=?
                   WHERE id=?""",
                (sub.title, sub.status, sub.last_ep, sub.emby_series_id, now_ms(), site_key, sub.id),
            )

    def delete_subscription(self, sub_id: int) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
            c.execute("DELETE FROM subscription_history WHERE sub_id=?", (sub_id,))

    def is_magnet_pushed(self, sub_id: int, magnet_url: str) -> bool:
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM subscription_history WHERE sub_id=? AND magnet_url=? LIMIT 1",
                (sub_id, magnet_url),
            ).fetchone()
            return bool(r)

    def is_episode_pushed(self, sub_id: int, episode_label: str) -> bool:
        """检查某分集标签是否已推送下载过。"""
        if not episode_label:
            return False
        with self._lock, self._conn() as c:
            r = c.execute(
                "SELECT 1 FROM subscription_history WHERE sub_id=? AND episode_label=? LIMIT 1",
                (sub_id, episode_label.strip()),
            ).fetchone()
            return bool(r)

    def get_pushed_episodes(self, sub_id: int) -> set[str]:
        """获取该剧所有已推送过的分集标签集合。"""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT episode_label FROM subscription_history WHERE sub_id=?",
                (sub_id,),
            ).fetchall()
            return {r["episode_label"].strip() for r in rows if r["episode_label"]}

    def record_pushed_magnet(self, sub_id: int, episode_label: str, magnet_url: str, quality: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO subscription_history(sub_id, episode_label, magnet_url, quality, pushed_at)
                   VALUES(?,?,?,?,?)""",
                (sub_id, episode_label, magnet_url, quality, now_ms()),
            )

    # 兼容别名
    get_pushed_labels = get_pushed_episodes
    record_subscription_push = record_pushed_magnet



