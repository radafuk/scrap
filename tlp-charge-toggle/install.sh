#!/usr/bin/env bash
#
# Install TLP Charge Toggle.
#
# What requires sudo?
# -------------------
# Only two system-owned files:
#
#   /usr/local/libexec/tlp-charge-toggle-helper
#   /usr/share/polkit-1/actions/org.tlpchargetoggle.policy
#
# They persist across reboot. The GNOME extension itself is installed only for
# the current user under ~/.local/share/gnome-shell/extensions/.
#
# Runtime clicks do not use sudo. They use pkexec + the installed polkit policy.
#
set -euo pipefail

UUID='tlp-charge-toggle@radafuk'

# Directory containing this install script and the files installed alongside it.
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Standard per-user GNOME Shell extension location.
EXTENSION_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"

HELPER_SOURCE="$SOURCE_DIR/tlp-charge-toggle-helper.py"
POLICY_SOURCE="$SOURCE_DIR/org.tlpchargetoggle.policy"

HELPER_TARGET='/usr/local/libexec/tlp-charge-toggle-helper'
POLICY_TARGET='/usr/share/polkit-1/actions/org.tlpchargetoggle.policy'


fail() {
    printf 'FAIL — %s\n' "$*" >&2
    exit 1
}


printf 'Checking requirements...\n'

command -v gnome-extensions >/dev/null 2>&1 ||
    fail 'gnome-extensions was not found'

command -v pkexec >/dev/null 2>&1 ||
    fail 'pkexec was not found'

command -v python3 >/dev/null 2>&1 ||
    fail 'python3 was not found'

[[ -f "$HELPER_SOURCE" ]] ||
    fail "missing helper source: $HELPER_SOURCE"

[[ -f "$POLICY_SOURCE" ]] ||
    fail "missing polkit policy: $POLICY_SOURCE"

[[ -f "$SOURCE_DIR/extension.js" ]] ||
    fail "missing GNOME extension code"

[[ -f "$SOURCE_DIR/metadata.json" ]] ||
    fail "missing GNOME extension metadata"


# Desktop user PATHs often omit /usr/sbin, so checking plain "command -v tlp"
# as the user can incorrectly claim TLP is absent. Check the locations the root
# helper itself trusts.
if ! sudo sh -c '
    for path in \
        /usr/local/sbin/tlp \
        /usr/sbin/tlp \
        /sbin/tlp \
        /usr/local/bin/tlp \
        /usr/bin/tlp \
        /bin/tlp
    do
        [ -x "$path" ] && exit 0
    done
    exit 1
'; then
    fail 'TLP was not found in the expected system paths'
fi


printf 'Installing root-owned helper and polkit policy...\n'

# /usr/local/libexec may not exist on every distribution.
sudo install -d -m 0755 /usr/local/libexec

# Root ownership follows from sudo install. Mode 0755 lets the desktop user run
# the helper's read-only "status" command without privilege elevation.
sudo install -m 0755 "$HELPER_SOURCE" "$HELPER_TARGET"

# Polkit action definitions are ordinary root-owned readable XML files.
sudo install -m 0644 "$POLICY_SOURCE" "$POLICY_TARGET"


printf 'Installing GNOME extension for user %s...\n' "$USER"

mkdir -p "$(dirname "$EXTENSION_DIR")"

# Replace only this extension's own directory.
rm -rf "$EXTENSION_DIR"
mkdir -p "$EXTENSION_DIR"

install -m 0644 "$SOURCE_DIR/extension.js" "$EXTENSION_DIR/extension.js"
install -m 0644 "$SOURCE_DIR/metadata.json" "$EXTENSION_DIR/metadata.json"


printf 'Testing read-only status helper...\n'
"$HELPER_TARGET" status


# GNOME may refuse to enable a newly copied extension until Shell has rescanned
# extension directories, commonly after a logout/login. Treat that as a normal
# installed-but-not-yet-loaded state, not as a fake success.
if gnome-extensions enable "$UUID" 2>/dev/null; then
    printf 'PASS — TLP Charge Toggle is installed and enabled.\n'
else
    printf 'INSTALLED — GNOME Shell has not loaded the new extension yet.\n'
    printf 'Log out and back in once, then run:\n'
    printf '  gnome-extensions enable %s\n' "$UUID"
fi
