# Migration Format

Migrations are ordered JSON files:

```text
migrations/
  0001-initial.json
  0002-add-review-date.json
```

Current supported operations are intentionally declarative:

```json
{
  "version": 1,
  "operations": [
    {"type": "ensure_json_records"}
  ]
}
```

Supported operation types:

- `ensure_json_records`
- `add_collection_metadata`
- `add_index_metadata`
- `set_schema_version`

The generic JSON record table is stable. Destructive migrations are rejected in v1.
