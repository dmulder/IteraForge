#!/usr/bin/env bash
set -euo pipefail

APP=iteraforge
PURGE=0
if [[ "${1:-}" == "--purge-data" ]]; then PURGE=1; fi

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/1024x1024/apps"
LEGACY_ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/$APP"

systemctl --user disable --now iteraforge-improve.timer >/dev/null 2>&1 || true
systemctl --user disable --now iteraforge-agent-worker.service >/dev/null 2>&1 || true
systemctl --user disable --now iteraforge.service >/dev/null 2>&1 || true
podman rm -f iteraforge >/dev/null 2>&1 || true

rm -f "$UNIT_DIR/iteraforge.service" "$UNIT_DIR/iteraforge-agent-worker.service" "$UNIT_DIR/iteraforge-improve.service" "$UNIT_DIR/iteraforge-improve.timer"
rm -f "$APP_DIR/iteraforge.desktop" "$ICON_DIR/iteraforge.svg" "$LEGACY_ICON_DIR/iteraforge.svg"
rm -f "$HOME/.local/bin/iteraforge-improve" "$HOME/.local/bin/iteraforge-agent-worker"
systemctl --user daemon-reload || true

if [[ "$PURGE" == 1 ]]; then
  read -r -p "Delete all IteraForge config and data? Type DELETE to continue: " answer
  if [[ "$answer" == "DELETE" ]]; then
    rm -rf "$CONFIG_HOME" "$DATA_HOME"
    echo "IteraForge data purged."
  else
    echo "Purge cancelled."
  fi
else
  echo "IteraForge removed. Config and data preserved at:"
  echo "  $CONFIG_HOME"
  echo "  $DATA_HOME"
fi
