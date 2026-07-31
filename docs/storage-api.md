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

The active tab is inferred from the runtime token.
