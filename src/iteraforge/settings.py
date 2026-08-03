from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .paths import config_home, opencode_root, secrets_root
from .providers import choose_default_provider, effective_provider_secrets, provider_config_root

DEFAULTS: dict[str, Any] = {
    "agent_provider": "opencode",
    "provider": "",
    "api_base_url": "",
    "model": "",
    "opencode_command": "opencode",
    "safe_args": ["run", "--format", "json"],
    "timeout_seconds": 900,
    "repair_attempts": 3,
    "app_port": 8765,
    "automatic_improvement_enabled": False,
    "improvement_interval_minutes": 240,
    "browser_command": "",
    "snapshot_retention": 20,
    "activity_retention": 1000,
    "ui_managed_keys": [
        "agent_provider",
        "provider",
        "api_base_url",
        "model",
        "opencode_command",
        "safe_args",
        "timeout_seconds",
        "repair_attempts",
        "app_port",
        "automatic_improvement_enabled",
        "improvement_interval_minutes",
        "browser_command",
        "snapshot_retention",
        "activity_retention",
    ],
}

PROVIDER_ENVIRONMENT_KEYS = (
    "AZURE_RESOURCE_NAME",
    "AZURE_COGNITIVE_SERVICES_RESOURCE_NAME",
)


def settings_file() -> Path:
    return config_home() / "config.json"


def opencode_config_file() -> Path:
    opencode_root().mkdir(parents=True, exist_ok=True)
    return opencode_root() / "iteraforge-managed.json"


def existing_opencode_candidates(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [home / ".config" / "opencode", home / ".opencode"]


def secret_file() -> Path:
    secrets_root().mkdir(parents=True, exist_ok=True)
    return secrets_root() / "api-key"


def opencode_auth_file() -> Path:
    return secrets_root() / "opencode-auth.json"


def provider_environment_root() -> Path:
    return secrets_root() / "provider-environment"


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


def load_settings() -> dict[str, Any]:
    data = DEFAULTS.copy()
    path = settings_file()
    if path.exists():
        data.update(json.loads(path.read_text(encoding="utf-8")))
    data["agent_provider"] = choose_default_provider(data.get("agent_provider"))
    data["opencode_config_path"] = str(opencode_root())
    data["api_key_configured"] = secret_file().exists() and secret_file().stat().st_size > 0
    data["opencode_auth_configured"] = (
        opencode_auth_file().exists() and opencode_auth_file().stat().st_size > 0
    )
    return data


def public_settings() -> dict[str, Any]:
    data = load_settings()
    data.pop("api_key", None)
    return data


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    updates = {k: v for k, v in updates.items() if v is not None}
    api_key = updates.pop("api_key", None)
    if api_key is not None:
        path = secret_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(api_key, encoding="utf-8")
        path.chmod(0o600)
    current = load_settings()
    current.pop("opencode_config_path", None)
    current.pop("api_key_configured", None)
    current.pop("opencode_auth_configured", None)
    current.update(updates)
    current["agent_provider"] = choose_default_provider(current.get("agent_provider"))
    _atomic_json(settings_file(), current)
    merge_opencode_config(current)
    return public_settings()


def import_existing_opencode_config(source: Path | None = None, overwrite: bool = False) -> dict[str, Any]:
    candidates = [source] if source else existing_opencode_candidates()
    selected = next((path for path in candidates if path and path.exists() and path.is_dir()), None)
    if not selected:
        return {"imported": False, "reason": "no existing OpenCode configuration found"}
    destination = opencode_root()
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    for child in selected.iterdir():
        if child.name in {"node_modules", ".cache"}:
            skipped.append(child.name)
            continue
        target = destination / child.name
        if target.exists() and not overwrite:
            skipped.append(child.name)
            continue
        if target.exists():
            backup = target.with_name(f"{target.name}.bak")
            if backup.exists():
                if backup.is_dir():
                    shutil.rmtree(backup)
                else:
                    backup.unlink()
            shutil.move(str(target), str(backup))
        if child.is_dir():
            shutil.copytree(child, target, ignore=shutil.ignore_patterns("node_modules", ".cache"))
        else:
            shutil.copy2(child, target)
        copied.append(child.name)
    provider_destination = provider_config_root("opencode")
    if copied and not provider_destination.exists():
        shutil.copytree(destination, provider_destination, ignore=shutil.ignore_patterns("node_modules", ".cache"))
    return {
        "imported": bool(copied),
        "source": str(selected),
        "copied": copied,
        "skipped": skipped,
    }


def merge_opencode_config(settings: dict[str, Any]) -> None:
    path = opencode_config_file()
    existing: dict[str, Any] = {}
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        existing = json.loads(path.read_text(encoding="utf-8"))
    managed = {
        "provider": settings.get("provider", ""),
        "api_base_url": settings.get("api_base_url", ""),
        "model": settings.get("model", ""),
        "managed_by": "iteraforge",
    }
    existing.setdefault("manual", {})
    existing["iteraforge"] = managed
    _atomic_json(path, existing)


def credential_environment() -> dict[str, str]:
    environment = provider_environment()
    auth_path = opencode_auth_file()
    if auth_path.exists() and auth_path.stat().st_size > 0:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(auth, dict):
            raise ValueError("OpenCode auth file must contain a JSON object")
        environment["OPENCODE_AUTH_CONTENT"] = json.dumps(auth, separators=(",", ":"))
    provider_auth = next((path for path in effective_provider_secrets("opencode") if path.name == "auth.json"), None)
    if provider_auth and provider_auth.exists() and provider_auth.stat().st_size > 0:
        auth = json.loads(provider_auth.read_text(encoding="utf-8"))
        if not isinstance(auth, dict):
            raise ValueError("OpenCode provider auth file must contain a JSON object")
        environment["OPENCODE_AUTH_CONTENT"] = json.dumps(auth, separators=(",", ":"))
    path = secret_file()
    if not path.exists():
        return environment
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        return environment
    environment.update({"OPENAI_API_KEY": value, "ANTHROPIC_API_KEY": value})
    return environment


def provider_environment() -> dict[str, str]:
    root = provider_environment_root()
    result: dict[str, str] = {}
    for key in PROVIDER_ENVIRONMENT_KEYS:
        path = root / key
        value = (
            path.read_text(encoding="utf-8").strip()
            if path.exists()
            else os.environ.get(key, "").strip()
        )
        if value:
            result[key] = value
    return result
