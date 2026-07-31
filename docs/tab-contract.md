# Tab Development Contract

Generated tabs must:

- Use plain declarative HTML and CSS.
- Store records through trusted declarative bindings such as `data-action`, `data-collection`, and `data-render-list`.
- Put custom behavior in `app.js` when declarative bindings are not enough.
- Execute JavaScript as trusted same-page code when needed; tabs are not sandboxed from the IteraForge UI at runtime.
- Keep all source inside the tab `source/` directory.
- Include `tab.json`, `AGENTS.md`, `index.html`, `app.js`, `style.css`, and `migrations/`.
- Avoid external scripts, analytics, third-party network calls, secrets, and host file access.

`AGENTS.md` must describe purpose, workflow, UI structure, storage collections, schema version, source isolation constraints, recent changes, known problems, and future improvements.

Generated tab JavaScript is loaded as trusted same-page code after the tab is mounted. A tab may load `app.js` from its entrypoint with `<script src="app.js"></script>`, or rely on IteraForge to load `source/app.js` by convention. It may use `window.IteraForgeRuntime`, `window.IteraForgeTabRoot`, `window.IteraForgeTabManifest`, and `window.IteraForgeBaseApi`.
