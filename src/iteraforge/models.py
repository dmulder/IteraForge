from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .security import validate_tab_id


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class TabManifest(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    entrypoint: str = "index.html"
    version: int = Field(ge=1)
    schema_version: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        validate_tab_id(value)
        return value

    @field_validator("entrypoint")
    @classmethod
    def valid_entrypoint(cls, value: str) -> str:
        if value.startswith("/") or "\\" in value or ".." in value or "/" in value:
            raise ValueError("entrypoint must be a single safe file name")
        if not value.endswith(".html"):
            raise ValueError("entrypoint must be an HTML file")
        return value


class RuntimeToken(BaseModel):
    token: str
    tab_id: str
    expires_at: float


class RecordIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: dict[str, Any] | None = None


class RecordOut(BaseModel):
    id: str
    collection: str
    data: dict[str, Any]
    created_at: str
    updated_at: str


class QueryRequest(BaseModel):
    collection: str
    filters: dict[str, Any] = Field(default_factory=dict)
    sort: str | None = None
    descending: bool = False
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class CacheOptions(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=120)
    key: str | None = Field(default=None, max_length=500)
    ttl_seconds: int | None = Field(default=None, ge=1)
    refresh: bool = False


class ConnectorWebRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    cache: CacheOptions | None = None


class ConnectorShellRequest(BaseModel):
    script: str = Field(min_length=1, max_length=20000)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    stdin: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    cache: CacheOptions | None = None


class ConnectorAiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    system: str | None = Field(default=None, max_length=8000)
    provider: str | None = None
    model: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=120, ge=1, le=900)
    cache: CacheOptions | None = None


class CacheRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=120)
    key: str | None = Field(default=None, min_length=1, max_length=500)
    value: Any = None
    ttl_seconds: int | None = Field(default=None, ge=1)


class ActivityEntry(BaseModel):
    id: str
    timestamp: str = Field(default_factory=utc_now)
    kind: str
    tab_id: str | None = None
    trigger: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class JobRequest(BaseModel):
    mode: Literal["create", "modify"]
    prompt: str = Field(min_length=1, max_length=8000)
    tab_id: str | None = None


class SettingsUpdate(BaseModel):
    agent_provider: str | None = None
    provider: str | None = None
    api_base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    opencode_command: str | None = None
    safe_args: list[str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=10, le=7200)
    repair_attempts: int | None = Field(default=None, ge=0, le=10)
    app_port: int | None = Field(default=None, ge=1024, le=65535)
    automatic_improvement_enabled: bool | None = None
    improvement_interval_minutes: int | None = Field(default=None, ge=15)
    browser_command: str | None = None
