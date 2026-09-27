#!/usr/bin/env bash
#
# Remove TLP Charge Toggle completely.
#
# This removes only files installed by install.sh. It does NOT modify TLP's own
# configuration or battery thresholds.
#
set -euo pipefail

UUID='tlp-charge-toggle@radafuk'
EXTENSION_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"
HELPER_TARGET='/usr/local/libexec/tlp-charge-toggle-helper'
POLICY_TARGET='/usr/share/polkit-1/actions/org.tlpchargetoggle.policy'


# Disabling can fail if GNOME has not currently loaded the extension. Removal
# should still continue in that case.
gnome-extensions disable "$UUID" 2>/dev/null || true

printf 'Removing per-user GNOME extension...\n'
rm -rf "$EXTENSION_DIR"

printf 'Removing root-owned helper and polkit policy...\n'
sudo rm -f "$HELPER_TARGET" "$POLICY_TARGET"

printf 'PASS — TLP Charge Toggle removed. TLP configuration was left untouched.\n'
