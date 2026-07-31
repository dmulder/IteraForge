from __future__ import annotations

import re
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

SAFE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_tab_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)[:63].strip("-")
    if not slug:
        raise ValueError("tab id must contain at least one alphanumeric character")
    validate_tab_id(slug)
    return slug


def validate_tab_id(value: str) -> None:
    if not SAFE_ID_RE.fullmatch(value):
        raise ValueError("tab id must be a lowercase slug")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError("tab id must not contain separators or traversal")


def resolve_inside(root: Path, candidate: Path) -> Path:
    root_real = root.resolve()
    resolved = candidate.resolve()
    if resolved != root_real and root_real not in resolved.parents:
        raise ValueError(f"path escapes root: {candidate}")
    return resolved


def reject_escaping_symlinks(root: Path) -> None:
    root_real = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            target = path.resolve()
            if target != root_real and root_real not in target.parents:
                raise ValueError(f"symlink escapes tab source: {path}")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def require_base_auth(request: Request) -> None:
    expected = request.app.state.base_token
    header = request.headers.get("x-iteraforge-token")
    cookie = request.cookies.get("iteraforge_session")
    if header != expected and cookie != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def reject_bad_origin(request: Request) -> None:
    host = request.headers.get("host", "")
    if host and not (
        host.startswith("127.0.0.1:")
        or host.startswith("localhost:")
        or host == "testserver"
    ):
        raise HTTPException(status_code=400, detail="invalid host")
    origin = request.headers.get("origin")
    if origin and not (origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")):
        raise HTTPException(status_code=403, detail="invalid origin")
