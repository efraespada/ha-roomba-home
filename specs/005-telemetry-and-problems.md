# Robot telemetry, progress, and problems

- Status: Draft
- Date: 2026-11-23
- Catalog capability ID: telemetry-and-problems
- Last verified: 2026-11-28
- Owners: ha-roomba-home maintainer
- Scope: Typed state, progress, connectivity, dock telemetry, consumables, and problem and mission events
- Related issues/PRs: Household state and live mission validation
- Required review gates: product, UX, architecture, testing, documentation, and security/operations
- Open decisions blocking readiness: Additional provider fields need verified type, units, and meaning.

## 1. Executive summary

Expose useful Roomba observations under the existing robot and dock devices.
Publish typed sensors and local events for current state, mission history,
supplies, connectivity, and problems. Keep original entity identities
through updates.

## 2. Problem, current behavior, and evidence

- Observed behavior: The current integration projects typed robot and dock state and distinguishes live cleaning from history. A low-battery trial observed the same cleaning mission while the robot charged.
- Intentional contract: Use only Roomba observations and confirmed physical transitions for telemetry.
- Known debt and limitations: Polling can miss short transitions. A mission-wide coverage percentage still needs provider evidence.
- Unknown rationale: Some provider values, including the exact meaning of `lastDisconnect`, remain unverified.
- Proposed improvements: Add fields after establishing source, validity, and lifetime on their supported model.

The native shadows report mission, dock, settings, firmware, and statistics.
The signed parts service and model catalog provide consumable readings and
names. The archived mission results provide prior measurements and errors.
[Telemetry reference](../docs/telemetry.md) ·
[Household errors](../docs/validation.md#household-live-coverage-and-active-errors) ·
[Active recharge](../docs/validation.md#charging-during-the-same-cleaning-mission)

## 3. Actors, surfaces, and terminology

| Actor | Surface | Result |
| --- | --- | --- |
| Operator | Robot and dock devices | Current state, progress, and maintenance |
| Automation author | Sensors, binary sensors, and events | Typed observations and transitions |
| Maintainer | Diagnostic download | Model, source health, and problem classifications |

Current state describes the active robot. History describes a completed
or ended run. The cloud receipt time and provider update time have
separate meanings.

## 4. Goals, non-goals, and fixed invariants

- TEL-01: The integration MUST preserve robot, dock, and entity identities.
- TEL-02: Published readings MUST have a verified source, type, unit, and availability rule.
- TEL-03: Projection MUST distinguish unknown, unsupported, failed, false, and zero values.
- TEL-04: Problem events MUST distinguish detection, code change, and resolution by source.
- TEL-05: Polling MUST separate fast state from slower telemetry and tolerate eligible partial failures.
- TEL-06: Diagnostics and public evidence MUST omit credentials, identifiers, names, floor geometry, and raw documents.
- TEL-07: Connectivity time MUST use the metadata of the field that supplied the connection state.
- TEL-08: Mission history MUST emit one event for each newly observed recognized outcome.

Settings changes, consumable resets, and physical controls have separate
capability and confirmation contracts.

## 5. Current versus proposed product journey

| Surface | Current behavior |
| --- | --- |
| Robot | Status, charge, connectivity, and verified measurements |
| Mission | Reported phase, mode, elapsed time, area, and history |
| Dock | Child device, available controls, maintenance, and problem sources |
| Automations | Entity-based triggers and local mission or problem events |

Additional readings follow the same typed contract and are attached to
their existing device.

## 6. Functional behavior and state model

Fast reads use `ro-currentstate` and `rw-constatus` every 15 seconds
while active and every 60 seconds at rest. The slower group includes
`rw-settings`, `rw-software`, `ro-stats`, and `rw-schedule`. It refreshes
every 300 seconds. Parts refresh every 1,800 seconds. A missing field
leaves its existing entity unavailable. A negative remaining count is
unavailable.

A fresh position batch can supply the last route activity when saved
maps are enabled. Clear that reading when the batch expires or the
mission ends. Publish area values with their verified units. An estimated
cleaning time requires a supported mapped plan and a verified active stage.
[Live maps](008-mission-detail-and-map-card.md)

TEL-07 uses `rw-constatus.metadata.reported.<field>.timestamp`. Prefer a
valid integer `connectedv2`, otherwise use a valid boolean `connected`.
Select the timestamp for that same field. Missing metadata leaves the
timestamp unknown. **Last cloud read** records Home Assistant receipt
time. An explicitly disconnected robot can retain a known provider
connectivity timestamp. Keep the observed `ro-currentstate.lastDisconnect`
field unassigned until its meaning is verified against a transition.

TEL-08 emits `mission_finished` when a new recognized history result is
available. Include mode, result, area, duration, and error fields when
available. Establish a baseline on the first successful read. Restore
the cursor across reloads and deduplicate by finish timestamp. An
unrecognized result or failed read preserves the existing cursor.

## 7. User-facing configuration

Telemetry is attached to the selected devices in the existing entry.
Home Assistant's entity registry controls enabled and disabled entities.
The map option enables eligible live measurements. Settings changes are
available through the separately verified controls.

## 8. Clean Architecture design

`core/telemetry.py` projects typed metrics. `core/problems.py` classifies
faults and their sources. The Home Assistant coordinator owns scheduling
and partial results. Platforms render the typed state. Event entities
track their own baselines and cursors across reloads.

## 9. UI/UX and content contract

Use English translation keys, published units, and explicit availability.
Expose raw numeric codes for unknown provider errors. Keep current
alerts and historical outcomes in distinct sensors and records.

- Pending: A scheduled observation or mission result is still awaited.
- Action required: A reported problem gives a matching code and source.
- Blocked: An unavailable prerequisite prevents a control.
- Partial: Valid fields remain available when an optional read fails.
- Complete: The current reading or a recognized history outcome is available.

## 10. Failure, recovery, and cleanup

A required read failure affects availability as defined by the
coordinator. An optional failure leaves the corresponding data
unavailable and preserves eligible fast state. Resolve a previous fault
only after valid state for the same source confirms the change. Unloading
removes listeners and closes owned work.

## 11. Security, permissions, and privacy

Use validated Roomba data for device observations. Problem and mission
events are local to Home Assistant. Diagnostic documentation uses reduced
evidence and generic examples. Use synthetic responses to test failure
codes and transitions.

## 12. Observability and operational UX

Track current faults by robot or dock source. Recognized dock entities
use the child device while the existing robot event retains its identity.
Expose detected, changed, and cleared states from confirmed source
observations. Keep an unknown source from clearing an earlier warning.

Use `cmd.command` for the last recorded mission command when it is
recognized. The active cycle, live activity, and recorded outcome are
independent observations. History errors describe the recorded mission
and have no effect on guards for the current robot state.

## 13. Compatibility, migration, rollout, and rollback

Home Assistant Core 2026.11.2 and SKU X185240 were tested. Existing robot,
dock, and entity IDs survive updates. Optional fields remain unavailable
where Roomba lacks a matching observation. Roll back using a verified
component release and the existing configuration entry.
[Installation](../docs/installation.md)

## 14. Testing strategy and numeric budget

| Area | Minimum independent cases | Coverage |
| --- | ---: | --- |
| Readings and parts | 25 | Types, ranges, units, and missing data |
| Problem transitions | 20 | Scope, deduplication, and confirmed resolution |
| Home Assistant lifecycle | 20 | Polling, partial failure, entities, and events |
| **Total** | **65** | Independent baseline cases |

The full suite requires 100% statement and branch coverage. Keep
synthetic failure tests separate from the household validation record.

## 15. Documentation and discoverability

The telemetry reference documents source fields and units. Usage gives
examples for alerts and mission events. The installed trials record
the visible Home Assistant state.
[Telemetry](../docs/telemetry.md) · [Usage](../docs/usage.md) ·
[Validation](../docs/validation.md)

## 16. Acceptance scenarios

1. Upgrade a configured account and preserve existing robot and dock IDs.
2. Show valid zero and false without substituting them for missing data.
3. Show reported mission area and elapsed time. Apply the estimate only in supported stages.
4. Preserve a dock fault's source and distinguish it from a robot fault.
5. Emit detection once when the same fault repeats.
6. Emit a code change and a confirmed resolution from the same source.
7. Keep valid fast state when a slow read fails.
8. Reload without repeating prior events or changing entity IDs.
9. Export diagnostics with private fields omitted.
10. Reuse unchanged provider metadata across reads and use the selected field's timestamp after fallback.
11. Emit a late history result once and preserve its cursor across reloads.

## 17. Requirements traceability

| Requirement | Component | Verification |
| --- | --- | --- |
| TEL-01 through TEL-03 | Projection and entity platforms | [Home Assistant telemetry](../tests/ha/test_telemetry_entities.py) |
| TEL-04 | Problem classifier and event entity | [Problem transitions](../tests/ha/test_telemetry_entities.py) |
| TEL-05 | Coordinator | [Scheduling and failures](../tests/ha/test_coordinator.py) |
| TEL-06 | Diagnostics and evidence | [Privacy](../tests/test_architecture_and_privacy.py) |
| TEL-07 | Connectivity projection and timestamp sensor | [Telemetry entities](../tests/ha/test_telemetry_entities.py) |
| TEL-08 | History projection and event cursor | [Mission events](../tests/ha/test_telemetry_entities.py) |

## 18. Implementation sequence

Record the authorized source and establish scope, type, units, and
validity. Add projection and failure tests. Expose the reading through
the existing device and verify it in the normal Home Assistant surface.

## 19. Definition of Done

- [x] Publish typed readings with documented source, units, and availability.
- [x] Preserve existing entities and event baselines through reloads.
- [x] Exercise confirmed events and partial failures with synthetic data.
- [x] Verify the telemetry and active problem surface on the household installation.

## 20. References and decisions

Recorded faults preserve the recognized outcome and last valid reported
error in the mission timeline. The coordinator can retry once when a
mission result appears late, subject to shared provider backoff. The
historical target sensor exposes the kind and number of known destinations.
[Historical fault evidence](../docs/evidence/2026-11-23-schedule-dispatch.json) ·
[Destination evidence](../docs/evidence/2026-11-23-temporary-zone-history.json) ·
[Home Assistant integration](003-home-assistant.md) ·
[Mission detail](008-mission-detail-and-map-card.md)
