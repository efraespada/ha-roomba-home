# Implementation report

Roomba Home for Home Assistant connects to the modern Roomba Home service
and exposes its associated robots, docks, maps, and cleaning programs.
The integration uses Roomba account data, signed reads, and reported
robot state. The floor plan card provides controls for already paired
robots. [Architecture](architecture.md) · [API contract](api.md)

## Verified hardware

| Model | Observed inventory | Recorded evidence |
| --- | --- | --- |
| X185240, Max 700 Combo | Three robots with recognized docks | Vacuuming, mopping, simultaneous cleaning, and a directed vacuum-then-mop sequence. Associated maps, history, schedules, consumables, and live mission state. |
| R981040 | One account association | The modern transport remains unverified. Setup excludes this model. |

The model matrix separates each observed capability, integration surface,
and physical trial. Features that depend on a compatible dock, map, or
software revision use the reported capabilities and availability.
[Capabilities and evidence](capabilities.md)

## Home Assistant surfaces

| Surface | Implementation |
| --- | --- |
| Robot device and `vacuum` entity | Standard start, pause, stop, return, locate, fan speed, and supported area cleaning. `vacuum.start` resumes a paused mission. |
| Dock child device | Supported manual emptying, washing, drying, stopping drying, and refill. Dock settings, status, counters, and problem events use the appropriate dock reports. |
| Robot configuration entities | Next-mission preferences and independently reported robot defaults. Supported controls include mode, suction, wetness, SmartScrub, two passes, carpet boost, voice, volume, name, and child and pet lock. |
| Floor plan card | Live position and route, mode-specific estimated coverage, mission summary and controls, room and zone selection, furniture, map settings, restrictions, and 2D and 3D views. |
| Cleaning programs | Saved routines and weekly or one-time schedules. Compatible drafts retain area order and individual settings for rooms, saved zones, and furniture. |
| Recorded reports and backups | Signed reports with archived paths, coverage, targets, and timeline. Local floor backups with preview, export, and recovery of supported edits. |

To mop, select `mop` as the next cleaning mode and run `vacuum.start`.
Compatible robots also offer simultaneous and sequential vacuuming and
mopping. For directed cleaning, review the map and choose each destination's
profile in the card. [Usage and examples](usage.md) ·
[Telemetry entities](telemetry.md)

## Boundaries and confirmation

The core projects vendor responses into typed models. The Home Assistant
coordinator shares account reads and serializes writes per robot. The
motion-control use case distinguishes the MQTT acknowledgement from the
robot's resulting state. Map and program edits verify the reviewed revision
and confirm the result through a fresh signed read. A replacement mission
invalidates the previous card review. [Architecture](architecture.md) ·
[Control specification](../specs/004-command-validation.md) ·
[Map specification](../specs/008-mission-detail-and-map-card.md)

Unavailable diagnostics stay unknown. Reported zeros remain valid readings.
Problem events preserve robot, dock, and firmware sources. Published
verification excludes private account data and uses cropped documentation
images that omit home geometry and device identifiers.
[Privacy policy](../SECURITY.md)

## Verification highlights

- Household installation of 0.10.0 registered three robots, three docks,
  and 470 entities. Version 0.11.0 enabled maps and verified position,
  room, trajectory, and return from a physical cleaning run.
  [Installation evidence](validation.md#home-installation-of-0100) ·
  [Live map evidence](validation.md#home-installation-and-live-map-test-of-0110)
- Physical tests established vacuuming and mopping transitions, resume,
  cancellation, and return. Later directed trials completed an ordered
  furniture sequence and vacuum-then-mop under one mission identity.
  [Physical sequences](validation.md#physical-control-sequence) ·
  [Ordered furniture evidence](evidence/2026-11-25-ordered-furniture-completion.json) ·
  [Sequential cleaning](validation.md#directed-vacuum-then-mop)
- A physical point-cleaning request was confirmed by the exact coordinates
  and map revision in signed history. A separate temporary-zone attempt
  reached the target workflow and recorded navigation error 48. The live
  error returned to zero after docking and history retained the failure.
  [Point evidence](evidence/2026-11-23-point-clean.json) ·
  [Temporary zone evidence](evidence/2026-11-23-temporary-zone-history.json)
- Signed reads and writes matched scheduled furniture and room destinations,
  individual profiles, and order. The schedule trial retained the exact
  furniture identifier in the final report. [Scheduling](validation.md#scheduled-furniture-cleaning)
- Roomba's Smart cleaning recommendation matched the Android selections.
  The physical mission summary trial recorded 87 distinct positions, and
  the household install verified that the summary clears at rest and showed the amber
  recommendation overlay. [Current mission](validation.md#current-mission-readout) ·
  [Recommendation comparison](validation.md#quick-routines-and-smart-recommendations-on-the-floor-plan)
- The installed 0.79.0 card paused, resumed, and canceled one physical
  furniture run, then returned the robot to its dock. An unfiltered
  Roomba history read confirmed the canceled report and exact target.
  [Household mission control evidence](validation.md#reviewed-mission-controls)

## Open verification

Physical verification still includes automatic recharge and resume, the
physical effect of remaining regional settings, and the conditions that
trigger dock emptying at a selected area threshold. The Max 700 Combo's
full-floor recovery and device provisioning workflows require separate
vendor verification. The physical spot command triggered by the robot's
button and the app's map-based point command have separate contracts.
[Pending verification](capabilities.md#pending-verification) ·
[Roadmap](roadmap.md)
