from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .activity import list_activity, log_activity
from .events import EventBus
from .models import JobRequest, QueryRequest, RecordIn, SettingsUpdate
from .paths import ensure_base_dirs, opencode_root
from .render import render_payload
from .security import new_token, reject_bad_origin, require_base_auth, validate_tab_id
from .settings import import_existing_opencode_config, public_settings, save_settings
from .storage import (
    collections,
    create_record,
    delete_record,
    get_record,
    get_schema_version,
    list_records,
    query_records,
    update_record,
)
from .tabs import db_path, list_tabs, load_manifest, revision_history, source_dir
from .workflow import JobManager


def create_app() -> FastAPI:
    ensure_base_dirs()
    app = FastAPI(title="IteraForge")
    app.state.base_token = new_token()
    app.state.runtime_tokens = {}
    app.state.event_bus = EventBus()
    app.state.jobs = JobManager(app.state.event_bus)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    def _runtime_tab(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing runtime token")
        token = authorization.removeprefix("Bearer ").strip()
        item = app.state.runtime_tokens.get(token)
        if not item or item["expires_at"] < time.time():
            raise HTTPException(status_code=401, detail="invalid runtime token")
        return item["tab_id"]

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        reject_bad_origin(request)
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(response: Response):
        response.set_cookie("iteraforge_session", app.state.base_token, httponly=True, samesite="strict")
        html = (static / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", app.state.base_token)
        return HTMLResponse(html)

    @app.get("/api/tabs")
    def api_tabs(_: None = Depends(require_base_auth)):
        return {"tabs": list_tabs()}

    @app.post("/api/tabs/{tab_id}/runtime-token")
    def runtime_token(tab_id: str, _: None = Depends(require_base_auth)):
        validate_tab_id(tab_id)
        token = new_token()
        app.state.runtime_tokens[token] = {"tab_id": tab_id, "expires_at": time.time() + 3600}
        return {"token": token, "expires_at": app.state.runtime_tokens[token]["expires_at"]}

    @app.get("/api/tabs/{tab_id}/render")
    def render_tab(tab_id: str, _: None = Depends(require_base_auth)):
        validate_tab_id(tab_id)
        token = new_token()
        app.state.runtime_tokens[token] = {"tab_id": tab_id, "expires_at": time.time() + 3600}
        try:
            return render_payload(tab_id, token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/tabs/{tab_id}/")
    def serve_tab(tab_id: str, file: str | None = None):
        return _serve_tab_file(tab_id, file)

    @app.get("/tabs/{tab_id}/{file}")
    def serve_tab_asset(tab_id: str, file: str):
        return _serve_tab_file(tab_id, file)

    def _serve_tab_file(tab_id: str, file: str | None = None):
        validate_tab_id(tab_id)
        manifest = load_manifest(tab_id)
        entry = file or manifest.entrypoint
        if "/" in entry or "\\" in entry or ".." in entry:
            raise HTTPException(status_code=400, detail="invalid file")
        path = source_dir(tab_id) / entry
        if not path.exists():
            raise HTTPException(status_code=404, detail="not found")
        response = FileResponse(path)
        _tab_headers(response)
        return response

    @app.get("/api/runtime/collections")
    def runtime_collections(tab_id: str = Depends(_runtime_tab)):
        return {"collections": collections(db_path(tab_id))}

    @app.get("/api/runtime/schema")
    def runtime_schema(tab_id: str = Depends(_runtime_tab)):
        return {"schema_version": get_schema_version(db_path(tab_id)), "collections": collections(db_path(tab_id))}

    @app.get("/api/runtime/records/{collection}")
    def runtime_list(collection: str, tab_id: str = Depends(_runtime_tab)):
        return {"records": list_records(db_path(tab_id), collection)}

    @app.post("/api/runtime/records/{collection}")
    def runtime_create(collection: str, payload: RecordIn, tab_id: str = Depends(_runtime_tab)):
        return create_record(db_path(tab_id), collection, payload.data if payload.data is not None else payload.model_extra)

    @app.get("/api/runtime/records/{collection}/{record_id}")
    def runtime_get(collection: str, record_id: str, tab_id: str = Depends(_runtime_tab)):
        record = get_record(db_path(tab_id), collection, record_id)
        if not record:
            raise HTTPException(status_code=404, detail="not found")
        return record

    @app.put("/api/runtime/records/{collection}/{record_id}")
    def runtime_update(collection: str, record_id: str, payload: RecordIn, tab_id: str = Depends(_runtime_tab)):
        record = update_record(db_path(tab_id), collection, record_id, payload.data if payload.data is not None else payload.model_extra)
        if not record:
            raise HTTPException(status_code=404, detail="not found")
        return record

    @app.delete("/api/runtime/records/{collection}/{record_id}")
    def runtime_delete(collection: str, record_id: str, tab_id: str = Depends(_runtime_tab)):
        return {"deleted": delete_record(db_path(tab_id), collection, record_id)}

    @app.post("/api/runtime/query")
    def runtime_query(query: QueryRequest, tab_id: str = Depends(_runtime_tab)):
        return {
            "records": query_records(
                db_path(tab_id),
                query.collection,
                query.filters,
                query.sort,
                query.descending,
                query.limit,
                query.offset,
            )
        }

    @app.post("/api/tasks")
    async def submit_task(job: JobRequest, _: None = Depends(require_base_auth)):
        return await app.state.jobs.submit(job)

    @app.get("/api/tasks")
    def jobs(_: None = Depends(require_base_auth)):
        return {"jobs": app.state.jobs.list_jobs()}

    @app.post("/api/tasks/{job_id}/cancel")
    async def cancel_job(job_id: str, _: None = Depends(require_base_auth)):
        job = app.state.jobs.cancel(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="not found")
        await app.state.event_bus.publish({"type": "job-changed", "job_id": job_id, "status": job["status"]})
        return job

    @app.get("/api/activity")
    def activity(_: None = Depends(require_base_auth)):
        return {"activity": list_activity()}

    @app.get("/api/tabs/{tab_id}/revisions")
    def revisions(tab_id: str, _: None = Depends(require_base_auth)):
        return {"revisions": revision_history(tab_id)}

    @app.post("/api/tabs/{tab_id}/restore")
    async def restore(tab_id: str, payload: dict[str, Any], _: None = Depends(require_base_auth)):
        result = app.state.jobs.restore(tab_id, payload["commit"], payload.get("snapshot"))
        await app.state.event_bus.publish({"type": "tabs-changed", "tab_id": tab_id, "action": "restored"})
        return result

    @app.get("/api/settings")
    def settings(_: None = Depends(require_base_auth)):
        data = public_settings()
        data["opencode_config_path"] = str(opencode_root())
        return data

    @app.put("/api/settings")
    def update_settings(payload: SettingsUpdate, _: None = Depends(require_base_auth)):
        data = save_settings(payload.model_dump(exclude_unset=True))
        log_activity("settings", "Settings updated")
        return data

    @app.post("/api/settings/import-opencode")
    def import_opencode(payload: dict[str, Any] | None = None, _: None = Depends(require_base_auth)):
        payload = payload or {}
        result = import_existing_opencode_config(
            Path(payload["source"]) if payload.get("source") else None,
            bool(payload.get("overwrite", False)),
        )
        log_activity("settings", "Imported existing OpenCode configuration", result=result)
        return result

    @app.get("/api/events")
    async def events(_: None = Depends(require_base_auth)):
        return StreamingResponse(app.state.event_bus.stream(), media_type="text/event-stream")

    return app


def _tab_headers(response: Response) -> None:
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self' http://127.0.0.1:* http://localhost:*; form-action 'none'; base-uri 'none'"
    )
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
