# TLP Charge Toggle

A small GNOME Shell Quick Settings extension for laptops that already use [TLP](https://linrunner.de/tlp/).

It adds exactly one tile to GNOME Quick Settings:

- **Full charge** — runs `tlp fullcharge`
- **Charge limit** — runs `tlp setcharge`

The extension does **not** choose your charging thresholds. Configure those in TLP itself. This button only switches between TLP's temporary full-charge mode and your normal configured thresholds.

## Why this exists

TLP already provides the commands. The inconvenient part is opening a terminal and using root privileges every time you want to temporarily charge to 100%, then restoring the normal battery-preservation thresholds later.

This extension makes that operation a normal GNOME Quick Settings toggle.

## What gets installed

There are three small pieces:

1. **GNOME Shell extension**  
   Runs as your desktop user. It draws the tile, reads status, and asks for one of two fixed battery actions.

2. **Root-owned helper**  
   Installed as `/usr/local/libexec/tlp-charge-toggle-helper`. It is intentionally tiny. It accepts only:
   - `status`
   - `fullcharge`
   - `setcharge`

   It cannot execute arbitrary commands supplied by the extension.

3. **polkit policy**  
   Installed as `/usr/share/polkit-1/actions/org.tlpchargetoggle.policy`. It permits an **active local desktop session** to run the fixed helper without typing a password on every click.

The installer uses `sudo` once to place the helper and policy in system directories. Those files persist across reboots. You do **not** need to run sudo again after every boot.

## Control flow

When GNOME refreshes the tile:

```text
GNOME extension
      |
      +----> helper status
               |
               +----> reads the kernel battery charge threshold from sysfs
```

When you click the tile:

```text
GNOME extension
      |
      +----> pkexec
               |
               +----> polkit checks the installed policy
                        |
                        +----> root-owned helper
                                  |
                                  +----> /usr/sbin/tlp fullcharge
                                  or
                                  +----> /usr/sbin/tlp setcharge
```

There is no shell command string, no `sudo sh -c` at runtime, and no user-supplied command passed to root.

## Security model

This project deliberately uses a **small privileged boundary**.

The GNOME extension itself is unprivileged. Only the helper runs as root, and only for the two state-changing operations.

The helper:

- rejects unknown commands;
- checks that state-changing operations actually run as root;
- invokes TLP using an argument array rather than a shell command;
- searches only normal system locations for the `tlp` executable;
- does not read arbitrary paths from the extension;
- has no general-purpose "run command" feature.

The supplied polkit rule uses `allow_active=yes`. In practical terms, an active local graphical session can use this helper without entering a password each time. That is convenient, but it is still a security decision: it grants passwordless access to these **specific battery-charge operations**.

If you do not want passwordless operation, edit the policy before installation and use an authentication-requiring polkit setting instead.

## Status detection

The tile reads:

```text
/sys/class/power_supply/BAT*/charge_control_end_threshold
```

Interpretation:

- end threshold at 100 → **Full charge**
- end threshold below 100 → **Charge limit**
- no readable threshold → **Unavailable**

This keeps status detection independent from parsing human-readable TLP output.

Hardware and kernel-driver support varies. If your laptop does not expose a charge threshold there, the button can still be installed, but its state cannot be displayed reliably and it will show **Unavailable**.

## Requirements

- GNOME Shell with Quick Settings
- TLP
- hardware/driver support for TLP charge thresholds
- polkit / `pkexec`
- Python 3

The helper explicitly checks common root/system paths such as `/usr/sbin/tlp`, because desktop-user PATHs often do not include `/usr/sbin`.

## Install

From this directory:

```bash
bash install.sh
```

The script:

1. checks that the required desktop and privilege tools exist;
2. verifies that TLP exists in a system path;
3. installs the helper and polkit policy using sudo;
4. copies the GNOME extension into your user extension directory;
5. tries to enable the extension.

GNOME Shell may not notice a brand-new extension until the next login. If the installer says it is installed but not yet loaded, log out and back in once, then run:

```bash
gnome-extensions enable tlp-charge-toggle@radafuk
```

To inspect its state:

```bash
gnome-extensions info tlp-charge-toggle@radafuk
```

## Uninstall

```bash
bash uninstall.sh
```

The uninstall script removes the user extension, the root helper, and the polkit policy. It does not modify your TLP configuration.

## File map

| File | Purpose |
| --- | --- |
| `extension.js` | GNOME Quick Settings UI and status refresh |
| `metadata.json` | GNOME extension identity and supported Shell versions |
| `tlp-charge-toggle-helper.py` | Small privileged boundary around TLP |
| `org.tlpchargetoggle.policy` | polkit authorization for the helper |
| `install.sh` | Installation with explicit checks |
| `uninstall.sh` | Clean removal |
| `README.md` | Architecture, security model, installation and troubleshooting |

## Troubleshooting

### The installer says TLP is missing

As root, check:

```bash
which tlp
```

A common location is:

```text
/usr/sbin/tlp
```

The installer and helper already search that path explicitly.

### The extension is installed but not visible

Log out and back in once, then:

```bash
gnome-extensions enable tlp-charge-toggle@radafuk
```

### The tile says “Unavailable”

Check whether the kernel exposes a charge-control threshold:

```bash
cat /sys/class/power_supply/BAT*/charge_control_end_threshold
```

If that path does not exist, status detection is not available on that hardware/driver combination.

### A click fails

Run the helper manually through polkit to see the exact error:

```bash
pkexec /usr/local/libexec/tlp-charge-toggle-helper fullcharge
```

or:

```bash
pkexec /usr/local/libexec/tlp-charge-toggle-helper setcharge
```

## Scope

This project intentionally does one thing only. It is not a TLP configuration editor, battery-health daemon, power-profile manager, or replacement for TLP.

## License

WTFPL v2. See the repository-level [LICENSE](../LICENSE).
