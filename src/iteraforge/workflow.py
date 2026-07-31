from __future__ import annotations

import asyncio
import re
import json
import uuid
from typing import Any

from .activity import log_activity
from .events import EventBus
from .migrations import apply_migrations
from .models import JobRequest
from .paths import opencode_root, runtime_root
from .runner import AgentRunner, OpenCodeRunner
from .settings import load_settings
from .storage import get_schema_version
from .tabs import (
    checkout_revision,
    commit,
    db_path,
    git_changed_files,
    git_head,
    load_manifest,
    scaffold_tab,
    snapshot_database,
    source_dir,
    tab_dir,
    validate_source_tree,
)
from .security import normalize_tab_id
from .validation import validate_tab


class JobManager:
    def __init__(self, event_bus: EventBus, runner: AgentRunner | None = None) -> None:
        self.event_bus = event_bus
        self.runner = runner or OpenCodeRunner()
        self.jobs: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def list_jobs(self) -> list[dict[str, Any]]:
        return list(self.jobs.values())[::-1]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)

    async def submit(self, request: JobRequest, trigger: str = "user") -> dict[str, Any]:
        tab_hint = request.tab_id or normalize_tab_id(_title_from_prompt(request.prompt))
        fingerprint = job_fingerprint(request.mode, tab_hint, request.prompt, trigger)
        for existing in self.jobs.values():
            if existing.get("fingerprint") == fingerprint and existing.get("status") in {"queued", "running"}:
                return {**existing, "duplicate": True, "existing_job_id": existing["id"]}
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "mode": request.mode,
            "tab_id": tab_hint,
            "prompt": request.prompt,
            "trigger": trigger,
            "fingerprint": fingerprint,
            "duplicate": False,
            "status": "queued",
            "cancel_requested": False,
            "output": [],
            "validation_errors": [],
            "validation_warnings": [],
            "repair_attempts": 0,
            "changed_files": [],
        }
        self.jobs[job_id] = job
        asyncio.create_task(self._run_job(job))
        return job

    async def _run_job(self, job: dict[str, Any]) -> None:
        tab_id = job["tab_id"]
        lock = self._locks.setdefault(tab_id, asyncio.Lock())
        async with lock:
            if job.get("cancel_requested"):
                job["status"] = "cancelled"
                job["cancelled_at"] = time_now()
                await self.event_bus.publish({"type": "job-changed", "job_id": job["id"], "status": "cancelled"})
                log_activity("job-cancelled", "Queued job cancelled before execution", tab_id=tab_id, trigger=job["trigger"])
                return
            job["status"] = "running"
            await self.event_bus.publish({"type": "job-changed", "job_id": job["id"], "status": "running"})
            try:
                await asyncio.to_thread(self._execute_job_sync, job)
                action = "created" if job["mode"] == "create" else "updated"
                await self.event_bus.publish({"type": "tabs-changed", "tab_id": tab_id, "action": action})
                await self.event_bus.publish({"type": "job-changed", "job_id": job["id"], "status": job["status"]})
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = str(exc)
                log_activity("job-failed", str(exc), tab_id=tab_id, trigger=job["trigger"])
                await self.event_bus.publish({"type": "job-changed", "job_id": job["id"], "status": "failed"})

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        if job.get("status") in {"succeeded", "failed", "cancelled"}:
            return job
        job["cancel_requested"] = True
        if job.get("status") == "queued":
            job["status"] = "cancelled"
            job["cancelled_at"] = time_now()
            log_activity("job-cancelled", "Queued job cancelled", tab_id=job.get("tab_id"), trigger=job.get("trigger"))
        return job

    def _execute_job_sync(self, job: dict[str, Any]) -> None:
        preflight_error = self.runner.preflight()
        if preflight_error:
            raise RuntimeError(preflight_error)
        settings = load_settings()
        repair_limit = int(settings.get("repair_attempts", 3))
        tab_id = job["tab_id"]
        job.setdefault("repair_attempts", 0)
        job.setdefault("validation_errors", [])
        job.setdefault("validation_warnings", [])
        job.setdefault("changed_files", [])
        if job.get("cancel_requested"):
            job["status"] = "cancelled"
            return
        pre_commit = git_head(tab_id) if tab_dir(tab_id).exists() else None
        pre_schema = get_schema_version(db_path(tab_id)) if db_path(tab_id).exists() else 1
        snapshot_id = None
        if job["mode"] == "create" and not source_dir(tab_id).exists():
            scaffold_tab(tab_id, _title_from_prompt(job["prompt"]), job["prompt"][:240], job["prompt"])
        else:
            validate_source_tree(tab_id)
            snapshot_id = snapshot_database(tab_id, "pre-update")
        prompt = build_prompt(job)
        for attempt in range(repair_limit + 1):
            result = self.runner.run(
                prompt,
                source_dir(tab_id),
                {"OPENCODE_CONFIG_DIR": str(opencode_root())},
                lambda text: job["output"].append(text),
                int(settings.get("timeout_seconds", 900)),
                lambda: bool(job.get("cancel_requested")),
            )
            if result.cancelled or job.get("cancel_requested"):
                job["status"] = "cancelled"
                job["cancelled_at"] = time_now()
                log_activity("job-cancelled", "Running job cancelled", tab_id=tab_id, trigger=job["trigger"])
                return
            if not result.ok:
                job["validation_errors"] = [result.stderr or "agent failed"]
            else:
                report = validate_tab(tab_id)
                job["validation_errors"] = report.errors
                job["validation_warnings"] = report.limited_warnings()
                job["validation_ignored_paths"] = report.ignored_paths[:50]
                if not report.errors:
                    manifest = load_manifest(tab_id)
                    if manifest.schema_version != pre_schema:
                        snapshot_id = snapshot_id or snapshot_database(tab_id, "pre-migration")
                        apply_migrations(tab_id, manifest.schema_version)
                    new_commit = commit(
                        tab_id,
                        f"Automated improvement: {job['prompt'][:72]}\n\n"
                        f"Reason: {job['prompt'][:200]}\n"
                        f"Schema: {pre_schema} -> {manifest.schema_version}\n"
                        f"Trigger: {job['trigger']}",
                    )
                    job["status"] = "succeeded"
                    job["commit"] = new_commit
                    job["snapshot"] = snapshot_id
                    job["changed_files"] = git_changed_files(tab_id, pre_commit, new_commit)
                    log_activity(
                        "job-succeeded",
                        job["prompt"][:200],
                        tab_id=tab_id,
                        trigger=job["trigger"],
                        previous_commit=pre_commit,
                        new_commit=new_commit,
                        previous_schema=pre_schema,
                        new_schema=manifest.schema_version,
                        snapshot=snapshot_id,
                        files=job["changed_files"],
                        warnings=job["validation_warnings"],
                        ignored_paths=job["validation_ignored_paths"],
                    )
                    return
            if attempt < repair_limit:
                job["repair_attempts"] += 1
                log_activity("repair-attempt", "Validation failed; requesting repair", tab_id=tab_id, trigger=job["trigger"], errors=job["validation_errors"])
                prompt = build_repair_prompt(job, prompt)
        diagnostic = preserve_failed_tree(tab_id, job["id"])
        if snapshot_id:
            from .tabs import restore_database

            restore_database(tab_id, snapshot_id)
        job["status"] = "failed"
        job["diagnostic"] = diagnostic
        log_activity("job-failed", "All repair attempts failed", tab_id=tab_id, trigger=job["trigger"], errors=job["validation_errors"], diagnostic=diagnostic)

    def restore(self, tab_id: str, commit_hash: str, snapshot_id: str | None = None) -> dict[str, Any]:
        before = git_head(tab_id)
        recovery = snapshot_database(tab_id, "pre-restore")
        result = checkout_revision(tab_id, commit_hash, snapshot_id)
        log_activity("restore", "Restored tab revision", tab_id=tab_id, previous_commit=before, recovery_snapshot=recovery, result=result)
        return result


def build_prompt(job: dict[str, Any]) -> str:
    return f"""You are modifying one isolated IteraForge tab application.

User request:
{job['prompt']}

Rules:
- Work only in the current directory.
- Keep the app plain HTML, CSS, and JavaScript.
- Use declarative HTML bindings for storage: data-action, data-collection, data-render-list, data-record-id, and data-field.
- Generated tabs are trusted same-page applications. JavaScript is allowed and expected.
- Put custom JavaScript in app.js when the requested behavior needs it. The entrypoint may load it with <script src="app.js"></script>.
- Do not add external network resources.
- Do not read secrets, host files, OpenCode config, or other tabs.
- Update AGENTS.md after meaningful changes.
- Keep migrations declarative JSON.
"""


def build_repair_prompt(job: dict[str, Any], original: str) -> str:
    return f"""{original}

The previous implementation failed validation. Fix the existing implementation without starting over.

Validation errors:
{json.dumps(job['validation_errors'], indent=2)}
"""


def job_fingerprint(mode: str, tab_id: str, prompt: str, trigger: str) -> str:
    normalized_prompt = re.sub(r"\s+", " ", prompt).strip().casefold()
    return "|".join([mode, tab_id, trigger, normalized_prompt])


def time_now() -> str:
    from .models import utc_now

    return utc_now()


def preserve_failed_tree(tab_id: str, job_id: str) -> str:
    diagnostic_root = runtime_root() / "failed-jobs"
    diagnostic_root.mkdir(parents=True, exist_ok=True)
    target = diagnostic_root / f"{tab_id}-{job_id}"
    if target.exists():
        return str(target)
    import shutil

    shutil.copytree(source_dir(tab_id), target, ignore=shutil.ignore_patterns(".git"))
    return str(target)


def _title_from_prompt(prompt: str) -> str:
    lowered = prompt.lower()
    if "named " in lowered:
        after = prompt[lowered.index("named ") + 6 :]
        name = after.split(" where ")[0].split(" for ")[0].split(".")[0].strip()
        if name:
            return name[:80]
    words = [word.strip(".,:;!?") for word in prompt.split() if word.strip(".,:;!?")]
    if words[:3] and words[0].lower() in {"create", "add", "build"}:
        words = words[1:]
    return " ".join(words[:4]) or "New Tab"
