# Mission Detail and Interactive Floor Maps

- Status: Draft
- Date: 2026-11-24
- Catalog capability ID: mission-detail-and-map-card
- Last verified: 2026-11-26
- Owners: ha-roomba-home maintainer
- Scope: Per-destination results, live progress, physical scenario verification, and map-based cleaning selection.
- Related issues/PRs: Local development and authorized household validation.
- Required review gates: product, UX, architecture, testing, documentation, and security/operations
- Open decisions blocking readiness: Household verification of continuous positions and live overlays, independently published live coverage, timing across interrupted stages, and outstanding physical scenarios.

## 1. Executive summary

Users can inspect reported results by destination and select where to clean from a Home
Assistant dashboard. Live progress uses the current Roomba mission. Movement
requires explicit confirmation and the existing command guards.

## 2. Problem, current behavior, and evidence

Version 0.11 exposes a saved image, sampled position and room, and aggregate
mission history. Roomba history includes finished room events. Captured live
timeline reports matched the active mission and included start and relocation.
The captures contain neither an active remaining-time value nor a mission-wide
coverage denominator. The planned room estimate is a separate API.
[Sanitized evidence](../docs/evidence/2026-11-24-live-progress.json)

The Max 700 Combo published separate travel and vacuuming samples during a
localized run. The live route uses those reported activities and keeps gaps
between batches. A compressed live snapshot contained earlier route samples
with matching modes and a different coordinate origin. The integration
matched overlapping samples to recover the earlier route on the same
floor. It retained the most recent incremental position for the marker.
[Live route evidence](../docs/evidence/2026-11-25-live-route-backfill.json)

Localized mopping and simultaneous vacuuming and mopping supply distinct
activity values in the position stream. Compare those samples with the
archived route of the same mission.
[Wet-cleaning validation](../docs/validation.md#wet-cleaning-route-activity)

Live and final saved-zone and furniture outcomes resolve the name using
the associated map revision from the mission command. The installed card
displayed the named furniture target while Roomba advertised a different
active revision. The same resolution applies to saved-zone names from the
archive, including zones removed after a mission.
[Installed validation](../docs/validation.md#directed-vacuum-then-mop)

MAP-03 now has physical evidence for a completed directed sequence and a
saved-zone run. The automatic recharge and resume scenario still needs a
complete observed mission.

The floor plan offers a reviewed skip when the current mission identifies
the active destination. Room and zone results show the reported skip once
the robot has skipped the area. [Command policy](004-command-validation.md) ·
[Physical validation](../docs/validation.md#skip-the-current-destination)

## 3. Actors, surfaces, and terminology

| Actor | Surface | Goal |
|---|---|---|
| Household operator | Dashboard map | Inspect the floor and confirm a room or saved-zone selection |
| Automation author | Sensors and actions | Read reported area outcomes and live mission detail |
| Maintainer | Sanitized evidence and test suite | Verify source semantics and device behavior |

A room result is a Roomba room event scoped to a map revision. The live
trajectory contains observed positions and retains sequence gaps.

## 4. Goals, non-goals, and fixed invariants

- MAP-01: Expose room, zone, and furniture outcomes, pass counts, and provider area fields from mission history.
  For a saved zone correlated to the mission command, expose its target
  size and the sum of reported area across confirmed passes in square
  metres alongside the raw fields. Count each pass index once and preserve
  unknown area when a confirmed pass has no valid measurement.
- MAP-02: Improve continuity of the observed path and correlate live timeline reads with the current mission.
- MAP-03: Physically verify sequential cleaning, a saved-zone run, and recharge with automatic resume.
- MAP-04: Provide zoom, room, zone, and furniture selection, keep-out overlays,
  and explicit confirmation in a standard dashboard card. Bulk room selection
  preserves the current order and adds missing rooms in map order. Clearing
  the room selection preserves zones and furniture. Link each selectable
  furniture footprint to its reviewed cleaning outline.
- MAP-05: Offer an optional 3D map from the reported wall layer. Keep room
  and zone selection, live positions, and detected features aligned when
  the camera rotates. Indicate when a fresh position is on mapped carpet.
- MAP-06: Show the reported center and mode of a current point-cleaning mission on the associated map revision.
- MAP-07: Browse recent cleaning reports, including numerical results and archived coverage, trajectories, and timelines.
  Include the recorded end of the run and the reported codes for robot
  errors, bin emptying, mop washing, and refill. Preserve the distinction
  between an explicit dock error code of zero and an unavailable code.
  Keep the reported evacuation count separate from the bin emptying stage.
- MAP-08: Read the active floor revision's room scores and suggested settings.
  Offer an overlay for the current Roomba recommendation. Match its exact
  room IDs and label them in the legend independently of cleaning selection.
- MAP-09: Show directed mission destinations, declared order, requested modes, and reported destination outcomes with a completion count.
- MAP-10: Estimate the remaining time for the applicable work in a directed mission using the provider's durations and verified live stage.
- MAP-11: Receive the authorized robot's live position updates continuously and deliver them to the displayed map. Show cleaned areas by the activity reported by Roomba.
- MAP-12: Show and hide provider-reported temporary obstacles on the live floor plan for the current mission and floor revision.
- MAP-13: Follow the confirmed mission floor when a robot has several saved maps. Allow the viewer to keep a chosen floor in view.
- MAP-14: Show saved zones, restrictions, and room labels from the exact
  archived revision. Offer separate controls for archived cleaning and
  travel paths and coverage. Keep the final recorded position visible.
- MAP-15: Show explicit requested settings and the reported pass count
  for each destination in the correlated live plan. Show time in the
  current cleaning stage when a valid timestamp identifies one active
  destination. Accumulate confirmed cleaning intervals across passes
  and hold the timer during a pause. Expose confirmed saved-zone
  completions separately from the provider's raw pass index.
- MAP-16: Show the ordered or unordered destinations originally requested
  in a directed cleaning report, including explicit settings and the final
  outcome and validated cleaning time for each destination.
- MAP-17: Offer a confirmed untargeted start with next-cleaning preferences
  for an idle or docked robot, including before its first saved floor.
- MAP-18: Support pinch-to-zoom and panning on live and recorded maps.
  Drag the 3D view at fit or when zoomed and provide arrow-key panning.
  Preserve dashboard scrolling over a fitted overhead map. Treat a tap
  as area selection only if it belongs to the current floor and stayed
  within the tap threshold.
- MAP-19: Show the selected robot's current mission phase, mode, time
  since start, and reported cleaned area above its floor plan. Keep the
  summary available without a saved floor or a correlated destination plan.
  Omit missing readings and clear the summary at mission end or disconnect.
- MAP-20: Offer pause, explicit resume, cancellation, and return from the
  floor plan to users with vacuum control permission. Bind the operation to
  the reviewed mission and recheck the current phase before publishing.
  Confirm cancellation and return in the card. Keep controls available to
  an identifiable mapping run before the first floor has been saved. Offer
  return after cancellation while Roomba reports an identifiable idle state
  off the dock.
- MAP-21: Offer an explicit history option to include short canceled manual
  runs from the signed Roomba history query. Keep the app-filtered view as
  the default. Use the same robot scope and archive validation for both
  views and keep a canceled report's outcome and original target intact.
  Preserve a selected report when it is present after changing the option.
  Recalculate the totals from the displayed list and discard late results
  when the option, selected robot, or open report changes.
- MAP-22: Offer a 30-day history window using Roomba's signed `maxAge`
  query. Default to ten days. Use the selected period for both the list
  and report detail and combine it with the short-cancellation option.
  A window describes the request period. Display the reports Roomba
  returns within the selected scope.
- All device data MUST originate from Roomba. Home Assistant supplies permissions, presentation, and automation.
- Fixtures use synthetic house data. Installed interface screenshots show only the relevant controls and values without private geometry or identifiers.

## 5. Current versus proposed product journey

| Stage | Current | Proposed |
|---|---|---|
| Review a run | Aggregate mission values | Per-room outcomes and reported values |
| Follow a run | Short MQTT sample and static image | Longer position collection and typed live timeline |
| Choose where to clean | Select service identifiers | Select regions on a map or from its keyboard-accessible list |

Text equivalent: open the card → inspect the current map → select regions →
review the selection → confirm → observe the resulting state.

## 6. Functional behavior and state model

Treat `timeline.finEvents[]` room and zone events as final history observations.
A later event for the same destination supersedes an earlier event. Scope
room labels by Roomba map ID, version, and room ID. Resolve furniture from
the same mission command's polygon link and map ID. Use its requested
user revision to label the object, even if Roomba has activated a newer
revision. Preserve measurements when a label is unavailable. Keep unknown
provider codes visible without assigning a meaning. Area fields retain
provider units until their unit is verified.

Open the cleaning history through the card. List recent cleaning missions
for the selected robot and preserve numerical results when their archives
are absent. When a report is selected, fetch only a map revision referenced
by that report. Keep trajectory segments and mode-specific coverage in
their original coordinates. Pan, zoom, and rotate the report independently
of the current floor view.

With saved floor plans enabled, expose room scores in the card and a
response-only action. Require read access to the linked vacuum. Resolve
rooms on the selected active floor and require the reply to match its map
ID and revision. Preserve the score on Roomba's original scale, including
zero, and label mission timestamps as part of the score record. Display
suggested settings for review. Return an empty list when the current
revision has no scores. Discard a delayed reply when the card switches
floors or revisions.

Read the current native recommendation through the floor-scoped routine
list. Highlight the rooms in its `CLEAN_DIRTY` command. Preserve the
existing selection, describe the highlighted rooms in text, and clear the
overlay on a floor, revision, or inventory change. A late response cannot
restore a cleared layer. [Recommendation validation](../docs/validation.md#recommended-rooms-on-the-floor-plan)

Position collection MUST retain bounded point counts, honor provider expiry,
and stop on unload or mission change. Label travel, vacuuming, mopping, and
simultaneous activity from verified provider modes. Use the same activity
colors in the card and floor image. Render unrecognized mode values using
the generic route color. Draw connections only between consecutive indices
and keep the legend consistent with rendered segments. Recover earlier
missing indices when a fresh snapshot on the authorized robot's live topic
matches the current mission and floor through multiple coordinate and mode
anchors. Bound each download, decoded route, and retry frequency. Continue
using direct position batches for the marker, room, activity sensor, and expiry. A live
timeline report MUST be associated with the active robot and mission
number. Display the provider's start time for its recognized current stage
when the timestamp belongs to the active mission. Query and report correlation prevents
stale replies from changing current telemetry. Preserve in-progress area
measurements from `event` separately from final results in `finEvents`.
Collect explicitly requested timelines independently of shadow completion
and position sampling. Keep accepted state when a timeline reaches the
shared MQTT deadline without a matched reply.
Compute elapsed seconds fresh for floor-plan reads during an active
room or zone stage with one matching destination. Hide this time during a
pause or travel and when the start time is missing or out of scope.
Use the complete correlated area sequence for the destination's elapsed
cleaning time. Merge overlapping area intervals and exclude overlapping
recorded pauses, recharge, and pad washes. Freeze an open area at the
pause timestamp and recover earlier passes when a viewer joins late.
Use elapsed cleaning time for the directed-room countdown when available.
Archived plans sum closed intervals from the same mission.
Count distinct saved-zone pass indexes from completion events that
correlate to the requested destination. Require an observed completed
index zero before reporting a confirmed total. Preserve the raw index.
During a verified zone stage, expose the current pass number for its
single open saved-zone event. Number the passes starting at one and keep
the completed count separate. Omit the current pass number when the
stage, event, or pass index is unavailable or cannot be associated.
Coverage requires a verified coordinate association and evidence of the
layer's activity semantics. During a mission, maintain an authorized position
subscription when possible. Draw each valid report on the matching floor and
preserve unobserved gaps. The marker must stop advancing when updates stop
and expire at the provider deadline.
With several saved floors, bind live data to the exact user revision
requested by the correlated command, or to the current saved revision of
the floor confirmed by relocalization. Keep the binding for the mission
across gaps in timeline delivery. Withhold the live view when the floor
is ambiguous or the bound revision changes. Use the active floor by
default. Keep manually selected floors and drafts in view until the
viewer switches floors or closes the draft.
Use a stable, separately authenticated client identity for the live
positions. Keep the existing state and timeline polling available during
stream failures. Tolerate the same bounded clock difference in the transport
and in the mission scope checks. Deliver map-scoped deltas only to
authorized clients. Animate consecutive positions, including intermediate
samples within a batch, across the observed provider intervals of up to six
seconds. When a new position interrupts an animation, continue from the
displayed position along the remaining reported legs. Bound animation to
1.8 seconds per update, honor reduced motion, and preserve gaps in the
reported trail.

Show the robot-wide mission summary separately from floor-scoped overlays.
Use the same wall-clock elapsed time as the existing mission sensor. Retain
a reported zero area, show a nonzero error code when available, and clear
active values when the robot has no active cleaning cycle or disconnects.

Show estimated live coverage from mode-tagged positions using a calibrated
footprint for each cleaning mode. Mark only known cleaning positions and
connect adjacent points of matching activity within a plausible travel
distance. Keep vacuum and mop data independently selectable. Accumulate
coverage after older route points scroll out of the visible trail and
recover additional footprints from an anchored raw snapshot. Clip the
display to room outlines and clear it when the mission or revision changes.
Keep the estimate distinct from archived native coverage polygons.

In a historical report, read saved zones and restrictions from the mission
archive. Retain each route segment and its ordering. Offer controls only
for present route or coverage layers and preserve the toggles through a
camera change. Keep the final recorded position and map restrictions
visible when a route layer is hidden.

Project a historical directed command through the same destination policy
as a live command. Use final events to report the outcome of each requested
destination. If an archived name is missing, consult the exact command
revision only for the same floor. Keep the plan and measurements readable
when a map archive is unavailable.

The **Clean everywhere** action confirms the robot and uses the untargeted
start command. The provider receives its next-cleaning profile. The action
needs a fresh idle or docked state and rejects a paused or active mission.

Draw temporary Roomba obstacles in an independent layer. Project the
points only when recent direct positions substantiate the snapshot's
coordinate frame. Accept a stable cluster of at least five recent anchors
for obstacle placement when Roomba has revised older route positions.
Recover missing route points only when all overlapping direct positions
agree. Accept the declared route prefix when a snapshot has extra samples.
Expire obstacle markers after 60 seconds or on a different mission or
floor revision. Publish replacement sets only to authorized map viewers.

Project the destinations in a correlated `start` command when it names a
specific map revision and includes a valid destination list. Preserve the
command's sequence and label it as ordered for a single destination or when
Roomba sets integer `ordered=1`. Show known requested modes independently
of physical route activity. Project explicit validated command preferences
after merging shared and regional values. Preserve booleans and zero pass
counts. Show the most relevant current or finished event's pass count
separately from the requested settings. Associate the current travel or cleaning
stage with the matching destination and count only final status `0`.
Represent skip, partial, and more-pass outcomes separately. Clear the
card on a revision mismatch, a mission change, or timeline expiry.
Expose the count and destination statuses without provider identifiers.

Room results from the matched command may carry the robot's internal
revision. Associate a declared room on the same floor with the command's
user revision. Resolve remaining work from its confirmed requested profile
and Roomba's room estimates. Subtract elapsed active room time when the
stage and destination agree. Keep completed and skipped destinations out
of the remaining sum. Omit the countdown during interrupted stages, on an
expired report, or while any remaining destination lacks a verified estimate.
Recalculate on each floor-plan read from existing verified stage times and
saved durations. Reading the countdown requires no additional provider
request and leaves the coordinator snapshot intact.

The card may show each associated map. Live position and track require a
verified map association. Select only supported rooms and saved zones. A
keep-out region is informative. Confirmation lists the chosen robot and targets.
The backend revalidates current map versions, permissions, and readiness.

An associated archive may provide walls, detected carpet, and dock points as
optional display layers. Omit malformed layers independently and retain all
valid rooms and overlays. Project live carpet membership from the latest
valid position and the active revision's carpet polygons. Expose an unknown
reading when no carpet layer is available, the position is outside mapped
rooms, or the position expires. A 3D view requires a reported wall segment. Leave
reported doors open. Render a raised approximation of walls and furniture
from their two-dimensional geometry. Project live positions, the observed
route, and selectable areas with the same map-to-screen transform. Furniture
visibility is user-controlled.

A correlated current timeline may contain a `point_clean` command. The card
projects its center in the same coordinate system as the path and shows the
reported mode. Expose this data only through the authenticated floor-plan
response. Clear the marker on timeline expiry, mission change, or a mismatch
between the viewed map revision and the command.

## 7. User-facing configuration

The existing account map option enables its geometry and private live data.
The dashboard card is optional and requires a Roomba vacuum entity. Selecting
a different map clears staged regions. Updating the map version invalidates a
staged confirmation. Existing actions, entities, and preferences retain their IDs.
The 3D toggle, camera rotation, pan, and zoom belong to local viewport
state. Adjust saved floor orientation through the floor editor. The card
uses its overhead view during geometry edits and resumes the chosen view
when the editor closes.

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
control available. Respect provider backoff. Expired positions clear the
marker, room, and route activity sensor. Disconnect live listeners and release memory on integration
unload. A timed-out command does not cause another movement request.

## 11. Security, permissions, and privacy

Authenticate geometry requests and enforce entity read permissions. Cleaning
requires entity control permissions and a valid selected map revision.
Resolve historical report keys against the selected robot's mission list
before requesting an archive. Exclude raw map and mission identifiers and
unprojected commands from the report response.
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
| Live data | Retained, invalid, expired, unmatched, late, and bounded messages. Verify travel, vacuuming, mopping, and simultaneous activity against the same mission's archive. |
| Dashboard | Click and keyboard selection, bulk room selection, furniture footprint and outline, ordered confirmation, zoom, exclusions, and stale maps |
| 3D view | Optional layer decoding, wall gaps, supported map detection, camera alignment, furniture visibility, and flat editing |
| Household | Complete sequential cycle, saved zone with matching history, and automatic recharge and resume |

The existing statement and branch gates apply. A physical scenario receives a
verified status only after its acceptance evidence exists.

## 15. Documentation and discoverability

The README links to setup, map configuration, telemetry, and evidence.
Update its screenshots with cropped card and entity views from the
verified household deployment. The capability matrix records verified
features, physical results, and open scenarios.

## 16. Acceptance scenarios

1. Read a completed mission and see the last known result for each reported room.
2. Observe fresh positions and active mission detail with expiry and no cross-mission carryover.
3. Start a confirmed room selection and observe provider state. Reject unknown, excluded, or stale choices.
4. Observe vacuuming, mopping, the same mission identity, and a final outcome.
5. Observe a saved-zone mission with the matching history destination and return.
6. Observe a low-battery return, charging, and automatic resumption of the same mission.
7. On a supported map, switch to 3D. Rotate the camera and select an area.
   Toggle furniture and open an editor. Verify the normal coordinate controls
   and that cancelling restores the 3D view with the same saved floor orientation.
8. Start cleaning a point and verify the reported center and mode appear on
   the relevant map. Check expiry, a different revision, and the end of the
   mission.
9. Open a historical report after the current floor revision has changed.
   Verify that its timeline, area, and route match the archived mission.
   Compare the reported bin emptying and finish order with Android. Verify
   that a recorded fault is shown in the source event's namespace.
   Rotate the history view, then open a report with an unavailable map and
   verify its numerical measurements still appear.
10. Complete localized mopping and simultaneous missions. Compare the live
    activity values with the same missions' archived trajectories. Verify
    that the live activity sensor clears when the last position expires.
11. Read the active revision's room scores through the card and response-only
    action. Verify an exact zero and a suggested setting of false, reject a
    stale revision, and discard a reply from a previously selected floor.
12. Follow a directed run with two destinations. Verify that the first result
    and the second active destination appear side by side. Check that the
    count increases only on a finished result and that stale, mismatched, and
    full-floor reports clear the itinerary.
13. Read a recorded, directed run and compare the order, settings, and
    reported outcomes against its original command and final room or zone
    events. Verify the name fallback against the signed command revision.
14. Review an untargeted start without a saved map. Verify that no floor
    or regions are sent and that a paused run cannot be resumed by this
    action.
15. On a mobile viewport, scroll the dashboard across the fitted overhead
    map and pinch to zoom the map. Drag the live 3D view at fit. Pinch, pan,
    and reset a recorded 3D map. Verify that a drag, cancelled gesture,
    or pinch cannot select a cleaning area.

## 17. Requirements traceability

| Requirement | Related specification | Validation |
|---|---|---|
| MAP-01 | [Telemetry](005-telemetry-and-problems.md) | [History parser tests](../tests/test_history.py), [card tests](../tests/frontend/map-card.test.cjs), [signed zone area comparison](../docs/validation.md#saved-zone-area-measurements), and [telemetry](../docs/telemetry.md) |
| MAP-02 | [Capabilities](007-device-capabilities.md) | [Transport tests](../tests/test_mqtt.py), [route correlation tests](../tests/test_live_route.py), [late join evidence](../docs/validation.md#live-route-recovery), and [active timeline evidence](../docs/validation.md#mission-detail-and-dashboard-validation) |
| MAP-03 | [Profiles](006-cleaning-profiles.md) and [capabilities](007-device-capabilities.md) | [Household validation](../docs/validation.md#mission-detail-and-dashboard-validation) |
| MAP-04 | [Home Assistant](003-home-assistant.md) | [Authenticated endpoint and command-scope tests](../tests/ha/test_roomba_map_api.py) and [card screenshots](../README.md#floor-plan-dashboard) |
| MAP-05 | [Map and zone editor](009-map-zone-editor.md) | [Archive parser tests](../tests/test_live_maps.py), [live entity tests](../tests/ha/test_live_map_entities.py), [authenticated snapshot tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [physical carpet validation](../docs/validation.md#carpet-boost-and-mapped-surface) |
| MAP-06 | [Capabilities](007-device-capabilities.md) | [Point timeline tests](../tests/test_live_maps.py), [authenticated snapshot tests](../tests/ha/test_roomba_map_api.py), and [card tests](../tests/frontend/map-card.test.cjs) |
| MAP-07 | [Archived report contract](../docs/api.md#archived-cleaning-reports) | [Archive tests](../tests/test_mission_map.py), [authenticated reports](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [device validation](../docs/validation.md#archived-cleaning-reports) |
| MAP-08 | [Cleaning score contract](../docs/api.md#room-cleaning-score-reads) | [Parser tests](../tests/test_clean_scores.py), [Home Assistant tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [device validation](../docs/validation.md#room-cleaning-scores) |
| MAP-09 | [Live timeline contract](../docs/api.md#live-mission-destinations) | [Parser tests](../tests/test_mission_plan.py), [Home Assistant tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [device evidence](../docs/validation.md#live-mission-destinations) |
| MAP-10 | [Estimated time contract](../docs/api.md#estimated-time-remaining) | [Timing tests](../tests/test_mission_time.py), [Home Assistant tests](../tests/ha/test_roomba_map_api.py), and [device evidence](../docs/validation.md#estimated-time-during-a-directed-mission) |
| MAP-11 | [Live delivery evidence](../docs/validation.md#continuous-position-and-cleaning-coverage) and [coverage replay](../docs/validation.md#live-coverage-reconstruction) | [MQTT tests](../tests/test_mqtt.py), [subscription tests](../tests/test_live_stream.py), [coverage tests](../tests/test_live_coverage.py), [authenticated endpoint tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and physical telemetry. Native live polygon publication and household card verification remain open. |
| MAP-12 | [Physical obstacle comparison](../docs/validation.md#live-temporary-obstacles) | [Snapshot decoder tests](../tests/test_live_route.py), [coordinator tests](../tests/ha/test_live_map_entities.py), [authenticated subscription tests](../tests/ha/test_roomba_map_api.py), and [card tests](../tests/frontend/map-card.test.cjs). Household dashboard verification remains open. |
| MAP-13 | [Confirmed floor associations from native missions](../docs/validation.md#multiple-saved-floors) | [Parser tests](../tests/test_live_maps.py), [coordinator tests](../tests/ha/test_live_map_entities.py), [WebSocket tests](../tests/ha/test_roomba_map_api.py), and [floor picker tests](../tests/frontend/map-card.test.cjs). An installed multi-floor cleaning trial remains open. |
| MAP-14 | [Historical layer contract](../docs/api.md#archived-cleaning-reports) | [Archive tests](../tests/test_mission_map.py), [authenticated reports](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [historical layer validation](../docs/validation.md#historical-map-layers) |
| MAP-15 | [Live destination preferences and timing](../docs/api.md#live-mission-destinations) | [Profile projection tests](../tests/test_mission_plan.py), [timing tests](../tests/test_mission_time.py), [authenticated plan tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), [pause and pass evidence](../docs/validation.md#accumulated-destination-cleaning-time), and [live saved-zone pass trial](../docs/validation.md#live-saved-zone-passes) |
| MAP-16 | [Archived report contract](../docs/api.md#archived-cleaning-reports) | [Destination and pass-event tests](../tests/test_history.py), [authenticated report tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), [signed report verification](../docs/validation.md#historical-destination-plans), and [recorded durations](../docs/validation.md#accumulated-destination-cleaning-time) |
| MAP-17 | [Clean everywhere action](../docs/usage.md#clean-everywhere) | [Home Assistant control tests](../tests/ha/test_cleaning_controls.py), [card tests](../tests/frontend/map-card.test.cjs), and [scope validation](../docs/validation.md#whole-area-and-directed-cleaning-scope) |
| MAP-18 | [Interactive floor plan](../docs/usage.md#interactive-floor-plan) and [cleaning history](../docs/usage.md#cleaning-history) | [Card tests](../tests/frontend/map-card.test.cjs) and [Chrome touch verification](../docs/validation.md#touch-navigation-for-floor-plans-and-reports) |
| MAP-19 | [Current mission WebSocket projection](../docs/api.md#current-mission-readout) | [Authenticated snapshot tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [physical trial](../docs/validation.md#current-mission-readout) |
| MAP-20 | [Reviewed mission controls](../docs/api.md#reviewed-mission-controls) | [Control policy tests](../tests/test_application.py), [Home Assistant action tests](../tests/ha/test_roomba_map_api.py), [card tests](../tests/frontend/map-card.test.cjs), and [household trial](../docs/validation.md#reviewed-mission-controls) |
| MAP-21 | [Archived report contract](../docs/api.md#archived-cleaning-reports) and [signed history comparison](../docs/validation.md#expanded-cleaning-history) | [Signed query tests](../tests/test_api_client.py), [authenticated report tests](../tests/ha/test_roomba_map_api.py), [list selection and race tests](../tests/frontend/map-card.test.cjs), and [household verification](../docs/validation.md#expanded-cleaning-history) |
| MAP-22 | [Signed history window comparison](../docs/validation.md#expanded-cleaning-history) | The 30-day query returned nine additional older reports. The period selector is planned. |

## 18. Implementation sequence

Project historical records. Extend observed live data and validate the read
path. Build the dashboard card and guard map selection. Verify with synthetic
fixtures before compiling an install package and starting physical trials.

## 19. Definition of Done

- [x] Pass the automated contract, integration, privacy, and frontend checks.
- [ ] Verify the latest package in the household installation and update the README with its cropped screenshots.
- [x] Record actual physical evidence or the concrete reason a scenario could not be verified.
- [x] Keep unsupported metrics and commands out of the advertised capability set.

## 20. References and decisions

[Home Assistant custom cards](https://contributors.home-assistant.io/frontend/custom-ui/card/) ·
[Observed Roomba API](../docs/api.md) · [Current validation](../docs/validation.md) ·
[Proposed map zone editor](009-map-zone-editor.md)
