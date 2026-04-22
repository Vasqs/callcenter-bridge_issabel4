#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYSTEMD_DIR="${ROOT_DIR}/deploy/systemd"

SERVICE_SRC="${SYSTEMD_DIR}/callcenter-bridge-relay.service"
TIMER_SRC="${SYSTEMD_DIR}/callcenter-bridge-relay.timer"
SCRIPT_SRC="${SYSTEMD_DIR}/callcenter-bridge-relay.sh.example"

SERVICE_DST="/etc/systemd/system/callcenter-bridge-relay.service"
TIMER_DST="/etc/systemd/system/callcenter-bridge-relay.timer"
SCRIPT_DST="/usr/local/bin/callcenter-bridge-relay.sh"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root." >&2
  exit 1
fi

for path in "${SERVICE_SRC}" "${TIMER_SRC}" "${SCRIPT_SRC}"; do
  if [ ! -f "${path}" ]; then
    echo "Missing required file: ${path}" >&2
    exit 1
  fi
done

install -m 0644 "${SERVICE_SRC}" "${SERVICE_DST}"
install -m 0644 "${TIMER_SRC}" "${TIMER_DST}"
install -m 0755 "${SCRIPT_SRC}" "${SCRIPT_DST}"

systemctl daemon-reload
systemctl enable --now callcenter-bridge-relay.timer
systemctl restart callcenter-bridge-relay.timer
systemctl start callcenter-bridge-relay.service

echo "Installed:"
echo "  ${SCRIPT_DST}"
echo "  ${SERVICE_DST}"
echo "  ${TIMER_DST}"
echo
systemctl status callcenter-bridge-relay.timer --no-pager
