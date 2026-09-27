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

# Linux power-supply drivers that support charge thresholds commonly expose
# this sysfs attribute. We use it only for read-only UI state detection.
END_THRESHOLD_GLOB = (
    "/sys/class/power_supply/BAT*/charge_control_end_threshold"
)


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


def read_end_threshold() -> tuple[str | None, int | None]:
    """Read the first usable battery end-charge threshold exposed by sysfs.

    Returns:
        (battery_name, threshold_percent)

    If no compatible battery attribute can be read, both values are None.
    Reading sysfs here does not require root on normal systems.
    """

    for raw_path in sorted(glob.glob(END_THRESHOLD_GLOB)):
        path = Path(raw_path)
        try:
            threshold = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            # A battery can disappear, a driver may deny access, or a value may
            # be malformed. Try another BAT* device before reporting unknown.
            continue

        return path.parent.name, threshold

    return None, None


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

    battery, threshold = read_end_threshold()

    if threshold is None:
        mode = "unknown"
    elif threshold >= 100:
        mode = "full"
    else:
        mode = "care"

    print(
        json.dumps(
            {
                "battery": battery,
                "mode": mode,
                "stop_threshold": threshold,
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
