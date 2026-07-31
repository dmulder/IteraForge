from __future__ import annotations

import os
from pathlib import Path


APP_ID = "iteraforge"
APP_TITLE = "IteraForge"


def config_home() -> Path:
    return Path(os.environ.get("ITERAFORGE_CONFIG_HOME", Path.home() / ".config" / APP_ID))


def data_home() -> Path:
    return Path(os.environ.get("ITERAFORGE_DATA_HOME", Path.home() / ".local" / "share" / APP_ID))


def tabs_root() -> Path:
    return data_home() / "tabs"


def activity_root() -> Path:
    return data_home() / "activity"


def backups_root() -> Path:
    return data_home() / "backups"


def runtime_root() -> Path:
    return data_home() / "runtime"


def secrets_root() -> Path:
    return config_home() / "secrets"


def opencode_root() -> Path:
    return config_home() / "opencode"


def ensure_base_dirs() -> None:
    for path in [config_home(), data_home(), tabs_root(), activity_root(), backups_root(), runtime_root(), opencode_root()]:
        path.mkdir(parents=True, exist_ok=True)
    secrets_root().mkdir(parents=True, exist_ok=True)
    try:
        secrets_root().chmod(0o700)
    except PermissionError:
        pass
