#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${ISSABEL_MODULE_STATE_ROOT:-/var/lib/asterisk/issabel-module-state}"
MODULE_STATE_DIR="${STATE_ROOT%/}/callcenter_bridge"
ASTERISK_CUSTOM_POST="/etc/asterisk/sip_custom_post.conf"
LEGACY_BEGIN='; BEGIN callcenter_bridge webrtc'
LEGACY_END='; END callcenter_bridge webrtc'

remove_legacy_webrtc_block() {
  local target_file="$1"
  local tmp_file

  [ -f "$target_file" ] || return 0
  tmp_file="$(mktemp)"

  awk -v begin="$LEGACY_BEGIN" -v end="$LEGACY_END" '
    $0 == begin { skip = 1; next }
    skip && $0 == end { skip = 0; next }
    !skip { print }
  ' "$target_file" >"$tmp_file"

  cat "$tmp_file" >"$target_file"
  rm -f "$tmp_file"
}

mkdir -p "$MODULE_STATE_DIR"
touch "$MODULE_STATE_DIR/agent_extensions.json"
touch "$MODULE_STATE_DIR/last_snapshot.json"

chmod 775 "$MODULE_STATE_DIR" 2>/dev/null || true
chmod 664 "$MODULE_STATE_DIR/agent_extensions.json" "$MODULE_STATE_DIR/last_snapshot.json" 2>/dev/null || true
chown -R asterisk:asterisk "$MODULE_STATE_DIR" 2>/dev/null || true

remove_legacy_webrtc_block "$ASTERISK_CUSTOM_POST"
asterisk -rx 'sip reload' >/dev/null 2>&1 || true
