# Roadmap

## Local map history and recovery

**Capture and browsing available in 0.59.0.** Each opt-in snapshot keeps the
native archive, floor settings, revision, destination identifiers, and a
capture timestamp. The owner can pin snapshots, compare the displayed active
floor with a saved revision, and export it. Home Assistant stores snapshots
locally and scopes access to the linked robot. [Map backups](usage.md#local-map-backups)

Saving and viewing these snapshots is feasible. A locally saved Max 700
Combo archive matched the same provider revision byte for byte. The
archive of a removed test floor also remained readable at the time of
testing. A request to make that floor visible again received an
acknowledgement, but the floor never returned to the usable map list in
the verification window. The original floor remained unchanged. iRobot
documents map rollback for Imprint Smart Maps. Its copy and retrieval guide
excludes newer ClearView robots such as the Max 700.
[Trial evidence](evidence/2026-11-25-map-backup-feasibility.json) ·
[iRobot backup and retrieval](https://homesupport.irobot.com/articles/en_US/Knowledge/53000) ·
[ClearView guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

The older mission detail in the inspected Android build displays its map
and timeline. The local SDK also contains a `revert_user_edits` command
which takes a map identifier and has an empty command parameter object.
The command has no archived revision selector. A signed request on an
edited disposable Max 700 Combo floor returned HTTP 500, and follow-up
reads retained the edited map and name.
[Archived map investigation](validation.md#clearview-archive-recovery)

1. **Capture and browse.** Available from the floor plan card. Save a
   verified snapshot on demand or automatically before a confirmed map
   edit or removal. Browse and export recorded floors independently of the
   current Roomba inventory. The panel shows capture dates, pin and retention
   settings, and errors from local storage.
2. **Recover supported edits.** Version 0.60.0 previews and restores the
   backed-up name and orientation on the active floor. Version 0.61.0
   recovers changed or removed cleaning zone outlines under their original
   identifiers. Restriction recovery restores keep-out and no-mop zones
   and linear virtual walls under the original identifiers while retaining
   newer restrictions. Furniture recovery restores compatible object IDs,
   source flags, and placements while retaining newer objects. Routine
   recovery can reattach furniture destinations pruned after deletion and
   preserve their per-area profiles. Recover room names and types when the
   room identifier and footprint match. Recombining a split can redraw the
   room boundary, so exact room layout recovery requires a verified
   version-level operation.
   Check the live revision before each write and verify the result from Roomba.
   Version 0.62.0 captures compatible routine and schedule destinations and
   recovers zone links that Roomba prunes after deletion. Each confirmation
   restores the backed-up order and per-area preferences for one surviving
   program and preserves its current name, schedule timing, and enabled state.
   [Zone recovery validation](validation.md#recovering-cleaning-zones) ·
   [Program recovery validation](validation.md#recovering-program-destinations) ·
   [Restriction recovery validation](validation.md#recovering-map-restrictions) ·
   [Furniture recovery validation](validation.md#recovering-furniture-placements) ·
   [Room details and boundary trial](validation.md#recovering-room-names-and-types)
3. **Investigate full restoration.** Verify a provider operation for
   importing or reactivating an entire floor after its remote revision is
   gone. Use a disposable floor to prove that the restored map reappears
   in Roomba, that its geometry and destinations are intact, and that the
   robot can use it. This evidence gates a full-restore control.

Acceptance covers per-robot isolation, offline viewing of a saved archive,
retention, export, stale revisions, and interrupted writes. The exported
archive includes floor geometry. Require the linked robot's read permission
to view or export a snapshot and its control permission to recover edits.
Verify each recovery operation independently on a disposable map, including
the resulting floor and its destinations, before offering it in the card.
[Map editor SDD](../specs/009-map-zone-editor.md)

## Local route captures for unarchived reports

A Max 700 Combo sent live positions during an approach that ended with
error 48. The signed report retained the outcome and the requested map
revision and omitted the mission map. The report can now show that original
requested floor. [Unarchived report proof](validation.md#requested-floor-in-an-unarchived-report)

The card's opt-in **Local route recording** keeps scoped position
checkpoints and can present the matching route with estimated coverage
when the archive is unavailable. The signed report remains the source of
its outcome, measurements, and archive. The tests cover persistent
checkpoints, scope isolation, deletion, and archive precedence.
A household vacuum-only run verified the live trajectory and the signed
result. One local recording persisted after the Core restart. A later
mop-only run showed its native route and coverage in the signed report.
During cleaning, Home Assistant saw the area increase without receiving
positions. A later side-by-side run with the restored Proxyman capture
showed both live overlays and associated the position interruptions with
the absence of repeated native map announcements. The integration now
renews its announcement on a bounded cadence. Verify that renewal on a
household run with the Android app in the background throughout.
[Household vacuum trial](validation.md#household-vacuum-route-after-clearing-error-48) ·
[Household mop-only trials](validation.md#household-mop-only-route-and-return) ·
[Side-by-side live mopping](validation.md#side-by-side-live-mopping)

When the provider omits the exact base revision, an existing verified
backup for that robot can supply the saved floor. The card identifies
that source and requires the same revision as the saved route.
[Recording controls](usage.md#local-route-recording)

## Physical automatic dock emptying

The Max 700 Combo's three Android choices and a custom threshold were
confirmed through signed settings. A completed 0.65 m² routine with
per-routine emptying enabled returned with zero reported evacuations.
Two runs of the same saved routine each reported one emptying after
cleaning about 12.4 m², first in per-routine mode and then at the 25 m²
setting. Investigate whether the dock carries area across runs or reports
another trigger. Include an uninterrupted dock trace and a run reaching
a configured threshold before promising specific physical timing.
[Short routine and map comparison](validation.md#physical-emptying-after-a-short-routine) ·
[Saved-routine comparison](validation.md#saved-routine-dock-frequency-comparison)

## Android setup walkthrough

**First-clean preparation available in 0.70.0.** The Max 700 Combo's
Robot Help walkthrough is available as a four-step checklist in the card,
alongside the manual and support articles. Verify other models in the app
before adding model-specific steps. Initial pairing, Wi-Fi changes, and
factory reset require separate verification and remain open.
[Robot help](usage.md#robot-help)

Android exposes **Reconnect or change Wi-Fi** on the Max 700 Combo's
Wi-Fi settings screen. The next dialog states that proceeding clears the
robot's current Wi-Fi settings. The inspected trial canceled at that
dialog. iRobot documents a credential step for reconnecting and Bluetooth
for initial setup. A reconnect validation must establish
that the robot returns online with its existing association, floors, and
programs. A factory reset through the app removes the robot from the
account, and iRobot documents no map save option for that workflow on
this model. Test reset and removal on a disposable robot or account with
explicit authorization for the data loss.
[iRobot pairing and reconnection](https://homesupport.irobot.com/articles/en_US/Knowledge/10503) ·
[iRobot reset behavior](https://homesupport.irobot.com/articles/en_US/Knowledge/9047)
