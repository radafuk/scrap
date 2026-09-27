/*
 * TLP Charge Toggle
 *
 * A deliberately small GNOME Shell Quick Settings extension.
 *
 * This file is the unprivileged UI half of the project. It does not call TLP
 * directly and it does not run arbitrary root commands.
 *
 * Read-only status path:
 *
 *   GNOME Shell -> helper status -> sysfs threshold -> JSON -> tile state
 *
 * State-changing path:
 *
 *   GNOME Shell -> pkexec -> polkit -> fixed helper -> tlp fullcharge/setcharge
 *
 * The helper and polkit policy are documented separately in this directory.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as QuickSettings from 'resource:///org/gnome/shell/ui/quickSettings.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';


/*
 * GNOME's Gio.Subprocess callback API is promisified here so the rest of this
 * small extension can use straightforward async/await control flow.
 */
Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async');


/*
 * These paths are fixed at install time.
 *
 * HELPER is root-owned after installation. The extension may execute "status"
 * directly because that operation is read-only. Mutating actions go through
 * PKEXEC, which asks polkit whether this active session may run HELPER as root.
 */
const HELPER = '/usr/local/libexec/tlp-charge-toggle-helper';
const PKEXEC = '/usr/bin/pkexec';


/**
 * Execute a process and return stdout as text.
 *
 * argv is passed directly to Gio.Subprocess. There is no shell involved, so
 * characters in arguments are not interpreted as shell syntax.
 *
 * Throws an Error containing stderr/stdout if the process exits unsuccessfully.
 */
async function execText(argv) {
    const process = Gio.Subprocess.new(
        argv,
        Gio.SubprocessFlags.STDOUT_PIPE |
            Gio.SubprocessFlags.STDERR_PIPE
    );

    const [stdout, stderr] =
        await process.communicate_utf8_async(null, null);

    if (!process.get_successful())
        throw new Error((stderr || stdout || 'Command failed').trim());

    return (stdout || '').trim();
}


/*
 * The visible Quick Settings tile.
 *
 * checked = true  means the kernel currently reports an end threshold of 100,
 *                  i.e. temporary full-charge mode.
 *
 * checked = false means a lower configured threshold is active.
 *
 * We do not persist our own state. Every refresh asks the kernel through the
 * helper, which prevents the UI from lying after reboot or after somebody runs
 * a TLP command in a terminal.
 */
const ChargeToggle = GObject.registerClass(
class ChargeToggle extends QuickSettings.QuickToggle {
    constructor(extension) {
        super({
            title: 'Charge to 100%',
            subtitle: 'Checking…',
            iconName: 'battery-level-100-charged-symbolic',
            toggleMode: true,
        });

        this._extension = extension;

        /*
         * Prevent overlapping privilege requests if the user clicks repeatedly
         * while one TLP operation is still running.
         */
        this._changing = false;

        this.connect('clicked', async () => {
            if (this._changing)
                return;

            this._changing = true;

            try {
                /*
                 * QuickToggle has already changed its checked state when the
                 * click handler runs:
                 *
                 * checked=true  -> request fullcharge
                 * checked=false -> restore configured thresholds with setcharge
                 */
                const command =
                    this.checked ? 'fullcharge' : 'setcharge';

                await this._extension.runPrivileged(command);
            } catch (error) {
                /*
                 * On failure we do not leave the optimistic clicked state as
                 * authoritative. The finally block immediately rereads the
                 * actual kernel state.
                 */
                Main.notify('TLP Charge Toggle', error.message);
            } finally {
                this._changing = false;
                await this._extension.refresh();
            }
        });
    }

    /**
     * Apply the helper's read-only status object to the tile.
     */
    applyStatus(status) {
        const threshold = status?.stop_threshold;

        if (status?.mode === 'full') {
            this.checked = true;
            this.subtitle = 'Enabled';
        } else if (status?.mode === 'care') {
            this.checked = false;
            this.subtitle = 'Disabled';
        } else {
            /*
             * Unknown normally means the kernel/driver exposes no readable
             * charge_control_end_threshold attribute.
             */
            this.checked = false;
            this.subtitle = 'Unavailable';
        }
    }
});


/*
 * GNOME requires Quick Settings items to belong to a SystemIndicator.
 * This indicator has no separate top-bar icon; it only contributes one tile.
 */
const Indicator = GObject.registerClass(
class Indicator extends QuickSettings.SystemIndicator {
    constructor(extension) {
        super();

        this.toggle = new ChargeToggle(extension);
        this.quickSettingsItems.push(this.toggle);
    }

    destroy() {
        for (const item of this.quickSettingsItems)
            item.destroy();

        super.destroy();
    }
});


/*
 * GNOME Shell extension lifecycle.
 */
export default class TlpChargeToggleExtension extends Extension {
    enable() {
        /*
         * Add the tile to GNOME's existing Quick Settings menu rather than
         * creating a separate menu or custom window.
         */
        this._indicator = new Indicator(this);
        Main.panel.statusArea.quickSettings
            .addExternalIndicator(this._indicator);

        /*
         * Populate state immediately, then refresh periodically so external
         * TLP changes become visible even when the user did not click our tile.
         */
        this.refresh();

        this._refreshId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            10,
            () => {
                this.refresh();
                return GLib.SOURCE_CONTINUE;
            }
        );
    }

    disable() {
        if (this._refreshId) {
            GLib.source_remove(this._refreshId);
            this._refreshId = 0;
        }

        this._indicator?.destroy();
        this._indicator = null;
    }

    /**
     * Read actual battery-threshold state without privilege elevation.
     */
    async readStatus() {
        const output = await execText([HELPER, 'status']);
        return JSON.parse(output);
    }

    /**
     * Ask polkit to execute one fixed helper operation as root.
     *
     * Keep the allow-list here as well as in the helper. The helper is the
     * actual security boundary; this client-side check is additional clarity
     * and defense in depth.
     */
    async runPrivileged(command) {
        if (!['fullcharge', 'setcharge'].includes(command))
            throw new Error(`Unsupported operation: ${command}`);

        return execText([PKEXEC, HELPER, command]);
    }

    /**
     * Synchronize the tile with the current kernel threshold.
     */
    async refresh() {
        if (!this._indicator)
            return;

        try {
            const status = await this.readStatus();

            // The extension can be disabled while the async process is running.
            if (this._indicator)
                this._indicator.toggle.applyStatus(status);
        } catch (error) {
            console.error(`TLP Charge Toggle: ${error}`);

            if (this._indicator)
                this._indicator.toggle.subtitle = 'Unavailable';
        }
    }
}
