# Storage API

Generated tabs use declarative HTML bindings. The trusted base runtime translates these bindings into scoped storage API calls:

```html
<form data-action="create" data-collection="risks">
  <input name="title">
  <button type="submit">Add</button>
</form>

<section data-render-list="risks">
  <p data-empty-state>No risks yet.</p>
  <template data-record-template>
    <article>
      <strong>{{data.title}}</strong>
      <button data-action="delete" data-collection="risks" data-record-id="{{id}}">Delete</button>
    </article>
  </template>
</section>
```

Backend endpoints:

- `GET /api/runtime/collections`
- `GET /api/runtime/schema`
- `GET /api/runtime/records/{collection}`
- `POST /api/runtime/records/{collection}`
- `GET /api/runtime/records/{collection}/{record_id}`
- `PUT /api/runtime/records/{collection}/{record_id}`
- `DELETE /api/runtime/records/{collection}/{record_id}`
- `POST /api/runtime/query`
- `GET /api/runtime/connectors/capabilities`
- `POST /api/runtime/connectors/web`
- `POST /api/runtime/connectors/shell`
- `POST /api/runtime/connectors/ai`
- `POST /api/runtime/connectors/cache/{get,set,delete,clear}`

The active tab is inferred from the runtime token.

Connector calls are available under `window.IteraForgeRuntime.connectors`. They are trusted base-mediated capabilities for local tabs, not a browser sandbox boundary:

```js
const response = await window.IteraForgeRuntime.connectors.web.request({
  url: "https://example.com/api",
  cache: {namespace: "research", key: "example", ttl_seconds: 3600}
});

const result = await window.IteraForgeRuntime.connectors.shell.run({
  script: "date && git --version",
  timeout_seconds: 10
});

const ai = await window.IteraForgeRuntime.connectors.ai.prompt({
  prompt: "Summarize this payload",
  context: {payload: response.body},
  cache: {namespace: "ai", key: "summary", ttl_seconds: 86400}
});
```

Connector requests can resolve successfully at the HTTP layer while the connector payload reports a provider-level failure. Tabs must inspect `result.ok === false` before using connector output, show an immediate pending state while the request is running, and render `error`, `stderr`, or useful response details inline when a call fails.
