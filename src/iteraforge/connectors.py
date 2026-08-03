from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import CacheOptions, ConnectorAiRequest, ConnectorShellRequest, ConnectorWebRequest
from .paths import runtime_root
from .providers import run_prompt


def capabilities() -> dict[str, Any]:
    return {
        "web": {"methods": ["GET", "POST", "PUT", "PATCH", "DELETE"], "cache": True},
        "shell": {"interpreter": "bash", "container": True, "cache": True},
        "ai": {"cache": True},
        "cache": {"ttl": True, "namespaces": True},
    }


def web_request(tab_id: str, request: ConnectorWebRequest) -> dict[str, Any]:
    cache_key = _call_cache_key("web", request.model_dump(exclude={"cache"}), request.cache)
    if request.cache and not request.cache.refresh:
        cached = cache_get(tab_id, request.cache.namespace, cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}

    started = time.time()
    method = request.method.upper()
    headers = dict(request.headers)
    data = request.body.encode("utf-8") if request.body is not None else None
    req = urllib.request.Request(request.url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=request.timeout_seconds) as response:
            body = response.read()
            result = {
                "ok": 200 <= response.status < 400,
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": body.decode("utf-8", errors="replace"),
                "duration_ms": round((time.time() - started) * 1000),
                "cache_hit": False,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read()
        result = {
            "ok": False,
            "status": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": body.decode("utf-8", errors="replace"),
            "duration_ms": round((time.time() - started) * 1000),
            "cache_hit": False,
        }
    if request.cache:
        cache_set(tab_id, request.cache.namespace, cache_key, result, request.cache.ttl_seconds)
    return result


def shell_run(tab_id: str, request: ConnectorShellRequest) -> dict[str, Any]:
    cache_key = _call_cache_key("shell", request.model_dump(exclude={"cache"}), request.cache)
    if request.cache and not request.cache.refresh:
        cached = cache_get(tab_id, request.cache.namespace, cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}

    started = time.time()
    cwd = Path(request.cwd).expanduser() if request.cwd else runtime_root()
    if not cwd.exists() or not cwd.is_dir():
        cwd = runtime_root()
    env = {**os.environ, **request.env}
    proc = subprocess.run(
        ["bash", "-lc", request.script],
        cwd=cwd,
        env=env,
        input=request.stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=request.timeout_seconds,
        check=False,
    )
    result = {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_ms": round((time.time() - started) * 1000),
        "cache_hit": False,
    }
    if request.cache:
        cache_set(tab_id, request.cache.namespace, cache_key, result, request.cache.ttl_seconds)
    return result


def ai_prompt(tab_id: str, request: ConnectorAiRequest) -> dict[str, Any]:
    cache_key = _call_cache_key("ai", request.model_dump(exclude={"cache"}), request.cache)
    if request.cache and not request.cache.refresh:
        cached = cache_get(tab_id, request.cache.namespace, cache_key)
        if cached is not None:
            return {**cached, "cache_hit": True}

    started = time.time()
    result = run_prompt(
        prompt=request.prompt,
        system=request.system,
        provider=request.provider,
        model=request.model,
        timeout=request.timeout_seconds,
        context=request.context,
    )
    payload = {
        **result,
        "duration_ms": round((time.time() - started) * 1000),
        "cache_hit": False,
    }
    if request.cache:
        cache_set(tab_id, request.cache.namespace, cache_key, payload, request.cache.ttl_seconds)
    return payload


def cache_get(tab_id: str, namespace: str, key: str) -> Any | None:
    data = _read_cache(tab_id)
    item = data.get(namespace, {}).get(key)
    if not item:
        return None
    expires_at = item.get("expires_at")
    if expires_at is not None and expires_at < time.time():
        data.get(namespace, {}).pop(key, None)
        _write_cache(tab_id, data)
        return None
    return item.get("value")


def cache_set(tab_id: str, namespace: str, key: str, value: Any, ttl_seconds: int | None = None) -> dict[str, Any]:
    data = _read_cache(tab_id)
    bucket = data.setdefault(namespace, {})
    bucket[key] = {
        "value": value,
        "created_at": time.time(),
        "expires_at": time.time() + ttl_seconds if ttl_seconds else None,
    }
    _write_cache(tab_id, data)
    return {"stored": True, "namespace": namespace, "key": key}


def cache_delete(tab_id: str, namespace: str, key: str) -> dict[str, Any]:
    data = _read_cache(tab_id)
    deleted = data.get(namespace, {}).pop(key, None) is not None
    _write_cache(tab_id, data)
    return {"deleted": deleted, "namespace": namespace, "key": key}


def cache_clear(tab_id: str, namespace: str | None = None) -> dict[str, Any]:
    data = _read_cache(tab_id)
    if namespace:
        count = len(data.get(namespace, {}))
        data.pop(namespace, None)
    else:
        count = sum(len(bucket) for bucket in data.values() if isinstance(bucket, dict))
        data = {}
    _write_cache(tab_id, data)
    return {"cleared": count, "namespace": namespace}


def _call_cache_key(kind: str, payload: dict[str, Any], cache: CacheOptions | None) -> str:
    if cache and cache.key:
        return cache.key
    encoded = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cache_path(tab_id: str) -> Path:
    return runtime_root() / "connectors" / tab_id / "cache.json"


def _read_cache(tab_id: str) -> dict[str, Any]:
    path = _cache_path(tab_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_cache(tab_id: str, data: dict[str, Any]) -> None:
    path = _cache_path(tab_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="cache", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
