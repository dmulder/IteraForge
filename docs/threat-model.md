# Threat Model

Primary risks:

- Generated tab attempts to access another tab's data.
- Generated tab attempts to call trusted base APIs.
- Generated tab JavaScript can execute in the base page and must be treated as trusted local code.
- Generated source attempts path traversal or symlink escape.
- Secrets leak into settings responses, logs, prompts, or tab source.
- OpenCode runs from the wrong working directory.
- Source revision and database schema drift apart.

Controls:

- Per-tab SQLite databases.
- Runtime tokens scoped to one tab.
- Base APIs require base session token.
- Generated tab JavaScript executes as trusted same-page code.
- Direct DOM mounting for generated tabs; runtime behavior is not a browser security boundary.
- Path and symlink validation.
- Separate secret files with restrictive permissions.
- Runner abstraction with tab source as working directory.
- Database snapshot before migrations/restores.
- Source-only restore compatibility checks.
