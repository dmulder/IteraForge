from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .paths import runtime_root
from .settings import credential_environment, load_settings

OutputCallback = Callable[[str], None]
CancelCallback = Callable[[], bool]


@dataclass
class RunnerResult:
    ok: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    cancelled: bool = False
    started_at: float = field(default_factory=time.time)
    ended_at: float = field(default_factory=time.time)


class AgentRunner:
    def preflight(self) -> str | None:
        return None

    def run(
        self,
        prompt: str,
        working_directory: Path,
        environment: dict[str, str],
        output_callback: OutputCallback,
        timeout: int,
        cancel_callback: CancelCallback | None = None,
    ) -> RunnerResult:
        raise NotImplementedError


class OpenCodeRunner(AgentRunner):
    def preflight(self) -> str | None:
        settings = load_settings()
        command = settings.get("opencode_command") or "opencode"
        missing = []
        if shutil.which("git") is None:
            missing.append("git")
        if shutil.which(command) is None and not Path(command).exists():
            missing.append(command)
        if missing:
            return f"Missing task runtime dependencies: {', '.join(missing)}"
        return None

    def run(
        self,
        prompt: str,
        working_directory: Path,
        environment: dict[str, str],
        output_callback: OutputCallback,
        timeout: int,
        cancel_callback: CancelCallback | None = None,
    ) -> RunnerResult:
        settings = load_settings()
        command = settings.get("opencode_command") or "opencode"
        args = list(settings.get("safe_args") or ["run", "--format", "json"])
        if shutil.which(command) is None and not Path(command).exists():
            return RunnerResult(ok=False, exit_code=127, stderr=f"OpenCode command not found: {command}")
        agent_home = runtime_root() / "agent-home" / working_directory.parent.name
        xdg_cache = agent_home / ".cache"
        xdg_config = agent_home / ".config"
        xdg_data = agent_home / ".local" / "share"
        xdg_state = agent_home / ".local" / "state"
        npm_cache = agent_home / ".npm"
        for path in [agent_home, xdg_cache, xdg_config, xdg_data, xdg_state, npm_cache]:
            path.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(agent_home),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_STATE_HOME": str(xdg_state),
            "npm_config_cache": str(npm_cache),
            "NPM_CONFIG_CACHE": str(npm_cache),
            "OPENCODE_CONFIG_DIR": str(Path(environment.get("OPENCODE_CONFIG_DIR", ""))),
            **credential_environment(),
            **environment,
        }
        started = time.time()
        proc = subprocess.Popen(
            [command, *args, "--dir", str(working_directory), prompt],
            cwd=working_directory,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        deadline = started + timeout
        while True:
            if cancel_callback and cancel_callback():
                proc.terminate()
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, err = proc.communicate()
                return RunnerResult(
                    False,
                    proc.returncode if proc.returncode is not None else -15,
                    out or "",
                    err or "cancelled",
                    True,
                    started,
                    time.time(),
                )
            remaining = max(0.1, min(0.25, deadline - time.time()))
            try:
                out, err = proc.communicate(timeout=remaining)
                if out:
                    stdout_parts.append(out)
                    output_callback(out)
                if err:
                    stderr_parts.append(err)
                    output_callback(err)
                break
            except subprocess.TimeoutExpired:
                if time.time() >= deadline:
                    proc.kill()
                    out, err = proc.communicate()
                    return RunnerResult(False, -1, out or "", err or "timeout", False, started, time.time())
        return RunnerResult(
            proc.returncode == 0,
            proc.returncode,
            "".join(stdout_parts),
            "".join(stderr_parts),
            False,
            started,
            time.time(),
        )


class FakeAgentRunner(AgentRunner):
    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    def run(
        self,
        prompt: str,
        working_directory: Path,
        environment: dict[str, str],
        output_callback: OutputCallback,
        timeout: int,
        cancel_callback: CancelCallback | None = None,
    ) -> RunnerResult:
        self.calls += 1
        if cancel_callback and cancel_callback():
            return RunnerResult(False, -2, stderr="cancelled", cancelled=True)
        output_callback(f"fake agent call {self.calls}\n")
        if self.fail_once and self.calls == 1:
            (working_directory / "app.js").write_text("function broken() {\n", encoding="utf-8")
            return RunnerResult(True, 0, "generated invalid js")
        agents = working_directory / "AGENTS.md"
        with agents.open("a", encoding="utf-8") as fh:
            fh.write(f"\nRecent change: {prompt[:120]}\n")
        app = working_directory / "app.js"
        if app.exists():
            text = app.read_text(encoding="utf-8")
            if text.count("{") != text.count("}"):
                app.write_text("// IteraForge loads this file as trusted same-page tab code.\n", encoding="utf-8")
            else:
                app.write_text(text + "\n// trusted same-page tab code\n", encoding="utf-8")
        return RunnerResult(True, 0, "ok")
