from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import config_home, runtime_root, secrets_root

PROVIDER_MOUNT_ROOT = Path(os.environ.get("ITERAFORGE_PROVIDER_MOUNT_ROOT", "/provider-config"))
PROVIDER_SECRET_MOUNT_ROOT = Path(os.environ.get("ITERAFORGE_PROVIDER_SECRET_MOUNT_ROOT", "/provider-secrets"))


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    title: str
    command: str
    prompt_args: tuple[str, ...]
    config_candidates: tuple[Path, ...]
    secret_candidates: tuple[Path, ...] = ()


def provider_specs(home: Path | None = None) -> dict[str, ProviderSpec]:
    explicit_home = home is not None
    home = home or Path.home()
    xdg_config = home / ".config" if explicit_home else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    xdg_data = home / ".local" / "share" if explicit_home else Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return {
        "opencode": ProviderSpec(
            "opencode",
            "OpenCode",
            "opencode",
            ("run", "--format", "json"),
            (xdg_config / "opencode", home / ".opencode"),
            (xdg_data / "opencode" / "auth.json",),
        ),
        "codex": ProviderSpec(
            "codex",
            "Codex",
            "codex",
            ("exec",),
            (home / ".codex", xdg_config / "codex"),
        ),
        "claude": ProviderSpec(
            "claude",
            "Claude",
            "claude",
            ("-p",),
            (home / ".claude", xdg_config / "claude"),
        ),
        "gemini": ProviderSpec(
            "gemini",
            "Gemini",
            "gemini",
            ("-p",),
            (home / ".gemini", xdg_config / "gemini"),
        ),
    }


def providers_root() -> Path:
    return config_home() / "providers"


def provider_config_root(provider: str) -> Path:
    return providers_root() / provider


def provider_secret_root(provider: str) -> Path:
    return secrets_root() / "providers" / provider


def mounted_config_candidates(provider: str) -> tuple[Path, ...]:
    return {
        "opencode": (
            PROVIDER_MOUNT_ROOT / "opencode-xdg",
            PROVIDER_MOUNT_ROOT / "opencode-home",
        ),
        "codex": (
            PROVIDER_MOUNT_ROOT / "codex-home",
            PROVIDER_MOUNT_ROOT / "codex-xdg",
        ),
        "claude": (
            PROVIDER_MOUNT_ROOT / "claude-home",
            PROVIDER_MOUNT_ROOT / "claude-xdg",
        ),
        "gemini": (
            PROVIDER_MOUNT_ROOT / "gemini-home",
            PROVIDER_MOUNT_ROOT / "gemini-xdg",
        ),
    }.get(provider, ())


def mounted_secret_candidates(provider: str) -> tuple[Path, ...]:
    return {
        "opencode": (PROVIDER_SECRET_MOUNT_ROOT / "opencode-data" / "auth.json",),
    }.get(provider, ())


def effective_provider_config(provider: str) -> Path:
    for path in [*mounted_config_candidates(provider), provider_config_root(provider)]:
        if _path_has_entries(path):
            return path
    return provider_config_root(provider)


def effective_provider_secrets(provider: str) -> list[Path]:
    return [
        path
        for path in [*mounted_secret_candidates(provider), *provider_secret_root(provider).glob("*")]
        if path.exists() and path.is_file()
    ]


def list_providers() -> list[dict[str, Any]]:
    result = []
    for spec in provider_specs().values():
        mounted = next((path for path in mounted_config_candidates(spec.id) if _path_has_entries(path)), None)
        snapshot = provider_config_root(spec.id)
        configured = bool(mounted) or _path_has_entries(snapshot) or bool(effective_provider_secrets(spec.id))
        available = shutil.which(spec.command) is not None
        result.append(
            {
                "id": spec.id,
                "title": spec.title,
                "command": spec.command,
                "configured": configured,
                "available": available,
                "config_path": str(mounted or snapshot),
                "config_source": "mounted" if mounted else "snapshot",
            }
        )
    return result


def import_provider_configs(source_home: Path | None = None, overwrite: bool = False) -> dict[str, Any]:
    specs = provider_specs(source_home)
    imported: dict[str, Any] = {}
    for spec in specs.values():
        copied = []
        skipped = []
        for source in spec.config_candidates:
            if not source.exists():
                continue
            target = provider_config_root(spec.id)
            if target.exists() and not overwrite:
                skipped.append(source.name)
                break
            _replace_path(source, target)
            copied.append(str(source))
            break
        secret_copied = []
        for source in spec.secret_candidates:
            if not source.exists() or not source.is_file():
                continue
            target = provider_secret_root(spec.id) / source.name
            if target.exists() and not overwrite:
                skipped.append(source.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            target.chmod(0o600)
            secret_copied.append(str(source))
        imported[spec.id] = {"copied": copied, "secrets": secret_copied, "skipped": skipped}
    return {"imported": imported, "default_provider": choose_default_provider()}


def choose_default_provider(current: str | None = None) -> str:
    known = provider_specs()
    if current in known and _provider_configured(current):
        return current
    configured = [provider for provider in ("opencode", "codex", "claude", "gemini") if _provider_configured(provider)]
    if configured:
        return configured[0]
    return current if current in known else "opencode"


def run_prompt(
    prompt: str,
    system: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    timeout: int = 120,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .settings import credential_environment, load_settings

    settings = load_settings()
    provider_id = provider or settings.get("agent_provider") or "opencode"
    specs = provider_specs()
    spec = specs.get(provider_id) or specs["opencode"]
    command = settings.get(f"{provider_id}_command") or spec.command
    if shutil.which(command) is None and not Path(command).exists():
        return {"ok": False, "provider": provider_id, "model": model, "response": "", "error": f"command not found: {command}"}
    full_prompt = _compose_prompt(prompt, system, context)
    env = _provider_prompt_environment(provider_id, credential_environment())
    if model:
        env["ITERAFORGE_MODEL"] = model
    proc = subprocess.run(
        [command, *spec.prompt_args, full_prompt],
        cwd=runtime_root(),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    payload = {
        "ok": proc.returncode == 0,
        "provider": provider_id,
        "model": model,
        "response": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }
    output_text = _provider_output_text(proc.stdout)
    if output_text:
        payload["output_text"] = output_text
        payload["text"] = output_text
    if proc.returncode != 0:
        payload["error"] = _provider_error(proc.stdout, proc.stderr)
    return payload


def _provider_prompt_environment(provider_id: str, credentials: dict[str, str]) -> dict[str, str]:
    provider_config = effective_provider_config(provider_id)
    agent_home = runtime_root() / "provider-prompts" / provider_id
    xdg_cache = agent_home / ".cache"
    xdg_config = agent_home / ".config"
    xdg_data = agent_home / ".local" / "share"
    xdg_state = agent_home / ".local" / "state"
    npm_cache = agent_home / ".npm"
    for path in [agent_home, xdg_cache, xdg_config, xdg_data, xdg_state, npm_cache]:
        path.mkdir(parents=True, exist_ok=True)
    if provider_id == "opencode":
        _link_config(provider_config, xdg_config / "opencode")
        if provider_config != xdg_config / "opencode":
            _link_config(provider_config, agent_home / ".opencode")
    elif provider_id in {"codex", "claude", "gemini"}:
        _link_config(provider_config, agent_home / f".{provider_id}")
        _link_config(provider_config, xdg_config / provider_id)
    env = {
        **os.environ,
        "HOME": str(agent_home),
        "XDG_CACHE_HOME": str(xdg_cache),
        "XDG_CONFIG_HOME": str(xdg_config),
        "XDG_DATA_HOME": str(xdg_data),
        "XDG_STATE_HOME": str(xdg_state),
        "npm_config_cache": str(npm_cache),
        "NPM_CONFIG_CACHE": str(npm_cache),
        "ITERAFORGE_PROVIDER_CONFIG": str(provider_config),
        **credentials,
    }
    if provider_id == "opencode":
        env["OPENCODE_CONFIG_DIR"] = str(provider_config)
    return env


def _link_config(source: Path, link: Path) -> None:
    if not source.exists() or source == link:
        return
    if link.exists() or link.is_symlink():
        if link.is_symlink() and link.resolve() == source.resolve():
            return
        if link.is_dir() and not link.is_symlink():
            return
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(source, target_is_directory=source.is_dir())


def _provider_error(stdout: str, stderr: str) -> str:
    for text in [stdout, stderr]:
        message = _provider_json_error(text)
        if message:
            return message
    return stderr.strip() or stdout.strip() or "provider failed"


def _provider_output_text(stdout: str) -> str:
    stdout = stdout.strip()
    if not stdout:
        return ""
    parts: list[str] = []
    parsed_any = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed_any = True
        text = _event_text(payload)
        if text:
            parts.append(text)
    if parts:
        return "".join(parts)
    if parsed_any:
        return ""
    return stdout


def _event_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    part = payload.get("part")
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return part["text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    if isinstance(payload.get("content"), str):
        return payload["content"]
    return ""


def _provider_json_error(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    candidates = [text]
    if "\n" in text:
        candidates.extend(line.strip() for line in text.splitlines() if line.strip())
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        message = _find_error_message(payload)
        if message:
            return message
    return None


def _find_error_message(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            message = _find_error_message(item)
            if message:
                return message
        return None
    if not isinstance(value, dict):
        return None
    for key in ("message", "error", "stderr"):
        message = _find_error_message(value.get(key))
        if message:
            return message
    return _find_error_message(value.get("data"))


def _provider_configured(provider: str) -> bool:
    return _path_has_entries(effective_provider_config(provider)) or bool(effective_provider_secrets(provider))


def _path_has_entries(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return path.stat().st_size > 0
    if not path.is_dir():
        return False
    try:
        return any(path.iterdir())
    except PermissionError:
        return True


def _replace_path(source: Path, target: Path) -> None:
    if target.exists():
        backup = target.with_name(f"{target.name}.bak")
        if backup.exists():
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink()
        shutil.move(str(target), str(backup))
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns(
                "node_modules",
                ".cache",
                "sessions",
                "logs",
                "history.jsonl",
                "*.sqlite",
                "*.sqlite-*",
                "*.db",
                "*.db-*",
            ),
        )
    else:
        shutil.copy2(source, target)


def _compose_prompt(prompt: str, system: str | None, context: dict[str, Any] | None) -> str:
    parts = []
    if system:
        parts.append(f"System:\n{system}")
    if context:
        parts.append("Context:\n" + json.dumps(context, indent=2, sort_keys=True))
    parts.append(prompt)
    return "\n\n".join(parts)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
