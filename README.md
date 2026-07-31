# IteraForge

IteraForge is a local-first workplace task-helper platform. It runs a trusted base web app locally and lets an agent create isolated direct-render tabs for project tracking, meeting notes, release checklists, research logs, operational workflows, and similar professional tools.

## Install

```bash
./install.sh
```

The installer builds `localhost/iteraforge:latest`, creates:

- `~/.config/iteraforge/`
- `~/.local/share/iteraforge/`
- `~/.config/systemd/user/iteraforge.service`
- `~/.config/systemd/user/iteraforge-improve.service`
- `~/.config/systemd/user/iteraforge-improve.timer`
- `~/.local/share/applications/iteraforge.desktop`

Launch manually:

```bash
google-chrome --app=http://127.0.0.1:8765
```

Status and logs:

```bash
systemctl --user status iteraforge.service
journalctl --user -u iteraforge.service -f
systemctl --user status iteraforge-improve.timer
```

Uninstall while preserving data:

```bash
./uninstall.sh
```

Purge all config and data:

```bash
./uninstall.sh --purge-data
```

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make dev
make test
make lint
make image
```

## Data Layout

```text
~/.config/iteraforge/
  config.json
  secrets/api-key
  secrets/opencode-auth.json
  secrets/provider-environment/<variable>
  opencode/iteraforge-managed.json

~/.local/share/iteraforge/
  tabs/<tab-id>/
    source/.git/
    source/tab.json
    source/index.html
    source/app.js
    source/style.css
    source/AGENTS.md
    source/migrations/
    data/tab.sqlite3
    database-snapshots/
    logs/
    state.json
  activity/events.jsonl
  backups/
  runtime/
```

## OpenCode Configuration

The Settings UI manages common fields and writes them to `~/.config/iteraforge/config.json` and `~/.config/iteraforge/opencode/iteraforge-managed.json`. Unknown keys in the OpenCode config file are preserved. Secrets are stored separately at `~/.config/iteraforge/secrets/api-key` with mode `0600` and are never returned by the Settings API.

On install, IteraForge attempts a non-destructive import from `~/.config/opencode` or `~/.opencode` into `~/.config/iteraforge/opencode`. Existing IteraForge files are preserved, and bulky runtime folders such as `node_modules` are skipped. It also imports `~/.local/share/opencode/auth.json` into the protected IteraForge secrets directory and captures supported provider identifiers such as `AZURE_RESOURCE_NAME`. The full OpenCode data directory is never mounted into the container. Set `ITERAFORGE_IMPORT_OPENCODE=0 ./install.sh` to skip these imports. The Settings UI also includes a config import action.

The container image includes Git and a pinned OpenCode CLI. Task execution performs a dependency preflight before creating or modifying tab files.

## Revision and Snapshot Synchronization

Each tab source tree is a local Git repository. Before updates that may affect schema, IteraForge snapshots `data/tab.sqlite3`, records the current commit and schema version, applies migrations, validates the tab, then commits source changes and records the active commit in `state.json`. Restore operations first create a recovery snapshot. Source-only restore is rejected when the target revision schema differs from the current database schema; combined restore can restore a compatible database snapshot with the source revision.

## Known Limitations

This initial v1 includes the host worker service as the stable integration point, but job execution currently runs in the web container so the UI can stream status directly. The runner abstraction isolates this decision and can be moved fully into the host worker without changing tab APIs.
