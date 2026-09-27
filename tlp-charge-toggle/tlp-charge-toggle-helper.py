#!/usr/bin/env python3
"""Privileged helper for TLP Charge Toggle.

Why a helper exists
===================

GNOME Shell extensions run as the logged-in desktop user, while changing TLP
charge thresholds commonly requires root privileges. Giving a desktop
extension arbitrary root command execution would be a poor security boundary.

This helper is therefore deliberately narrow. It recognizes exactly three
commands:

    status
        Read-only. Reports the kernel's current end-charge threshold.

    fullcharge
        Root-only. Executes: tlp fullcharge

    setcharge
        Root-only. Executes: tlp setcharge

There is intentionally no generic command runner, no shell=True, no command
string assembled from user input, and no configurable executable path supplied
by the GNOME extension.

The GNOME extension invokes the state-changing commands through pkexec. The
matching polkit policy controls whether that invocation requires interactive
authentication.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


# TLP is frequently installed in /usr/sbin, which is normally visible to root
# but may not appear in the PATH inherited from a graphical desktop session.
# Keep this list explicit so an inspector can see exactly where this helper is
# willing to find an executable named "tlp".
TLP_SEARCH_PATHS = (
    "/usr/local/sbin/tlp",
    "/usr/sbin/tlp",
    "/sbin/tlp",
    "/usr/local/bin/tlp",
    "/usr/bin/tlp",
    "/bin/tlp",
)

# Linux power-supply drivers expose charge-control state in different ways.
#
# Many drivers provide a numeric end threshold:
END_THRESHOLD_GLOB = (
    "/sys/class/power_supply/BAT*/charge_control_end_threshold"
)

# Lenovo's ideapad_laptop driver can instead expose symbolic charge modes in a
# file such as:
#
#     Fast Standard [Long_Life]
#
# Square brackets mark the active type. TLP maps its charge-threshold setting
# to Standard (normal/full charging) or Long_Life (battery-care mode).
CHARGE_TYPES_GLOB = "/sys/class/power_supply/BAT*/charge_types"


def fail(message: str, code: int = 1) -> NoReturn:
    """Print one human-readable error and terminate with a non-zero status."""

    print(message, file=sys.stderr)
    raise SystemExit(code)


def find_tlp() -> str:
    """Return a trusted system path to the TLP executable.

    We first inspect a fixed list of normal system locations. The final
    shutil.which() uses an explicit system PATH rather than the caller's PATH,
    so a desktop session cannot redirect this helper to a similarly named
    executable in a user-controlled directory.
    """

    for raw_path in TLP_SEARCH_PATHS:
        path = Path(raw_path)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)

    path = shutil.which(
        "tlp",
        path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    )
    if path:
        return path

    fail("TLP executable not found in the expected system paths.")


def read_charge_state() -> tuple[str | None, str, int | None, str | None]:
    """Read the active charge mode from kernel power-supply sysfs.

    Detection is intentionally read-only and does not call TLP.

    First choice: numeric charge_control_end_threshold
        100 or above -> "full"
        below 100    -> "care"

    Lenovo ideapad_laptop fallback: charge_types
        Example: "Fast Standard [Long_Life]"

        The bracketed value is active:
            Standard  -> "full" (displayed as “Full charge”)
            Long_Life -> "care"

    Returns:
        (battery_name, mode, numeric_threshold, active_charge_type)

    If neither interface provides a recognized state, mode is "unknown".
    """

    for raw_path in sorted(glob.glob(END_THRESHOLD_GLOB)):
        path = Path(raw_path)
        try:
            threshold = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue

        return (
            path.parent.name,
            "full" if threshold >= 100 else "care",
            threshold,
            None,
        )

    for raw_path in sorted(glob.glob(CHARGE_TYPES_GLOB)):
        path = Path(raw_path)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        active = None
        for token in value.split():
            if token.startswith("[") and token.endswith("]"):
                active = token[1:-1]
                break

        if active == "Standard":
            return path.parent.name, "full", None, active
        if active == "Long_Life":
            return path.parent.name, "care", None, active
        if active is not None:
            return path.parent.name, "unknown", None, active

    return None, "unknown", None, None

def print_status() -> None:
    """Emit a small JSON object consumed by the GNOME extension.

    Mode is intentionally inferred from the kernel threshold, not from a
    remembered toggle state:

        threshold >= 100  -> "full"
        threshold < 100   -> "care"
        unavailable       -> "unknown"

    This means the tile can recover the correct visual state after login,
    reboot, or an external TLP command.
    """

    battery, mode, threshold, charge_type = read_charge_state()

    print(
        json.dumps(
            {
                "battery": battery,
                "mode": mode,
                "stop_threshold": threshold,
                "charge_type": charge_type,
            },
            separators=(",", ":"),
        )
    )


def require_root() -> None:
    """Reject a mutating operation unless pkexec actually gave us root."""

    if os.geteuid() != 0:
        fail("This operation requires root privileges (normally via pkexec).")


def run_tlp(subcommand: str) -> None:
    """Run one of the two explicitly supported TLP charge commands.

    The caller cannot provide arbitrary TLP arguments: main() only reaches this
    function with the literal strings "fullcharge" or "setcharge".

    subprocess.run() receives an argument list and never invokes a shell.
    """

    require_root()

    if subcommand not in {"fullcharge", "setcharge"}:
        # This is defensive duplication of main()'s allow-list. Keeping the
        # check here makes the privileged function safe if it is reused later.
        fail(f"Unsupported TLP operation: {subcommand}", 2)

    process = subprocess.run(
        [find_tlp(), subcommand],
        text=True,
        capture_output=True,
        check=False,
    )

    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        fail(detail or f"tlp {subcommand} failed", process.returncode or 1)

    # Return fresh state after TLP finishes. The extension uses this only as
    # command output; it also performs its own refresh afterward.
    print_status()


def main() -> None:
    """Parse the intentionally tiny command surface."""

    if len(sys.argv) != 2:
        fail(
            "Usage: tlp-charge-toggle-helper "
            "{status|fullcharge|setcharge}",
            2,
        )

    command = sys.argv[1]

    if command == "status":
        print_status()
    elif command == "fullcharge":
        run_tlp("fullcharge")
    elif command == "setcharge":
        run_tlp("setcharge")
    else:
        fail(
            "Unknown command. Allowed: status, fullcharge, setcharge.",
            2,
        )


if __name__ == "__main__":
    main()
