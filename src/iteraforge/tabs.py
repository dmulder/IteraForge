from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .models import TabManifest, utc_now
from .paths import tabs_root
from .security import normalize_tab_id, reject_escaping_symlinks, resolve_inside, validate_tab_id
from .storage import get_schema_version, init_tab_db

GIT_ENV = {
    "GIT_AUTHOR_NAME": "IteraForge",
    "GIT_AUTHOR_EMAIL": "local-agent@localhost",
    "GIT_COMMITTER_NAME": "IteraForge",
    "GIT_COMMITTER_EMAIL": "local-agent@localhost",
}
GIT_ARTIFACT_PATHS = [
    ".cache",
    ".config",
    ".local",
    ".npm",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "tmp",
    "temp",
]


def tab_dir(tab_id: str) -> Path:
    validate_tab_id(tab_id)
    return tabs_root() / tab_id


def source_dir(tab_id: str) -> Path:
    return tab_dir(tab_id) / "source"


def data_dir(tab_id: str) -> Path:
    return tab_dir(tab_id) / "data"


def db_path(tab_id: str) -> Path:
    return data_dir(tab_id) / "tab.sqlite3"


def state_path(tab_id: str) -> Path:
    return tab_dir(tab_id) / "state.json"


def snapshots_dir(tab_id: str) -> Path:
    return tab_dir(tab_id) / "database-snapshots"


def logs_dir(tab_id: str) -> Path:
    return tab_dir(tab_id) / "logs"


def load_manifest(tab_id: str) -> TabManifest:
    manifest_path = source_dir(tab_id) / "tab.json"
    manifest = TabManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.id != tab_id:
        raise ValueError("manifest id must match tab directory")
    return manifest


def list_tabs() -> list[dict[str, Any]]:
    tabs_root().mkdir(parents=True, exist_ok=True)
    result: list[dict[str, Any]] = []
    for child in sorted(tabs_root().iterdir()):
        if not child.is_dir():
            continue
        try:
            manifest = load_manifest(child.name)
            state = load_state(child.name)
            result.append({**manifest.model_dump(), "state": state})
        except Exception as exc:
            result.append({"id": child.name, "title": child.name, "invalid": True, "error": str(exc)})
    return result


def load_state(tab_id: str) -> dict[str, Any]:
    path = state_path(tab_id)
    if not path.exists():
        return {
            "active_commit": None,
            "schema_version": get_schema_version(db_path(tab_id)) if db_path(tab_id).exists() else 1,
            "revisions": [],
            "automatic_improvement_enabled": True,
            "last_reviewed": None,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(tab_id: str, state: dict[str, Any]) -> None:
    path = state_path(tab_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="state", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def scaffold_tab(tab_id: str, title: str, description: str, prompt: str) -> None:
    tab_id = normalize_tab_id(tab_id)
    src = source_dir(tab_id)
    src.mkdir(parents=True, exist_ok=True)
    (src / "migrations").mkdir(exist_ok=True)
    manifest = TabManifest(id=tab_id, title=title, description=description, entrypoint="index.html", version=1, schema_version=1)
    (src / "tab.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (src / "index.html").write_text(_default_html(title), encoding="utf-8")
    (src / "style.css").write_text(_default_css(), encoding="utf-8")
    (src / "app.js").write_text(_default_js(), encoding="utf-8")
    (src / "migrations" / "0001-initial.json").write_text(
        json.dumps({"version": 1, "operations": [{"type": "ensure_json_records"}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (src / "AGENTS.md").write_text(_agents_md(title, description, prompt), encoding="utf-8")
    init_tab_db(db_path(tab_id), manifest.schema_version)
    for path in [snapshots_dir(tab_id), logs_dir(tab_id)]:
        path.mkdir(parents=True, exist_ok=True)
    ensure_git(src)
    commit(tab_id, "Initial tab scaffold\n\nReason: Create isolated tab project.\nSchema: 1 -> 1\nTrigger: create")


def ensure_git(src: Path) -> None:
    if not (src / ".git").exists():
        subprocess.run(["git", "init"], cwd=src, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "IteraForge"], cwd=src, check=True)
    subprocess.run(["git", "config", "user.email", "local-agent@localhost"], cwd=src, check=True)


def git_head(tab_id: str) -> str | None:
    src = source_dir(tab_id)
    if not (src / ".git").exists():
        return None
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip() if result.returncode == 0 else None


def commit(tab_id: str, message: str) -> str:
    src = source_dir(tab_id)
    ensure_git(src)
    subprocess.run(["git", "add", "--all", *git_source_pathspecs()], cwd=src, check=True, env={**os.environ, **GIT_ENV})
    status = subprocess.run(["git", "status", "--porcelain", *git_source_pathspecs()], cwd=src, check=True, text=True, stdout=subprocess.PIPE)
    if status.stdout.strip():
        subprocess.run(["git", "commit", "-m", message], cwd=src, check=True, env={**os.environ, **GIT_ENV}, stdout=subprocess.PIPE)
    head = git_head(tab_id)
    if not head:
        raise RuntimeError("git commit failed")
    manifest = load_manifest(tab_id)
    state = load_state(tab_id)
    revisions = state.setdefault("revisions", [])
    if not revisions or revisions[-1].get("commit") != head:
        revisions.append(
            {
                "commit": head,
                "timestamp": utc_now(),
                "schema_version": manifest.schema_version,
                "message": message.splitlines()[0],
                "snapshot": None,
            }
        )
    state["active_commit"] = head
    state["schema_version"] = manifest.schema_version
    save_state(tab_id, state)
    return head


def git_changed_files(tab_id: str, old_commit: str | None, new_commit: str | None) -> list[str]:
    if not old_commit or not new_commit:
        result = subprocess.run(["git", "ls-files"], cwd=source_dir(tab_id), text=True, stdout=subprocess.PIPE, check=True)
    else:
        result = subprocess.run(["git", "diff", "--name-only", old_commit, new_commit], cwd=source_dir(tab_id), text=True, stdout=subprocess.PIPE, check=True)
    return [line for line in result.stdout.splitlines() if line]


def git_source_pathspecs() -> list[str]:
    pathspecs = ["."]
    for path in GIT_ARTIFACT_PATHS:
        pathspecs.append(f":(exclude){path}")
        pathspecs.append(f":(exclude){path}/**")
    return pathspecs


def snapshot_database(tab_id: str, reason: str) -> str:
    db = db_path(tab_id)
    init_tab_db(db)
    snap_dir = snapshots_dir(tab_id)
    snap_dir.mkdir(parents=True, exist_ok=True)
    current_commit = git_head(tab_id)
    schema = get_schema_version(db)
    name = f"{utc_now().replace(':', '').replace('.', '-')}-{schema}.sqlite3"
    target = snap_dir / name
    source = sqlite3.connect(db)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    metadata = {
        "id": name,
        "timestamp": utc_now(),
        "reason": reason,
        "source_commit": current_commit,
        "schema_version": schema,
    }
    (snap_dir / f"{name}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return name


def restore_database(tab_id: str, snapshot_id: str) -> None:
    snap = snapshots_dir(tab_id) / snapshot_id
    resolve_inside(snapshots_dir(tab_id), snap)
    if not snap.exists():
        raise FileNotFoundError(snapshot_id)
    db = db_path(tab_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    for sidecar in [db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]:
        if sidecar.exists():
            sidecar.unlink()
    if db.exists():
        db.unlink()
    source = sqlite3.connect(snap)
    try:
        dest = sqlite3.connect(db)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def revision_history(tab_id: str) -> list[dict[str, Any]]:
    return load_state(tab_id).get("revisions", [])


def checkout_revision(tab_id: str, commit_hash: str, restore_snapshot: str | None = None) -> dict[str, Any]:
    state = load_state(tab_id)
    current_schema = get_schema_version(db_path(tab_id))
    target = next((rev for rev in state.get("revisions", []) if rev["commit"].startswith(commit_hash)), None)
    if not target:
        raise ValueError("unknown revision")
    if restore_snapshot:
        snapshot_database(tab_id, "pre-restore recovery")
        restore_database(tab_id, restore_snapshot)
    elif int(target["schema_version"]) != current_schema:
        raise ValueError("source-only restore rejected because schema versions are incompatible")
    subprocess.run(["git", "checkout", target["commit"], "--", "."], cwd=source_dir(tab_id), check=True)
    new_commit = commit(
        tab_id,
        f"Restore revision {target['commit'][:12]}\n\nReason: User restore.\nSchema: {current_schema} -> {get_schema_version(db_path(tab_id))}\nTrigger: restore",
    )
    return {"commit": new_commit, "restored_from": target["commit"]}


def validate_source_tree(tab_id: str) -> None:
    src = source_dir(tab_id)
    reject_escaping_symlinks(src)
    manifest = load_manifest(tab_id)
    if manifest.id != tab_id:
        raise ValueError("manifest id mismatch")
    entry = src / manifest.entrypoint
    resolve_inside(src, entry)
    if not entry.exists():
        raise ValueError("entrypoint does not exist")


def _default_html(title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="iteraforge-tab">
    <header>
      <h1>{title}</h1>
      <p>Local tab workspace</p>
    </header>
    <form data-action="create" data-collection="items">
      <input name="title" placeholder="Item" required>
      <input name="status" placeholder="Status">
      <button type="submit">Add</button>
    </form>
    <section data-render-list="items">
      <p class="muted" data-empty-state>No records yet.</p>
      <template data-record-template>
        <article class="record">
          <div>
            <strong>{{data.title}}</strong>
            <div class="muted">{{data.status}}</div>
          </div>
          <button type="button" data-action="delete" data-collection="items" data-record-id="{{id}}">Delete</button>
        </article>
      </template>
    </section>
  </main>
</body>
</html>
"""


def _default_css() -> str:
    return """.iteraforge-tab{max-width:920px;margin:0 auto;padding:24px;color:#1f2933;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.iteraforge-tab header{margin-bottom:18px}.iteraforge-tab h1{font-size:28px;margin:0 0 4px}.iteraforge-tab form{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}.iteraforge-tab input,.iteraforge-tab button{font:inherit;padding:10px;border:1px solid #b8c0cc;border-radius:6px}.iteraforge-tab button{min-height:36px;background:#1f6feb;color:white;border-color:#1f6feb;cursor:pointer}.iteraforge-tab .record{background:white;border:1px solid #d7dde5;border-radius:8px;padding:12px;margin:8px 0;display:flex;justify-content:space-between;gap:12px}.iteraforge-tab .muted{color:#5c6775}"""


def _default_js() -> str:
    return """// IteraForge loads this file as trusted same-page tab code.
// Declarative HTML bindings work without JavaScript, but custom tab behavior may be added here.
"""


def _agents_md(title: str, description: str, prompt: str) -> str:
    return f"""# {title}

Purpose: {description or "A workplace workflow tab created by IteraForge."}

Initial user request:
{prompt}

Storage contract:
- Use declarative HTML bindings such as `data-action`, `data-collection`, and `data-render-list`.
- Store user data through JSON record collections.
- Put custom same-page behavior in app.js when declarative bindings are not enough.

Style contract:
- Follow the IteraForge base app style: neutral light background, white panels, #d7dde5 borders, #1f6feb primary buttons, 6-8px radii, compact headings, and Inter/system UI typography.
- Keep all tab CSS scoped under the tab root class in index.html. Do not redefine global `:root`, `html`, `body`, `main`, `nav`, `footer`, headings, form controls, `*`, or base shell classes such as `.workspace`, `.brand`, `.sidebar`, `.toolbar`, `.panel`, or `.view`.
- Avoid standalone website shells, hero sections, tab-local top navigation, footer branding, custom design-token palettes, and page-level resets unless the user explicitly asks for a distinct website-like experience.
- Add custom styles only for workflow-specific layout or states that the base app does not already provide.

Security constraints:
- Do not read secrets, OpenCode configuration, other tabs, host files, or network resources unless the user explicitly asks.
- Prefer declarative bindings for routine record storage; use app.js for custom interactions when needed.
- Do not add external scripts, analytics, or third-party network calls.

Schema version: 1
Known problems: None recorded.
Potential future improvements: Improve workflow-specific fields, filters, summaries, and accessibility as requested.
"""
