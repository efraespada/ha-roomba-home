# Extended Telemetry, Progress and Robot Problems

- Status: Draft
- Date: 2026-11-23
- Catalog capability ID: telemetry-and-problems
- Last verified: 2026-11-23
- Owners: ha-roomba-home maintainer
- Scope: Telemetry, progress, consumables, and problem and mission events.
- Related issues/PRs: Local development requested by the account owner.
- Required review gates: product, UX, architecture, testing, documentation, and security/operations
- Open decisions blocking readiness: None for typed, verified fields.

## 1. Executive summary

The incumbent requests all useful information available from each robot and its progress, as
well with his or her problems being detected. Each robot preserves its HA device. The
addition of sensors, binary sensor and an event entity per robot are added. Each parameter
does not become a separate device

## 2. Problem, current behavior, and evidence

- Observed behavior: 0.1.0 only exposes vacuum, battery and service error code.
- Intentional contract: preserve existing identities and verified physical orders.
- Known debt and limitations: The cloud consultation can omit short transitions, with no
  total percentage or ETA observed.
- Unknown rationale: Not all future supplier code are available.
- Proposed improvements: Expand tipped data, progress or problems without issuing raw
  documents.

The catches have mission, base and adjustments with firmware. They contain statistics as
well at least seven consumables by modern robot The catalogs and types of the official SDK
allow them to contrast consumables names with status code of the dock. The catches and code
extracted remains outside the repository.

## 3. Actors, surfaces, and terminology

| Actor | Surface | Necessity |
| --- | --- | --- |
| Holder | HA device | Consult information and progress |
| Automation | Sensors and event entity | Detect problem, change and resolution |
| Maintainer | Diagnostics | Distinguish data loss, transport and physical damage |

An information setting is read-only. Unknown code isn't confirmed health. A cloud reading
doesn't prove physical presence or freshness of the robot.

## 4. Goals, non-goals, and fixed invariants

- TEL-01: Keep one device per robot and stable entity identities.
- TEL-02: Expose mission, progress, dock, settings, firmware, statistics, and consumables with verified units.
  With saved floor plans enabled, expose the last fresh route activity as an
  enum sensor on the robot. Source the value from the direct position batch
  and clear it when that batch expires or the mission ends.
- TEL-03: Distinguish missing, zero, false, unsupported, and failed reads.
- TEL-04: Emit a distinct detection, change, or resolution for each problem source.
- TEL-05: Poll fast state separately from slow data. Optional failures leave the vacuum usable.
- TEL-06: Keep room names, maps, mission IDs, credentials, and raw documents out of diagnostics and public evidence.
- TEL-07: Expose Roomba's connectivity attribute timestamp.
- TEL-08: Emit one event for each newly observed, recognized result from mission history.

Settings writes, consumable resets, fault clearing, and cleaning controls are
covered separately and require physical evidence.

## 5. Current versus proposed product journey

| Stage | Current | Enlargement |
| --- | --- | --- |
| Watch robot | 4 entities | Entities separated by useful and tested data |
| Following mission | General | phase, cycle and mode with an information area or startup |
| Review Base | Not available | Expand, complete with washing or drying. |
| Maintenance | Not available | Use and quantity remaining per consumable |
| Automate errors | Mission code | Added problem and events by source |

## 6. Functional behavior and state model

Fast reads use `ro-currentstate` and `rw-constatus`. Slow reads use
`rw-settings`, `rw-software`, `ro-stats`, and `rw-schedule`. Consumables use
the signed parts GET and the model's catalog. The active interval is 15
seconds and the idle interval is 60 seconds. Slow data refresh every 300
seconds and consumables every 1800 seconds. The projection declares fields,
types, ranges, and units. Missing fields leave discovered entities registered
with unknown values. Negative remaining counts remain unavailable.

Robot and dock problems are distinguished by source. Events contain the source,
code, and classification. A missing source or disconnected robot does not
clear a previous problem. Unknown codes retain their numeric value.

TEL-07 MUST take the timestamp from
`rw-constatus.metadata.reported.<field>.timestamp`. The selected field is the
same one used for connectivity, preferring valid integer `connectedv2` and using
a boolean `connected` as fallback. The timestamp was observed for three robots.
Missing or invalid metadata leaves the sensor unknown. **Last cloud read**
continues to report receipt time in Home Assistant. The connectivity update
sensor reuses the existing shadow read. The integer `ro-currentstate.lastDisconnect`
was observed with the same value for two devices. Its meaning still needs
verification against a connectivity transition.

TEL-08 MUST emit `mission_finished` when a newer result with a recognized
outcome is observed. Its attributes include the result, modes, area, duration,
and error code when present. The first successful read establishes a baseline.
The entity restores its history cursor across reloads and uses the finish
timestamp to deduplicate older or repeated reads. A failed read or a result
with no recognized outcome leaves the previous cursor in place.

## 7. User-facing configuration

The existing account and selection are preserved. No need to reconfigure robots. The
extension adds entities under current arrangements. The adjustments are presented as
information sensors with no controls involving unvalidated textures. The user can disable
entities from the HA registry.

## 8. Clean Architecture design

The core projects fields and classifies problems regardless of HA. The orchestral
coordinator sources, cadences and partial faults. The platforms translate this projection
into an entity. The event entity retains its base line between recharges and does not
interpret supplier's document on their own.

## 9. UI/UX and content contract

Entity names use English. Fields with unverified meanings retain their code labels.
Operating and diagnostic data are separated. The area is expressed as m² and no figure of
complete or ETA. The events allow automations by entity and source of the problem.

## 10. Failure, recovery, and cleanup

A status defect MQTT affects availability. A malfunction of consumables or adjustments leave
these values unknown and retries at his next window without concealing the valid fast
status. Session limits and expires. Rearm and download remove listeners, close jobs as in
the initial version.

Recovery from a source does not result in false resolution if the data that demonstrated
this problem remains missing.

## 11. Security, permissions, and privacy

No authentication destinations and credentials are added to the public catalogue. No actual
documents, names or IDs are included in tests and guides. The events belong to local HA and
do not send messages with mobile phones, mail or other outside destinations. The
implementation does not cause physical malfunctions to prove them.

## 12. Observability and operational UX

Each robot has an added problem and event with source or code. The bug sensors retain the
supplier's number. The diagnoses show quantity of metric and available sources with no
account data. The report distinguishes actual readings and error tests with synthetic data.

A recognized base MUST have its own child device event entity with basic code and
maintenance of their consumables. The existing event of the robot MUST will preserve his or
her identity and all its origins. A state other than a component and an explicitly
incompatible capacity MUST will be out of its diagnosis. A valid status transition from that
same component can solve an earlier event.

The order of last cleanup MUST come from `cmd.command` from the registered mission. A known
code is published and an entity's availability remains. The live cycle and track command are
independent reading. The coordinates and map identifiers are excluded from historic
telemetry.

## 13. Compatibility, migration, rollout, and rollback

HA 2026.11.2 and SKU X185240 That's the initial range. Do not change the config entry
version and existing unique_id versions. It installs itself about 0.1.0 with copies of
rollback, configuration check Reinitiation and review of domestic HA entities. The first
version's evidence retains its original quantity and date.

## 14. Testing strategy and numeric budget

| Area | Minimum new cases | Risk |
| --- | ---: | --- |
| Projection of telemetry and parts | 25 | Types, ranges and units with privacy or absent fields |
| Classification and transitions of problems | 20 | Duples, unknown code and false resolution |
| HA and Coordination | 20 | Partial availability, cadences and events |
| Total | 65 | Other cases, additional to the existing suite |

100% cover of judgements and branches in the complete component; full suite, Ruff with
Hassfest's privacy or catalogue. Reactual reading of the three robots and monitoring for
upgrade at domestic HA. Physical malfunctions are simulated in Harness.

## 15. Documentation and discoverability

Updating README, use and installation of an API with architecture. Add entity inventory and
problem automation examples with generic identifiers. To register this SDD and all its
evidence in the catalogue.

## 16. Acceptance scenarios

1. Updating preserves all three devices and the original twelve entities.
2. A field absent does not become zero or miss.
3. Progress shows an area and information start with no percentage invented.
4. A basic problem isn't attributed to the robot's engine.
5. To repeat the same error in ten consultations produces a single event of appearance.
6. Switching code produces a change and explicit normal phone production.
7. An optional defect does not invalidate the vacuum or erase a known error.
8. Reloading preserves entity identities and does not repeat active alerts.
9. Diagnostics and package do not contain private data of the campaign.
10. Repeating a read does not change the connectivity timestamp. The legacy
    boolean uses its own metadata. Explicitly disconnected robots can report
    their last update.
11. A late, recognized history result emits once. Reloading or reading the
    same mission again preserves the event state and does not re-emit it.

## 17. Requirements traceability

| Requirement | Expected implementation | Evidence |
| --- | --- | --- |
| TEL-01/02 | Projection, Platforms and Device Record | Test of entity and actual installation |
| TEL-03 | Pure Valids and Optional Sources | Type and partial failure tests |
| TEL-04 | Clasifier and event entity | synthetic HA transitions |
| TEL-05 | Coordinator | Controlled clocks and actual reading |
| TEL-06 | Extent and diagnostics | Scanner and testing with lure fields |
| TEL-07 | Metadata projection and timestamp sensor | Captures, precedence and fallback tests, and disconnected sensor test |
| TEL-08 | Per-robot mission event | Synthetic history updates, missing outcomes, cancellation, errors, and reload |

## 18. Implementation sequence

To inventory evidence, to project fields and select problems. No robots are modified to
create deliberate mistakes during this campaign.

## 19. Definition of Done

- [x] Inventory of data and documented entities with provenance or boundaries.
- [x] Expand fields, consumables with problems implemented.
- [x] Unduplicated events with maintenance between reloads, tested.
- [x] Retirement and quality monitoring budget.
- [ ] Controlled domestic update and well-known evidence.

## 20. References and decisions

The historic diagnosis is obtained from the last mission of his robot itself. The parser preserves `done=stuck` and the last valid code of `timeline.finEvents` with `type=error`. That track record has its own sensors and does not participate in the blocking of orders by current faults. [Evidence of an error that persists in the record](../docs/evidence/2026-11-23-schedule-dispatch.json)

When detecting the end of a mission, integration looks at his or her robot's history and retries once if registration isn't shown. The retirement period of the account with a demand limit is respected. The target sensor exposes only the classification and number of known regions. [Evidence of destination and error](../docs/evidence/2026-11-23-temporary-zone-history.json)

[API observed](../docs/api.md), [HA adapter](003-home-assistant.md), [SDD standard](README.md), [HA event entities](https://contributors.home-assistant.io/core/entities/event/). Standard dataset entities are chosen to provide a record and automations, with the supplier's private documents not becoming generic attributes.

Per-room history follows MAP-01. [Mission detail and interactive maps](008-mission-detail-and-map-card.md)
