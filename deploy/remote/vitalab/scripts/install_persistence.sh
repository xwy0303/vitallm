#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
load_inventory "${1:-${VITALAB_INVENTORY:-}}"

os_value="$(remote_os)"
root_q="$(shell_quote "${VITALAB_ROOT}")"
profiles_q="$(shell_quote "${VITALAB_COMPOSE_PROFILES}")"

case "${os_value}" in
  linux)
    ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
PROFILES=${profiles_q}
SERVICE_FILE="\${VITALAB_ROOT}/deploy/systemd/vitalab-compose.service"
SENTINEL_SERVICE_FILE="\${VITALAB_ROOT}/deploy/systemd/vitalab-quick-tunnel-sentinel.service"
USER_SERVICE_FILE="\${HOME}/.config/systemd/user/vitalab-compose.service"
USER_SENTINEL_SERVICE_FILE="\${HOME}/.config/systemd/user/vitalab-quick-tunnel-sentinel.service"
mkdir -p "\${VITALAB_ROOT}/deploy/systemd"
sed \
  -e "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
  -e "s#__VITALAB_COMPOSE_PROFILES__#\${PROFILES}#g" \
  "\${VITALAB_ROOT}/deploy/systemd/vitalab-compose.service.template" > "\${SERVICE_FILE}"
sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
  "\${VITALAB_ROOT}/deploy/systemd/vitalab-quick-tunnel-sentinel.service.template" > "\${SENTINEL_SERVICE_FILE}"

if command -v systemctl >/dev/null 2>&1; then
  if [[ -w /etc/systemd/system ]]; then
    cp "\${SERVICE_FILE}" /etc/systemd/system/vitalab-compose.service
    systemctl daemon-reload
    systemctl enable vitalab-compose.service
    systemctl restart vitalab-compose.service
    if [[ -f "\${VITALAB_ROOT}/secrets/cloudflare.env" ]]; then
      cp "\${SENTINEL_SERVICE_FILE}" /etc/systemd/system/vitalab-quick-tunnel-sentinel.service
      systemctl daemon-reload
      systemctl enable vitalab-quick-tunnel-sentinel.service
      systemctl restart vitalab-quick-tunnel-sentinel.service
      systemctl status vitalab-quick-tunnel-sentinel.service --no-pager || true
    else
      echo "WARNING: \${VITALAB_ROOT}/secrets/cloudflare.env missing; sentinel service generated but not installed/started" >&2
    fi
    systemctl status vitalab-compose.service --no-pager || true
  elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n cp "\${SERVICE_FILE}" /etc/systemd/system/vitalab-compose.service
    sudo -n systemctl daemon-reload
    sudo -n systemctl enable vitalab-compose.service
    sudo -n systemctl restart vitalab-compose.service
    if [[ -f "\${VITALAB_ROOT}/secrets/cloudflare.env" ]]; then
      sudo -n cp "\${SENTINEL_SERVICE_FILE}" /etc/systemd/system/vitalab-quick-tunnel-sentinel.service
      sudo -n systemctl daemon-reload
      sudo -n systemctl enable vitalab-quick-tunnel-sentinel.service
      sudo -n systemctl restart vitalab-quick-tunnel-sentinel.service
      sudo -n systemctl status vitalab-quick-tunnel-sentinel.service --no-pager || true
    else
      echo "WARNING: \${VITALAB_ROOT}/secrets/cloudflare.env missing; sentinel service generated but not installed/started" >&2
    fi
    sudo -n systemctl status vitalab-compose.service --no-pager || true
  elif systemctl --user show-environment >/dev/null 2>&1; then
    mkdir -p "\$(dirname "\${USER_SERVICE_FILE}")"
    sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
      "\${VITALAB_ROOT}/deploy/systemd/vitalab-compose.user.service.template" > "\${USER_SERVICE_FILE}"
    systemctl --user daemon-reload
    systemctl --user enable vitalab-compose.service
    systemctl --user restart vitalab-compose.service
    if [[ -f "\${VITALAB_ROOT}/secrets/cloudflare.env" ]]; then
      sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
        "\${VITALAB_ROOT}/deploy/systemd/vitalab-quick-tunnel-sentinel.user.service.template" > "\${USER_SENTINEL_SERVICE_FILE}"
      systemctl --user daemon-reload
      systemctl --user enable vitalab-quick-tunnel-sentinel.service
      systemctl --user restart vitalab-quick-tunnel-sentinel.service
      systemctl --user status vitalab-quick-tunnel-sentinel.service --no-pager || true
    else
      echo "WARNING: \${VITALAB_ROOT}/secrets/cloudflare.env missing; sentinel service generated but not installed/started" >&2
    fi
    systemctl --user status vitalab-compose.service --no-pager || true
    if command -v loginctl >/dev/null 2>&1 && loginctl show-user "\$(id -un)" -p Linger 2>/dev/null | grep -q 'Linger=yes'; then
      echo "user-level systemd persistence installed with linger enabled"
    else
      echo "WARNING: installed user-level systemd service, but linger is not enabled; boot persistence requires root to install \${SERVICE_FILE} or run: loginctl enable-linger \$(id -un)" >&2
    fi
  else
    echo "systemd exists but installing requires root/sudo or a running user systemd; generated: \${SERVICE_FILE}" >&2
  fi
else
  echo "systemd not found; generated service template only: \${SERVICE_FILE}" >&2
fi
EOF
    ;;
  macos)
    ssh_remote_bash <<EOF
set -euo pipefail
VITALAB_ROOT=${root_q}
PLIST_DIR="\${HOME}/Library/LaunchAgents"
mkdir -p "\${PLIST_DIR}" "\${VITALAB_ROOT}/logs"
sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
  "\${VITALAB_ROOT}/deploy/launchd/com.vitalab.compose.plist.template" > "\${PLIST_DIR}/com.vitalab.compose.plist"
chmod 644 "\${PLIST_DIR}/com.vitalab.compose.plist"
launchctl bootout "gui/\$(id -u)" "\${PLIST_DIR}/com.vitalab.compose.plist" >/dev/null 2>&1 || true
launchctl bootstrap "gui/\$(id -u)" "\${PLIST_DIR}/com.vitalab.compose.plist"
launchctl kickstart -k "gui/\$(id -u)/com.vitalab.compose"
if [[ -f "\${VITALAB_ROOT}/secrets/cloudflare.env" ]]; then
  sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
    "\${VITALAB_ROOT}/deploy/launchd/com.vitalab.quick-tunnel-sentinel.plist.template" > "\${PLIST_DIR}/com.vitalab.quick-tunnel-sentinel.plist"
  chmod 644 "\${PLIST_DIR}/com.vitalab.quick-tunnel-sentinel.plist"
  launchctl bootout "gui/\$(id -u)" "\${PLIST_DIR}/com.vitalab.quick-tunnel-sentinel.plist" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/\$(id -u)" "\${PLIST_DIR}/com.vitalab.quick-tunnel-sentinel.plist"
  launchctl kickstart -k "gui/\$(id -u)/com.vitalab.quick-tunnel-sentinel"
  launchctl print "gui/\$(id -u)/com.vitalab.quick-tunnel-sentinel" | awk '/state =|pid =|last exit code =/'
else
  sed "s#__VITALAB_ROOT__#\${VITALAB_ROOT}#g" \
    "\${VITALAB_ROOT}/deploy/launchd/com.vitalab.quick-tunnel-sentinel.plist.template" > "\${VITALAB_ROOT}/deploy/launchd/com.vitalab.quick-tunnel-sentinel.plist"
  echo "WARNING: \${VITALAB_ROOT}/secrets/cloudflare.env missing; sentinel plist generated but not installed/started" >&2
fi
launchctl print "gui/\$(id -u)/com.vitalab.compose" | awk '/state =|pid =|last exit code =/'
EOF
    ;;
  *)
    die "unsupported remote OS: ${os_value}"
    ;;
esac
