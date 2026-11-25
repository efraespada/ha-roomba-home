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
documents map rollback for Imprint Smart Maps and a separate remapping flow
for ClearView. [Trial evidence](evidence/2026-11-25-map-backup-feasibility.json) · [Imprint guide](https://homesupport.irobot.com/articles/en_GB/Knowledge/64102) · [ClearView guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

1. **Capture and browse.** Available from the floor plan card. Save a
   verified snapshot on demand or automatically before a confirmed map
   edit or removal. Browse and export recorded floors independently of the
   current Roomba inventory. The panel shows capture dates, pin and retention
   settings, and errors from local storage.
2. **Recover supported edits.** Version 0.60.0 previews and restores the
   backed-up name and orientation on the active floor. Version 0.61.0
   recovers changed or removed cleaning zone outlines under their original
   identifiers. Verify room edits, restrictions, and furniture separately.
   Check the live revision before each write and verify the result from Roomba.
   Version 0.62.0 captures compatible routine and schedule destinations and
   recovers zone links that Roomba prunes after deletion. Each confirmation
   restores the backed-up order and per-area preferences for one surviving
   program and preserves its current name, schedule timing, and enabled state.
   [Zone recovery validation](validation.md#recovering-cleaning-zones) ·
   [Program recovery validation](validation.md#recovering-program-destinations)
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
