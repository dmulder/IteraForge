# Tab Development Contract

Generated tabs must:

- Use plain declarative HTML and CSS.
- Store records through trusted declarative bindings such as `data-action`, `data-collection`, and `data-render-list`.
- Put custom behavior in `app.js` when declarative bindings are not enough.
- Execute JavaScript as trusted same-page code when needed; tabs are local trusted applications, not sandboxed browser plugins.
- Make `app.js` reload-safe because IteraForge may mount it repeatedly in the same page. Wrap custom code in a scoped initializer instead of leaving top-level `let`, `const`, or `class` state, and register `window.IteraForgeTabCleanup` when adding document/window listeners, observers, intervals, or other persistent resources.
- Keep all source inside the tab `source/` directory.
- Include `tab.json`, `AGENTS.md`, `index.html`, `app.js`, `style.css`, and `migrations/`.
- Use `window.IteraForgeRuntime.connectors` for base-mediated web calls, shell execution inside the container, AI prompting, and cache access.
- Avoid hard-coding secrets in tab source; provider and credential material belongs in trusted base configuration.
- For long-running connector calls, show immediate visible pending state, disable or relabel the triggering control, and make the result location clear.
- Connector calls may return HTTP success with `ok: false` in the JSON payload. Tabs must surface `error`, `stderr`, or useful response details inline instead of showing success or an empty result.

`AGENTS.md` must describe purpose, workflow, UI structure, storage collections, schema version, source isolation constraints, recent changes, known problems, and future improvements.

Generated tab JavaScript is loaded as trusted same-page code after the tab is mounted. A tab may load `app.js` from its entrypoint with `<script src="app.js"></script>`, or rely on IteraForge to load `source/app.js` by convention. It may use `window.IteraForgeRuntime`, `window.IteraForgeTabRoot`, `window.IteraForgeTabManifest`, and `window.IteraForgeBaseApi`.

The primary isolation boundary is for AI CLIs that create or modify tab source. Those tools must work only inside the target tab source directory and must not modify base IteraForge code or other tabs.
