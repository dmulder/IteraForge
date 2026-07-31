from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .models import ActivityEntry
from .paths import activity_root


def activity_file() -> Path:
    activity_root().mkdir(parents=True, exist_ok=True)
    return activity_root() / "events.jsonl"


def log_activity(kind: str, summary: str, tab_id: str | None = None, trigger: str | None = None, **details: Any) -> ActivityEntry:
    entry = ActivityEntry(id=str(uuid.uuid4()), kind=kind, summary=summary, tab_id=tab_id, trigger=trigger, details=details)
    with activity_file().open("a", encoding="utf-8") as fh:
        fh.write(entry.model_dump_json() + "\n")
    return entry


def list_activity(limit: int = 200) -> list[dict[str, Any]]:
    path = activity_file()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[-limit:][::-1]
