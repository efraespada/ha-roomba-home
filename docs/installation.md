# Installation and setup

The integration is tested with Home Assistant Core 2026.11.2 and modern
Roomba robots with SKU X185240. Use the account you sign in to Roomba Home
with. The integration skips other models. Local copies can be installed
manually. Published releases and HACS installation are pending.

## Manual installation

1. Copy `custom_components/roomba_home` into
   `<config_dir>/custom_components/roomba_home` on the Home Assistant server.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and search for
   **Roomba Home**.
4. Enter the account email, password, and two-letter country code, such as
   `ES`. Select the robots to manage.

The setup flow stores the credentials and app profile in private Home
Assistant configuration. Protect configuration backups. Diagnostic downloads
omit credentials, names, maps, and account identifiers. Emulator, capture,
and token files belong to the research workflow. The icon loads from the
local `brand/` directory. [Branding](branding.md)

## Entities and behavior

Each selected robot retains its device and existing entity IDs. A recognized
dock appears as a child device, with its own controls, errors, and consumables.
The **Last cloud read** entity starts disabled. Polling runs every 15 seconds
during activity and every 60 seconds at rest. Commands trigger additional
confirmation reads. [Telemetry](telemetry.md) · [Capabilities](capabilities.md) · [Usage](usage.md)

If the password changes, Home Assistant can ask for reauthentication.
Reauthentication preserves the selected robots, app profile, and registry IDs.

Open the integration's options to change which robots Home Assistant manages.
Keep at least one selected. Deselecting a robot stops its reads and controls.
Reselecting it restores its existing entities and saved cleaning preferences.
**Show saved floor plans and live room updates** is off by default.
[Set up the interactive floor plan](../README.md#floor-plan-dashboard) ·
[Map and progress details](telemetry.md#how-to-interpret-progress)

## Removal and upgrades

Remove the entry from **Devices & services** to close the integration's
connections and stop its checks. The account's robots, maps, and routines remain
in Roomba Home. A previously submitted mission can continue and be checked in
the app.

To upgrade a manual copy, keep a backup of the previous folder, replace the
integration folder, and restart Home Assistant. The existing entry and its
entity IDs carry forward. The config entry has schema version 1. In an
isolated rollback, 0.1.0 restored the original twelve entities. Reinstalling
0.3.0 brought back the mopping mode, wetness, and area associations.
[Upgrade and rollback results](validation.md)

### Verified installations

| Version | Home Assistant Green result |
|---|---|
| 0.1.0 | Core 2026.11.2, configuration check and restart, three robots and twelve entities. [Validation](validation.md) |
| 0.3.0 and 0.3.1 | Reload preserved the links between three robots and three docks. Entity counts were 415 and 425 respectively. [Validation](validation.md) |
| 0.4.0 | Kept six devices and 425 entities. Listed schedules and changed the time of a disabled test schedule. [Validation](validation.md#weekly-schedule-writes-in-040) |
| 0.4.1 | Kept six devices and added entities for a total of 431. Verified schedule activation, deactivation, and the last recorded error. [Validation](validation.md#enabled-schedule-run-in-041) |
| 0.5.0 | Kept six devices and 431 entities. Two identical schedule requests returned the same ID. [Validation](validation.md#schedule-creation-and-deletion-in-050) |
| 0.7.0 | Backed up 0.5.0 and passed the Core configuration check. Registered three robots, three docks, and 453 entities, and exposed **Vacuum a map point**. [Validation](validation.md#home-assistant-action-in-070) |
| 0.10.0 | Registered three robots, three docks, and 470 entities. [Validation](validation.md#home-installation-of-0100) |
| 0.11.0 | Verified three robots and three docks, enabled maps, and tested one robot's live position, room, path, and return to dock. [Validation](validation.md#home-installation-and-live-map-test-of-0110) |
| 0.12.1 | Verified three robots, three docks, and 487 entities. Tested live room measurements and dashboard-based room selection. [Validation](validation.md#mission-detail-and-dashboard-validation) |

## Troubleshooting

| Situation | Check |
|---|---|
| Integration missing from Add integration | Check the folder path and restart Home Assistant. |
| Credentials rejected | Verify access in Roomba Home and reauthenticate when prompted. |
| New session fails after successful app sign-in | Keep the existing app profile and let the integration retry. [Authentication stages](api.md#authentication) |
| No supported robots found | Verify the robot SKU. Account associations can include unsupported models. |
| Vacuum unavailable | Check the robot's connectivity and wait for a successful poll. |
| Command result unconfirmed | Check the state in Home Assistant or Roomba Home before retrying. |
| Mission paused | Start resumes the same mission. To change modes, cancel that mission first. |
| Start or dock action blocked | Check preparation, bins, tanks, and the problem code. [Problem events](telemetry.md#problems-and-events) |
| Region unavailable | Verify it is still in the active saved map and check the Home Assistant area assignment. |
| Custom card unavailable after upgrading | Check the JavaScript module URL and reload the browser once Core has finished starting. |
| Rate limit or connection failure | Polling follows the provider's Retry-After or the coordinator's backoff. |

Include a description and sanitized Home Assistant diagnostics in issue
reports. Keep HAR files, tokens, private configuration, and map screenshots
out of public reports.
