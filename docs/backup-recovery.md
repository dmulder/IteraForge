# Backup and Recovery

Back up these directories:

```text
~/.config/iteraforge/
~/.local/share/iteraforge/
```

Each tab has local Git history under `source/.git` and database snapshots under `database-snapshots/`. Restore operations create a recovery snapshot first, so a restore can be reversed by selecting the recovery revision/snapshot pair.
