#!/usr/bin/env bash
set -euo pipefail

APP=iteraforge
PORT="${ITERAFORGE_PORT:-8765}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROWSER="${BROWSER:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

need podman
need systemctl
if [[ -z "$BROWSER" ]]; then
  for candidate in google-chrome chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$(command -v "$candidate")"; break; fi
  done
fi
if [[ -z "$BROWSER" ]]; then
  echo "No Chromium-compatible browser found. Re-run with BROWSER=/path/to/browser." >&2
  exit 1
fi

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/1024x1024/apps"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user stop iteraforge.service >/dev/null 2>&1 || true
for path in "$CONFIG_HOME" "$DATA_HOME"; do
  if [[ -e "$path" ]]; then
    # Migrate ownership left by older :U bind mounts back to the invoking user.
    podman unshare chown -R 0:0 "$path"
  fi
done

mkdir -p "$CONFIG_HOME/secrets/provider-environment" "$CONFIG_HOME/secrets/providers" "$CONFIG_HOME/opencode" "$CONFIG_HOME/providers" "$DATA_HOME/tabs" "$DATA_HOME/activity" "$DATA_HOME/backups" "$DATA_HOME/runtime" "$APP_DIR" "$ICON_DIR" "$UNIT_DIR" "$HOME/.local/bin"
chmod 700 "$CONFIG_HOME/secrets"
mkdir -p \
  "$HOME/.config/opencode" \
  "$HOME/.opencode" \
  "$HOME/.codex" \
  "$HOME/.config/codex" \
  "$HOME/.claude" \
  "$HOME/.config/claude" \
  "$HOME/.gemini" \
  "$HOME/.config/gemini" \
  "${XDG_DATA_HOME:-$HOME/.local/share}/opencode"

if [[ "${ITERAFORGE_IMPORT_OPENCODE:-1}" == "1" ]]; then
  for variable in AZURE_RESOURCE_NAME AZURE_COGNITIVE_SERVICES_RESOURCE_NAME; do
    if [[ -n "${!variable:-}" ]]; then
      printf '%s' "${!variable}" > "$CONFIG_HOME/secrets/provider-environment/$variable"
      chmod 0600 "$CONFIG_HOME/secrets/provider-environment/$variable"
    fi
  done
fi

echo "Building container image localhost/$APP:latest"
podman build -t "localhost/$APP:latest" "$ROOT"

install -m 0644 "$ROOT/systemd/iteraforge.service" "$UNIT_DIR/iteraforge.service"
install -m 0644 "$ROOT/systemd/iteraforge-agent-worker.service" "$UNIT_DIR/iteraforge-agent-worker.service"
install -m 0644 "$ROOT/systemd/iteraforge-improve.service" "$UNIT_DIR/iteraforge-improve.service"
install -m 0644 "$ROOT/systemd/iteraforge-improve.timer" "$UNIT_DIR/iteraforge-improve.timer"

cat > "$HOME/.local/bin/iteraforge-improve" <<EOF
#!/usr/bin/env bash
exec podman exec iteraforge python -m iteraforge.improve
EOF
chmod 0755 "$HOME/.local/bin/iteraforge-improve"

cat > "$HOME/.local/bin/iteraforge-agent-worker" <<EOF
#!/usr/bin/env bash
exec podman exec iteraforge python -m iteraforge.worker
EOF
chmod 0755 "$HOME/.local/bin/iteraforge-agent-worker"

sed \
  -e "s|@BROWSER@|$BROWSER|g" \
  -e "s|@PORT@|$PORT|g" \
  -e "s|@HOME@|$HOME|g" \
  "$ROOT/packaging/iteraforge.desktop.in" > "$APP_DIR/iteraforge.desktop"
chmod 0644 "$APP_DIR/iteraforge.desktop"
install -m 0644 "$ROOT/packaging/iteraforge.svg" "$ICON_DIR/iteraforge.svg"

systemctl --user daemon-reload
systemctl --user enable --now iteraforge.service

echo "IteraForge installed."
echo "Launch: $BROWSER --app=http://127.0.0.1:$PORT"
echo "Desktop entry: $APP_DIR/iteraforge.desktop"
echo "Status: systemctl --user status iteraforge.service"
echo "Logs: journalctl --user -u iteraforge.service -f"
echo "Automatic improvement timer is installed but disabled by default."
