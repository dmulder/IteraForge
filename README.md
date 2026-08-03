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
  secrets/providers/<provider>/
  secrets/provider-environment/<variable>
  opencode/iteraforge-managed.json
  providers/<provider>/

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

## Agent Provider Configuration

The Settings UI manages common fields and writes them to `~/.config/iteraforge/config.json` and `~/.config/iteraforge/opencode/iteraforge-managed.json`. Unknown keys in the OpenCode config file are preserved. Secrets are stored separately at `~/.config/iteraforge/secrets/api-key` with mode `0600` and are never returned by the Settings API.

On install, IteraForge mounts known OpenCode, Codex, Claude, and Gemini configuration locations into the container read-only. This keeps IteraForge aligned with changes the user makes through the upstream CLIs. IteraForge still keeps writable CLI runtime/cache state under its own data directory, and the Settings UI includes an explicit provider import action for taking a snapshot fallback into `~/.config/iteraforge/providers/<provider>`.

The container image includes Git and the supported AI CLI entrypoints. Task execution performs a dependency preflight before creating or modifying tab files.

## Trusted Connectors and Community Tabs

Tabs are trusted local applications mounted directly into the base page. They can use `window.IteraForgeRuntime.connectors` for base-mediated web requests, shell commands inside the container, AI prompt responses, and per-tab cache entries.

IteraForge includes the structure for a bundled community tab catalog. The catalog may ship empty; future entries can be proposed by source PR and, once accepted, are installed by copying their source into the user's editable tab tree.

## Revision and Snapshot Synchronization

Each tab source tree is a local Git repository. Before updates that may affect schema, IteraForge snapshots `data/tab.sqlite3`, records the current commit and schema version, applies migrations, validates the tab, then commits source changes and records the active commit in `state.json`. Restore operations first create a recovery snapshot. Source-only restore is rejected when the target revision schema differs from the current database schema; combined restore can restore a compatible database snapshot with the source revision.

## Known Limitations

This initial v1 includes the host worker service as the stable integration point, but job execution currently runs in the web container so the UI can stream status directly. The runner abstraction isolates this decision and can be moved fully into the host worker without changing tab APIs.
