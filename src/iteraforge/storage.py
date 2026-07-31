from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import utc_now


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_tab_db(path: Path, schema_version: int = 1) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
              id TEXT PRIMARY KEY,
              collection TEXT NOT NULL,
              data TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_collection ON records(collection)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)",
            (str(schema_version),),
        )


def get_schema_version(path: Path) -> int:
    init_tab_db(path)
    with connect(path) as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 1


def set_schema_version(path: Path, version: int) -> None:
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(version),),
        )


def create_record(path: Path, collection: str, data: dict[str, Any]) -> dict[str, Any]:
    init_tab_db(path)
    now = utc_now()
    record_id = str(uuid.uuid4())
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO records(id, collection, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (record_id, collection, json.dumps(data, sort_keys=True), now, now),
        )
    return {"id": record_id, "collection": collection, "data": data, "created_at": now, "updated_at": now}


def list_records(path: Path, collection: str) -> list[dict[str, Any]]:
    init_tab_db(path)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM records WHERE collection=? ORDER BY updated_at DESC", (collection,)
        ).fetchall()
    return [_row(row) for row in rows]


def get_record(path: Path, collection: str, record_id: str) -> dict[str, Any] | None:
    init_tab_db(path)
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM records WHERE collection=? AND id=?", (collection, record_id)
        ).fetchone()
    return _row(row) if row else None


def update_record(path: Path, collection: str, record_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    init_tab_db(path)
    now = utc_now()
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE records SET data=?, updated_at=? WHERE collection=? AND id=?",
            (json.dumps(data, sort_keys=True), now, collection, record_id),
        )
        if cur.rowcount == 0:
            return None
    return get_record(path, collection, record_id)


def delete_record(path: Path, collection: str, record_id: str) -> bool:
    init_tab_db(path)
    with connect(path) as conn:
        cur = conn.execute("DELETE FROM records WHERE collection=? AND id=?", (collection, record_id))
        return cur.rowcount > 0


def collections(path: Path) -> list[str]:
    init_tab_db(path)
    with connect(path) as conn:
        rows = conn.execute("SELECT DISTINCT collection FROM records ORDER BY collection").fetchall()
    return [row["collection"] for row in rows]


def query_records(
    path: Path,
    collection: str,
    filters: dict[str, Any],
    sort: str | None,
    descending: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    records = list_records(path, collection)
    for key, value in filters.items():
        records = [record for record in records if record["data"].get(key) == value]
    if sort:
        records.sort(key=lambda record: record["data"].get(sort) or "", reverse=descending)
    return records[offset : offset + limit]


def integrity_check(path: Path) -> None:
    init_tab_db(path)
    with connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise ValueError(f"sqlite integrity check failed: {row[0] if row else 'no result'}")


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "collection": row["collection"],
        "data": json.loads(row["data"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
