"""FastAPI 应用定义与路由注册。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .service import ServerService

STATIC_DIR = Path(__file__).parent / "static"


class ParseRequest(BaseModel):
    site_ids: Optional[list[int]] = None


class DetailRequest(BaseModel):
    detail_url: str
    module_id: str = ""


class SearchRequest(BaseModel):
    keyword: str
    site_ids: Optional[list[int]] = None
    max_pages: int = 1


class AddSubRequest(BaseModel):
    title: str
    detail_url: str
    site_key: str = ""


class DownloadRequest(BaseModel):
    url: str
    host_id: Optional[int] = None
    sub_id: Optional[int] = None
    ep_label: str = ""
    quality: str = ""


class EmbyTestRequest(BaseModel):
    server_url: str
    api_key: str


def create_app() -> FastAPI:
    app = FastAPI(title="6vdown / C2Down Web Server", version="1.0.4")

    # 允许跨域（方便前端独立开发或同源访问）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局服务实例
    service = ServerService()

    # ------------------------------------------------------------ 状态与全局
    @app.get("/api/status")
    def get_status():
        cur_site = service.db.current_site()
        active_host = service.db.active_host()
        subs = service.db.list_subscriptions()
        return {
            "version": "1.0.4",
            "current_site": cur_site.name if cur_site else "未设置",
            "active_host": f"{active_host.name} ({active_host.type.upper()})" if active_host else "未配置",
            "subscriptions_count": len(subs),
            "emby_enabled": service.cfg.get("emby_enabled", False),
        }

    # ------------------------------------------------------------ 解析工作台
    @app.get("/api/sites")
    def list_sites():
        return service.get_sites()

    @app.post("/api/sites/current")
    def set_current_site(payload: dict):
        site_id = payload.get("site_id")
        if not site_id:
            raise HTTPException(400, "缺少 site_id")
        return {"ok": service.set_current_site(int(site_id))}

    @app.get("/api/workbench")
    def get_workbench(site_ids: Optional[str] = None):
        ids = [int(x) for x in site_ids.split(",") if x.isdigit()] if site_ids else None
        return service.get_workbench_items(ids)

    @app.post("/api/workbench/parse")
    def start_parse(req: ParseRequest):
        started = service.start_parse(req.site_ids)
        return {"ok": started, "message": "解析任务已启动" if started else "解析任务正在运行中"}

    @app.get("/api/workbench/parse_status")
    def parse_status():
        return service.get_parse_status()

    @app.post("/api/workbench/detail")
    def fetch_detail(req: DetailRequest):
        res = service.fetch_item_detail(req.detail_url, req.module_id)
        if not res:
            raise HTTPException(404, "抓取详情失败或未找到磁力")
        return res

    # ------------------------------------------------------------ 跨站搜索
    @app.post("/api/search")
    def search(req: SearchRequest):
        return service.search(req.keyword, req.site_ids, req.max_pages)

    # ------------------------------------------------------------ 订阅追剧
    @app.get("/api/subscriptions")
    def list_subs():
        return service.list_subscriptions()

    @app.post("/api/subscriptions")
    def add_sub(req: AddSubRequest):
        sub_id = service.add_subscription(req.title, req.detail_url, req.site_key)
        return {"ok": True, "sub_id": sub_id}

    @app.delete("/api/subscriptions/{sub_id}")
    def delete_sub(sub_id: int):
        return {"ok": service.delete_subscription(sub_id)}

    @app.post("/api/subscriptions/{sub_id}/check")
    def check_single_sub(sub_id: int):
        res = service.check_single_subscription(sub_id)
        return {"ok": True, "update": res}

    @app.post("/api/subscriptions/check_all")
    def check_all_subs():
        updates = service.check_all_subscriptions()
        return {"ok": True, "updates_count": len(updates), "updates": updates}

    # ------------------------------------------------------------ 发送下载
    @app.post("/api/download")
    def send_download(req: DownloadRequest):
        res = service.send_download(req.url, req.host_id, req.sub_id, req.ep_label, req.quality)
        if not res.get("ok"):
            raise HTTPException(400, res.get("message", "发送下载失败"))
        return res

    # ------------------------------------------------------------ 系统设置
    @app.get("/api/settings")
    def get_settings():
        from ..constants import DEFAULT_ENABLED_BLOCKS, app_data_dir
        return {
            "config": service.get_config(),
            "hosts": service.list_hosts(),
            "available_blocks": DEFAULT_ENABLED_BLOCKS,
            "data_dir": app_data_dir(),
        }

    @app.post("/api/settings/config")
    def update_config(payload: dict):
        return {"ok": True, "config": service.update_config(payload)}

    @app.post("/api/settings/emby_test")
    def test_emby(req: EmbyTestRequest):
        return service.test_emby(req.server_url, req.api_key)

    @app.post("/api/settings/host")
    def save_host(payload: dict):
        host_id = service.save_host(payload)
        return {"ok": True, "host_id": host_id}

    @app.post("/api/settings/host_activate")
    def activate_host(payload: dict):
        host_id = payload.get("id")
        if not host_id:
            raise HTTPException(400, "缺少 host_id")
        return {"ok": service.activate_host(int(host_id))}

    @app.delete("/api/settings/host/{host_id}")
    def delete_host(host_id: int):
        return {"ok": service.delete_host(host_id)}

    @app.post("/api/settings/host_test")
    def test_host(payload: dict):
        return service.test_host(payload)

    @app.post("/api/settings/reset_cache")
    def reset_cache():
        return {"ok": service.reset_cache()}

    # ------------------------------------------------------------ 前端静态页面
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    index_file = STATIC_DIR / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def index():
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h2>6vdown / C2Down Web Server 正在运行中</h2><p>Web 前端静态页面准备就绪中……</p>")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()

