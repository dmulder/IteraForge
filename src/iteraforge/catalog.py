from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import TabManifest
from .security import normalize_tab_id, resolve_inside, validate_tab_id
from .storage import init_tab_db
from .tabs import commit, db_path, ensure_git, load_manifest, save_state, snapshots_dir, source_dir
from .validation import validate_tab


def catalog_root() -> Path:
    return Path(__file__).parent / "community_tabs"


def list_catalog_tabs() -> list[dict[str, Any]]:
    root = catalog_root()
    if not root.exists():
        return []
    result = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "tab.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = TabManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            result.append({**manifest.model_dump(), "template_id": child.name})
        except Exception as exc:
            result.append({"template_id": child.name, "invalid": True, "error": str(exc)})
    return result


def install_catalog_tab(template_id: str, tab_id: str | None = None) -> dict[str, Any]:
    validate_tab_id(template_id)
    source = catalog_root() / template_id
    resolve_inside(catalog_root(), source)
    if not source.exists() or not source.is_dir():
        raise ValueError("unknown catalog template")
    manifest = TabManifest.model_validate_json((source / "tab.json").read_text(encoding="utf-8"))
    target_id = normalize_tab_id(tab_id or manifest.id)
    target = source_dir(target_id)
    if target.exists():
        raise ValueError("tab already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "node_modules", ".cache"))
    manifest_data = json.loads((target / "tab.json").read_text(encoding="utf-8"))
    manifest_data["id"] = target_id
    (target / "tab.json").write_text(json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    copied_manifest = load_manifest(target_id)
    init_tab_db(db_path(target_id), copied_manifest.schema_version)
    snapshots_dir(target_id).mkdir(parents=True, exist_ok=True)
    provenance = {
        "template_id": template_id,
        "template_title": manifest.title,
        "installed_from": "bundled-community-catalog",
    }
    save_state(
        target_id,
        {
            "active_commit": None,
            "schema_version": copied_manifest.schema_version,
            "revisions": [],
            "automatic_improvement_enabled": True,
            "last_reviewed": None,
            "catalog_provenance": provenance,
        },
    )
    ensure_git(target)
    report = validate_tab(target_id)
    if report.errors:
        shutil.rmtree(target.parent)
        raise ValueError("; ".join(report.errors))
    commit(target_id, f"Install catalog tab {template_id}\n\nReason: Install bundled community tab.\nSchema: {copied_manifest.schema_version} -> {copied_manifest.schema_version}")
    return {"installed": True, "tab_id": target_id, "template_id": template_id, "provenance": provenance}


def write_catalog_index() -> None:
    root = catalog_root()
    root.mkdir(parents=True, exist_ok=True)
    index = {"templates": [item for item in list_catalog_tabs() if not item.get("invalid")]}
    (root / "catalog.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
