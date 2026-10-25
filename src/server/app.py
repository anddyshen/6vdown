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
    title: str = ""
    raw_label: str = ""


class EmbyTestRequest(BaseModel):
    server_url: str
    api_key: str


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


class VerifyRequest(BaseModel):
    token: str = ""


def create_app() -> FastAPI:
    app = FastAPI(title="6Vdown Web Server", version="1.0.4")

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
    active_sessions: set[str] = set()

    def _get_auth_creds():
        username = (
            os.environ.get("C2DOWN_WEB_USERNAME")
            or os.environ.get("C2DOWN_USERNAME")
            or service.cfg.get("web_username")
            or "admin"
        ).strip()
        password = (
            os.environ.get("C2DOWN_WEB_PASSWORD")
            or os.environ.get("C2DOWN_PASSWORD")
            or service.cfg.get("web_password")
            or ""
        ).strip()
        api_token = (
            os.environ.get("C2DOWN_API_TOKEN")
            or service.cfg.get("api_token")
            or ""
        ).strip()
        return username, password, api_token

    # 安全鉴权中间件（当配置了密码/Token 或环境变量时强制校验）
    @app.middleware("http")
    async def token_auth_middleware(request, call_next):
        path = request.url.path
        # 静态资源、根路径和鉴权登录接口放行
        if not path.startswith("/api/") or path in ("/api/auth/verify", "/api/auth/login", "/api/auth/logout"):
            return await call_next(request)

        username, password, api_token = _get_auth_creds()
        auth_required = bool(password or api_token)
        if not auth_required:
            return await call_next(request)

        # 获取请求携带的 Token：优先 X-API-Token，其次 Bearer Token，再次 URL 参数 ?token=
        token = request.headers.get("X-API-Token") or ""
        if not token:
            auth_val = request.headers.get("Authorization") or ""
            if auth_val.lower().startswith("bearer "):
                token = auth_val[7:].strip()
        if not token:
            token = request.query_params.get("token") or ""

        is_valid = False
        if token:
            if token in active_sessions:
                is_valid = True
            elif api_token and token == api_token:
                is_valid = True
            elif password and token == password:
                is_valid = True

        if not is_valid:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"ok": False, "error": "Unauthorized: 未授权访问，请先登录后台"},
            )

        return await call_next(request)

    # ------------------------------------------------------------ 鉴权与登录接口
    @app.post("/api/auth/login")
    def auth_login(req: LoginRequest):
        username, password, api_token = _get_auth_creds()
        auth_required = bool(password or api_token)
        if not auth_required:
            return {"ok": True, "token": "anonymous", "username": username or "admin", "auth_required": False}

        # 校验用户名与密码
        match_user = (req.username.strip() == username) or (not password and api_token)
        match_pass = (password and req.password == password) or (api_token and req.password == api_token)
        if match_user and match_pass:
            import secrets
            session_token = secrets.token_hex(24)
            active_sessions.add(session_token)
            return {"ok": True, "token": session_token, "username": username, "auth_required": True}
        return {"ok": False, "error": "用户名或密码错误", "auth_required": True}

    @app.post("/api/auth/verify")
    def verify_auth(req: Optional[VerifyRequest] = None):
        username, password, api_token = _get_auth_creds()
        auth_required = bool(password or api_token)
        if not auth_required:
            return {"ok": True, "auth_required": False, "token_required": False, "version": "1.0.4"}

        token = (req.token if req else "") or ""
        is_valid = False
        if token:
            if token in active_sessions or (api_token and token == api_token) or (password and token == password):
                is_valid = True

        return {
            "ok": is_valid,
            "auth_required": True,
            "token_required": True,
            "username": username if is_valid else "",
            "version": "1.0.4",
        }

    @app.post("/api/auth/logout")
    def auth_logout(req: Optional[VerifyRequest] = None):
        token = (req.token if req else "") or ""
        if token in active_sessions:
            active_sessions.discard(token)
        return {"ok": True}

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

    @app.get("/api/workbench/incremental")
    def get_incremental():
        return service.get_latest_incremental()

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
        res = service.send_download(
            req.url,
            host_id=req.host_id,
            sub_id=req.sub_id,
            ep_label=req.ep_label,
            quality=req.quality,
            title=req.title,
            raw_label=req.raw_label,
        )
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

    # ------------------------------------------------------------ 系统与操作日志
    @app.get("/api/logs")
    def get_logs(category: str = "", keyword: str = "", limit: int = 200):
        return {"ok": True, "logs": service.db.list_operation_logs(limit=limit, category=category, keyword=keyword)}

    @app.post("/api/logs/clear")
    def clear_logs():
        service.db.clear_operation_logs()
        return {"ok": True}

    # ------------------------------------------------------------ 前端静态页面与 PWA
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    index_file = STATIC_DIR / "index.html"

    @app.get("/manifest.json")
    def manifest():
        manifest_path = STATIC_DIR / "manifest.json"
        if manifest_path.exists():
            return FileResponse(manifest_path, media_type="application/manifest+json")
        raise HTTPException(404)

    @app.get("/sw.js")
    def service_worker():
        sw_path = STATIC_DIR / "sw.js"
        if sw_path.exists():
            return FileResponse(sw_path, media_type="application/javascript")
        raise HTTPException(404)

    @app.get("/", response_class=HTMLResponse)
    def index():
        if index_file.exists():
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return HTMLResponse("<h2>6vdown / C2Down Web Server 正在运行中</h2><p>Web 前端静态页面准备就绪中……</p>")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()

