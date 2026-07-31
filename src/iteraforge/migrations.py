from __future__ import annotations

import json
from pathlib import Path

from .storage import get_schema_version, integrity_check, set_schema_version
from .tabs import db_path, source_dir


def migration_files(tab_id: str) -> list[Path]:
    mig_dir = source_dir(tab_id) / "migrations"
    if not mig_dir.exists():
        return []
    return sorted(mig_dir.glob("*.json"))


def validate_migrations(tab_id: str) -> None:
    expected = 1
    for path in migration_files(tab_id):
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = int(payload["version"])
        if version != expected:
            raise ValueError(f"migration {path.name} has version {version}, expected {expected}")
        for op in payload.get("operations", []):
            if op.get("type") not in {"ensure_json_records", "add_collection_metadata", "add_index_metadata", "set_schema_version"}:
                raise ValueError(f"unsupported migration operation in {path.name}: {op.get('type')}")
        expected += 1


def apply_migrations(tab_id: str, target_version: int) -> None:
    current = get_schema_version(db_path(tab_id))
    if target_version < current:
        raise ValueError("reverse migrations are not supported")
    validate_migrations(tab_id)
    for path in migration_files(tab_id):
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = int(payload["version"])
        if current < version <= target_version:
            # Current v1 migrations are declarative metadata only; JSON record storage schema is stable.
            set_schema_version(db_path(tab_id), version)
    set_schema_version(db_path(tab_id), target_version)
    integrity_check(db_path(tab_id))
