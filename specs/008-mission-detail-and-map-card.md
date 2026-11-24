# Mission Detail and Interactive Floor Maps

- Status: Draft
- Date: 2026-11-24
- Catalog capability ID: mission-detail-and-map-card
- Last verified: 2026-11-24
- Owners: ha-roomba-home maintainer
- Scope: Per-room results, live progress, physical scenario verification, and map-based cleaning selection.
- Related issues/PRs: Local development and authorized household validation.
- Required review gates: product, UX, architecture, testing, documentation, and security/operations
- Open decisions blocking readiness: Provider evidence for remaining time, global coverage, and outstanding physical scenarios.

## 1. Executive summary

Users can inspect reported room results and select where to clean from a Home
Assistant dashboard. Live progress uses the current Roomba mission. Movement
requires explicit confirmation and the existing command guards.

## 2. Problem, current behavior, and evidence

Version 0.11 exposes a saved image, sampled position and room, and aggregate
mission history. Roomba history includes finished room events. Captured live
timeline reports matched the active mission and included start and relocation.
The captures contain neither an active remaining-time value nor a mission-wide
coverage denominator. The planned room estimate is a separate API.
[Sanitized evidence](../docs/evidence/2026-11-24-live-progress.json)

## 3. Actors, surfaces, and terminology

| Actor | Surface | Goal |
|---|---|---|
| Household operator | Dashboard map | Inspect the floor and confirm a room or saved-zone selection |
| Automation author | Sensors and actions | Read valid room outcomes and live mission detail |
| Maintainer | Sanitized evidence and test suite | Verify source semantics and device behavior |

A room result is a Roomba room event scoped to a map revision. The live
trajectory contains observed positions and retains sequence gaps.

## 4. Goals, non-goals, and fixed invariants

- MAP-01: Expose room outcomes, pass counts, and provider area fields from mission history.
- MAP-02: Improve continuity of the observed path and correlate live timeline reads with the current mission.
- MAP-03: Physically verify sequential cleaning, a saved-zone run, and recharge with automatic resume.
- MAP-04: Provide zoom, room and zone selection, keep-out overlays, and explicit confirmation in a standard dashboard card.
- All device data MUST originate from Roomba. Home Assistant supplies permissions, presentation, and automation.
- Screenshots and fixtures MUST use synthetic house data.

## 5. Current versus proposed product journey

| Stage | Current | Proposed |
|---|---|---|
| Review a run | Aggregate mission values | Per-room outcomes and reported values |
| Follow a run | Short MQTT sample and static image | Longer position collection and typed live timeline |
| Choose where to clean | Select service identifiers | Select regions on a map or from its keyboard-accessible list |

Text equivalent: open the card → inspect the current map → select regions →
review the selection → confirm → observe the resulting state.

## 6. Functional behavior and state model

Treat `timeline.finEvents[]` room events as final history observations. A
later event for the same room revision supersedes an earlier event. Match
labels only by Roomba map ID, version, and room ID. Preserve useful values when
the label is unavailable. Keep unknown provider codes visible without assigning
a meaning. Area fields retain provider units until their unit is verified.

Position collection MUST retain bounded point counts, honor provider expiry,
and stop on unload or mission change. A live timeline report MUST be associated
with the active robot and mission number. Query and report correlation prevents
stale replies from changing current telemetry. Preserve in-progress room
measurements from `event` separately from final results in `finEvents`.
Coverage and remaining time require corroborated fields and behavior during
pause, return, and recharge.

The card may show each associated map. Live position and track require a
verified map association. Select only supported rooms and saved zones. A
keep-out region is informative. Confirmation lists the chosen robot and targets.
The backend revalidates current map versions, permissions, and readiness.

## 7. User-facing configuration

The existing account map option enables its geometry and private live data.
The dashboard card is optional and requires a Roomba vacuum entity. Selecting
a different map clears staged regions. Updating the map version invalidates a
staged confirmation. Existing actions, entities, and preferences retain their IDs.

## 8. Clean Architecture design

The core projects room events and live MQTT data and interprets associated
map geometry. The coordinator owns polling, expiry, and permission-scoped
snapshots. The authenticated Home Assistant interface exposes typed drawing
data. The card renders and submits confirmed selections through validated
Home Assistant actions.

## 9. UI/UX and content contract

Use readable labels, a floor selector, zoom controls, and a separate region
list for keyboard use. Distinguish selected regions and keep-out geometry
with text and styling. Provide explicit empty, unavailable, stale, and
unconfirmed states. Refresh the plan and preserve a valid selection during
routine position updates.

## 10. Failure, recovery, and cleanup

Optional history, timeline, and geometry failures leave standard device
control available. Respect provider backoff. Expired positions clear the current
marker and room. Disconnect live listeners and release memory on integration
unload. A timed-out command does not cause another movement request.

## 11. Security, permissions, and privacy

Authenticate geometry requests and enforce entity read permissions. Cleaning
requires entity control permissions and a valid selected map revision.
Floor plans, names, raw IDs, and movement traces are private to Home Assistant.
Source fixtures and published screenshots use synthetic geometry and names.

## 12. Observability and operational UX

Expose history and current position through existing Home Assistant surfaces
and typed map data. Log source classifications and aggregate measurements.
Record command confirmation, final state, and scenario limits in public
evidence without household names.

## 13. Compatibility, migration, rollout, and rollback

Support the existing validated model and Home Assistant version. Preserve
existing account and entity registry entries. Validate an upgrade, keep the
previous component as rollback, and verify the household integration after
restart before operating the two authorized robots.

## 14. Testing strategy and numeric budget

| Check | Required evidence |
|---|---|
| Room parsing | Duplicates, unknown codes, zero values, units, and exact map revision |
| Live data | Retained, invalid, expired, unmatched, late, and bounded messages |
| Dashboard | Click and keyboard selection, zoom, exclusions, confirmation, and stale maps |
| Household | Complete sequential cycle, saved zone with matching history, and automatic recharge and resume |

The existing statement and branch gates apply. A physical scenario receives a
verified status only after its acceptance evidence exists.

## 15. Documentation and discoverability

The README links to setup, map configuration, telemetry, and evidence. Include
real frontend renders populated with synthetic data. The capability matrix
distinguishes features, data still unverified, and physical results.

## 16. Acceptance scenarios

1. Read a completed mission and see the last known result for each reported room.
2. Observe fresh positions and active mission detail with expiry and no cross-mission carryover.
3. Start a confirmed room selection and observe provider state. Reject unknown, excluded, or stale choices.
4. Observe vacuuming, mopping, the same mission identity, and a final outcome.
5. Observe a saved-zone mission with the matching history destination and return.
6. Observe a low-battery return, charging, and automatic resumption of the same mission.

## 17. Requirements traceability

| Requirement | Related specification | Validation |
|---|---|---|
| MAP-01 | [Telemetry](005-telemetry-and-problems.md) | [History parser tests](../tests/test_history.py) and [telemetry](../docs/telemetry.md) |
| MAP-02 | [Capabilities](007-device-capabilities.md) | [Transport tests](../tests/test_mqtt.py) and [active timeline evidence](../docs/validation.md#mission-detail-and-dashboard-validation) |
| MAP-03 | [Profiles](006-cleaning-profiles.md) and [capabilities](007-device-capabilities.md) | [Household validation](../docs/validation.md#mission-detail-and-dashboard-validation) |
| MAP-04 | [Home Assistant](003-home-assistant.md) | [Authenticated endpoint and command-scope tests](../tests/ha/test_roomba_map_api.py) and [card screenshots](../README.md#floor-plan-dashboard) |

## 18. Implementation sequence

Project historical records. Extend observed live data and validate the read
path. Build the dashboard card and guard map selection. Verify with synthetic
fixtures before compiling an install package and starting physical trials.

## 19. Definition of Done

- [x] Pass the automated contract, integration, privacy, and frontend checks.
- [x] Verify the installed package and update the README with screenshots.
- [x] Record actual physical evidence or the concrete reason a scenario could not be verified.
- [x] Keep unsupported metrics and commands out of the advertised capability set.

## 20. References and decisions

[Home Assistant custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/) ·
[Observed Roomba API](../docs/api.md) · [Current validation](../docs/validation.md) ·
[Proposed map zone editor](009-map-zone-editor.md)
