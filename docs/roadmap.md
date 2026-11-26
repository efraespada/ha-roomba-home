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

## Physical automatic dock emptying

The Max 700 Combo's three Android choices and a custom area threshold
were exercised through Home Assistant and confirmed through the signed
settings response. Observe a completed routine with per-routine emptying
enabled and match the dock activity and evacuation count to that mission.
Separately observe a run that reaches a configured area threshold.
[Setting validation](validation.md#automatic-dock-emptying-frequency)
