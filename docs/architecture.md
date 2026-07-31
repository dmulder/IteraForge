# Architecture

IteraForge has two layers:

- Trusted base application: FastAPI backend, static frontend, settings, validation, revision control, activity log, and agent orchestration.
- Generated tabs: HTML/CSS/JavaScript packages mounted directly into the base page and backed by per-tab SQLite databases.

The base application is part of the container image. Runtime data is mounted from `~/.config/iteraforge` and `~/.local/share/iteraforge`. Generated tabs are isolated under `tabs/<tab-id>`.

## Trust Boundaries

The trusted base runtime receives a short-lived bearer token scoped to the active tab. Runtime APIs infer the tab from that token, never from a user-submitted tab path. Generated tab JavaScript runs as trusted same-page code, can use the base API helper, and is not sandboxed from the base page at runtime.

Tabs are mounted directly into the base DOM and use trusted declarative event bindings for storage actions. Validation blocks structural load failures such as path traversal, unsafe tab IDs, missing entrypoints, and symlink escapes. Source isolation is enforced by creating and modifying generated apps only inside their tab source directories.

## Agent Boundary

OpenCode is accessed through `AgentRunner`. The default runner sets the working directory to the target tab source root, but places home/config/cache state under runtime storage so tool artifacts are not written into tab source. Tests use `FakeAgentRunner`.

The installed service set includes `iteraforge-agent-worker.service` as the host-side boundary for moving agent execution into a separate constrained process/container. The web app does not mount Podman or Docker sockets.
