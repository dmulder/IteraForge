# Manifest Specification

`tab.json`:

```json
{
  "id": "project-risks",
  "title": "Project Risks",
  "description": "Track project risks, owners, mitigations, and review dates.",
  "entrypoint": "index.html",
  "version": 1,
  "schema_version": 1
}
```

Rules:

- `id` must be a lowercase slug containing only `a-z`, `0-9`, and `-`.
- `id` must match the containing tab directory.
- `id` must not contain path separators or traversal.
- `entrypoint` must be a single HTML file name in the source root.
- `schema_version` must be a positive integer.
