# Architecture

IteraForge has two layers:

- Trusted base application: FastAPI backend, static frontend, settings, validation, revision control, activity log, and agent orchestration.
- Generated tabs: trusted HTML/CSS/JavaScript packages mounted directly into the base page and backed by per-tab SQLite databases plus base-mediated connector capabilities.

The base application is part of the container image. Runtime data is mounted from `~/.config/iteraforge` and `~/.local/share/iteraforge`. Generated tabs are isolated under `tabs/<tab-id>`.

## Trust Boundaries

The trusted base runtime receives a short-lived bearer token scoped to the active tab. Runtime APIs infer the tab from that token, never from a user-submitted tab path. Generated tab JavaScript runs as trusted same-page code, can use the base API helper and runtime connectors, and is not sandboxed from the base page at runtime.

Tabs are mounted directly into the base DOM and use trusted declarative event bindings for storage actions. Validation blocks structural load failures such as path traversal, unsafe tab IDs, missing entrypoints, and symlink escapes. Source isolation is enforced by creating and modifying generated apps only inside their tab source directories.

## Agent Boundary

AI CLIs are accessed through `AgentRunner`. The default runner sets the working directory to the target tab source root, mounts upstream CLI configuration read-only, and places writable home/cache state under runtime storage so tool artifacts are not written into tab source. Tests use `FakeAgentRunner`.

The installed service set includes `iteraforge-agent-worker.service` as the host-side boundary for moving agent execution into a separate constrained process/container. The web app does not mount Podman or Docker sockets.

## Community Catalog

The bundled community catalog lives inside the source tree and may be empty. Installing a catalog entry copies that template into the user's tab source tree, initializes normal tab state, and leaves the tab editable like any AI-created tab.
