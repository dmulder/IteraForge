from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from iteraforge.app import create_app
from iteraforge.catalog import list_catalog_tabs
from iteraforge.connectors import cache_get, cache_set, shell_run
from iteraforge.events import EventBus
from iteraforge.models import ConnectorShellRequest, JobRequest
from iteraforge.providers import choose_default_provider, import_provider_configs, list_providers, provider_config_root, run_prompt
from iteraforge.render import render_payload, sanitize_html
from iteraforge.runner import FakeAgentRunner, OpenCodeRunner, RunnerResult
from iteraforge.security import new_token, require_base_auth, resolve_inside, validate_tab_id
from iteraforge.settings import (
    credential_environment,
    import_existing_opencode_config,
    load_settings,
    save_settings,
)
from iteraforge.storage import create_record, get_schema_version, list_records
from iteraforge.tabs import (
    checkout_revision,
    commit,
    db_path,
    git_head,
    load_state,
    scaffold_tab,
    snapshot_database,
    source_dir,
    tab_dir,
)
from iteraforge.validation import validate_tab
from iteraforge.workflow import JobManager
from iteraforge.workflow import build_prompt


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ITERAFORGE_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("ITERAFORGE_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    yield tmp_path


def subprocess_run_git(tab_id: str, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=source_dir(tab_id), check=True, text=True, stdout=subprocess.PIPE)
    return result.stdout


def test_runtime_crud_and_persistence():
    scaffold_tab("project-risks", "Project Risks", "desc", "prompt")
    db = db_path("project-risks")
    record = create_record(db, "risks", {"title": "A"})
    assert list_records(db, "risks")[0]["id"] == record["id"]
    assert list_records(db, "risks")[0]["data"]["title"] == "A"


def test_tabs_use_distinct_databases_and_tokens_are_scoped():
    scaffold_tab("one", "One", "", "")
    scaffold_tab("two", "Two", "", "")
    create_record(db_path("one"), "items", {"name": "one"})
    create_record(db_path("two"), "items", {"name": "two"})
    assert list_records(db_path("one"), "items")[0]["data"]["name"] == "one"
    assert list_records(db_path("two"), "items")[0]["data"]["name"] == "two"
    assert db_path("one") != db_path("two")
    tokens = {new_token(): "one", new_token(): "two"}
    assert len(set(tokens)) == 2
    assert set(tokens.values()) == {"one", "two"}


def test_tab_token_cannot_call_privileged_api():
    app = create_app()
    app.state.base_token = "base"
    with pytest.raises(HTTPException):
        require_base_auth(
            SimpleNamespace(
                app=app,
                headers=Headers({"x-iteraforge-token": "runtime"}),
                cookies={},
            )
        )


def test_invalid_manifest_path_traversal_and_symlink_rejected(tmp_path):
    with pytest.raises(ValueError):
        validate_tab_id("../../bad")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        resolve_inside(root, tmp_path / "outside")
    scaffold_tab("safe", "Safe", "", "")
    (source_dir("safe") / "tab.json").write_text(json.dumps({"id": "../bad", "title": "x", "entrypoint": "index.html", "version": 1, "schema_version": 1}), encoding="utf-8")
    report = validate_tab("safe")
    assert report.errors


def test_validation_ignores_tool_artifacts_and_warns_without_errors():
    scaffold_tab("artifacts", "Artifacts", "", "")
    cache = source_dir("artifacts") / ".npm" / "_cacache"
    cache.mkdir(parents=True)
    (cache / "blob").write_text("https://registry.example.invalid\n" * 100, encoding="utf-8")
    (source_dir("artifacts") / "app.js").write_text("function broken() {\n", encoding="utf-8")

    report = validate_tab("artifacts")

    assert report.errors == []
    assert any(path == ".npm" for path in report.ignored_paths)
    assert any("unbalanced braces" in warning for warning in report.warnings)
    assert not any(".npm/_cacache/blob" in warning for warning in report.warnings)


def test_validation_allows_trusted_tab_runtime_capabilities():
    scaffold_tab("trusted", "Trusted", "", "")
    (source_dir("trusted") / "app.js").write_text(
        """
localStorage.setItem("x", "y");
window.IteraForgeRuntime.connectors.web.request({url: "https://example.com"});
window.IteraForgeRuntime.connectors.shell.run({script: "date"});
""",
        encoding="utf-8",
    )

    report = validate_tab("trusted")

    assert report.errors == []
    assert not any("https?" in warning for warning in report.warnings)
    assert not any("localStorage" in warning for warning in report.warnings)
    assert not any("IteraForgeRuntime" in warning for warning in report.warnings)


def test_validation_warns_for_reload_unsafe_tab_javascript():
    scaffold_tab("reload-risk", "Reload Risk", "", "")
    (source_dir("reload-risk") / "app.js").write_text(
        """
const state = new Map();
document.addEventListener("click", () => state.clear());
""",
        encoding="utf-8",
    )

    report = validate_tab("reload-risk")

    assert report.errors == []
    assert any("same-page tab reloads" in warning for warning in report.warnings)
    assert any("IteraForgeTabCleanup" in warning for warning in report.warnings)


def test_commit_excludes_tool_artifacts():
    scaffold_tab("commit-artifacts", "Commit Artifacts", "", "")
    artifact = source_dir("commit-artifacts") / ".cache" / "tool"
    artifact.mkdir(parents=True)
    (artifact / "state").write_text("do not commit", encoding="utf-8")
    (source_dir("commit-artifacts") / "AGENTS.md").write_text("changed\n", encoding="utf-8")

    commit("commit-artifacts", "change")

    result = subprocess_run_git("commit-artifacts", ["ls-files"])
    assert ".cache/tool/state" not in result


def test_settings_redacts_secret_and_preserves_unknown_opencode_keys():
    from iteraforge.settings import opencode_config_file

    opencode_config_file().parent.mkdir(parents=True, exist_ok=True)
    opencode_config_file().write_text(json.dumps({"manual": {"keep": True}, "unknown": 7}), encoding="utf-8")
    public = save_settings({"api_key": "secret", "model": "test-model"})
    assert "api_key" not in public
    assert public["api_key_configured"] is True
    merged = json.loads(opencode_config_file().read_text(encoding="utf-8"))
    assert merged["unknown"] == 7
    assert merged["manual"]["keep"] is True
    assert load_settings()["model"] == "test-model"


def test_import_existing_opencode_config(tmp_path):
    source = tmp_path / "existing-opencode"
    source.mkdir()
    (source / "opencode.json").write_text('{"model":"x"}', encoding="utf-8")
    (source / "node_modules").mkdir()
    result = import_existing_opencode_config(source)
    assert result["imported"] is True
    from iteraforge.paths import opencode_root

    assert (opencode_root() / "opencode.json").exists()
    assert not (opencode_root() / "node_modules").exists()


def test_credential_environment_loads_opencode_auth_and_provider_identifier(tmp_path):
    from iteraforge.settings import opencode_auth_file, provider_environment_root

    auth = opencode_auth_file()
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text(json.dumps({"azure": {"type": "api", "key": "secret"}}), encoding="utf-8")
    provider = provider_environment_root() / "AZURE_RESOURCE_NAME"
    provider.parent.mkdir(parents=True, exist_ok=True)
    provider.write_text("example-resource", encoding="utf-8")

    environment = credential_environment()
    assert json.loads(environment["OPENCODE_AUTH_CONTENT"])["azure"]["key"] == "secret"
    assert environment["AZURE_RESOURCE_NAME"] == "example-resource"


def test_provider_import_and_default_selection(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text("model = 'x'\n", encoding="utf-8")

    result = import_provider_configs(home)

    assert result["imported"]["codex"]["copied"]
    assert choose_default_provider() == "codex"
    providers = {provider["id"]: provider for provider in list_providers()}
    assert providers["codex"]["configured"] is True


def test_opencode_preflight_reports_missing_dependencies(monkeypatch):
    monkeypatch.setattr("iteraforge.runner.shutil.which", lambda _command: None)
    assert OpenCodeRunner().preflight() == "Missing task runtime dependencies: git, opencode"


def test_opencode_runner_uses_runtime_home_outside_tab_source(monkeypatch):
    scaffold_tab("runner-env", "Runner Env", "", "")
    captured = {}

    class Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return ("ok", "")

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(*args, **kwargs):
        captured.update(kwargs["env"])
        return Proc()

    monkeypatch.setattr("iteraforge.runner.shutil.which", lambda _command: "/usr/bin/tool")
    monkeypatch.setattr("iteraforge.runner.subprocess.Popen", fake_popen)

    result = OpenCodeRunner().run("prompt", source_dir("runner-env"), {"OPENCODE_CONFIG_DIR": "/config/opencode"}, lambda _text: None, 10)

    assert result.ok is True
    assert captured["HOME"] != str(source_dir("runner-env"))
    assert str(source_dir("runner-env")) not in captured["npm_config_cache"]
    assert "/runtime/agent-home/runner-env" in captured["HOME"]


def test_connector_cache_and_shell_run():
    cache_set("connector-tab", "n", "k", {"value": 1}, ttl_seconds=60)
    assert cache_get("connector-tab", "n", "k") == {"value": 1}

    result = shell_run("connector-tab", ConnectorShellRequest(script="printf hello"))

    assert result["ok"] is True
    assert result["stdout"] == "hello"


def test_generated_prompt_documents_connectors():
    prompt = build_prompt({"prompt": "Build", "mode": "create", "tab_id": "x"})

    assert "window.IteraForgeRuntime.connectors.web.request" in prompt
    assert "window.IteraForgeRuntime.connectors.shell.run" in prompt
    assert "window.IteraForgeRuntime.connectors.ai.prompt" in prompt
    assert "window.IteraForgeRuntime.connectors.cache.get/set/delete/clear" in prompt
    assert "Show immediate visible pending state" in prompt
    assert "ok === false" in prompt
    assert "Do not hard-code API keys" in prompt
    assert "reload-safe" in prompt
    assert "window.IteraForgeTabCleanup" in prompt


def test_runtime_ai_prompt_uses_configured_opencode_home(monkeypatch):
    config = provider_config_root("opencode")
    config.mkdir(parents=True)
    (config / "opencode.json").write_text('{"model":"azure/gpt-5.6-sol"}\n', encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr("iteraforge.providers.shutil.which", lambda _command: "/usr/bin/opencode")
    monkeypatch.setattr("iteraforge.providers.subprocess.run", fake_run)

    result = run_prompt("hello")

    assert result["ok"] is True
    assert captured["args"][:3] == ["opencode", "run", "--format"]
    assert captured["env"]["OPENCODE_CONFIG_DIR"] == str(config)
    assert captured["env"]["XDG_CONFIG_HOME"] != str(Path.home() / ".config")
    linked = Path(captured["env"]["XDG_CONFIG_HOME"]) / "opencode"
    assert linked.is_symlink()
    assert linked.resolve() == config.resolve()


def test_runtime_ai_prompt_extracts_opencode_json_error(monkeypatch):
    config = provider_config_root("opencode")
    config.mkdir(parents=True)
    error_payload = {
        "type": "error",
        "error": {
            "name": "APIError",
            "data": {
                "message": "Not Found: DeploymentNotFound: claude-sonnet-4-6 does not exist"
            },
        },
    }

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout=json.dumps(error_payload), stderr="")

    monkeypatch.setattr("iteraforge.providers.shutil.which", lambda _command: "/usr/bin/opencode")
    monkeypatch.setattr("iteraforge.providers.subprocess.run", fake_run)

    result = run_prompt("hello")

    assert result["ok"] is False
    assert "DeploymentNotFound" in result["error"]
    assert result["exit_code"] == 1


def test_runtime_ai_prompt_extracts_opencode_text_events(monkeypatch):
    config = provider_config_root("opencode")
    config.mkdir(parents=True)
    stdout = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": '{"summary":"'}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": 'ok"}'}}),
        ]
    )

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("iteraforge.providers.shutil.which", lambda _command: "/usr/bin/opencode")
    monkeypatch.setattr("iteraforge.providers.subprocess.run", fake_run)

    result = run_prompt("hello")

    assert result["ok"] is True
    assert result["output_text"] == '{"summary":"ok"}'
    assert result["text"] == '{"summary":"ok"}'


def test_empty_catalog_is_valid():
    assert list_catalog_tabs() == []


class PreflightFailureRunner(FakeAgentRunner):
    def preflight(self):
        return "Missing task runtime dependencies: opencode"


def test_preflight_failure_does_not_scaffold_tab():
    manager = JobManager(EventBus(), runner=PreflightFailureRunner())
    job = {
        "id": "preflight",
        "mode": "create",
        "tab_id": "not-created",
        "prompt": "Create a tab",
        "trigger": "test",
        "status": "queued",
        "output": [],
    }
    with pytest.raises(RuntimeError, match="Missing task runtime dependencies"):
        manager._execute_job_sync(job)
    assert not tab_dir("not-created").exists()


def test_git_commit_and_failed_restore_schema_check():
    scaffold_tab("risk", "Risk", "", "")
    first = git_head("risk")
    assert first
    manifest = source_dir("risk") / "tab.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    manifest.write_text(json.dumps(data), encoding="utf-8")
    from iteraforge.tabs import commit

    second = commit("risk", "schema two\n\nSchema: 1 -> 2")
    assert second != first
    assert get_schema_version(db_path("risk")) == 1
    with pytest.raises(ValueError):
        checkout_revision("risk", second)


def test_snapshot_and_combined_restore():
    scaffold_tab("restore", "Restore", "", "")
    create_record(db_path("restore"), "items", {"name": "before"})
    snap = snapshot_database("restore", "test")
    create_record(db_path("restore"), "items", {"name": "after"})
    from iteraforge.tabs import restore_database

    restore_database("restore", snap)
    rows = list_records(db_path("restore"), "items")
    assert [row["data"]["name"] for row in rows] == ["before"]


def test_validation_warnings_do_not_trigger_repair_and_commit():
    scaffold_tab("repair", "Repair", "", "")
    manager = JobManager(EventBus(), runner=FakeAgentRunner(fail_once=True))
    job = {"id": "1", "mode": "modify", "tab_id": "repair", "prompt": "Improve", "trigger": "test", "status": "queued", "output": []}
    manager._execute_job_sync(job)
    assert job["status"] == "succeeded"
    assert job["repair_attempts"] == 0
    assert job["validation_warnings"]
    assert load_state("repair")["active_commit"] == git_head("repair")


def test_base_ui_has_direct_tab_mount_not_iframe():
    html = (Path("src/iteraforge/static/index.html")).read_text(encoding="utf-8")
    assert "<iframe" not in html.lower()
    assert 'id="tab-mount"' in html


def test_tab_render_payload_allows_trusted_javascript_and_uses_runtime_token():
    scaffold_tab("rendered", "Rendered", "", "")
    (source_dir("rendered") / "index.html").write_text(
        """<!doctype html>
<html>
<body>
  <button onclick="window.rendered = true">Run</button>
  <script src="app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    payload = render_payload("rendered", "runtime-token")
    assert payload["runtime_token"] == "runtime-token"
    assert payload["manifest"]["id"] == "rendered"
    assert payload["asset_version"] == git_head("rendered")
    assert 'onclick="window.rendered = true"' in payload["html_body"]
    assert '<script src="app.js"></script>' in payload["html_body"]
    assert "trusted same-page tab code" in payload["js"]


def test_sanitizer_blocks_scripts_handlers_urls_and_nested_frames():
    html, errors = sanitize_html(
        '<body><script>alert(1)</script><button onclick="x()">X</button>'
        '<a href="javascript:alert(1)">bad</a><iframe src="/x"></iframe></body>'
    )
    assert "onclick" not in html
    assert "javascript:" not in html
    assert "<iframe" not in html
    assert any("blocked tag <script>" in error for error in errors)
    assert any("inline event handler" in error for error in errors)
    assert any("unsafe URL" in error for error in errors)
    assert any("blocked tag <iframe>" in error for error in errors)


class SlowRunner(FakeAgentRunner):
    def __init__(self) -> None:
        super().__init__()
        self.started = False

    def run(self, prompt, working_directory, environment, output_callback, timeout, cancel_callback=None):
        self.started = True
        deadline = time.time() + 5
        while time.time() < deadline:
            if cancel_callback and cancel_callback():
                return RunnerResult(False, -2, stderr="cancelled", cancelled=True)
            time.sleep(0.02)
        return super().run(prompt, working_directory, environment, output_callback, timeout, cancel_callback)


def test_duplicate_queued_job_returns_existing_job():
    async def scenario():
        manager = JobManager(EventBus(), runner=FakeAgentRunner())
        request = JobRequest(mode="create", prompt="Create a tab named Duplicate Queue")
        first = await manager.submit(request)
        second = await manager.submit(request)
        assert second["duplicate"] is True
        assert second["existing_job_id"] == first["id"]
        assert len(manager.jobs) == 1
        manager.cancel(first["id"])
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_duplicate_running_job_returns_existing_job_and_cancel_stops_runner():
    async def scenario():
        manager = JobManager(EventBus(), runner=FakeAgentRunner())
        request = JobRequest(mode="modify", tab_id="dup-running", prompt="Improve the workflow")
        from iteraforge.workflow import job_fingerprint

        first = {
            "id": "running-job",
            "mode": request.mode,
            "tab_id": request.tab_id,
            "prompt": request.prompt,
            "trigger": "user",
            "fingerprint": job_fingerprint(request.mode, request.tab_id, request.prompt, "user"),
            "status": "running",
        }
        manager.jobs[first["id"]] = first
        second = await manager.submit(request)
        assert second["duplicate"] is True
        assert second["existing_job_id"] == first["id"]
        cancelled = manager.cancel(first["id"])
        assert cancelled["cancel_requested"] is True
        assert cancelled["status"] == "running"
        runner = SlowRunner()
        result = runner.run("prompt", Path("."), {}, lambda _text: None, 1, lambda: True)
        assert result.cancelled is True

    asyncio.run(scenario())


def test_different_prompt_is_not_duplicate_and_queued_cancel_prevents_execution():
    async def scenario():
        scaffold_tab("queue-cancel", "Queue Cancel", "", "")
        runner = FakeAgentRunner()
        manager = JobManager(EventBus(), runner=runner)
        first = await manager.submit(JobRequest(mode="modify", tab_id="queue-cancel", prompt="First change"))
        second = await manager.submit(JobRequest(mode="modify", tab_id="queue-cancel", prompt="Second change"))
        assert second.get("duplicate") is False
        assert len(manager.jobs) == 2
        cancelled = manager.cancel(second["id"])
        assert cancelled["status"] == "cancelled"
        manager.cancel(first["id"])
        await asyncio.sleep(0)
        assert manager.get_job(second["id"])["status"] == "cancelled"

    asyncio.run(scenario())


def test_sse_event_on_success():
    async def scenario():
        bus = EventBus()
        stream = bus.stream()
        await stream.__anext__()
        await bus.publish({"type": "tabs-changed", "tab_id": "x", "action": "created"})
        event = await asyncio.wait_for(stream.__anext__(), timeout=1)
        assert "tabs-changed" in event

    asyncio.run(scenario())


def test_automated_improvement_disabled_prevents_change():
    save_settings({"automatic_improvement_enabled": False})
    scaffold_tab("auto", "Auto", "", "")
    before = git_head("auto")
    from iteraforge.improve import run_once

    asyncio.run(run_once())
    assert git_head("auto") == before
