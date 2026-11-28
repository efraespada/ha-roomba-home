# Roomba Home validation

## Side-by-side live mopping

The installed 0.86.1 card and Android displayed the same Max 700 Combo
mop-only mission on one saved floor. Android drew a shaded path in the
room containing the dock. In a pair of observations 44 seconds apart,
the visible path extended. Home Assistant received
mode-tagged mopping samples and displayed travel, mopping, and estimated
coverage during the same interval.

Proxyman decoded the app's `GET /v1/p2maps/livemap?rawOnly=true` calls.
The response contained the expected `mqtt_topic`. After the live view
opened, decoded requests recurred at roughly 49 to 58 seconds. The
integration still received positions shortly after Android went into
the background. It then kept a 141-point trail while the current
position expired and the robot reported that it was still cleaning.
Bringing Android back to the foreground produced new successful calls.
The installed card's trail reached 148 points and position, mopping, and
coverage updates resumed before the return request.

The Home Assistant recorder measured the return after the card submitted
its command. At 38 seconds, the robot entered `returning`. The 0.86.1
command sensor reported `unconfirmed` at 147 seconds while Android still
showed the return. At 336 seconds, the dock reported wash code 602. At
571 seconds, Roomba reported `docked` and the dock returned to wash code
601. The signed report recorded 6.69 m² and an end requested by the user.
The 0.87.1 core and Home Assistant service tests replay this late wash
and arrival. A qualified long return continues on regular account reads,
keeping the same robot available for a new cancellation command. The
new return policy still needs a physical trial on 0.87.1.

The same-mission comparison supports renewing the map announcement.
It leaves open whether Android also resumes other connection activity
that contributes to the recovery. The new coordinator tests
verify the renewal schedule, rate limit handling, and mission and topic
scope. The updated installation still needs a physical standalone run
with Android kept in the background.
[Anonymized paired evidence](evidence/2026-11-27-paired-live-mopping.json) ·
[Installed live legend](screenshots/roomba-live-mopping.jpg)

## Household mop-only route and return

The installed 0.86.0 card started one Max 700 Combo mop-only mission
in the room containing the dock. The trial requested wetness 1 and
one pass. After the initial pad wash, Roomba reported floor cleaning
and a positive area. A fresh Home Assistant WebSocket subscription was
accepted, and the inspected floor snapshots during cleaning contained
zero trail points, no current position, and zero coverage rows. Reloading
the card during cleaning gave the same result. One direct position
arrived during the wash after the requested return, without a drawable
mop segment or estimated coverage. Local recording kept a second route
and was disabled again after the trial.

The confirmation window expired while the post-return wash was active.
The dock's Home Assistant state history recorded a new wash code 602
about 82 seconds after the return request. Its next idle code 601 came
268 seconds later. Roomba subsequently reported the robot docked. The signed
report showed a canceled mop-only mission, 3:10 of cleaning for its one
requested room, and 4.09 m². Its native archive displayed the mopping
route and coverage in Home Assistant.

Control policy and Home Assistant service tests replay a return followed
by a same-mission dock wash that takes longer than the normal window.
The new deadline applies once and the sequence publishes one pause and
one dock command. It confirms at the idle dock. The tests cover unrelated
washes, later missions, dock faults, and a wash that outlasts the extension.
[Anonymized household evidence](evidence/2026-11-27-household-mop-return.json) ·
[Installed archive legend](screenshots/roomba-archived-mopping.jpg) ·
[iRobot Max 700 dock behavior](https://homesupport.irobot.com/articles/en_US/Knowledge/70501)

### Physical confirmation on 0.86.1

The installed card started a second mop-only run in the room containing
the dock and returned the robot after about three minutes of floor
cleaning. Home Assistant's command sensor reported `pending` eight
seconds after the return request. The dock reported wash code 602
94 seconds after the request. At 338 seconds, the dock returned to code
601 and the command sensor changed to `confirmed`. The sensor recorded
no `unconfirmed` state during this return. The signed canceled report
recorded three minutes of cleaning for its one room and 4.09 m². The
installed card opened the native mopping route and coverage.

Home Assistant reproduced the missing position updates during floor
cleaning. The Android app displayed the active mopping state, but its
map stayed on the loading screen while Proxyman reported a TLS
certificate error on the map host. The Proxyman CA was missing from the
emulator's system store after a stock cold boot. The emulator setup
assistant restored the certificate on the test emulator. With the robot
back at the dock, the app loaded the saved floor. Proxyman showed HTTP
200 for three signed map list reads and one floor routine list read.
These reads verify the restored capture. The simultaneous live-map
comparison still needs a cleaning run with a working capture.
[Anonymized physical confirmation](evidence/2026-11-27-household-mop-return-confirmed.json) ·
[Proxyman emulator setup](https://proxyman.com/docs/debug-devices/android-device/google-play-android-emulator-with-magisk)

## Household vacuum route after clearing error 48

A Max 700 Combo reported error 48 while connected and charging. A
normal reboot from the Android app produced an observed disconnection
and reconnection. Roomba then reported error code zero and no active
faults. The existing floor remained readable, and its dock position
was inside the room selected for the follow-up test.

With local recording enabled, the installed 0.85.0 card submitted one
vacuum-only run for the dock's room. The live layers showed travel and
vacuuming. The review sent the robot back to its dock, where it returned
to charging with error code zero. The signed canceled report matched
the exact room and recorded 3.9 m² and one native archive. The card
displayed the native path and coverage. Recording was turned off with
one saved route retained.

Home Assistant passed the Core configuration check and restarted with
version 0.86.0. The installed card retained the disabled setting and one
saved route. Reopening the signed report showed the same 3.9 m² and
the native path and coverage controls.
[Anonymized household evidence](evidence/2026-11-27-household-local-route.json) ·
[Installed recording status](screenshots/roomba-local-route-recording.jpg) ·
[iRobot error 48 instructions](https://homesupport.irobot.com/articles/en_US/Knowledge/10548)

## Backed-up floor in cleaning history

An isolated Home Assistant instance read a signed incomplete Max 700
Combo report and saved the exact floor revision from its cleaning order.
The test then simulated an unavailable archive response for that
revision. Home Assistant reopened the saved copy and showed the same
six rooms and original furniture outline. The signed outcome, 0 m² and
timeline remained available. Deleting the matching backup removed the
floor from the report, and a completed control report retained its native
archived trajectory.

Authenticated tests also cover a matching saved route on a local backup,
an alternate archived revision without transplanted route or target
geometry, a damaged copy before a valid copy, and backups owned by a
different robot. Chrome at 358 and 900 pixels verified the local floor
caption and the native archive controls. No robot commands were sent by
this test.
[Anonymized comparison](evidence/2026-11-27-backed-up-history-floor.json)

## Local route recording replay

An isolated Home Assistant instance replayed thirteen position batches
from the recorded trajectory in a signed Max 700 Combo archive. The
test converted archived points to live position messages and inserted
sequence gaps. It used the normal position parser and coordinator path,
then reopened the private store before querying the authenticated card
endpoint. The unavailable-archive case was simulated with the same
signed report and a readable matching base revision.

The returned route preserved the injected gaps and included separately
labeled estimated coverage. The original signed area was unchanged.
Restoring the archive reference returned the native trajectory and
coverage instead. Deleting local routes returned the static requested
floor on the next query. Chrome at 358 and 900 pixels verified the
estimate label, read-only controls, explicit delete confirmation, and
the return to the requested floor. No robot commands were sent.

The household configuration check and Core restart passed with version
0.85.0. The installed card showed recording off and zero saved routes
for the selected robot. Enabling and disabling recording changed the
displayed setting and left the count at zero. The test used no robot
commands and restored the recording setting to off.
[Anonymized replay](evidence/2026-11-27-local-route-replay.json) ·
[Recording contract](api.md#local-route-recording)

## Requested floor in an unarchived report

A signed Max 700 Combo report associated error 48 with one incomplete
furniture destination and 0 m² cleaned. Its `p2maps` list had no references. The
cleaning order retained the original floor and revision and the four
vertices of its furniture target. That revision returned six rooms and
the intended furniture item. Its route and coverage layers were empty.

Three map scopes found in the same report's `reloc` and `travel` events
returned HTTP 400 through the map archive route. A completed comparison
report had an archived map scope distinct from all three of its own
event scopes. The verified cleaning order is the floor context for this
case. The trial issued zero additional cleaning commands.

An isolated Home Assistant instance read that signed report through the
card's authenticated WebSocket. It returned the six-room requested floor
and the exact furniture footprint, with no path or coverage. A completed
control report returned its archived trajectory. Chrome at 358 and 900
pixels verified the source label, legend, and archive layer controls.

The installed 0.84.0 dashboard opened both reports from the standard
thirty-day history. The incomplete report showed the requested floor
label and target outline with no route or coverage controls. The
completed report showed its original route and coverage controls. Both
reports were read without sending robot commands.
[Anonymized evidence](evidence/2026-11-27-unarchived-requested-floor.json) ·
[Household failure trial](#household-live-coverage-and-active-errors) ·
[iRobot archive documentation](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

## Household live coverage and active errors

A Max 700 Combo started one vacuum-only furniture target through the
installed 0.82.0 floor plan. The dashboard showed the travel path and
estimated coverage during the run. A separate read-only subscription
received 41 distinct position updates with a median interval of one
second. It held 180 route points and seven estimated vacuum coverage
rows. Four downloaded live snapshots each had zero obstacle records.

Roomba reported error 48 during the return phase `hmPostMsn`. The
robot subsequently reported `charge` and cycle `none` while error 48
was still active. Its signed report matched the reviewed furniture
target, recorded an incomplete outcome, and reported zero cleaned area.
The report retained error 48 in its summary and timeline and had no
archived map reference.
The 0.82.0 card cleared both live overlays and the mission readout and
left the current fault out of the floor plan once the mission ended.
The coverage seen during the run was an estimate based on position
modes. The archived cleaned area is a separate provider measurement.

The candidate tests verify that the reported phase and active fault can
be displayed at the same time. They retain current faults at the dock
and before the first saved floor, distinguish robot and dock code
sources, and clear stale readings on disconnect. The new projection
returned the physical robot's active error 48 while it reported `charge`
with no ongoing mission. Isolated Chrome at 358 and 900 pixels verified
the display during return, after the mission ended, and after clearing
the code. Household obstacle marker verification still requires a run
with Roomba-reported detections.

The household installation of 0.83.0 passed its Core configuration check
and restart. The Lovelace resource and served module matched the release.
The installed card showed **Mission error** and **48 · Path blocked**
above the saved floor with no current mission. The other live controls
were absent after the return. The remote dashboard showed the same fault
and served the exact released module.
[Anonymized trial](evidence/2026-11-27-household-live-active-errors.json) ·
[iRobot Error 48 guidance](https://homesupport.irobot.com/articles/en_US/Knowledge/10548)

## Automatic Smart cleaning overlay

On a Max 700 Combo, opening the saved floor's details in Roomba Home
3.4.1 showed the amber recommendation before interacting with the map.
Five of the six rooms were highlighted, matching the signed
`CLEAN_DIRTY` selection. No cleaning commands or map edits were issued.

In the same app, the active map displayed detected carpet. The edit menu
offered room division and merging, names, furniture, cleaning and exclusion
zones, and floor rotation. Its furniture catalog and map legend offered
no carpet editing control. The app release notes list carpet editing
among new features. The ClearView map parser shows the reported carpet
geometry for this Max 700 Combo.

Isolated Chrome at 358 and 900 pixels verified actual amber pixels on the
recommended room, the layer control and legend layout, an unchanged floor
poll, and hiding across a floor change. Re-enabling the layer drew the
second floor's own recommendation. The test issued zero robot commands.

On the household instance, Core passed its configuration check, restarted,
and served the exact 0.82.0 module. After the Lovelace resource update and
dashboard reload, the card listed all five recommended rooms before the
viewer used **Recommended rooms**. The control hid the layer and restored
the same five rooms. The Android and installed room names matched exactly.
The same default layer and module were verified through the household's
remote Home Assistant dashboard.

For 0.84.0, a new read of the same floor again matched all five Android
destinations to the signed recommendation and the exact room preferences.
Chrome at 358 and 900 pixels verified that the amber fill moves to the
updated room when a response changes on the same revision, and that
ordinary floor polls within the interval do not repeat the routine read.
The household Core configuration check and restart passed. The dashboard
served the exact 0.84.0 module and showed the five Android destinations
before using the layer control. Hiding and restoring the layer kept the
same five destinations. The trial sent no robot commands.
[Anonymized native comparison](evidence/2026-11-27-automatic-smart-overlay.json) ·
[Installed map legend](#recommended-rooms-on-the-floor-plan) ·
[iRobot app release notes](https://homesupport.irobot.com/articles/en_US/Knowledge/40500)

## Cleaning history periods

Signed reads of the same Max 700 Combo produced these report counts.

| Period | Standard filter | Include short canceled runs |
| --- | ---: | ---: |
| Ten days | 18 | 26 |
| Thirty days | 27 | 35 |

The thirty-day standard view returned nine reports older than ten days.
One report from fifteen days earlier had positive cleaned area and an
original map archive with route and coverage. The authenticated candidate
WebSocket returned all four counts and opened the same archive under both
thirty-day filters. It excluded that report from the ten-day scope. Chrome
verified the period, combined filters, and selection at 358 and 900 pixels.

The household 0.81.0 installation passed its Core configuration check and
restart. The served card matched the release, and the updated Lovelace
resource loaded that version. The installed dialog showed all four counts.
Turning off **Include short canceled runs** in the thirty-day view kept the
same fifteen-day-old report selected with its archived map, route, and
coverage visible.
[Anonymized period comparison](evidence/2026-11-27-cleaning-history-periods.json)

## Expanded cleaning history

Two signed reads for the same Max 700 Combo compared the normal history
query and the query with only `filterType` omitted. The normal view had
18 cleaning reports and the expanded one had 26. All 18 original selection
keys were present. The eight additional reports were canceled missions.
The report for the reviewed 0.79.0 trial matched the furniture target and
had positive cleaned area. Its signed map revision supplied the target
label, recorded trajectory, and coverage.

The candidate Home Assistant returned the same 18 and 26 reports through
its authenticated WebSocket endpoint. The expanded view resolved the
canceled report's furniture target and original archive. The same report
key in the standard view returned `report_not_found`. Chrome exercised the
default view, the expanded totals, report selection, and return to the
default view at 358 and 900 pixels.

The household 0.80.0 installation passed its configuration check and
restarted Core. The served module matched the release. After updating the
Lovelace resource and reloading the dashboard, the installed card displayed
18 standard and 26 expanded reports. Selecting the exact earlier furniture
run showed its canceled outcome, target name, saved map, recorded route,
and coverage. The screenshot captures the selected checkbox from that
installed dialog.

Additional signed reads used the expanded query with `maxAge` set to 10,
30, and 90. The 30-day response contained 35 reports, including nine older
than ten days. The oldest was 28 whole days old. The 90-day response for
the same robot contained the same count and oldest age. The 0.80.0
history view used the ten-day window.
[Anonymized history comparison](evidence/2026-11-27-expanded-cleaning-history.json) ·
[Mission control trial](#reviewed-mission-controls)

## Reviewed mission controls

Home Assistant tests pause eligibility during cleaning, explicit resume
from a paused mission, and return while an identified robot is idle off
the dock. The tests reject a stale mission review before publication and
reject a different mission as proof of a resume. A floor plan read with
read permission alone omits the controls. A paused mission can be
reviewed before the first saved floor.

Home Assistant Core passed its configuration check and restarted with
0.79.0 on the household instance. The module matched the release. After
updating the Lovelace resource and reloading the dashboard, one reviewed
furniture-target trial exercised all four controls on a Max 700 Combo.
Roomba reported `stop` after pause and `run` after resume. The installed
readout showed a paused vacuum mission with 2:21 elapsed and 0 m², and
the robot later reported positive area. Confirming cancellation removed
the active readout and left **Return to dock** available. The card sent
that request, the robot reported `hmUsrDock` and returned with error zero,
and the card cleared the mission controls. The trial kept the previous
release available for rollback.

The signed history query with the app's usual
`omit_quickly_canceled_not_scheduled` filter returned zero matching records.
Removing only that parameter returned one record matching the start and
end times and the exact furniture target. It recorded a canceled vacuum
mission with positive area. [Anonymized household trial](evidence/2026-11-27-household-mission-controls.json)

## Current mission readout

One Max 700 Combo trial started vacuuming around a previously verified
furniture target through an isolated Home Assistant instance. Nine
authenticated floor plan reads matched the robot's current phase, mode,
and area. Time since start advanced from 14 to 146 seconds. A reported zero
remained visible until Roomba began reporting positive area. The live
position subscription delivered 87 distinct positions and estimated
coverage rows during that interval.

The trial requested return to the dock after the measurements. Roomba Home
showed the return, and the signed history confirmed the exact furniture
target, vacuuming, positive cleaned area, and a cancelled outcome. The
WebSocket closed during the return. A fresh authenticated read confirmed
the robot at the dock with no error and the mission readout cleared.

The tests cover a missing destination plan, no saved floor, a pause,
disconnect, missing readings, and a reported fault. Isolated Chrome at
358 and 900 pixels showed the active measurements and cleared them at
the end of the fixture mission.

Home Assistant Core passed its configuration check and restarted with 0.78.0
on the household instance. The served card matched the release byte for byte.
After updating the Lovelace module URL to 0.78.0, the installed card showed
the floor controls and kept the mission readout hidden while the robot was idle.
[Anonymized trial](evidence/2026-11-27-current-mission-readout.json) ·
[iRobot live map documentation](https://homesupport.irobot.com/articles/en_GB/Knowledge/20500)

## Quick routines and Smart recommendations on the floor plan

Opening **Smart cleaning** in Roomba Home 3.4.1 loaded five of six rooms on
a Max 700 Combo floor. Each selected room exposed its cleaning settings.
The map legend marked recommended cleaning with one colored category.
The signed `CLEAN_DIRTY` response named the exact same rooms, and its
`clean_score_id` matched `smart_clean_id` on the active floor score row.
Each room's command settings matched its `smart_clean_prefs`. The reported
`0.7` range boundary separated the five target rooms in this read. The
app reached the review screen without starting a mission.

A signed read through the shortcut client returned two compatible saved
routines and three loadable native options on the same floor. The tests
cover saved order and profiles, stale geometry and changed furniture,
read permission, confirmation, and the amber fill with a selected outline.
Isolated Chrome at 358 and 900 pixels opened the panel, wrapped a long
routine name, loaded the recommendation, and rendered its amber fill.
[Anonymized comparison](evidence/2026-11-27-smart-cleaning-shortcuts.json) ·
[ClearView routine documentation](https://homesupport.irobot.com/articles/en_GB/Knowledge/20500)

## Room and furniture selection on the floor plan

Roomba Home 3.4.1 switched from room add controls to per-room cleaning
settings after selecting all rooms on a Max 700 Combo floor. Home Assistant
checks cover bulk selection with an existing room, zone, and furniture
selection, retention of individual settings in a draft, the destination
limit, and stale floor revisions. The card keeps the existing order and
adds missing rooms in map order.

Tests also compare an object's selectable footprint with its expanded
cleaning outline and verify that a confirmed mixed selection sends the
exact map review and destination order. An earlier physical schedule on
the same model reached a supported furniture destination and reported
cleaned area for its exact furniture link. A separate 0.76.0 household
trial selected and cleared all six rooms in the installed card, then
started vacuuming around one furniture object. The signed report matched
the exact target and recorded cleaned area and natural completion. The
robot returned to its dock with error code zero.
[Scheduled furniture cleaning](#scheduled-furniture-cleaning)

## Recommended rooms on the floor plan

Roomba Home 3.4.1 marked five of the six current rooms on a Max 700 Combo
floor with its **Cleaning recommended** legend. A signed read of the same
floor's quick routines returned a `CLEAN_DIRTY` recommendation. Its five
targets matched the app's highlighted rooms. All five profiles projected
to supported simultaneous vacuuming and mopping settings. The native
recommendation left the order to the robot.

The Home Assistant tests cover read permission, floor revision validation,
and draft loading. The map discards results for a different floor or
after the layer is turned off. Loading a recommendation preserves its
automatic order, and starting still requires the usual confirmation.

The household 0.78.0 and 0.81.0 cards showed five recommended destinations
on the verified floor. The 0.81.0 check matched the five displayed names
to the Android selection and used only read operations. The capture
includes only the map key.
[Anonymized recommendation comparison](evidence/2026-11-27-recommended-rooms.json)

![Amber Cleaning recommended map key in the installed Home Assistant card](screenshots/roomba-recommended-rooms-key.png)

## Scheduled furniture cleaning

Roomba Home 3.4.1 selected a saved furniture object and a room as two
ordered destinations. A temporary Sunday automation stored a weekly
rule with day zero, a `tid` linked to the furniture polygon, and a `rid`
for the room. The rule was removed and signed reads matched the original
schedule set for the selected robot.

The integration created separate disabled weekly and one-time schedules
with those destinations and distinct cleaning modes. An identical
creation returned the same schedule ID. Updating the order and modes
preserved the weekly schedule's timing and disabled state. Both entries
were removed and the original schedule set matched the baseline.

A separate one-time schedule started vacuuming around the selected
furniture object 14 seconds after the configured start. The signed report
matched the exact furniture link and recorded a positive cleaned area.
After the bounded test, the robot returned to the dock with error code
zero and recorded a canceled result. The temporary schedule was removed.
The original schedule kept its ID, timing, activation, and command.
Roomba changed its `created_time` metadata.
[Anonymized schedule comparison](evidence/2026-11-27-furniture-scheduling.json)

## Saved routine display order

The native order endpoint moved two temporary Max 700 Combo routines
before and after one another. Both requests returned HTTP 200. Confirming
reads showed the requested relative order when sorted by `display_order`.
The response array alone did not reflect the display ranks. The signed
read-back retained every cleaning command and the relative order of the
original six routines.

The temporary routines were removed without starting a mission. A separate
signed read verified the original list, names, settings, and order.
Roomba reassigned the numeric display ranks and both internal modification
timestamps for the six original records. Those were the only changed
fields.

An authenticated Home Assistant connection returned the two original
R2-D2 routines in their ranked order. The reorder action returned that
same list for a position already in effect and rejected a stale reviewed
order. A signed comparison found the collection unchanged after these
Home Assistant calls. R2-D2 remained docked.
[Anonymized routine order trial](evidence/2026-11-26-routine-display-order.json)

## Live saved-zone passes

Home Assistant started a two-pass vacuum run in a 9.92 m² test rectangle
on a disposable Max 700 Combo floor. The matched live zone events
reported a target of 106 ft² and changed the `passCount` index from zero
to one. The open event sampled during the second pass supplied `area`
and `passCount`. Its separate first-pass completion supplied
`totalArea` of 62 ft². Neither sampled event included `coverage` or
`passArea`.

A separate read-only Home Assistant instance confirmed the second pass
through the authenticated floor-plan command and the live timeline
sensor. The plan showed **Pass 2** and one completed pass. The target
was 9.85 m² and the confirmed pass measured 5.76 m². A signed duration
request on this disposable floor returned HTTP 404 with both the empty
zone selector and the saved-zone selector. A later positive control on the
usual floor returned 36 profile estimates for a known room. That floor had
no saved zones at the time of the read.

Roomba returned 65 matching timelines for 66 requests. The final live
completion measured 63 ft² for the second pass. The signed archive
confirmed both pass measurements and a separate 126 ft² mission total.
The current mission shadow had reported 125 ft² near the end of cleaning.
Home Assistant removed the disposable floor after docking. Signed reads
confirmed the original floor revision, geometry, programs, and settings.
The authenticated history command then returned 9.85 m² for the target,
11.61 m² for two completed passes, and 11.71 m² for the mission.
The active pass cleared after docking.
[Anonymized live and archived evidence](evidence/2026-11-26-live-saved-zone-passes.json)

## Saved-zone area measurements

The Max 700 Combo's signed history contained 38 missions, including 32
with room or zone events. All 31 zone events and 15 room events had `area`
and `totalArea`. The Android SDK describes optional `coverage` and
`passArea` fields. Neither field appeared in these signed results.

The matching saved-zone archives supplied independent polygon footprints.
For a 9.922 m² footprint, Roomba reported a target of 106 ft². The two
completed events reported 66 and 67 ft² in one mission and 67 ft² each in
another, matching their mission totals of 133 and 134 ft². The 2.56 m²
zone reported a target of 27 ft² and 35 ft² for each of its two completed
passes. A canceled pass reported a negative `totalArea`, so the conversion
uses measured area from completed passes only.

The integration now shows the reported target size and the completed-pass
sum in square metres. Raw area values remain available. The room samples
reported zero `totalArea` even in missions that recorded cleaning, so
this comparison establishes the contract for correlated saved zones.
[Anonymized archive comparison](evidence/2026-11-26-saved-zone-area-measurements.json)

An isolated Home Assistant instance sent a one-off vacuum order with two
passes in a 2.56 m² zone on a disposable attic floor. The completed mission
recorded a target of 27 ft² and pass measurements of 15 and 14 ft². Its
mission-wide total was 30 ft². The authenticated history command returned
2.51 m² for the reported target and 2.69 m² for completed passes alongside
the separate mission total of 2.79 m². The same command returned the
expected conversions for three previously archived reports.

Signed reads after cleanup confirmed the original floor revision and
geometry, routines, schedules, and robot settings. The robot was docked.
A corroborating live zone reading was unavailable during this trial.
[Signed trial and Home Assistant readback](evidence/2026-11-26-saved-zone-area-measurements.json)

## Household installation of 0.71.2

The 81 component files in the published archive matched the release tag.
Home Assistant passed its configuration check, retained 0.71.1 for
rollback, and restarted Core. The remote connection temporarily stopped
completing TLS after the restart and recovered before verification.

The authenticated frontend reported integration version 0.71.2 and the
matching Lovelace module. The served module matched the release bytes.
The device registry showed three robots with one distinct linked dock each.
The R2-D2 card showed a **Bin emptying stage** alongside **Recorded bin
emptyings** of zero in the signed archived report. The household check
used read-only actions. [Household evidence](evidence/2026-11-26-household-0712.json)
[Component capture](screenshots/roomba-history-emptying.png)

## Household installation of 0.71.1

Home Assistant verified the release archive and configuration, kept
0.71.0 as a rollback, and restarted Core. Lovelace loaded the 0.71.1
resource. The served module matched the release, and the authenticated
device registry showed three robots with one linked dock each.

The installed card opened a canceled report with 5.95 m² of recorded
cleaning. It showed **Bin emptying stage** and dock state 301 before
**Finished**. The separate **Recorded bin emptyings** measurement showed
the explicit count of zero. The signed dock error code was zero. The
household check used an archived report without sending robot commands.
[Household evidence](evidence/2026-11-26-history-zero-emptyings-household.json)

## Household installation of 0.71.0

Home Assistant checked the 0.71.0 configuration before restarting Core and
retained 0.70.0 as a rollback. The installed card matched the release
bytes and Lovelace registered the 0.71.0 resource. The authenticated device
registry showed three robots and three docks with one dock linked to each
robot.

The installed card opened a completed 6.50 m² report. Its timeline showed
a 17-second bin emptying with dock state 301, followed by the end of the
mission two seconds later. The authenticated response carried the
explicit dock error code zero. An independent signed observation confirmed
the robot was connected, docked, and reporting error code zero after the
check. [Household evidence](evidence/2026-11-26-archived-dock-household.json)

## First-clean preparation

In Android, the Max 700 Combo device page opens a separate Robot Help
walkthrough. The first two steps show the matching A and B side brush
mounts and the clean water tank with its optional detergent reservoir.
The lower section checks the robot charge and prepares the rooms. The
Home Assistant checklist presents the same four steps in order and links
to iRobot's unboxing guide. It uses English text and Home Assistant icons.
[iRobot unboxing guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20503)

An authenticated local Home Assistant instance linked only to the trial
robot returned the same four steps from the WebSocket command and
response action with maps disabled. The linked unboxing guide returned
HTTP 200. The robot stayed docked. The full suite passed 2,610 Python
tests with 100% statement and branch coverage, 74 card tests, and
the official hassfest integration checks.
[Anonymized evidence](evidence/2026-11-26-first-clean-preparation.json)

In the household Home Assistant, the installed 0.70.0 card matched the
published module byte for byte. The authenticated view showed the three
robots and their three dock devices. The dashboard resource was updated
to 0.70.0. The R2-D2 card displayed the four steps and the unboxing link.
The documentation capture isolates the rendered checklist and heading
from the household dashboard.
[Household evidence](evidence/2026-11-26-first-clean-household.json) ·
[Component screenshot](screenshots/roomba-first-clean.png)

### Wi-Fi settings entry

The Max 700 Combo's Android device settings opened the Wi-Fi settings page
with a separate reconnect control. Leaving that page without starting
reconnection preserved the signed connection state. The robot was still
docked, ready, and at 100% charge with error code zero. Reconnection and
pairing remain separate validation scenarios.
[iRobot reconnection guide](https://homesupport.irobot.com/articles/en_US/Knowledge/10503)

## Robot help after moving a card

A Chromium browser reproduced the modal losing its top-layer state when the
open card moved between dashboard containers. The dialog retained its
`open` attribute and the selected code while its visible modal was lost.
The 0.69.1 card restores the native modal on reattachment and on an
explicit reopen. The browser repeated the same move and retained both
the visible modal and the selected charging error. The card suite also
checks that the catalog is read only once.
[Regression tests](../tests/frontend/map-card.test.cjs)

The household installation verified the published archive, passed
`ha core check`, restarted Core, and retained a 0.69.0 rollback. The
0.69.1 resource matched the released module. Chrome showed all three
robots and docks. Reattaching the original R2-D2 card in place kept the
dialog modal and preserved the selected charging article.
[Household evidence](evidence/2026-11-26-robot-help-home-assistant.json)

## Version 0.69.0

The release adds the Robot help panel and the response-only action.
Validation passed 2,609 Python tests with 100% line and branch coverage,
72 card tests, hassfest, Ruff, and the SDD and privacy checks. Both pull
requests passed GitHub validation.

The household installation verified the release archive checksum, kept
a 0.68.0 rollback, passed `ha core check`, and restarted Core. The browser
resource pointed to the exact 0.69.0 module. The authenticated integration
page showed three robots and three docks. In Chrome, the authorized
robot's panel presented the Spanish Android manual and produced the
matching links for error 48, charging error 101 and start refusal 1.
The screenshot isolates the rendered panel from the household dashboard.
[Robot help validation](#robot-help-catalog) · [Panel screenshot](screenshots/roomba-robot-help.png)

## Version 0.68.0

The release adds the automatic emptying selector and preserves the area
number and its unit conversion. Validation passed 2,580 Python tests with
100% line and branch coverage, 70 card tests, hassfest, Ruff, and the SDD and
privacy checks. Both pull requests passed GitHub validation.
[Setting validation](#automatic-dock-emptying-frequency)

The household installation verified the release archive checksum, kept a
0.67.0 rollback, passed `ha core check`, and restarted Core. The browser
resource pointed to the exact 0.68.0 module. The authenticated integration
page showed three robots and three docks. The authorized robot's linked
dock showed the area number and all three automatic emptying choices in
Chrome. The household selector switched from 25 m² to **After each
routine** and back. Independent signed reads confirmed both writes while
the robot stayed docked with error code 0.
[Selector crop from the installed Home Assistant](screenshots/roomba-dock-auto-empty.png)

## Robot help catalog

Android opened the 36-page Spanish manual for the Max 700 Combo. The
public catalog returned the same PDF and 87 diagnostic entries. Four
duplicate entries resolved to identical URLs. The integration returned
49 distinct error codes, 16 charging error codes, 18 start refusals,
and six setup and control links. The English catalogs selected the
British edition for Spain and the US edition for the United States.
[Android and catalog discovery](evidence/2026-11-26-robot-help-discovery.json)

An authenticated Home Assistant instance associated with the authorized
robot exercised both the card WebSocket command and the action with maps
disabled. Their results matched. The PDF and article selections for
error 48, charging error 101, and start refusal 1 returned HTTP 200.
The docked robot reported error 0 and Home Assistant displayed no
current error links.
[Home Assistant and Roomba evidence](evidence/2026-11-26-robot-help-home-assistant.json)

## Automatic dock emptying frequency

On the Max 700 Combo, Android switched from 25 m² to **After each routine**
and back. Independent signed settings reads confirmed `autoevacFreq` values
of 0 and 25.
[Android evidence](evidence/2026-11-26-auto-emptying-discovery.json)

An authenticated Home Assistant session used the dock selector to switch
the native code from `25` to `0`, then to `50`, and back to `0`.
The area number then set a custom threshold of 37 m² and the selector
restored 25 m². Each signed settings
read matched the Home Assistant state. At code 0, the number was available
with an unknown area. The robot remained docked with error code 0. Its
mission identity, other settings, floors, routines, and schedules matched
the preflight reads. These checks establish setting changes.
[Home Assistant and Roomba evidence](evidence/2026-11-26-auto-emptying-home-assistant.json)

### Physical emptying after a short routine

The authorized robot completed a vacuum-only routine targeting a temporary
0.72 m² zone and returned on its own. Throughout the run the signed
settings reported frequency 0 and evacuation allowed. The mission history
reported two minutes, 0.65 m² cleaned and zero evacuations. The sampled
dock evacuation state stayed at 301. This records the result for one short
routine. The conditions that trigger the physical emptying cycle remain open.

Independent reads confirmed the original 25 m² setting, cleaning settings,
room, restrictions and schedules after removal of the trial zone and
routine. A new provider map archive contained changed border, detected
furniture, wall, carpet and dock-pose data. The furniture came from robot
detection and the feature counts matched. The private preflight archive
was retained. An independent read retrieved that earlier version byte for
byte while the active version was different. Android displayed the map
legend and timeline for an inspected older report. Reactivating the
earlier provider revision remains open.
[Anonymized trial and restoration evidence](evidence/2026-11-26-short-routine-auto-emptying.json)

### Saved-routine dock frequency comparison

Two vacuum-only runs used the same saved routine, 9.92 m² cleaning zone,
suction level, and two-pass setting on a disposable floor. Signed history
matched each report to that floor and destination. Both completed and
reported one bin emptying. The **After each routine** run recorded 12.45 m²
in 18 minutes. The **Every 25 m²** run recorded 12.36 m² in 21 minutes.
Both evacuation stages lasted 18 seconds and reported dock state 301
with error code zero.

An independent signed read confirmed the 25 m² setting before and after
the second run. The live observer lost confirmation from Home Assistant
and recovered the result from the signed mission report. The dock never
reported a motor-active state in the captured samples. These runs show a
counted emptying on 25 m² mode even though the mission's reported area
was below that setting. They leave the effective trigger and any dock-side
accumulated area unresolved.

After the robot docked, the temporary routine and floor were removed. The
original floor revision, decoded map layers, routines, and schedules
matched the preflight snapshot. Independent settings reads reported the
original dock frequency of 25 m².

The Home Assistant recorder showed the reported default suction changing
from 1 to 2 when the first routine started. After the trials a signed
settings write and read restored level 1 without starting a new mission.
[Anonymized trial and restoration evidence](evidence/2026-11-26-saved-routine-dock-frequency.json)

### ClearView archive recovery

The Android Max 700 Combo report showed the original map legend, cleaning
statistics, and timeline for an older mission. Its inspected detail view
offered no action to activate that map. iRobot's support guide excludes
this model from its current map save and retrieval workflow.
[iRobot save and retrieval guide](https://homesupport.irobot.com/articles/en_US/Knowledge/53000)

The inspected client SDK declares `revert_user_edits` for an identified
map with an empty command parameter object. The declaration has no input
for choosing a saved version.

A signed Max 700 Combo trial created a separate floor through a mapping
run. The active archive confirmed a saved zone and the floor settings
confirmed a temporary name. One SDK-shaped request to revert user edits
returned HTTP 500. The following reads kept the edited revision, zone,
effective cleaning destination, and name. The initial geometry did not
reappear during the observation window. This trial leaves complete
archived-floor recovery open.

The disposable floor was removed afterward. Independent reads confirmed
the original floor revision and decoded layers, the original routines
and schedules, and the robot docked.
[Anonymized signed trial](evidence/2026-11-26-clearview-revert-trial.json)

### Archived bin emptying and faults

Two completed Max 700 Combo reports each recorded one bin emptying. Their
cleaned areas were 6.50 m² and 6.04 m². Their evacuation events lasted
17 and 18 seconds and ended two seconds before the signed report timestamp.
Both events reported dock state 301 and error code zero. Android displayed
bin emptying before the end of the matching 6.50 m² report. The active
automatic emptying setting at the time of either mission is unknown.

A follow-up signed read identified three further reports with the same
evacuation state and error in the timeline and an evacuation count of zero.
Two reports were canceled and one completed. The card labels this event
as a stage and displays the reported count independently.

The Home Assistant history command returned both evacuations, the matching
end of each report, and separately recorded robot error codes 48 and 654
in an authenticated session linked to the Max 700 Combo. The robot stayed
docked. Refill codes and an explicitly reported finish event were covered
with protocol fixtures.
[Anonymized evidence](evidence/2026-11-26-archived-dock-timeline.json)

### Android history list and totals

All 29 visible Android reports for the Max 700 Combo matched signed
reports by start minute, duration, and outcome. Two completed reports
were visible without a map. In the same signed response, Android omitted
one mapping run, two canceled cleaning runs without a map, and one
cleaning attempt that got stuck without a map. Home Assistant kept the
three cleaning reports and excluded the mapping run.

The 29 matching reports totaled 189 minutes. Android displayed 3.1 h
and 123.3 m². The exact conversion of the matched signed areas totaled
123.7 m². The source calculation for Android's area total remains open.
Home Assistant calculates its total from the signed reports it displays.
[Anonymized comparison](evidence/2026-11-26-android-history-totals.json)

## Version 0.67.0

The release adds accumulated cleaning time by destination, mapped carpet
membership, and recovery when a short cleaning job finishes during a return
request. Validation passed 2,571 Python tests with 100% line and branch
coverage, 70 card tests, hassfest, and the SDD and privacy checks.
[Timing validation](#accumulated-destination-cleaning-time) ·
[Carpet and return validation](#carpet-boost-and-mapped-surface)

The household installation verified the release checksum, retained the
0.66.0 rollback, passed `ha core check`, and restarted Core. The dashboard
resource was updated to 0.67.0. The installed integration showed all three
robots and three docks. The saved-zone report showed 48 seconds of cleaning
and one completed pass. The deployment verification sent no robot commands.

## Version 0.65.0

The release adds one-off area cleaning preferences, explicit selection of
compatible remembered profiles, and routine icon and color editing. A
Max 700 Combo accepted the reviewed one-off room settings and returned to
its dock. Signed reads confirmed both remembered combined profiles and
the appearance changes in removable trial routines.

## Version 0.64.0

The release adds remembered area profiles, a maintenance panel with official
iRobot replacement and care links, and touch navigation for floor plans and
cleaning reports. The feature sections below record the Max 700 Combo and
browser trials for each change.

## Maintenance catalog and links

The Android maintenance view for a Max 700 Combo opened the replacement
filter's product page in a web view. The model's Spanish catalog returned
five replacement SKUs and two washing-system guides. In browser-profile
HTTP probes, iRobot's mobile product route redirected to the storefront.
Each short Spanish shop URL built from the catalog SKU redirected to the
corresponding official product page. The filter page matched the Android
product title. [Official filter listing](https://www.irobot.es/es_ES/4849940.html)

An isolated Home Assistant instance loaded the authorized robot with the
map option disabled. Its authenticated WebSocket response contained seven
parts, six signed counters, five replacement references, and two guides.
The existing filter sensor matched the response. The dust bag included
its shop reference with the usage counter disabled. Chrome rendered the
anonymized report at 358 and 900 pixels and verified all seven links.
[Anonymized catalog evidence](evidence/2026-11-26-maintenance-catalog.json)

## Touch navigation for floor plans and reports

Isolated Chrome sessions at 358 × 844 and 390 × 844 CSS pixels used
browser-dispatched touch events with synthetic geometry. A one-finger
swipe scrolled the dashboard across a fitted overhead map. A pinch
changed the map zoom from 1 to 1.9 while the browser viewport stayed at
scale 1.
One finger panned the 3D floor at fit. The recorded 3D map responded to
pinch, pan, and reset. None of the gestures selected a cleaning area.

The card tests also cover a remaining finger after a pinch, arrow-key
panning, cancellation, a changed map, and a stationary selection.
[Card tests](../tests/frontend/map-card.test.cjs) ·
[iRobot's 3D panning release notes](https://homesupport.irobot.com/articles/en_US/Knowledge/40500)

## Version 0.63.0

The release candidate passed 2,500 Python tests with 100% line and
branch coverage and 57 card tests. Physical runs on a Max 700 Combo
confirmed the whole-area start and the staged return in an isolated
Home Assistant coordinator. Household installation and browser
screenshots remain pending.

## Return during active cleaning

A Max 700 Combo ignored a direct `dock` while actively vacuuming.
A second physical trial confirmed that `pause` kept the same mission,
then `dock` produced `hmUsrDock / dock` and reached `charge / none` with
error code 0. A fresh provider read confirmed the original rooms, zones,
restrictions, routines, and schedules.

The Home Assistant control tests cover the staged return, a changed or
unidentified mission, connectivity loss, already paused and returning
states, and unloading during the action. An isolated Home Assistant
integration verified one `vacuum.return_to_base` action on the physical
robot. Roomba reported active cleaning, pause, return, and arrival. The
action returned `confirmed` at the dock with error code 0, and the
provider read again found the original map and programs.
[Anonymized return evidence](evidence/2026-11-26-return-during-cleaning.json)

## Carpet boost and mapped surface

The signed Max 700 Combo floor included a carpet polygon. An isolated
Home Assistant instance created one temporary 0.72 m² saved zone within
that polygon and requested vacuuming with suction level 1. Two missions
used the same zone and changed only the requested carpet boost setting.
Each run supplied two distinct vacuuming position samples on the mapped
carpet. The map response and the **On mapped carpet** binary sensor
classified those positions consistently. Each run also supplied positions
outside the carpet. The active timeline and signed report preserved false
in the first mission and true in the second. The observed current-state
and mission shadows supplied no effective motor power measurement.

The first zone finished as Home Assistant was requesting a pause ahead of
return. The signed timeline recorded completed zone cleaning, automatic
travel, then a pause. The robot stopped idle without an error and returned
after a separate dock request. The regression test replays this transition.
The return action now proceeds to dock when the same mission becomes idle
and leaves a different or unverified mission untouched.

The second trial ended with a return request after its readings were
collected. Signed history contained the interrupted zone result. An
independent read confirmed the robot at the dock with error code zero,
the original suction, pass, and boost settings, and removal of the test
zone. The map layers, routines, and schedules matched the original reads.
[Anonymized trial evidence](evidence/2026-11-26-mapped-carpet.json)

## Whole-area and directed cleaning scope

A signed Max 700 Combo suggestion contained `CLEAN_ALL`, the associated
floor, and no list of regions. The signed history contained one whole-area
start with null map and region fields and 16 directed starts with a floor
and destination list. The history projection now recognizes null regions
in the whole-area record. An opaque favorite reference still requires
destination evidence before the history can describe its scope.

The Home Assistant harness confirmed that **Clean everywhere** requires
explicit confirmation, uses the next-cleaning profile, and supplies no
map target. A paused mission was rejected before publication. The
availability tests cover a supported robot before its first saved map,
active and paused missions, missing capability, connectivity, and entity
control permission.

Isolated Chrome verified the confirmation, cancellation, and service call
at 358 and 900 pixels using a device fixture with no saved map.

The Home Assistant action also started a new vacuuming mission on one
physical Max 700 Combo. Roomba reported a new mission identity and
entered its vacuuming phase. A direct return command during that run
received no physical confirmation. Ending the trial mission first
allowed the robot to return to its dock with error code 0. The signed
report for this trial contained an untargeted `start`, which the
integration classified as whole-area cleaning.

The suite passed 2,483 Python tests with 100% line and branch coverage,
57 card tests, and Home Assistant's integration validator.
[Anonymized scope evidence](evidence/2026-11-26-whole-area-cleaning-scope.json)

## Copying a routine into a schedule

An isolated Home Assistant coordinator read a signed one-room routine
from a Max 700 Combo and copied its explicit suction and two-pass settings
into a disabled weekly schedule. A new provider read confirmed the same
destination and profile, the requested days, and the disabled state. The
routine was unchanged after copying. Both test entries were removed, and
the original routines, schedules, and saved floor matched the initial
reads. The trial sent zero movement commands.

The card regression test copies a saved cleaning zone followed by a room
with different modes and settings. It verifies the exact order and profile
of the creation request, rejects stale floors, and excludes furniture and
automatic-order selections. Isolated Chrome verified the button and save
flow with the signed one-room routine at 358 and 900 pixels. The suite
passed 2,473 Python tests with 100% line and branch coverage, 56 card
tests, and Home Assistant's integration validator.
[Anonymized schedule copy evidence](evidence/2026-11-26-routine-schedule-copy.json)

## Historical destination plans

The coordinator read two signed Max 700 Combo reports. The first recorded
two furniture destinations in a requested sequence. Both requested
vacuuming with different preferences and both had a final `finished`
result. The mission archive supplied one name. The signed revision from
the original start command supplied the missing name in one additional
read. The card retained the mission archive for the drawing.

The other report kept the room's requested suction level and two-pass
setting. The mission reported `ok` while the room reported `user_ended`
with zero passes. The projection kept both outcomes and used only the
mission archive to name the room. Both reports used a different archive
revision from the revision in the original command. This verification
sent zero movement commands and made zero map writes.

An isolated Chrome run loaded both real reports from a local test fixture
at 358 and 900 pixels. It verified destination order, names, settings,
reported passes, and switching between reports. Authenticated WebSocket
tests cover the plan with an expired archive and fallback failures.
The suite passed 2,473 Python tests with 100% line and branch coverage,
55 card tests, and Home Assistant's integration validator.
[Anonymized report evidence](evidence/2026-11-26-historical-destination-plans.json)

## Requested settings and reported passes

A reviewed Home Assistant draft directed the docked Max 700 Combo to vacuum
one room with suction level 1 and two passes enabled. The matching Roomba
timeline echoed both settings and reported zero passes during the active
room stage. Its signed history later returned `done: ok` and a room event
with status `5` (`user_ended`) and `passCount: 0` after a return-to-base
request. This run verifies the request and reporting path. A natural second
pass was outside the scope of this room trial.

The robot returned to its dock with error code 0. The active floor revision,
rooms, zones, restrictions, routines, and schedules matched the initial
reads. The run changed the robot's reported two-pass setting from off to
on. A targeted setting write restored off and an independent read confirmed
it while the robot stayed docked.

Isolated Chrome rendered the live row from a real timeline at 358 and 900
pixels. The card displayed suction and two passes under **Requested** and
zero under **Reported passes**. The authenticated WebSocket and automated
checks verify those fields, preservation of false and zero, and handling of
null parameter groups. The suite passed 2,465 Python tests with 100% line
and branch coverage and 55 card tests.
[Anonymized trial evidence](evidence/2026-11-25-requested-and-reported-passes.json)

### Saved-zone passes and live stage timing

Two isolated Home Assistant trials used a 2.56 m² saved zone on a
Max 700 Combo with suction 1 and two passes requested. The official
Android app displayed the requested passes and elapsed zone minutes.
A return-to-base request ended the first trial during the second pass.
The second trial completed after seven minutes and returned to the
dock without a control command. Both trials ended at the dock with
error code zero.

For both trials, the signed history contained a first event with
status `finished_with_more_passes` and raw `passCount: 0`. The
second event used raw `passCount: 1` and reported `user_ended` in
the cancelled trial and `finished` in the completed trial. The two
passes used different robot revisions for the same saved zone. The
integration correlates them against the requested floor and zone
before counting the completion events. Authenticated Home Assistant
history exposed two confirmed passes, the raw value of one, and the
zone label from the archived map after the trial zone was deleted.

The updated integration also returned time in the zone's current stage
on authenticated floor-plan reads. At 118 seconds from mission start it
reported 67 seconds in the cleaning stage. The Android view showed two
minutes at 121 seconds from mission start. While the robot was relocating,
the destination had no stage time. Isolated Chrome verified that the
same destination row showed the requested setting, reported pass count,
and elapsed time at 358 and 900 pixels without overflowing.
The elapsed value restarted when Roomba reported the second stage.
Android continued to show accumulated minutes for the whole zone.
The accumulated timer was later reproduced from the full event sequence.

The temporary zones were removed. The saved rooms, zone and policy
layers, boundaries, routines, and schedules matched the baseline.
Suction and the two-pass default matched the preflight values after
the natural run. Roomba updated robot-detected furniture identifiers
and moved the dock marker by 25.63 cm in the map while learning from
the run. The run added no user-saved furniture or cleaning regions.
[Anonymized zone evidence](evidence/2026-11-26-saved-zone-passes.json)

### Household 0.66.0 upgrade

The 0.66.0 archive downloaded on the household instance matched the
checksum calculated from the published release archive.
The household deployment backed up 0.27.0, passed `ha core check`, and
restarted Core. Home Assistant served the released map card and listed
all three robots and their three dock devices. The dashboard resource was
updated to the 0.66.0 URL. The installed card displayed two completed
passes and the requested suction and pass settings for the real saved-zone
report. The deployment verification sent no robot commands.

### Accumulated destination cleaning time

The completed two-pass zone report supplied the intervals 51–207 and
208–366 seconds after mission start. Replaying the report through the
live decoder recovered 70 seconds at the first Android sample and 220
seconds during the second pass. Android showed two and four minutes at
those samples. The signed history reports 314 accumulated seconds.

A separate physical trial used one pass on a temporary saved zone. The
robot reported the zone starting at second 29 and the pause starting at
second 58. Android displayed one elapsed minute both early in the
pause and 72 seconds after it began. The correlated live replay kept
the cleaning clock at 29 seconds. The robot kept the original area
timestamp after resume and closed the pause at second 147. The
following live readings showed 46 and 59 elapsed cleaning seconds.
The signed report closed the area at second 206 and recorded a second
pause ahead of docking. Its accumulated cleaning time was 74 seconds.
An authenticated isolated Home Assistant instance independently
returned 314 and 74 seconds for the matching signed reports.
Chrome replayed the live and completed rows at 358 and 900 pixels and
verified the elapsed time, paused state, and confirmed pass count.

The robot returned to the dock with error code zero. Read-back
confirmed the original map geometry, saved programs, suction, and
two-pass setting after the temporary zone was removed.
[Anonymized timing evidence](evidence/2026-11-26-destination-elapsed.json)

## Historical map layers

The integration opened 21 signed reports for the Max 700 Combo using each
mission's own floor revision. Three included a saved cleaning zone. The
21 reports had no policy shapes. A separate signed read of an earlier map
edit revision from the same robot returned a keep-out area, a no-mop area,
and a virtual wall. The historical projection matched all three against
the private local snapshot. All calls were reads.

An isolated Chrome run used a real archived report with a saved zone and
verified the cleaning path, travel path, and coverage controls at 358
and 900 pixels. Hiding a path kept the final recorded position and zone
visible. The 3D view and camera controls kept the filters. The authenticated
Home Assistant regression test checks that a zone and wall come from the
report revision. The full suite passed 2,463 Python tests with 100% line
and branch coverage and 55 card tests.
[Anonymized layer evidence](evidence/2026-11-25-historical-map-layers.json)

## Editing virtual walls

On a docked Max 700 Combo, the coordinator created a horizontal wall,
changed it to a vertical wall, changed it to a diagonal wall, and removed
it. Each step took one signed map write. Both moves kept the same identifier.
The returned archives confirmed the endpoints and preserved a companion
no-mop zone, the room geometry, and other map layers. With automatic
backups enabled, Home Assistant saved one snapshot before each write.
After the companion zone was removed, the parsed active map matched its
state at the start of this trial. The trial sent zero movement commands.

The authenticated WebSocket tests cover creating, reading, changing, and
removing a line through Home Assistant. Isolated Chrome verified the
keyboard endpoint fields, floor-specific confirmation, and resulting
request at 358 and 900 pixels. The suite passed 2,463 Python tests with
100% line and branch coverage, 54 card tests, and Home Assistant's
integration validator.
[Anonymized wall evidence](evidence/2026-11-25-virtual-wall-editing.json)

## Recovering room names and types

A signed Max 700 Combo trial divided and recombined an open room. The active
map returned to one room with the original identifier, name, and type. The
floor border, furniture, restrictions, and all other parsed layers matched
the pre-edit archive. Roomba recalculated the room outline. Its maximum
deviation from the original was 0.05 native map units, and the room area
changed by approximately 0.0077%. The original archive was retained for
comparison. A later signed read returned the exact pre-edit archive, and
the active map still showed the room-outline difference. The trial issued
zero movement commands.

A follow-up trial recorded the active map, set a temporary accented room
name and type, and received a JSON revision acknowledgement. Home Assistant
read the published revision and its signed archive before reporting the
successful edit. The recovery review identified the changed boundary in the
pre-split backup. A second backup with the matching footprint recovered the
original room name and type in one write and reported no remaining metadata
changes on a repeated review. The room footprint, other map layers, and
original routines matched their state at the start of the metadata trial.
[Anonymized evidence](evidence/2026-11-25-room-details-recovery.json)

The changes passed 2,452 Python tests with 100% line and branch coverage,
53 card tests, and Home Assistant's integration validator. Isolated Chrome
verified the review and confirmation at 358 and 900 pixels using a
synthetic floor.

## Recovering furniture placements

A signed Max 700 Combo trial saved all 18 supported furniture types and
read back their type, source, orientation, and ordered corners. Cleanup
preserved the existing furniture and restored the original floor. A
separate trial showed that Roomba ignores an unlearned identifier sent as
robot-detected furniture.

The recovery trial moved a user-added object, removed a detected object,
and added newer furniture. Roomba removed the detected object's destination
from a three-area routine. The first recovery returned the expected sources
and vertices with a heading difference of approximately 0.011 degrees for
two objects. The integration now accounts for this rounding when it verifies
the saved furniture layer.

The end-to-end trial reviewed the changes and the linked routine, saved an
automatic pre-restore backup, and restored both placements in one native
write. The detected object returned with its original `robot` source and
the newer object stayed on the map. Program review waited for the matching
placement, then restored the missing destination with a separate
confirmation. Roomba returned the same routine ID, three destinations in
order, original per-area vacuum and mop preferences, and matching furniture
polygons. Cleanup restored the original map and routines with zero movement
commands. [Sanitized evidence](evidence/2026-11-25-map-furniture-recovery.json)

The changes passed 2,434 Python tests with 100% line and branch coverage,
52 card tests, Home Assistant's integration validator, and isolated Chrome
checks on a synthetic floor at widths of 358 and 900 pixels.

## Recovering map restrictions

A signed Max 700 Combo trial saved a keep-out zone, a no-mop zone, and a
linear virtual wall. The previous line encoding returned the same point
twice. The follow-up confirmed that kind `2` with `[A, A, B, B]` retained
both endpoints during creation and a later policy-layer replacement.

The integration saved a local backup, moved the keep-out zone, and removed
the no-mop zone and wall. The recovery review showed the three changes and
confirmation saved an automatic pre-restore backup. One native write
restored the original identifiers and shapes, kept a newer no-mop zone, and
returned a new active revision. A repeated review reported zero changes.
Cleanup restored the original floor and sent zero movement commands.
[Sanitized evidence](evidence/2026-11-25-map-restriction-recovery.json)

The recovery changes passed 2,423 Python tests with 100% line and branch
coverage and 51 map card tests. Isolated Chrome verified the reviewed write
at 358 and 900 pixels with a synthetic floor. Home Assistant's integration
validator reported zero invalid integrations.

## Recovering program destinations

A signed Max 700 Combo trial captured two cleaning zones, a routine, and a
disabled schedule in a local backup. The trial changed both program names
and the scheduled day and time after capture. Deleting one linked zone
pruned it from both programs. Zone recovery reproduced its original rotated
outline. Each program review displayed the recovered zone and the original
sequence and vacuum and mop preferences. Separate confirmations returned
the same two program IDs, destinations, and per-area preferences while
keeping the newer names, scheduled time, weekday, and disabled state.
Cleanup restored the original floor geometry, settings, and program lists.
The trial sent zero movement commands.
[Sanitized evidence](evidence/2026-11-25-program-destination-recovery.json)

Version 0.62.0 passed 2,415 Python tests with 100% statement and branch
coverage, 50 map card tests, and Home Assistant's integration validator.

## Recovering cleaning zones

A signed Max 700 Combo trial saved two temporary cleaning zones and linked
both to a temporary routine and a disabled schedule. Moving and renaming
one zone retained both targets and their settings in each program. Deleting
the second zone reduced both programs to one target. Roomba accepted one
batch write restoring the moved zone and recreating the deleted zone under
its original identifier. The recreated destination remained absent from
both programs after the restore was confirmed.

A separate run verified the integration's local backup, recovery review,
two currently linked programs, automatic pre-restore backup, one native
write, and the published geometry and zone identifiers. The trials sent
zero movement commands. Cleanup removed the temporary programs and zones
and confirmed the original floor geometry, settings, and program lists.
Map writes generated new revisions during the trials.
[Sanitized evidence](evidence/2026-11-25-cleaning-zone-recovery.json)

A follow-up signed trial recovered a rotated zone with its original vertices
and reattached its destination through separate routine and schedule edits.
Roomba confirmed the same program IDs, area order, vacuum and mop preferences,
scheduled time, and disabled state. This verified the protocol for a separate
program recovery flow. The current card recovers cleaning zone geometry and
previews the programs that currently refer to those zones.

Version 0.61.0 passed 2,388 Python tests with 100% statement and branch
coverage and 49 card tests. Isolated Chrome verified the review, current
program dependencies, and confirmation at 358 and 900 pixels with synthetic
data. Household installation and screenshots of this version remain pending.

## Restoring backed-up floor settings

A signed Max 700 Combo trial captured an active floor, then temporarily
changed its name and rotation. The restore review read the local backup and
the current floor without sending a write. Confirmation saved an automatic
pre-restore copy and sent one settings request. A fresh Roomba read returned
the recorded name and angle with identical revision, destination inventory,
and native archive bytes. The trial fully restored the original floor and
sent zero movement commands. A separate signed probe confirmed that an
accented 20-character name and orientation can be set together on an
existing floor and that both original settings can be restored.

Home Assistant tests verified that a backup of an older revision can restore
settings on the same floor, denied confirmation without control permission,
and refused to write after the current settings changed during automatic
capture. [Sanitized evidence](evidence/2026-11-25-map-settings-restore.json)

Version 0.60.0 passed 2,368 Python tests with 100% statement and branch
coverage and 48 card tests. Isolated Chrome verified the review, accented
name, angle, and confirmation at 358 and 900 pixels with synthetic data.
Household installation and screenshots of this version remain pending.

## Local map backups

A signed Max 700 Combo trial used the live attic floor to verify automatic
backup before a temporary rename. The recorded floor settings and native
archive matched the active revision before the write. The trial restored
the original name and confirmed the same revision, destination inventory,
orientation, and archive bytes. Repeating the capture returned the same
ID and timestamp, and pinning the saved copy persisted in private storage
with file mode `0600`. The trial sent zero movement commands.

A fresh isolated Home Assistant instance then read the pinned snapshot
after closing Roomba's connection. It rebuilt the floor geometry from the
local archive and recovered the original binary byte for byte. Authenticated
Home Assistant tests separately verified export after unloading the provider
entry, per-robot isolation, stale revisions, retention, and failure before
a provider edit when an automatic backup cannot be saved.
[Sanitized evidence](evidence/2026-11-25-local-map-backups.json)

Version 0.59.0 passed 2,354 Python tests with 100% statement and branch
coverage and 47 card tests. Hassfest and specification validation passed.
Isolated Chrome verified the offline preview, accented names, layer legend,
and JSON export at 358 and 900 pixels with synthetic data. Installation and
new screenshots from the household dashboard remain pending.

## Schedule editor and per-area settings

Roomba Home Android 3.4.1 exposed an existing weekly schedule's cleaning
preferences from **Edit automation**. Four observed weekly schedules used
ordered regional commands. The integration read the recognized profiles
from all four and checked both attic schedules against the current floor.
The captured one-time Android command also exposed an inactive mop
wetness value in a vacuum region. The editor loaded it and kept it available
when switching the room to mop mode.

Two signed trials on the Max 700 Combo used disabled temporary schedules.
One updated a weekly entry's name and changed its room from vacuum to mop.
The other loaded the native timestamped one-time format and changed its
room to mop. Both read back the exact wetness and SmartScrub settings,
original start and frequency, and disabled state. Both trial entries were
removed. The original schedules and floor matched their preflight reads.
The trials sent zero movement commands.
[Sanitized schedule editor evidence](evidence/2026-11-25-schedule-editor.json)

Version 0.58.0 passed 2,329 Python tests with 100% statement and branch
coverage and 45 card tests. Hassfest and specification validation passed.
The schedule editor passed a weekly creation and one-time settings edit in
isolated Chrome at 358 and 900 pixels with synthetic data. Household
installation and screenshots of this version remain pending.

## Native multi-area favorites

The signed edition 1 collection contained six favorites across three
Max 700 Combo robots. Each favorite contained one robot command. Four
favorites had five or six rooms and used ordered Replay or timestamped
formats. The integration recovered the complete regional settings from all
six favorites and resolved every destination against its current floor.
One six-room favorite used automatic order. The Android Automations view
grouped schedule rows by robot separately from saved favorites.

A signed one-room trial created an automatic-order favorite and repeated
the create request to verify it returned the same ID. The trial changed
the favorite to listed order, read back identical regional preferences,
and then removed it. The original favorites and floor matched the
preflight reads, and the trial sent zero movement commands. Home Assistant
tests cover dispatch with different modes per area, an explicit current
floor revision, and furniture validation.

Version 0.57.0 passed 2,303 Python tests with 100% statement and branch
coverage and 43 card tests. Hassfest and specification validation passed.
The motion, coverage filters, and automatic-order editor also passed in
isolated Chrome at 358 and 900 pixels with synthetic data. Household
installation and screenshots of this version remain pending.

## Recent and suggested routines

The signed Max 700 Combo floor request returned three recent routines and
two suggestions, clean all rooms and clean a point. Android opened the
same furniture destination as the first recent entry. Two archived
furniture polygons resolved to their current outlines, with a maximum
observed difference of 0.05 mm. The current floor projection could load
all three recent drafts. [Native routine guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

On a second Max 700 Combo, the candidate loaded a provider recent routine
for one room and started that reviewed vacuum-only draft through the
Home Assistant vacuum entity and the real robot command transport.
The signed mission history matched the sole room, the reviewed revision,
and the exact per-area preferences. Roomba reported one minute before the
trial cancellation. The robot returned to its dock without an error, and
the floor archive, account favorites, and robot schedules matched their
preflight values.
[Anonymized trial evidence](evidence/2026-11-25-quick-routines.json)

The suite passed 2,207 Python tests with 100% statement and branch coverage
and 31 card tests. Hassfest and specification validation passed. The routine
list, draft import, and start review rendered in isolated Chrome at 358 and
900 pixels. Household installation and screenshots remain pending.

## One-off area cleaning

In Roomba Home on Android, the Max 700 Combo's room editor showed Normal
with medium suction and liquid. Choosing Light and tapping the room
editor's **Save** applied low suction and liquid to the current selection.
A signed read after the change matched the original active revision,
room defaults, and account favorites. Reopening the floor after restart
showed Normal again.

A repeat with verified HTTPS capture recorded three time-estimate calls
and one analytics event while editing. Tapping **Save** produced zero
requests to the observed Roomba hosts during the test window. The signed
room defaults, map revision, and favorite inventory still matched the
preflight values. These observations confirm that the edit applied to
the current draft.

In an isolated Home Assistant instance, the authenticated floor plan
provided the single active room and its exact revision. The normal
`run_cleaning_draft` service started a vacuum mission targeting that room. The robot
returned to its dock without errors when Home Assistant requested it,
with the original rooms, zones, restrictions, routines, and schedules
preserved.

An independent signed history read without the quick-cancellation filter
matched the reviewed room, vacuum mode, suction level 1, and two passes
on the requested map revision. The standard filtered history excluded
the short canceled mission. The stored command confirmed the requested
two-pass setting. The trial ended before a second pass.
[Anonymized trial evidence](evidence/2026-11-26-one-off-area-cleaning.json)

Chrome exercised the map selection, one-off preferences, start
confirmation, and transfer to the named routine editor at 358 and 900
pixels using redacted data. The suite passed 2,544 Python tests with 100%
statement and branch coverage and 68 card tests.

## Remembered area cleaning preferences

Roomba Home's release notes describe the Routine Builder remembering its
last cleaning settings. In the Max 700 Combo trial, the signed map response
contained twelve metadata records. The active archive matched one current
room. Roomba returned vacuum, mop, and two combined profiles for that room,
with vacuum as the last recorded mode. The Android room preview displayed
combined cleaning when opened. The card shows the reported mode separately
and lets the user explicitly choose which mode's settings to reuse.
[Roomba Home release notes](https://homesupport.irobot.com/articles/en_US/Knowledge/40500)

An isolated Home Assistant instance received the four profiles through the
authenticated floor plan command and received them again without geometry
when it requested the same map with the cached inventory identifier. Its
standard routine action saved the chosen vacuum profile, with suction 1 and
two passes. A separate signed account read confirmed the settings. The
temporary routine was deleted and the original routines, floor, and
remembered settings matched their preflight values. No movement command was sent.
[Anonymized trial evidence](evidence/2026-11-26-remembered-area-preferences.json)

Chrome opened the card's routine and schedule editors at 358 and 900 pixels
using the redacted live profile response. In the routine editor, it exposed
both combined variants, applied the vacuum settings to the draft, and
issued only the routine and schedule list actions. The suite passed 2,544
Python tests with 100% statement and branch coverage and 65 card tests.

A second trial selected both combined variants separately. The signed
read-backed routines retained suction and liquid levels of 1 and 1 for
the profile recorded under mode 6, and 3 and 2 for the profile recorded
under mode 32. The temporary routines were removed, and the map, defaults,
and original favorites matched their preflight values. The trial sent no
movement command.

At both viewport widths, the one-off editor copied each profile on
request, kept its settings visible, and required a new review when a
reported profile changed. Copying either profile left the draft unsaved.
The updated suite passed 2,544 Python tests at 100% statement and branch
coverage and 69 card tests.

## Routine draft estimates

The captured Android favorite supplied an empty estimate array at creation.
Two disposable integration favorites with the same reviewed room and
combined profile returned an identical good-confidence estimate of 3,449
seconds, one with that field omitted and one with an empty array. The
signed read confirmed cleanup of both routines and preservation of the map.

The signed estimate table returned 36 profile rows for the current room
on a Max 700 Combo. A comparison across seven favorites captured from
Android 3.4.1 matched their saved times to the second. Normal combined
cleaning matched 3,449 seconds, Deep combined cleaning matched 6,899,
and Deep sequential cleaning matched 7,200.

The Android draft with a furniture area and a room displayed 58 minutes
beside the room and omitted the time for the furniture and the full draft.
The integration retained both areas in order and reported the room's
3,449 seconds as partial. The read confirmed the same floor revision
afterward. The trial sent zero robot, favorite, or map writes.
[Anonymized draft evidence](evidence/2026-11-25-routine-draft-estimates.json)

The Home Assistant vacuum entity also returned the same reviewed subtotal
from Roomba through an in-memory coordinator. The suite passed 2,164 Python
tests with 100% statement and branch coverage and 29 card tests. Hassfest
and specification validation passed. The mixed partial estimate rendered
and reset on a changed revision in isolated Chrome at 358 and 900 pixels.
Household installation and screenshots of this version remain pending.

## Fixed routine presets

The Max 700 Combo advertised `digiCap.cleaningProfiles: 2`. In Android
3.4.1, the Light, Normal, and Deep preferences showed three combinations
of suction, liquid, and passes across vacuuming, mopping, combined
cleaning, and sequential cleaning. Signed favorite reads confirmed the
Deep parameters in all four modes. The sequential favorite used mode
512 without an edit marker. The candidate read its exact regional profile.
The four Smart editor screens displayed no fixed room levels.
[iRobot routine guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

A signed save and edit test mixed one room and two furniture destinations
with three different modes and profiles. Roomba confirmed the initial
order and every setting. Applying one preset to all three areas during a
reorder retained all three modes. The verified floor archive and six
original favorites stayed intact. The test removed the four temporary
routines and sent no movement commands.
[Anonymized preset evidence](evidence/2026-11-25-fixed-routine-presets.json)

The suite passed 2,155 Python tests with 100% statement and branch
coverage and 26 card tests. Hassfest and specification validation passed.
In isolated Chrome, both preset controls worked on synthetic mixed-mode
areas at 358 and 900 pixels. Household installation and screenshots of
this version remain pending.

## Smart routine recommendations

The current signed score response for a Max 700 Combo included seven
room recommendations. Six rooms received suction and liquid level 1.
The seventh received level 3, two passes, SmartScrub, and carpet boost.
The response matched the active floor revision.

On the attic robot, Android saved a temporary favorite with **Smart**
selected. That record contained concrete suction and liquid level 2 for
its room. A signed read for the same floor revision recommended level 1
for both. A repeat captured the successful Android write itself and
confirmed it already carried the level 2 regional parameters.
The command contained no field identifying Smart. The integration's
recommendation preset uses the signed room score preferences.
[iRobot Smart routine guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

The integration read the attic recommendations through its production
coordinator and saved a temporary ordered routine with a furniture
destination and one room through the Home Assistant vacuum entity. The
signed read-back confirmed the order, the furniture's chosen suction,
and the room's recommended settings in its selected mop mode.
Both temporary favorites were removed. The final signed reads matched
the preflight favorites and floor revision.
[Recommendation tests](../tests/test_routine_presets.py) ·
[Draft tests](../tests/frontend/map-card.test.cjs)

## Routine appearance

The Android favorite editor offered seven colors and an emoji picker.
On a Max 700 Combo, its edition 1 favorites request stored a smile emoji
and `#CBCBFB`. Proxyman recorded HTTP 201, and an independent signed
read confirmed both fields and the reviewed destination. The trial then
removed the temporary routine.

In isolated Home Assistant, **Create a cleaning routine** stored the same
appearance. **Update a cleaning routine** changed it to a joined emoji
with `#FDF4A9`. A signed read confirmed the new values with the same
command, creation timestamp, and other routine metadata. The temporary
routine was removed. A separate update confirmed that the color picker
could store `#4466AA`, outside the seven presets. The original active routines and floor were
preserved, and the trials sent zero movement commands.

Chrome verified the icon preview, seven swatches, appearance-only update,
and duplication on 358 and 900 pixel viewports. The suite passed 2,555
Python tests with 100% statement and branch coverage and 70 card tests.
[Anonymized trial evidence](evidence/2026-11-26-routine-appearance.json)

## Native single-area routines

Roomba Home Android 3.4.1 saved Light, Normal, Deep, and Smart with one
room on the current Max 700 Combo floor. All four records stored the
concrete combined vacuum-and-mop settings for that room. The app displayed
58 minutes for Light, Normal, and Smart, and 115 minutes for Deep. Roomba
returned minute estimates with good confidence. An integration read matched
all four profiles and read two original ordered app routines with the
Normal profile tag.

Smart and Normal saved the same parameters in this trial. Reopening the
Smart routine showed Normal in the app. The integration exposes the
recorded room settings. Adaptive selection in other conditions requires
additional verification. [Android trial evidence](evidence/2026-11-25-native-single-area-routines.json) · [iRobot map and routine guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

The vacuum action started the Android-created Light routine on R2D2 via
the integration command path. The robot washed its mop and reached the
cleaning phase. The cancellation test returned it to the dock. Signed
history matched the active map revision, the room, and every saved regional
parameter. The report recorded two minutes and a cancelled outcome. A
separate read confirmed that R2D2 was docked and drying had resumed.

A signed rename preserved the estimate and all regional settings. A
duplicate kept the saved settings and accepted a suction edit independently.
The trial removed the duplicate and the four app test routines. A fresh
read matched all six original active favorites and the existing floor revision.

The suite passed 2,142 Python tests with 100% statement and branch
coverage and 25 card tests. Hassfest and specification validation passed.
The estimate dialog rendered with synthetic data at 358 and 900 pixels
in an isolated Chrome profile. Household installation and screenshots of
this version remain pending.

## Room cleaning scores

A read with the production client on a Max 700 Combo matched the current
floor plan and the room inventory from its saved archive. A second floor
read confirmed that the revision stayed current. Roomba reported one room
score of `0.0`, a range boundary of `0.7`, normal traffic, and timestamps
for the update and for its latest processed, cleaned, and unfinished
mission records. The suggested profile was combined vacuuming and mopping,
suction level 1, wetness level 1, and three disabled options for two passes,
SmartScrub, and carpet boost. The trial issued zero robot or map commands.
[Anonymized trial evidence](evidence/2026-11-25-room-cleaning-scores.json)

The suite passed 2,120 Python tests with 100% statement and branch
coverage and 24 card tests. Hassfest and specification validation passed.
An isolated Chrome session rendered the score dialog with synthetic data
at 358 and 900 pixels. Household installation and screenshots remain
pending.

## One-time cleaning schedules

In Roomba Home Android, saving a future time without weekly repeat days
showed a single execution. The signed read confirmed `frequency: ONCE`
and one ISO weekday. The native command relied on the robot ID in the
schedule options. The test removed that entry and verified the five
original household schedules. [Roomba Home release notes](https://homesupport.irobot.com/articles/en_US/Knowledge/40500)

The integration created a disabled entry, edited its time, converted it
to weekly and back to one-time, selected tomorrow, and confirmed
activation and deactivation. All edits preserved the selected destination.
Deletion and a fresh read confirmed that the test entry was removed.

A separate test armed a one-time vacuuming schedule. The integrated
next-start calculation matched the planned time. Roomba reported an
active cloud-initiated mission 28 seconds after that time. The trial
cancelled the mission after confirming start, returned R2D2 to its dock,
and restored drying. Roomba had already removed the one-time schedule.
A signed read matched all five original household schedule groups.

The automated suite covers frequency and ownership, idempotent writes,
weekly compatibility, one-time dates, and daylight saving transitions.
The suite passed 2,097 Python tests with 100% statement and branch
coverage and 22 card tests. Household installation and screenshots
remain pending. [Anonymized trial evidence](evidence/2026-11-25-once-schedule.json)

## Wet-cleaning route activity

Two localized missions on the Max 700 Combo completed through Roomba Home
Android. The combined run recorded 3.25 m² and the mop-only run recorded
3.07 m². The archived route of each mission established how the live
position codes correspond to movement. Code 6 matched 182 combined
vacuum-and-mop points and code 4 matched 154 mop-only points. One sample
of each code matched travel. The comparison used the nearest
unambiguous trajectory within 4 cm. Code 0 occurred mainly on travel.
[Anonymized wet-cleaning evidence](evidence/2026-11-25-wet-route-activity.json)

The first combined start returned to the point picker while the dock
was actively drying. The next start succeeded after ending the drying
cycle. The mop-only picker initially disabled Start for the displayed
point. Moving the point enabled Start and the mission began. Post-mission
pad washing and drying matched the dock's documented lifecycle.
[AutoWash dock documentation](https://homesupport.irobot.com/articles/en_US/Knowledge/10014)

The matched mop timeline reported that the active zone stage began 232
seconds after mission start. The request was read 339 seconds into the
mission. The app showed elapsed time for the point. The stage timestamp
is exposed separately from the last timeline update and whole-mission
elapsed time.

The final device read confirmed charging, zero mission errors, and
automatic drying. Both runs kept the original floor, rooms, cleaning
zones, and restrictions. Roomba advanced the map revision and changed
four of ten furniture entries. The trial sent zero map-edit requests.

Home Assistant tests cover the four activity options, expiry and mission
end, confirmed stage times, and both map views. The suite passed 2,076
Python tests with 100% statement and branch coverage and 22 card tests.
Household installation and cropped screenshots remain pending.

## Live route recovery

The late-join replay used a localized vacuum mission already completed
by the Max 700 Combo. It started with 20 direct position samples from
partway through the mission. The production client fetched the signed
route object from Roomba's update. The replay also used an earlier copy
captured while the robot was cleaning. Each restored 64 preceding
positions and kept all 20 direct positions. The recovered samples
matched the direct recording's operating modes. The maximum coordinate
difference was 1.12 cm. The live marker kept its direct position.

The automated checks cover cross-robot and expired URLs, broken objects,
unrelated or insufficient motion, optional read failure, rate of retry,
and removal of the route when the mission ends. The replay sent zero
commands. Household installation and cropped captures remain pending.
[Anonymized replay evidence](evidence/2026-11-25-live-route-backfill.json)

## Live route activity

The Max 700 Combo completed one localized vacuum mission started from
Roomba Home Android. The app showed elapsed time and followed the return
to the dock. The MQTT stream supplied 283 positions in 122 batches, with
mode value 0 during travel and 5 during vacuuming. The archived four-minute
report showed 3.25 m² cleaned, five travel segments, and four vacuuming
segments. The test resumed the drying cycle that was active beforehand.

One raw map snapshot contained 83 positions whose indices and modes
matched the incremental stream. The snapshot used a different coordinate
origin. The available live state provided area cleaned and elapsed time.
A provider-backed remaining-time value and mission coverage denominator
still need verification.

Roomba advanced the saved floor revision during the mission. The same
floor, room geometry, clean zones, and restrictions were retained. Ten
furniture observations were present before and afterward, with six
identical across both revisions. The trial issued zero map-edit requests.

Home Assistant tests check the live map payload and expiry. Card tests
verify route colors, a matching legend, and gaps between batches.
[Anonymized live route evidence](evidence/2026-11-25-live-route-activity.json)

## Archived cleaning reports

The official Android app showed 18 map-backed cleaning reports for the
Max 700 Combo. The integration returned the same 18 and two other signed
cleaning records with no map reference. The first three map-backed reports
matched the app's recorded durations of 14, 11, and 9 minutes. Each archive
identified the exact historical revision referenced by the mission. All
three differed from the currently active revision.

The archived routes contained 15, 5, and 9 separate segments. One report
included simultaneous vacuuming and mopping. The same archives supplied
coverage, and the associated mission records supplied 9, 8, and 9 timeline
events. The comparison used only reads of existing records.

Home Assistant tests cover entity read permission, report ownership,
expired archives, and unknown report selections. An isolated Chrome run
verified opening the 3D report view with synthetic data. A follow-up
signed read checked three reports, each tied to its own archived
revision with walls, furniture, route, and coverage. Isolated Chrome used
one of those real archives to verify the report dialog, overhead and 3D
rendering, and camera rotation at 358 and 900 pixels. The original suite
passed 2,012 Python tests with 100% statement and branch coverage, 21 card
tests, and official hassfest validation. Household installation and cropped
captures in the user's Chrome session remain pending.
[Anonymized report evidence](evidence/2026-11-25-archived-cleaning-reports.json)
[Follow-up report evidence](evidence/2026-11-25-archived-report-rendering.json)

## Robot software status

On the Max 700 Combo, the Android app showed the installed robot build,
dock firmware, and the date of the last update. Its software detail page
reported that the robot was up to date. The integration read the same
installed values, retained the UTC time from `rw-software.lastSwUpdate`,
and received an empty firmware list for the installed version and dock.
The comparison used read-only requests while the robot was docked.
The suite passed 1,998 Python tests with 100% statement and branch
coverage, 18 dashboard tests, and official hassfest validation.
[Anonymized software evidence](evidence/2026-11-25-software-status.json)

## Mapping and floor removal

On a docked Max 700 Combo, the official Android app started a mapping-only
cycle. The cycle stayed `train` while its phase changed from `run` to
`stop` and back after pause and resume. Roomba returned to the dock on its
own and published a second map with a different map identifier. The original
settings, revision, room and zone inventory, and geometry layers matched the
pre-run snapshot.

The new floor was active and visible before the API supplied room metadata.
The app saved its name, and the signed archive supplied a visible room
even while the separate room inventory was absent. The app showed a
20-character first-name limit and a 16-character rename limit. The
settings endpoint accepted and returned an accented 20-character name on
the disposable floor without changing its geometry revision.

The integration started, paused, resumed, and cancelled a second short
mapping run in the same attic. It returned the robot to the dock and
restarted drying. One signed visibility request removed the disposable
floor. A separate list and archive read confirmed the original map and its
destinations were intact and it was the only visible floor on that robot.
An individual metadata read still returned the removed map with
`visible: false`, while its former active revision did not match the
read-back. The removed map was also absent from a list requested with
`visible=false`.

The suite passed 1,971 Python tests with 100% statement and branch
coverage, 18 dashboard tests, and official hassfest validation. Household
deployment and cropped Chrome screenshots remain pending.
[Anonymized lifecycle evidence](evidence/2026-11-25-map-lifecycle.json)

## Washing during drying

With the Max 700 Combo dock drying, the official Android app accepted a
manual wash after confirmation. The robot reported `padWash`, wash state
`602`, dry state `701`, and dock error `0`. The wash completed with the
robot charging and drying stopped.

After starting drying again, the integration transport sent one `washPad`
command. It received an acknowledgement and observed the same wash and
drying state changes. The robot returned to charging after roughly four
minutes with dock error `0`. The trial restarted drying and verified the
same map revision and destination inventory. Home Assistant tests confirm
that the wash button remains available during drying. Other busy-state
checks are preserved.
The suite passed 1,950 Python tests with 100% statement and branch
coverage, 16 dashboard tests, and official hassfest validation.
[Anonymized dock wash evidence](evidence/2026-11-25-wash-during-drying.json)

## Maintenance counter reset

The official Android app showed reset controls for the four tracked
replacement parts and completion controls for the two washing systems on a
Max 700 Combo. A signed read listed the same six counters, and the public
catalog marked the dust bag counter as disabled. The native SDK specifies
a one-part zero-counter request. The household counters were preserved.

Home Assistant tests cover explicit confirmation, disabled or missing
counters, signed request scoping, lost acknowledgements and delayed
provider confirmation. A live write remains to be verified after a part is
replaced or serviced. The suite passed 1,948 Python tests with 100%
statement and branch coverage, 16 dashboard tests, and official hassfest
validation.

## Voice pack installation

The official Android app downloaded and installed Czech on a docked Max
700 Combo. Independent reads confirmed download, installation and
automatic selection. Spanish (Spain) was selected again after the trial.
The robot reported one slot for additional voices and 13 factory voices.

A Danish attempt during an outstanding deployment reached error 139 and
preserved the installed and active voices. The official app installed the
same Danish package after the pending deployment ended. The integration
transport then replaced that Danish pack with Czech from a fresh catalog
response. Independent reported state matched the deployment ID and
confirmed installation nine seconds after the request. The integration
restored Spanish (Spain). Czech remains in the additional slot. The map,
factory voices, docked state and active drying were preserved.

Home Assistant tests cover availability, pending deployments, a missed
acknowledgement, terminal provider errors, correlation, timeouts, and
selecting an already installed voice. The physical check used the
integration transport. Deployment in the household installation remains
pending. The suite passed 1,932 Python tests with 100% statement and
branch coverage, 16 dashboard tests, and official hassfest validation.
[Anonymized voice installation evidence](evidence/2026-11-25-voice-installation.json)

## Robot reboot and voice catalog

The 0.33.0 integration adds a configuration button for reboot. The app
reboot and the integration's direct `reset` publication both produced a
connection drop and a subsequent return. With the integration transport,
the robot first reported offline after 36 seconds and was back, docked and
charging, after 91 seconds. The associated map, its region inventory, the
robot name, and the selected voice matched the readings before the command.
The app trial interrupted an active drying cycle. After the experiments,
the original dock returned to active drying.

The public model catalog returned 25 languages. The same robot reported
13 installed voices, leaving 12 additional options in its catalog response.
The count matched the additional options in the official app, and the
current voice remained Spanish (Spain). The suite passed 1,904 Python
tests with 100% statement and branch coverage and 16 dashboard tests.
[Reboot and voice catalog evidence](evidence/2026-11-25-reboot-and-voice-catalog.json)

## Robot name and voice language

The 0.32.0 integration adds a configuration text entity for the robot name
and a selector for its installed voices. The official Android app and the
integration's MQTT writer changed both settings on a docked Max 700 Combo.
Independent reported-state reads confirmed each change and restoration,
including a name with an accented character. The installed inventory had
13 options before and after the trial.

Home Assistant tests cover native configuration actions, an installed voice
removed since the last poll, and an external rename. Device and entity
identifiers and the Home Assistant device alias remain stable. The suite
passed 1,892 Python tests with 100% statement and branch coverage and 16
dashboard tests. The household Chrome session still needs deployment and
visual verification.
[Robot settings evidence](evidence/2026-11-25-robot-identity.json)

## Point cleaning from the floor plan

Version 0.30.0 added a marker and confirmation dialog for point vacuuming.
Dashboard tests verify pointer placement on a rotated 3D floor, keyboard
coordinates, an overlapping saved zone, rejection of a keep-out location,
and one submission after confirmation. A changed map revision invalidates
the previous confirmation. Authenticated Home Assistant tests cover the
control permission, the older unreviewed service call, and rejection of
stale map and inventory identifiers before a command is published.

Version 0.31.0 adds mopping to the point action and card. The official app
started a mopping mission on the Max 700 Combo. Independent reads saw pad
preparation, a mopping run, automatic return and pad washing, then charging.
Roomba's history reported success and 36 ft². Its command contained
`point_clean`, the selected map revision, `geom.center`, and mode 4 as the
sole parameter. Roomba published a newer revision of the same map after the
run. The test used the cleaning controls and made no map edits.
[Point mopping evidence](evidence/2026-11-25-point-modes.json)

The first simultaneous attempt stopped at the dock with a full dirty-water
tank (654). After dock maintenance and a new point selection, the official app
sent `point_clean` with mode 6. The robot prepared the pad, vacuumed and
mopped together, and returned to the dock. History reported success and
37 ft². The new parser also recognized the active point from the correlated
live timeline.

The fourth localized-cleaning choice sent mode 512 as the sole parameter.
The same mission reported vacuum mode (2) first and mop mode (4) after the
transition. Roomba reported success, 76 ft², and a return to charging.
The live timeline and history preserved the original point and mode 512.

A final archive comparison confirmed the same map, rooms, borders, saved
zone outlines, and restrictions. Roomba refreshed detected furniture
geometry and the reported dock point in its automatic revisions. The robot
stayed in its dock after completing the test series.

Home Assistant tests cover the optional mode, the vacuum default, the
visible choices by capability, and stale map reviews. The card and service
reject wet points in no-mop zones. A dock fault that appears after sending
the wet command produces an unconfirmed result and a dock-readiness error.
The live marker tests cover the current mission, the requested map revision,
and expiry. The suite passed 1,875 Python tests with 100% statement and
branch coverage and 16 dashboard tests. The household card still needs
verification in Chrome.
[Earlier vacuum point evidence](evidence/2026-11-23-point-clean.json)

## Automatic mop wash settings

The official Android app and independent Roomba reads established all four
settings and their supported values on a Max 700 Combo. An isolated Home
Assistant instance loaded the 0.29.0 install archive and registered three
selectors and one switch on the robot's linked dock device.

The Home Assistant services exercised every offered water temperature,
wash frequency, dispensing state, and drying duration. After each change,
the entity state matched an independent `rw-settings.state.reported` read.
Changing the wash frequency preserved the area and time interval fields.
All original values were restored with the robot docked. No mission, wash,
or drying cycle started during these settings tests.

The suite passed 1,846 Python tests with 100% statement and branch coverage,
twelve card tests, and official hassfest validation.
[Anonymized settings trial](evidence/2026-11-25-dock-preferences.json)

## Robot configuration controls

With a docked Max 700 Combo, the official Android app lowered the voice
volume from 100% to 76%, then restored 100%. A separate trial enabled and
disabled the child and pet lock. An independent Roomba client observed the
corresponding `rw-settings.state.reported` changes and the original values
after restoration.

An isolated Home Assistant instance checked and loaded the 0.28.0 install
archive with only the test robot configured. `number.set_value` changed the
volume to 76%. `switch.turn_on` enabled the lock. The entity state matched
the independent Roomba reading after each action. The same Home Assistant
services restored 100% and disabled the lock. Diagnostics reported the
loaded integration version. The robot stayed docked throughout the trials.

The full suite passed 1,823 Python tests with 100% statement and branch
coverage, twelve card tests, and official hassfest validation.
[Anonymized test results](evidence/2026-11-25-device-configuration.json)

## 3D floor plan

The official Android app on a Max 700 Combo displayed a raised floor plan
with wall faces, furniture, and a dock. Switching the 3D view off returned
to the original overhead map. The test left the robot at the dock and made
no map edits.

An active map archive contained ten exterior wall segments, one carpet
polygon, one dock point, and ten furniture footprints. The dashboard uses
those planar features and draws estimated vertical surfaces. Its WebSocket
tests verify that the optional geometry uses the same permissions and revision
as the rooms. Frontend tests cover camera rotation, selection alignment, dock
and live-marker alignment, furniture visibility, and editing in the overhead
view. The complete suite passed 1,809 Python tests with 100% statement and
branch coverage and twelve card tests.
[Archive types and units](api.md#floor-plan-display-layers)

## Skip the current destination

On a Max 700 Combo, the Android app started an ordered vacuum run at two
furniture destinations. The user confirmed skipping while the dining
table was active. The app marked the table as skipped and showed the robot
traveling toward the sofa within the same mission. Home Assistant
subsequently read a skipped result for the table and a finished result for
the sofa. The robot docked without a return command.

The device advertised `cap.mc: 3` in its associated robot capabilities.
The native SDK uses its basic `skip` command for this control. A direct
diagnostic login received HTTP 403, so this Android trial used the official
app and the installed Home Assistant timeline and history as evidence.

The installed 0.26.0 card then confirmed a skip during another two-target
vacuum mission. The Android app showed the table omitted and the robot
traveling to the sectional sofa. Home Assistant reported
`last_command_result: confirmed` while the same mission remained active.
The mission finished and the official app recorded 4.6 m² cleaned.
On 0.26.1, the card showed pending and confirmed feedback when the only
destination in another vacuum mission was skipped. The official app
reported the area omitted and the robot returning to the dock.
Home Assistant recorded the area as skipped in history, retained its
confirmed command result, and reported the robot charging at the dock.
The final installation showed all three robots and their docks.
The suite passed 1,805 Python tests with 100% statement and branch coverage
and ten card tests. It covers the stale-review guard and visible feedback.
[Anonymized skip evidence](evidence/2026-11-25-skip-current-area.json)

## Immediate saved-zone selection in 0.25.0

The installed 0.25.0 card showed one room after the previous trial's
zone was removed. An independent read still found the removed zone ID in
Roomba's inventory. The card used the active map archive to omit it.

The editor then drew and saved a new disposable rectangle. The area
appeared as a cleaning destination immediately. An independent read
confirmed its outline and absence from the associated inventory before
launch. **Run saved routine** selected that zone alone and started the
robot. The command carried one `zid`, regional vacuum mode 2, and the
confirmed active map revision. Roomba reported vacuuming after 17
seconds, and an independent read found the new ID in the inventory
during that mission.

The robot returned to the dock without intervention. Mission history
reported success, the exact saved-zone ID, and 45 ft² (4.18 m²) cleaned.
The Home Assistant card removed the temporary routine and zone. The
cleaning list returned to the original single room while the historical
result kept the zone's name. Reopening the floor in the official app
confirmed the original room, an empty zone overlay, and the previous
routine shortcuts. The package passed `ha core check`, 1,785
Python tests with 100% statement and branch coverage, nine card tests,
and official hassfest validation.

## Directed vacuum then mop

On a Max 700 Combo, the official Android app started a single furniture
destination using regional mode 512. The robot reported physical mode 2
(vacuuming) and switched to mode 4 (mopping) under the same remote mission
identity. Both phases reported error code 0.
It returned to its dock and finished the post-mission pad wash. Roomba
recorded a successful mission with 89 ft² (8.27 m²) total, including
4 minutes of vacuuming and 9 minutes of mopping in its per-mode history.

Home Assistant passed `ha core check` and restarted with 0.24.0. All three
map cards loaded, and the served card module matched the tested package.
The installed **Current mission measurements** panel displayed the
furniture name even though Roomba advertised a newer active map revision
than the one used to start the mission.

A temporary saved zone appeared in the active archive before Roomba's
destination inventory listed it. Home Assistant displayed the saved routine
with an unresolved destination. Opening the same routine in the Android app
preselected the zone. The app sent its ID as the sole `zid` destination and
the robot started vacuuming. An independent read during the run found the
zone in the associated inventory under the same active revision. The run
finished with 45 ft² (4.18 m²) cleaned and a natural return to the dock.
Mission history confirmed the exact saved zone. The Home Assistant card
offered the destination after its map refresh at mission end.

The installed 0.24.0 card then launched the saved routine on the same
zone. The command targeted one `zid` with `ordered: 1`, regional mode 512,
and no command-level cleaning parameters. Roomba reported vacuuming after
18 seconds and mopping after 325 seconds under the same mission identity.
The robot completed the sequence, washed its pad, and returned to a
charging state. Its final result was `ok` with 89 ft² (8.27 m²) total.
The history included 4 minutes of vacuuming and 6 minutes of mopping.

The live timeline used its own event revision while the command referenced
the saved user map revision. Version 0.24.1 resolves saved-zone names from
the exact command archive for live and finished results. This also
preserves the historical name when the zone is later removed.
After Core restarted with 0.24.1, the installed card showed the correct
zone name during the mopping phase. The integration registry listed all
three robots and their docks. The served module matched the tested package.

The trial zone and routine were removed. An independent read confirmed
the original room identifiers and polygons, borders, restrictions, floor
name, orientation, and routine list. Roomba retained automatic updates
to learned data, including furniture, floor types, and dock poses. Its
inventory retained the removed zone ID after the active archive returned
to its original zone layer. The historical card kept the zone's name.
[Anonymized sequence evidence](evidence/2026-11-25-directed-sequence.json)

## Ordered furniture completion and area results in 0.23.0

A Max 700 Combo completed a vacuum mission through two furniture targets
in order. The command requested suction levels 2 and 1 for the dining
table and sofa, respectively. A correlated MQTT timeline showed the table
finished and the sofa in progress, then recorded both finished as the
robot returned to the dock. The final history reported `ok`, both zone
results with status 0, the requested order and profiles, and 65 ft²
(6.04 m²) cleaned. The robot docked without a return command.

The raw timeline's zone revision differed from the user map revision in
the command. Replaying the captured history and active report through
the integration resolved the two furniture names and preserved their
individual area values, outcome codes, and reported pass counts.

Roomba automatically published a new active map revision after the run.
The new archive updated detected furniture, inferred floor type, dock
pose, and a simplified room outline. The room identifier, room name,
room polygon, borders, zone layer, and restriction layer matched the
original. The trial issued no map edits or routine mutations.

The full suite passed 1,772 Python tests at 100% statement and branch
coverage and nine card tests. Home Assistant passed `ha core check` and
restarted with 0.23.0. The installed **Last mission by area** card then
showed both furniture names, status **finished**, and the two distinct
sets of provider measurements from the historical revision.
[Evidence](evidence/2026-11-25-ordered-furniture-completion.json)

## Ordered furniture routine validation in 0.21.0

A signed API trial saved a mixed routine with a room and two furniture
destinations, with a different suction level for each. Reloading confirmed
the order and profile of every entry. Saving the same routine again
returned the existing record. The trial reordered it and removed the
temporary favorite after confirming the updated settings. The active floor
and original favorite list matched the baseline.

Home Assistant passed `ha core check` and restarted with 0.21.0. In the
installed editor, a temporary routine saved a sofa and dining table with
suction levels 1 and 3. Moving the dining table first kept the suction
settings attached to the same objects on a fresh read. **Run saved routine**
displayed the saved order before sending the start.

The robot entered area cleaning. After more than five minutes it was
sent back to its dock. Roomba recorded a cancelled mission with 36 ft²
(3.34 m²) cleaned. History retained the dining table followed by the sofa,
the matching suction levels 3 and 1, and the active map revision.
The timeline contained a zone event with status 0 for the dining table.
There was no sofa result in that run. Roomba reported the robot docked
with error code 0. The temporary routine, dashboard card, and transfer
archive were removed. A separate API read verified the original map
layers and the absence of the trial routine.

The full suite passed 1,766 tests with 100% Python statement and branch
coverage. Seven JavaScript tests passed. The furniture cases verify
mixed ordering, per-target profiles, map revalidation, and confirmation
before launch. Hassfest, Ruff, and SDD validation passed.
[Routine evidence](evidence/2026-11-25-furniture-routine.json) ·
[Installed routine editor](screenshots/roomba-furniture-routine.jpg)

## Furniture editor validation in 0.20.0

Home Assistant passed `ha core check` and restarted with 0.20.0.
The installed card placed a chair, changed its center, dimensions, and
rotation, then removed it. Reopening the editor read back the changed
placement and confirmed the original ten detected objects after removal.
An independent Roomba read found their original identifiers, sources,
orientations, and outlines. A derived cleaning outline changed during the
trial. A final write restored that outline and an independent read
confirmed the exact original archive layers. The robot remained docked.
The temporary Home Assistant card and transfer archive were removed.

The full suite passed 1,745 tests with 100% Python statement and branch
coverage. Six JavaScript tests passed, including furniture placement on
a rotated map and confirmation before dispatch. Hassfest, Ruff, SDD
validation, and the privacy scan passed.
[Furniture edit protocol](api.md#furniture-edits) ·
[Installed furniture controls](screenshots/roomba-furniture-editor.jpg)

## Restriction editor validation in 0.19.0

On the Max 700 Combo, the Android app created a no-mop rectangle, added
a separate keep-out rectangle, moved and resized each, and removed each
independently. All six saves returned HTTP 200 and a new binary map
revision. Each update kept the existing restriction ID and preserved the
other rectangle. Removing the final restriction left an empty policy
layer with the original rooms, borders, and cleaning zones. The robot
remained docked throughout the trial.

All six captured exchanges were replayed through the integration's request
serializer and archive verifier. The generated write preserved the IDs,
types, and outlines in each request, and the returned revision passed the
read-back checks.

Home Assistant passed `ha core check` and restarted with 0.19.0. The
installed card created both types, moved and resized each, and removed
each independently. An independent Roomba read verified every active
revision, the retained restriction count, and unchanged rooms, borders,
cleaning zones, floor settings, and destination inventory. The final map
matched the original policy layer exactly. The robot's Home Assistant
entity was docked. The temporary card and transfer archive were removed.

The full suite passed 1,708 tests with 100% Python statement and branch
coverage. Five JavaScript tests checked the card, including two-click
restriction placement in native coordinates and a room confirmation that
survives inventory publication. Hassfest, Ruff, SDD validation, and the
privacy scan passed.
[Restriction protocol](api.md#restriction-edits) ·
[Installed restriction controls](screenshots/roomba-restriction-editor.jpg)

### Furniture edit investigation

The Android app added a temporary chair to a map with ten automatically
detected objects, saved a change to the chair's position, size, and
orientation, and removed it. All three operations returned a new map
archive. Each app request marked the retained furniture as user-edited.
The chair's removal preserved the ten original outlines but changed
source and orientation metadata. A full write with the original source
flags restored the original layer.

A separate signed request sent only the temporary chair and confirmed
whole-layer replacement. The subsequent restoration returned all ten
original objects with identical geometry and properties. An independent
provider read confirmed the restored map, including the other archive
layers. An additional create, update, and removal sent the complete
list with the original source flags. Each response and active read-back
preserved all untouched furniture properties. The final map again matched
the original. [Furniture edit evidence](evidence/2026-11-25-map-furniture.json)

The Android app saved a temporary routine containing a sofa followed by
a dining table. The provider returned HTTP 201 and the active favorite
list included the routine. Its ordered regions contained two furniture
polygons and separate parameter blocks with the same default settings.
Home Assistant removed the test routine and a direct provider read
confirmed its absence. The trial saved the routine without starting it.
[Furniture routine contract](api.md#furniture-targets-in-routines)

## Floor settings validation in 0.18.0

The signed client renamed the test floor with an accented label and saved
a clockwise quarter-turn. The active archive revision, region inventory,
routine list, and schedule list were unchanged. The client restored and
verified the exact original name, angle, and archive.

After Core passed its configuration check and restarted, the installed
card saved an accented floor name and showed it in the header. Cancelling
a rotation preview restored the original projection. A saved clockwise
turn persisted through a full dashboard reload, and the inverse turn
restored the original projection. A final Roomba read confirmed the
original name, exact angle, room inventory, and boundary. The robot's
Home Assistant entity reported docked. The test card and transfer
archive were removed.

The local suite passed 1,679 tests with 100% Python statement and branch
coverage. The native image test checks the rotated room, path, and heading.
Three JavaScript tests verify map projection, inverse click coordinates,
and preview cancellation with the original selection.
[Floor settings protocol](api.md#floor-name-and-orientation) ·
[Installed rotation controls](screenshots/roomba-floor-rotation.jpg)

## Room naming validation in 0.17.0

On the Android app, a custom room name and the Spanish bathroom preset
saved separately through the map-version route. The editor exposed a
31-character limit for custom labels. Home Assistant uses the native
room-type identifiers verified by Roomba.

The integration saved and read back all eight room types on a single-room
Max 700 map. A temporary routine and disabled weekly schedule retained
the same ordered region and settings through the edits. A final API read
confirmed the restored room name, type, geometry, and original lists
after the temporary routine and schedule were removed.

Home Assistant passed `ha core check` and restarted with 0.17.0. The
installed card saved an accented test label and its bathroom type, then
reopened the active revision with both values. The editor restored the
original label and type. An independent read confirmed the original floor
and room names, room and border geometry, zero test zones, and a docked robot.
The temporary card and transfer archive were removed.

The local suite passed 1,650 tests with 100% Python statement and branch
coverage. It covers rename validation, mismatched acknowledgments, a delayed
region label, and stable cleaning selection after the revision changes.
[Room naming protocol](api.md#room-naming) ·
[Installed room naming controls](screenshots/roomba-room-name-editor.jpg)

## Cleaning zone editor validation

Home Assistant passed `ha core check` and restarted with 0.16.0. A temporary
map card on the test robot created a cleaning zone, moved it, changed its
size and name, and removed it. A reload showed the accented name intact.
The card distinguished the saved outline from the absent cleaning destination.
The final check confirmed the original room geometry, outer border, and
restrictions with zero saved or listed zones. The dashboard was restored
and the transfer archive removed. The editor issued no cleaning commands.

Version 0.16.1 accepts rectangles that overlap a room while extending
past its boundary. Its geometry checks were verified with three saved
outlines from the Android captures. After a Core restart, the installed
card saved and removed one of those shapes on the test floor. The full
suite passed 1,633 tests with 100% Python statement and branch coverage.
[Official app cleaning-zone lifecycle](#official-app-cleaning-zone-lifecycle) ·
[Installed cleaning-zone controls](screenshots/roomba-zone-editor.jpg)

## Room boundary editor validation in 0.15.0

The Home Assistant installation verified the candidate archive checksum,
passed `ha core check`, and restarted Core. The previous 0.14.0 component
was backed up. The three vacuum entities were present after restart. The
dashboard JavaScript resource was updated to the 0.15.0 URL and the existing
floor-plan cards loaded.

Using a temporary card for the test robot, **Edit rooms** saved a division
and displayed two selectable room destinations. The review dialog showed
the new room as the cleaning target and was cancelled before dispatch.
**Merge rooms** then saved the two adjacent rooms as one and the refreshed
card showed the original single destination. The temporary dashboard card
and transfer archive were removed.

The local suite passed 1,606 tests with 100% Python statement and branch
coverage. It includes the signed write contract, divider validation,
same-version inventory delays, stale edit rejection, permissions, and
an unconfirmed save. The official app test verified physical vacuuming
in the new room separately.
[Official app room division and merge](#official-app-room-division-and-merge)
[Editor controls](screenshots/roomba-room-editor.jpg)

### Installed room editor validation in 0.22.0

Home Assistant accepted the update with `ha core check` and restarted Core.
The card resource pointed to 0.22.0 and served the exact JavaScript from
this revision. In the installed editor, saving a divider exposed two
cleaning destinations immediately. The merge editor started with no room
selected and only enabled review after two adjacent rooms were clicked
on the canvas. The confirmation named both rooms. Saving returned the card
to one destination. An independent API read confirmed that the active
archive matched all original layers and the robot was docked. The temporary
card was removed.

The full suite passed 1,766 Python tests with 100% statement and branch
coverage, eight card tests, and official hassfest validation.
[Anonymized results](evidence/2026-11-25-room-destination-publication.json)

### Controlled room destination publication

A repeat test on a Max 700 Combo started with one visible room and two IDs
in the inventory. Dividing twice created three visible rooms with one ID
absent from both inventory responses. It stayed absent after more than a
minute at the dock. The first directed vacuum job cleaned 60 square feet
in an already listed room. Both endpoints still listed two rooms after
the robot returned.

The official Android app then started a vacuum job with only the newly
created room selected. Six seconds after the start action, independent
reads found the new ID in both the list and detail responses. The robot
reported phase `run`, and the map revision matched the pre-mission read.
The official app requested estimates and sent telemetry around the start
action. The inventory update occurred without an HTTP map-version write.
The app's running timeline showed the selected room's vacuuming step.
The final API history confirmed the exclusive target, the matching map
revision, and 47 square feet cleaned before the robot returned to the dock.
Two merges restored the active
archive to its original room and all original layer contents with the
same floor name and orientation. The separate inventory still held all
three IDs. [Anonymized results](evidence/2026-11-25-room-destination-publication.json)

### Installed room boundary recheck

On 2026-11-25, version 0.18.0 divided and merged a single-room test floor
from the Home Assistant card. The second room appeared immediately and the
cleaning confirmation named it as the sole destination. The confirmation
was cancelled without starting a mission.

An independent Roomba read showed that both metadata endpoints already
listed two room IDs before the division. The split reused the retained
ID from the earlier Android trial. After the merge, both endpoints still
listed two IDs and the card again offered exactly one room. Comparing the
active map with the baseline confirmed identical rooms, borders, cleaning
zones, restrictions, floor name, and orientation. The temporary dashboard
card was removed. [Room publication evidence](evidence/2026-11-25-room-destination-publication.json)

## Floor plan and routine dashboard validation in 0.14.0

The complete suite passed 1,581 tests with 100% Python statement and branch
coverage. Chrome exercised the card with synthetic data. It displayed a
no-mop area, found both routine and weekly schedule dependencies, signalled
unresolved destinations, reordered and duplicated a saved routine with its
per-area profile, renamed an unsupported routine without replacing its
targets, and confirmed deletion of the duplicate. A changed map inventory
prevented an outdated draft from being submitted. The routine flow issued no
cleaning commands.
[Synthetic routine editor screenshot](../README.md#floor-plan-dashboard)

The household installation verified the archive and passed `ha core check`
before restarting Core. Three robots and three docks loaded. The existing
dashboard resource was updated to the 0.14.0 URL. The two authorized floor
plans loaded, and the dependency review returned matching routines and a
weekly schedule. From the installed card, a disposable two-area routine
was created, reordered, renamed, and duplicated. The temporary entries
were deleted, and a fresh read showed the original routine count. The
0.13.0 component is available as the immediate rollback.

Android retained its Roomba Home session after a cold boot and loaded the
selected floor plan. The remote viewer opened the map details, but the edit
control remained blocked. This session established no new provider write
contract for map edits.

### Emulator graphics and display

On Apple silicon, the Android 17 capture AVD ran four virtual CPUs with
Hypervisor.framework available. Android reported approximately 4 GB of RAM.
The emulator selected SwiftShader for OpenGL ES 3.1 and Lavapipe for Vulkan.
An explicit host GPU test booted in 11.6 seconds, compared with 15.0 seconds
for one software boot at the same display setting. Roomba Home rendered
its home view with the host GPU. The guest reported OpenGL ES 3.0, below
the emulator's stated API 37 graphics target, so the capture AVD returned
to the OpenGL ES 3.1 software renderer.

The capture AVD's display was reduced from 1600 × 1920 at 320 dpi to
960 × 1152 at 192 dpi. This kept the same logical layout and reduced the
pixel count by 64%. Slow, separate clicks still did not establish a map
write. A completed cold boot and successful display are separate checks
from the ability to observe a provider edit.
[Android Emulator graphics acceleration](https://developer.android.com/studio/run/emulator-acceleration)

## Saved cleaning routine validation in 0.13.0

The complete suite passed 1,566 tests and reached 100% Python statement and
branch coverage. Ruff, hassfest, JavaScript syntax, privacy scanning, and
the specification catalog passed.

The signed API confirmed listing, creation with a server-assigned ID, an
identical create request returning the same routine, a rename and suction
change, and removal. The initial and final inventories matched. No motion
command was sent by any of those operations.

The household server verified the archive, passed Core configuration checks,
and restarted with 0.13.0. Three robots, their three docks, and the existing
floor plan dashboard loaded. From Home Assistant Actions, a single test
routine was listed, created, renamed, updated, and removed. A fresh list
confirmed the original routines were preserved. Version 0.12.1 remains
available as the immediate rollback.
[Saved routine actions](usage.md#saved-cleaning-routines)

## Mission detail and dashboard validation

Version 0.12.1 passed 1,546 tests with 100% Python statement and branch
coverage. Ruff, hassfest, the SDD validator, the privacy scan, and JavaScript
syntax checks passed. Chrome rendered the actual card using synthetic map
data and exercised zoom, review, cancellation, and confirmed service dispatch.
[Screenshots](../README.md#floor-plan-dashboard)

The household installation verified the 0.12.1 archive, passed `ha core check`,
and restarted Core. The integration listed three robots, three docks, and 487
entities. The 0.12.0 component is available as the immediate rollback. The
dashboard displayed two saved floor plans and Roomba's live room updates.

A confirmed single-room selection from the dashboard ran on the intended
robot, returned to its dock, and published a completed vacuum mission with
one room result. Independent Roomba readings matched the mission start and
reported zero mission errors. No movement was requested on the third robot.

An active sequential mission provided a matched timeline reply containing room
area readings and pass counts in the active event list. The installed card
showed four room measurements from a fresh report. During a pause, the same
mission returned a `pause` event and five room readings. The robot resumed
that mission after the Home Assistant resume action. Both timeline replies
had empty future event lists. An earlier capture verified position batches
during targeted cleaning. A later trial matched the live countdown.
Coverage percentage and room area units still require provider evidence.
[Prior capture evidence](evidence/2026-11-24-live-progress.json)

The sequential mission changed its reported cleaning mode from vacuuming
to mopping under the same mission start, with a zero error code. The robot
returned, washed its mop, and reported charging with no active cleaning
cycle. Interim bin emptying also retained the mission start. The trial
ended with more than 40% battery and provided no low-battery recharge and
automatic resume sequence. Repeated history reads after docking still showed
the previous record. The latest mission's archive outcome remains unverified.

The saved-zone command passed fixture checks. The two authorized maps had
no saved cleaning zones at the start of the test. A v2 write returned HTTP 500.
The v1 map edit route added and renamed a temporary zone in the active map's
`cleanZones` geometry while the associated region inventory continued to
report zero saved zones. A targeted command briefly entered the running
phase and then stopped. Home Assistant confirmed cancellation. A full
saved-zone cleaning outcome remains unverified. A read-back after removing
the temporary zone confirmed that the original rooms, boundaries, and
restrictions were preserved.
[Map and zone editor SDD](../specs/009-map-zone-editor.md)

### Official app room division and merge

On 2026-11-25, a room division in the official Android app on a physical
device produced two room shapes and one listed room destination. A repeat
on the Android emulator started with one room in both sources. Proxyman
decoded the app's `split_room` write and its HTTP 200 archive. The two
resulting polygons shared edges, and each listed the other in
`adjacentRoomIDs`. The associated destination inventory remained at one
room after saving and again after confirming the exit from the editor.

In initial merge attempts, the app prompted for adjacent rooms and
sent no map-version write. After reopening the app, both selections
were visible and **Save** became enabled. The app sent `arrange_room`
with the two split room IDs. Its HTTP 200 archive contained one room
with the original ID and a `borders` layer identical to the baseline.
After confirming the exit from the editor, a metadata read returned the
merged revision as active with the original room inventory. The robot
stayed docked throughout the emulator test.

The MQTT observation captured a `service.mapedit` schematic-data read.
Both successful writes used the HTTPS map service.

A follow-up division again kept one room in both map metadata responses and
in the estimated-duration entries. Naming the new room sent a successful
`set_room_metadata` write, with one listed room still present afterward.
The official app offered the new room immediately. Its directed vacuum
mission reached the new room and showed active vacuuming there. Both map
metadata responses then contained two matching room IDs during the mission
under the same revision, before the robot returned to the dock. This was
the first observed publication of the second ID in the metadata.

The follow-up merge restored the original room ID, name, and outer boundary.
After another vacuum mission used the restored room and the robot docked,
the active archive and app showed one room. The last metadata reads still
listed the removed room. The integration uses visible rooms from the archive
associated with the requested map and active revision.
[Room edit requests and responses](api.md#room-division-and-merge)

### Official app cleaning-zone lifecycle

An Android emulator trial started with a single-room map and zero saved
cleaning zones. Four saves on the active map created a rectangle, moved it,
changed its name and size, and removed it. The three writes that kept the
zone used `set_permanent_area` and returned the same ID. The removal used
`del_permanent_area`. Every response was HTTP 200 with a new map archive.

The active archive reflected the expected changes after each save. The
associated inventory continued to advertise zero zone destinations. The
final read confirmed zero zones in both sources, the same outer border,
and one room. The robot remained in its dock throughout this trial.
[Cleaning-zone write contract](api.md#cleaning-zone-edits)

### Region inventory changes

A read-only follow-up of two household maps found one associated cleaning zone
without matching `cleanZones` geometry. The other map listed no cleaning
zones. The installed Home Assistant dashboard offered the saved zone in
the area list. Its confirmation showed the selected zone and was cancelled
before dispatch.

A synthetic Home Assistant regression starts with a zone present only in
the archive. The dashboard reports the unmatched zone and leaves it out of
the selection. A later inventory associates that zone and renames a room
under the same archive revision. The WebSocket returns refreshed geometry
and the cleaning action rejects the old inventory before publishing a
command. The fixture also verifies that a listed zone without matching geometry
keeps its entry in the area list. A Chrome check confirmed that the old review
dialog closes, the new region becomes selectable, and the cleaning action
carries the current inventory identifier.

## Local rendering checks for 0.11.1

Reproduced the replacement glyph in 0.11.0 using Pillow's default font.
The bundled font rendered distinct Spanish accents and canonically equivalent
spellings in synthetic maps. Label tests covered long names, narrow rooms,
holes, occupied label space, and clearance around the active robot marker.
A side-by-side render confirmed the changes at a reduced display size.

The full suite passed 1,536 tests with 100% statement and branch coverage.
Ruff, hassfest, the privacy scan, and the SDD validator passed. These checks
used synthetic maps. The home server test below used 0.11.0.


## Local checks for 0.11.0

Home Assistant Core 2026.11.2 and the synthetic provider harness verified
robot deselection and reselection, restoration of entity identity and
preferences, connectivity timestamps while disconnected, and deduplicated
mission result events across reloads. Map tests cover signed announcement
matching, unavailable map data, version changes, expired positions, and
trajectory gaps. The suite passed 1,532 tests with 100% statement and branch
coverage. Ruff, hassfest, the privacy scan, and the SDD validator passed.

The test suite used synthetic provider data in an isolated Home Assistant
instance. The home server test below separately verifies the installed package.

### Home installation and live map test of 0.11.0

On 2026-11-24, the home server verified the install package SHA-256 and passed
`ha core check`, then restarted Core. The integration reported version 0.11.0
and listed three X185240 robots and their three associated docks. The previous
0.10.0 component was retained as a rollback copy. The map option was enabled
with all three robots selected.

One robot ran a short vacuum mission from Home Assistant. Its saved floor
plan loaded. The position timestamp advanced, the current-room sensor
reported a room, and the image displayed a position marker, heading, and
received path segments. Some accented letters in image labels rendered as
replacement glyphs. The room sensor displayed the original label correctly.
The return command was confirmed with phase `charge` and mission error code
0. Live room and position sensors were unknown after the mission. No
movement commands were sent to the other robots.


The version 0.5.0 expands the weekly hours with creation and retirement. The suite passed 1.278 with 100 % cover of judgements and branches. [0.5.0](evidence/2026-11-23-schedule-crud.json) [0.4.1](evidence/2026-11-23-schedule-dispatch.json) · [0.4.0](evidence/2026-11-23-schedule-writes.json) · [0.3.1](evidence/2026-11-23-cleaning-quality.json)

The diagnosis catalogue crosses the Max series code 700 with DK phases and states. The Harness checks jammings, load errors and firmware. Retirees have been put into place with a start-up block even if the main code's at zero but they are damaged of the dock while an explicit warning resolution has to be found as well The [and effects on each order](telemetry.md#problems-and-events) indicates how they are shown in HA.

The preserved readings of the three robots were reproduced at an instance Home Assistant.
Three robots and their three daughter bases were registered with 29 entities at each base.
The recharge retained the 357 identities of that evidence register. Reproduced data cover
the shadows and consumables of capture with deactivated network applications. The Suite also
checks the reassociation of existing entities and their availability if a database or some
information remains missing.

The reproduction of 6 mission logs confirms new fields for duration, recharging and
emptying. Four records include vacuuming and two includes simultaneous mode. The state at
base during a mission has been tested in Harness. A real cycle of recharging and re-opening
remains to be observed.

At a mopping passed 150,9 seconds between `padWash` and `run` with the same number and start
of mission. The reproduction confirms that monitoring expects the cleanup phase. Tests with
simulated supplier also check cancellation, mission change and failure at the dock.

The schedule consultation of Roomba Home returned five programs and none activated for the
three compatible robots. The catches of the three adjustments have valid IANA zones. The
calculation left an empty date of next cleanup for all three. The tests simulate active
programs, passage to the following week and summer time transitions. The consultation was
made in reading mode and did not modify programs or activate the robot.

The concurrently tests check that a second robot can complete his order while the first one
expects confirmation. Two simultaneous checks re-use currently occurring reading. Retirement
tests count the requests and check that neither manual refresher nor an area demand advance
a limited source's reattempt.

The update was tested 0.1.0 → 0.3.0 with final file of installation and persistent storage
in an HA 2026.11.2 Isolated. The Core configuration validator accepted the installation. The
entrance and the original twelve entities have preserved their identifiers, including an
entity's custom name. Three robots, three bases and 369 entities with the data reproduced
were registered. The recharge preserved the 369 identities. The endpoint of brands returned
the requested four icons, including dark fallbacks and diagnoses covered all three robots
without account fields.

The folder was later restored 0.1.0. The original 12 entities have been put back into
activity. Home Assistant have been keeping additional records, preferences mopping and
association of an area. Once re-installed 0.3.0, the selector was reactivated with mode and
maintenance of moisture level as well to check rooms using their original identifiers. The
configuration was tested at both 0.3.0 installations. The test replicated data from robots
at an isolated level and blocked the network to its supplier.

The final installation file 0.3.0 was charged at an isolated instance of Home Assistant 2026.11.2 with an authorized account. The configuration assistant authenticated the account and integration registered three connected robots, its 3 bases 415 entities. The battery was obtained and details, consumables have been consulted with maps of all three. The six record and schedule indicators have been turned on. HA's action to list regions returned 1, 6 and 6 rooms. The duration action returned 36 combinations per room for all four modes with a robot consultation. The privacy of the diagnoses for all three robots was checked and their entry had been correctly downloaded. The test blocked the vendor's writings and physical orders. [Evidence of the package](evidence/2026-11-23-cleaning-quality.json)

Two absent responses from a robot were simulated locally at the same connection MQTT as
another Robot. The consultation ended at 17,07 seconds. The second robot remained available.
The robot concerned preserved its last reading mark, shown the vacuum cleaner as unavailable
and regained by restoring his read at next cycle.

The back suite verifies the recovery of maps. A failed response preserves the configured
areas, deactivates an indicator of available data and doesn't publish a command. Recovery
uses the newly read version. A valid response without maps removes the entity's regions.

have been observed vacuuming, mopping and simultaneous with pause, cancellation or base. It was also found targeted vacuuming with a resumption. The map consulted contains six rooms and a temporary region, with no one saved zone at that reading. The first stage of the complete housing sequential mode began to awaken and his test stopped before monitoring mopping. Regional parameters and manual basic commands are also tested with fixtures. The [Physical evidence](evidence/2026-11-23-cleaning-modes.json) indicates the steps and their boundaries.

The base reported a alert 517 during an earlier wet test. Following maintenance, Home
Assistant reported basic code 0. The domestic update and time cycle of vacuuming have been
checked with 0.3.0.

# Validation and limits

Campaign initiated by 2026-11-23 with authorisation from the holder, a actual test account
and an app Roomba Home 3.4.1 on Android. Temporary credentials and complete evidence remains
outside the repository.

## Completed checks

| Area | Observed result | Scope |
| --- | --- | --- |
| Capture Proxyman | 199 Exported inputs from four hosts iRobot | Named legible HTTPS |
| Independent access | `/v2/login` | Reactual temporary credentials |
| Catalogue signed | 4 Partnerships | 3 `X185240` and 1 `R981040` |
| HTTP Validation | 26 checks, 0 Failed | Access 24 and forced renewal |
| Forced renewal | Rotated credentials and stable inventory | New complete access and does not wait for natural expiry |
| MQTT independent | 2 accepted connections and subscriptions | Torens separated from the app |
| Classic Shadow | 4 responses accepted | That's bad for a modern state. |
| Modern Shadows | 24 accepted and 3 Rejected 404 | 9 for 3 robots |
| Contrast with app | Accessible robot Connectivity and Display | The app also shows map and consumables |
| Reusable tool MQTT | 36 responses, 2 connections | 9 for 4 and associations; classified absences |
| Independent physical monitoring | Vacuuming, pause and cancellation with confirmed return | A modern robot, 210 second test vacuuming |
| HA with simulated supplier | Loading, 12 entities and recharging with Reauth | Official Harness HA 2026.11.2 |
| Reactual HA reading | 3 robots with known and base batteries | Config validation and co-ordinator with no orders at that check |
| Home installation | Config check, reset and high 3 and 12 That's right. | HA Green, aarch64 and Core 2026.11.2 |
| Control from HA | Reconfirmed start, pause and cancellation | Standard vacuum controls and a robot |
| Domestic Rearms | Conserva 3 and 12 all connected, with and without error | after-cycle check |

`ro-sensor` He's back 404 The three modern robots. It's an observed capacity limitation, not
a authentication error. Batteries and mission are found at `ro-currentstate` and
connectivity with `rw-constatus`.

The HTTP results were achieved by applying `tools/validate_api.py` against the services. The
initial MQTT were obtained with a private Peaho-based probe, contrasted to the SDK
configuration of an app. The reusable tool `tools/validate_mqtt.py` also passed with its own
client's identity. It was detected and corrected to change only device_id does not separate
customers: app_id That's the determining field. Subscriptions were also attached to the
limit of eight filters per AWS IoT package. The ABS and code extracted are not part of the
project.

Extended HTTP capture contains 1829 tickets of the four hosts iRobot. That contract was
obtained from the SDK and verified by sending it to an independent client as a capture of
orders MQTT.

## Physical control sequence

The incumbent authorized a specific robot and 3 to 4 minutes ride. Public data only uses
order, relative time or phase:

| Approximate time | Evidence |
| --- | --- |
| 0 s | start accepted by broker |
| 5,5 s | run / clear, mode 2 confirmed |
| 210 s | pause sent after requested duration |
| 214,8 s | stop / clear: pause confirmed |
| 219,9 s | stop sent to cancel |
| 225 s | stop / none: confirmed cancellation |
| 225,1 s | dock sent as a separate return |
| 230,4 s | hmUsrDock / dock: confirmed return |
| 292 s | charge / none: again at the dock, without error |

The emulator's app showed the task currently under way and then his robot was ready at the dock. The [Normalized evidence](evidence/2026-11-23-control.json) contains no names, identifiers or credentials. Following the checks, a temporary TCP deviation from an emulator was withdrawn and SSL iRobot / Gigya rules were restored.

## Installation and control on the home server

It's been copied only `custom_components/roomba_home` to server, checked package integrity
and passed `ha core check`. Following re-start HA, config flow authenticated the account and
select all three robots X185240. Three devices and twelve entities with valid reading have
been established.

The standard controls of the vacuum entity performed another physical sequence. Activities,
phase and cycle `last_command_result` were inspected at an interface:

| Time from state Cleanup | Status confirmed at HA |
| --- | --- |
| 0 s | `run / clean`, `confirmed` |
| 544 s | At pause: `stop / clean`, `confirmed` |
| 568 s | Inactivated: `stop / none`, `confirmed` |
| 607 s | Coming back: `hmUsrDock / dock` Still. `pending` |
| 706 s | Based on: `charge / none`, `confirmed` and batteries 99%, error 0 |

That additional HA test exceeded 3 to 4 minutes: there were 544 seconds between cleaning and
pause states. The deviation is recorded and does not show a temporary stop automation. The
first independent client campaign did send pause to 210 seconds.

A temporized sequence with the HA Script Engine and simulated services was then tested. The
pause was requested 210 seconds after first status `run`. If that state did not come, the
pause attempt was requested to 45 seconds and moved to cancel back to the dock. The same
order was found with start and pause malfunctions. The initial checks restrict test to the
robot indicated, at its disposal and with vacuuming. The time of test corresponds to
applications. The times observed at the physical test 0.3.0 are shown in Section 3.

The integration was later recharged from his menu. Three devices and twelve entities remained, all connected with an error of mission 0. The [normalised domestic evidence](evidence/2026-11-23-home-assistant.json) omits counts, names and identifiers. The visual catches are preserved outside the repository. Reauth and the stability of identifiers are checked at his Harness. The actual password was not changed during this test

### Upgrade and timed cleaning with 0.3.0

The final package was verified by SHA-256 It happened. `ha core check` and activated after
re-start Core while maintaining a backup of 0.1.0. The existing entry registered three
robots, 3 bases and 415 entities. The icon was seen on the test robot's page. The actions of
regions returned 6 rooms and the ones with durations back 36 combinations in four ways for a
room.

| Time from confirmation of vacuuming | Status confirmed at HA |
| --- | --- |
| 0 s | Cleanup phase `run`, cycle `clean` Mode Vacuum |
| 221 s | At pause |
| 236 s | Inactivated after cancellation |
| 306 s | Docked |

The script called for a pause 210 second of first reading `run`. The track confirmed the
implementation of all four standard actions. During vacuuming The robot reported misconduct
0.

The second cycle select **Mop** and used the same entity `vacuum`. The base reported code 0
prior to initiation. The production sensor was activated while washing and turned off at the
start of mopping ground.

| Time from first production confirmation | Status confirmed at HA |
| --- | --- |
| 0 s | `padWash` Mode Mop Retirement and production |
| 153 s | `run` Mode Mop, ready to go. |
| 199 s | At pause |
| 209 s | `run` after resuming with `vacuum.start` |
| 240 s | Inactivated after cancellation |
| 250 s | Falling back to the dock |
| 293 s | Docked |

The robot reported mission error 0 during mopping and the base held code 0 while matching. It was restored **Vacuum** as a way of next cleanup. The emptying button of the dock was tested with the coupled robot. It's been 301 a 302 in 20 seconds and back to 301 No. 36 pulse seconds. The warrant was confirmed and the clearance or base error code reported 0. The time script was disabled after the test. [0.3.0](evidence/2026-11-23-cleaning-quality.json)

### Reload and manual dock maintenance

Recharged entrance 0.3.0 from the integration menu. Home Assistant have preserved all 6
devices, 415 and robot links of the dock tested. The robot re-reported the connection and
its coupled status.

| Button of the dock | Observed status | Outcome |
| --- | --- | --- |
| Dry up mop | `701 → 702` | Active dry 10 after pulse |
| To stop drying of mop | `702 → 701` | Retirement to rest 10 after pulse |
| Wash the mop | `601 → 602 → 601` | First active status after 10 and back to rest 241 after |

The washing, drying and base error codes were maintained at 0. During manual washing, the
robot reported `padWash` with ground cycle `none`. The version 0.3.0 left the main state
unknown in that combination. The correction 0.3.1 shows them as coupled when the base
confirms washing and preserves a mission start-up block.

### Vacuuming two rooms on a second robot

Home Assistant He returned six rooms and 216 estimated duration for a second robot. Two
rooms were sent from the same map with action `roomba_home.clean_regions`, in mode Vacuum
and with the powers 1 and 2. The robot's started. 13 seconds after the warrant and reported
2,04 m² during the mission with misassignment 0. The first robot remained attached to the
check while his second was moved.

| Time from confirmation of vacuuming | Status confirmed at HA |
| --- | --- |
| 0 s | Cleaning, mode Vacuum |
| 205 s | At pause |
| 220 s | Inactivated after cancellation |
| 230 s | Falling back to the dock |
| 270 s | Docked |

The track Home Assistant records the directed order, pause and cancellation. The temporary script was disabled. The global telemetry continued to show power 3 and had no current room. The course of both rooms and the power applied to each room remains outstanding. The map also did not contain a persistent area. [Evidence of the directed evidence](evidence/2026-11-23-cleaning-quality.json)

### Upgrade to 0.3.1 after testing

Home Assistant checked the package's hash and Core configuration before re-starting. A copy of the folder 0.3.0 was retained. The interface shown the version 0.3.1 Three robots, three bases. 425 entities and local icon. The two test robots preserved their pages, re-connected and once again reported a coupled status with an error of mission 0. The link to the dock of the first robot was checked. At that time the base dried up mop and his washing button was disabled. The conduct corrected during a washing was checked at the Harness with code as set out in 0.3.0. [Evidence of an update](evidence/2026-11-23-cleaning-quality.json)

### Weekly schedule writes in 0.4.0

Four responses were tested for the app and his write requests. A survey and after that the
client of integration have changed his start to two time schedules. Both were created
disabled, copying a routine from the same robot. The later reading confirmed the changes and
retained his activation or command. Following the withdrawal of every hour, it was found
that all five existing hours remained intact. No motion warrant was sent to the robot.

The Harness of Home Assistant checked the registration and their responses. It also checked
the selection of others, limited consultations and recovery where an uncertain response to a
change.

Home Assistant Green checked the package and retained a copy of 0.3.1 Before we re-start. The version 0.4.0 have shown all 6 devices and 425 Institutions. The server interface listed the schedules of a robot and changed his or her time for an activated third timeframe. The action itself confirmed its values and a second session verified that the command as well an earlier five hours were preserved. Following his retirement from the time schedule, a list was repeated since Home Assistant. No motion orders. [Evidence of schedules](evidence/2026-11-23-schedule-writes.json)

### Enabled schedule run in 0.4.1

A time schedule was established for vacuum a room with an active map and its activation
checked. The robot entered `run` Mode 2, 40 seconds after intended start. Reported origin
`cloud` and error code 0. The survey observed the status without publishing a start command.

The schedule was deactivated after confirmation of initiation. The robot paused, cancelled and returned to the dock without error. The record confirmed an requested room and two minutes of vacuuming. The final consultation confirmed his retirement and retained the previous five with their same days, hours as routines or activation. The metadata field `created_time` He differed with respect to the archived readings of his app. [Evidence of shooting](evidence/2026-11-23-schedule-dispatch.json)

Home Assistant Green checked. 0.4.1, held a copy of 0.4.0 and reset with 6 devices 431
Institutions. The interface activated and deactivated a time schedule from another robot
with an hour that remained several days later. A separate session confirmed both changes and
checked the time with command. The robot remained at the dock and the time was withdrawn.

### Targeted vacuum then mop and the recorded navigation error

The command form of an actual schedule with mode 512 was tested by region, in a room on his active map. The robot reported vacuuming 27,7 seconds after scheduled time. After 69 seconds observed vacuuming happened to `hmPostMsn` with code 48. iRobot identifies that code as a path block. The second phase remains pending. [Error 48 in the Max series 700](https://homesupport.irobot.com/articles/en_US/Knowledge/10548)

The final reading confirmed that the robot was at the dock with current error 0. The record's back. `stuck` a matching room and final event `error.value=48`. The integration keeps that code to its historic sensor. The time schedule was withdrawn and the previous five were disabled. The interface of Home Assistant shown **Attack**, historic error 48 with origin `cloud` and current mission error 0. [Evidence of sequential](evidence/2026-11-23-schedule-dispatch.json)

A separate consultation at the robot of his test plant confirmed that he was connected, at the dock with mop and deposited with an error 0 both at the robot and at the dock. The active map returned a room and zero maintenance zones. The intended duration of vacuum and mop That room in sequence was from 6.898 seconds. The check was read only. To measure both phases in a short mission, we require an accessible and small area that's been saved on this map. [Cleaning zones at Roomba Home](https://homesupport.irobot.com/s/article/20500)

### Schedule creation and deletion in 0.5.0

The integration client created and retreated two deactivated schedules for a room with an active map. The later reading confirmed how 4 and 32 and the select map version. A separate test verified the withdrawal of an activated time schedule and its start remained several days later. The five existing schedules have been retained. The shooting of an hour vacuuming was validated at 0.4.1. [Evidence of creation and withdrawal](evidence/2026-11-23-schedule-crud.json)

In Home Assistant Green was set up a mopping disabled for a room. Two identical executions
returned the same identifier. A separate session found that only a few hours of proof
existed with an 4 and the requested adjustments, with his retirement from 0.5.0. The
retirement action of Home Assistant rejected the missing identifier. The list retrieved its
two editable schedules, the account remained at five and his robot stayed at the dock. The
installation preserved 431 entities.

### SmartScrub and wetness during mopping

A solo mission mopping requested moisture 1, SmartScrub activated and a passing. Preparation
of the mop was observed. The mopping from the ground began 154,5 and was observed for 25,9
seconds. The pause was confirmed and the robot came back to the dock with error 0 both
devices.

The shadow of adjustments changed moisture 3 a 2 and SmartScrub Fitted to activated. The values persisted at the end of his mission. The moisture was restored 3 and SmartScrub Fitted with SDK's tuning textures. A later reading confirmed both values with the robot at the dock. It remains to be checked if the mission used moisture 1 requested. [Evidence of mopping and adjustments](evidence/2026-11-23-mop-preferences.json)

### Default preferences in 0.6.0

The integration client requested moisture 1 from the base. A separate consultation confirmed
the level 1 in 1,2 seconds and then confirmed the restoration at level 3. The tour was
repeated with SmartScrub. The activation was confirmed at 1,18 and turn them off at 1,27
seconds. The robot remained coupled during both tests and final reading confirmed the
starting values. That operation writes the robot's configuration independently of a mission
start.

The installation file was loaded at an isolated instance of Home Assistant Core 2026.11.2. The configuration check passed and the instance registered 149 entities for the selected robot. Services `number.set_value`, `switch.turn_on` and `switch.turn_off` The values shown in HA have been changed. A separate reading confirmed the changes and restoration. The robot remained at the dock throughout the test. [Evidence of preset adjustments](evidence/2026-11-23-mop-preferences.json)

### Diagnostics of the dock in 0.6.1

The independent update of 0.6.0 a 0.6.1 He re-used catches of all three robots and their
bases. He preserved the 378 and test including custom name of a sensor and next cleaning
preferences. He added an event to each base device.

The direct update was also tested from 0.5.0, a proven version of the domestic server. The
earlier 372 entities remained their identities in the secluded environment. 6 default
adjustment controls and 3 basic events were added.

The simulations co-existed with the mission code 1026 and washing system.
654. The event of the dock included the washing malfunction and robot events
It reflected both origins. A filled state received at the washing field preserved alert. The resolution event came as a valid washing status was reported. The test He did not send orders or have caused physical damage. [Evidence of diagnoses](evidence/2026-11-23-dock-diagnostics.json)

### Cleaning a map point

The API returned the geometry of an active test robot map. A clear point was chosen and sent
`point_clean` with mode vacuuming. The robot published `run/clean` Mode 2 without an
immediate echo of the order. The cycle was identified by its start during the test,
cancelled and confirmed return to the dock with error 0.

The report of that mission retained the requested point and version. He's been searching for two minutes and 1,95 m². They remained to observe the exact path and natural completion. The activity history of Home Assistant have recorded the change of power from 3 a 1. The level was restored 3 and robot confirmed reading at the dock. [Evidence of clearance by point](evidence/2026-11-23-point-clean.json)

### Home Assistant action in 0.7.0

The signed reading of the active version returned his compressed file. The action turned the
fractions of his room to an exact same point as earlier. The service's tests rejected other
rooms, areas and points outside the perimeter.

A Home Assistant Isolated uploaded the exact file from 0.7.0 and executed
`roomba_home.clean_point` about a real robot. The action returned **Envoy** and the track
record confirmed its point or version. The last-order sensor was updated to `point_clean`.
The test concluded with cancellation and misverified return 0 and 1,95 m² reported in two
minutes. The preset power and next cleanup preferences remained valid. The natural
completion and exact path remains to be verified.

Isolated update from 0.5.0 preserved his 372 identities and 0.6.1 preserved his 381 identities. Both remained a custom name and moist preference. In both tests the resultant registration had 384 entities, including a new mission order sensor per robot. The Suite of 0.7.0 happened. 1.417 with 100 % cover of judgements and branches. Hassfest He validated the integration and passed Ruff, privacy with all seven SDDs. [Retirement records](evidence/2026-11-23-point-clean.json)

The home server was updated from 0.5.0 a 0.7.0. The file's fingerprint coincided, copies of
0.5.0 were preserved and the Core check was completed correctly. After re-initiation, Home
Assistant shown the version 0.7.0 6 devices, 453 and the three order sensors of last
cleanup. The share `roomba_home.clean_point` was shown in the stock catalogue. The domestic
check was made from the registration and catalogue without starting missions.

### Default suction in 0.8.0

A Home Assistant Isolated uploaded the installation file and run `number.set_value` in
**Suction power**. A separate reading verified the change of 3 a 2 and turn to 3. The robot
remained at the dock and retained his last mission's identifier. The choice of next cleanup
remained separate.

The first test failed with the restoration action. The direct write confirmed recovery at level 3. Rerepeating test with an independent client's identity, the two standard HA actions confirmed their values. The test have preserved the 384 and 0.7.0 and added three preset power numbers. They passed 1.428 with 100 % cover of judgments and branches, Hassfest and the seven SDDs. [Undetermined power evidence](evidence/2026-11-23-default-suction.json)

### Two passes, carpet boost, and automatic emptying in 0.9.0

A separate reading confirmed the changes and restoration of `twoPass`, `carpetBoost` and
`autoevacFreq`. The exact package of 0.9.0 run the same tours from a Home Assistant
insulated with `switch.turn_on`, `switch.turn_off` and `number.set_value`. The monitoring of
automatic emptying was set up at square feet and robot readings confirmed the change in m²
of 25 a 50 and turn to 25. The robot remained at its base and retained the same earlier
mission as his original adjustments.

The test and maintenance of the 384 and 0.7.0 and 387 of 0.8.0. The result in both cases was 396 entities. They passed 1.457 with 100 % cover of judgements and branches, more Hassfest, Ruff and the seven SDDs. The path to two passes, effective strengthening of carpet and shooting from the automatic emptying at the threshold. [Evidence of persistent adjustments](evidence/2026-11-23-persistent-cleaning-options.json)

### Temporary zone and mission history at 0.10.0

The experimental order of vacuuming with a region `tid` He initiated a mission. The track record confirmed the region, polygon and map version requested with a result `stuck` That's bad. 48 and surface zero. A separate reading confirmed his return to the dock, the current error 0 and the map inventory preserved. The two readings of the live map returned his intended channel. Subscription was activated 56 seconds with no place or map. [Evidence of test](evidence/2026-11-23-temporary-zone-history.json) · [Error 48 of iRobot](https://homesupport.irobot.com/articles/en_US/Knowledge/10548)

The moisture read after the tour was 1. The last level verified was re-established within
the permitted range 3. The earlier reading of HA was shown 4 and above the stated maximum of
3. A new reading confirmed the restored setting, other tested settings and robot at its
base.

The HA Suite will conduct a consultation at the end of an assignment, reattempt if
registration is delayed and demand limits or target sensor. The exact package of 0.10.0
Reproduced that record at a Home Assistant Isolated. He's shown **Temporary zones** a
region, an outcome `stuck` and error 48 with meaning `path_blocked`. At that instance, the
discovery and access to Gigya worked but `POST /v2/login` returned HTTP 403. The previously
obtained registration was used. A later check at the domestic instance shown his robot at
the dock, connected with current error 0 and moisture restored to 3.

A renewal with the same 403 at the Harness of Home Assistant. The controls and sensors
concerned have been unavailable. The orders while waiting did not issue messages MQTT. Upon
receiving a new session, the vacuum and historic target or error sensors regained their
reading with same identities. A re-authentication flow was not opened.

Isolated update preserved 397 and test of 0.7.0 and 409 of 0.9.0. Both routes reached 412
entities and included three new target sensors. The custom name and local moisture
preference have been preserved. They passed 1.489 with 100 % cover of judgments and
branches, Hassfest, ruff and privacy with the seven SDDs. The installation and restoration
were tested with a configuration check local copy.

### Home installation of 0.10.0

The 24 The prints were checked from November SHA-256 from the installation file and script.
`ha core check` passed and Core re-started with the new version. The record shown three
robots X185240 its 3 associated bases and 470 entities after uploading the readings. A copy
of the version 0.7.0 was saved.

At the robot of test earlier, live reading shown connection and status at the dock, moisture 3 and an active error 0. The record was shown **Temporary zones** and error 48. The preset power controls have also been found, two passes and carpet boost. The check at Home Assistant was made without sending orders to the robots. [Test of installation](evidence/2026-11-23-temporary-zone-history.json)

### Live map and progress

Two X185240 have been drawn into one room each. The responses from `/v1/p2maps/livemap` and
have been received 32 Map and 154 Position messages between the two tests. The geometry of
the active map allowed to associate with a single room each 222 coordinates. Some of the
path passed through rooms other than that selected.

The Android app shown the room up and about seven minutes, with a living plane still
uploading onto his sample. The API returned 397 seconds for the same destination and profile
of vacuuming. The hidden plane had been loaded onto the app before his mission. The live
cartography was received as a compressed file, to be interpreted.

A short additional test verified a response from the timeline associated with that same mission to start and relocate events. The second reader stopped after receiving a list of events and the messages that came up to date are preserved. A remaining time counter and an overall percentage while cleaning remains to be verified. The return to the dock of the two initial tests and maintenance have been established. After an additional test, the robot continued to report back after five minutes. That return had been stopped and the state held outside confirmed of the dock with an active error 0. [Position and map evidence](evidence/2026-11-24-live-progress.json)

## Live mission destinations

On a Max 700 Combo, a three-minute vacuum-only run selected one room.
The current-state shadow reported 0 and then 21 square feet cleaned
(about 1.95 m²). The archived command matched the selected room, map
revision, and cleaning settings. After cancellation the robot docked
with error code 0. The floor archive, six favorites, and schedules were
unchanged.

The production parser replayed eight previously captured ordered
two-furniture timeline reports. Five showed the first destination
finished while the second remained active. Three showed both finished.
Another 112 reports from three single-destination runs covered pending,
travel, cleaning, and completion for furniture and saved zones. Home
Assistant tests covered the floor snapshot, sensor projection, map
revision mismatch, and timeline expiry. Chrome rendered the card with
synthetic data at 358 and 900 pixels, including accented names, long
labels, and disappearance on expiry. The 0.49.0 card requires
verification on the physical Home Assistant installation.
[Sanitized evidence](evidence/2026-11-25-live-itinerary.json)

## Android device settings comparison

The signed Max 700 Combo parts read agreed with the Android **Robot
health** screen for remaining life on the edge brush, main brushes, and
filter. The app displayed whole hours. Dividing the API's remaining
minutes by 60 and taking the integer part yielded the same three
readings. The dust bag displayed a status bar in the app. Its signed
parts projection supplied no consumable life count.

The **Robot settings** screen included an **About** view with name, model,
serial, software version, and update date. It also listed automatic pad
washing, emptying frequency, voice, volume, child and pet lock, locate,
reboot, and Wi-Fi change. The robot page exposed a factory reset
and removal entry. The review opened the settings and maintenance
screens and performed a read-only parts check. The two device lifecycle
flows remain open in the device specification.

On the connected Max 700 Combo, opening **Reconnect or change Wi-Fi**
showed a confirmation that continuing would clear its current Wi-Fi
configuration. The trial canceled there without supplying credentials
or clearing the connection.
[Device capability specification](../specs/007-device-capabilities.md)

### Dock controls on the floor plan

Roomba Home 3.4.1 exposed **Dock controls** from both the floor plan and
the device page on the Max 700 Combo. The panel offered mop-and-tray
washing and bin emptying and showed drying in progress. This inspection
opened the panel while the robot was docked and left the existing drying
cycle running. The map legend and editor menus were also inspected.

The Home Assistant panel uses the same registered buttons as the linked
dock device page. Its test opens the panel data on a saved floor and
before the first floor is saved, projects active drying from Roomba,
rejects a button without control permission, follows an entity rename,
and presses the linked wash button against a simulated robot. The card
tests exercise a stale review, duplicate prevention, and a rejected
command.

Home Assistant passed its configuration check and restarted Core with
0.88.0. The dashboard loaded all three maps, and the integration registry
listed three robots with their three linked docks. The installed card
reported an active drying cycle. It offered mop-and-tray washing and
stopping the dryer, and disabled bin emptying while the dryer was in use.
The review displayed the wash confirmation and returned to the dock panel
through **Back**. The observed Home Assistant session sent no service call
during the review and continued to report drying. A confirmed physical
dock command from this panel remains unverified.
[Dock usage](usage.md#dock-settings) ·
[Dock controls SDD](../specs/008-mission-detail-and-map-card.md) ·
[Installed dock panel](screenshots/roomba-dock-controls.jpg)

### Robot status without a floor plan

The native Max 700 Combo device screen displayed the robot's battery and
its active drying operation when opened from the map. The Home Assistant
card now shows these readings in its header and can retain the device
controls when a floor plan is unavailable.

Home Assistant service tests verify the same reported battery with maps
enabled or disabled, including zero percent, explicit disconnection, an
unknown connection, a mapping mission, and error 48. The tests verify
permissions and confirm that the overview requests no geometry. The card
tests check that a review remains usable through repeated map failures,
and that a late reply for a different robot cannot update the card.

The household installation passed the configuration check, restarted Core,
and loaded all three cards on 0.89.0. For one Chrome refresh, the selected
Max 700 Combo card received a simulated `map_unavailable` error. The card
hid the floor and loaded the real `roomba_home/robot_overview` response
from Home Assistant. It displayed the reported docked activity, active
mop drying, and battery. **Dock controls** and **Clean everywhere** stayed
available. The next normal refresh restored the floor on the same card.
[Overview contract](api.md#robot-overview-without-a-floor-plan) ·
[Installed card status](screenshots/roomba-robot-status.jpg)

## Robot serial number

The authenticated asset lookup returned a 21-character serial and the
exact requested robot identifier for two associated Max 700 Combo units.
Both serials matched the values in the respective Android **About**
screens.
The Home Assistant registry tests cover setup, later discovery, identity
preservation across refresh, and handling of unavailable and rate-limited
responses. The public evidence records the match and format.
[Signed lookup tests](../tests/test_api_client.py) ·
[Registry tests](../tests/ha/test_telemetry_entities.py) ·
[iRobot serial-number guide](https://homesupport.irobot.com/s/article/274)

## Robot activation date

Opening **Settings → About** on the docked Max 700 Combo displayed a
registration day. Proxyman recorded successful connection and signed
inventory reads while the app loaded. An independent signed asset lookup
for the same robot returned `min_utc_reg_date` as an integer at midnight
UTC. Its calendar day matched the native display. No robot commands were
sent during the comparison.

The client tests check UTC boundaries, missing and malformed dates,
association validation, and preservation of the serial lookup. Home
Assistant tests check late discovery, per-robot dates, a disconnected
robot, provider rate limits, and omitted dates after a verified value.

In the household Home Assistant, the 0.90.0 package passed the
configuration check and Core restarted. Roomba Home reported version
0.90.0 with six associated devices. The test robot's **Diagnostics**
listed **Robot activation date**. The date matched the native display
and signed asset read for that same robot. No robot commands were sent.

[Asset contract](api.md#robot-activation-date) ·
[Entity tests](../tests/ha/test_telemetry_entities.py)

## Estimated time during a directed mission

During a physical single-room vacuum mission, Android showed approximately
9, 9, 8, and 7 minutes at 46, 70, 109, and 148 seconds after mission start.
The signed estimate matrix returned 502 seconds for the room and reported
profile. The correlated timeline recorded the start of the room stage at
47 seconds. Replaying the reports projected 502, 479, 440, and 401 seconds.
Both displays rounded to the same minute in three of the four samples.
The robot reported a different internal revision for the same declared
room identity. The command used the verified user revision throughout.
After cancellation the robot returned to the dock with error code 0.
[Sanitized timing evidence](evidence/2026-11-25-live-timing-and-position.json)

A second trial used the published 0.65.0 integration in isolated Home
Assistant. It started a Max 700 Combo vacuum mission for a reviewed room,
with suction 1 and two passes requested. Android showed about 115 minutes
at 63 and 81 seconds after start and 114 minutes at 98 seconds.
Home Assistant held the signed 6,899-second estimate during relocation,
then reported 6,824 seconds at 99 seconds, which rounds up to 114 minutes.
It also received position and reconstructed coverage during the run.
The signed history confirmed the requested room and settings after
the robot returned to the dock with error code 0. The map, routines,
and schedules matched the preflight values.

The captured Android live-map response contained the topic announcement.
The observed mission shadow reported area in square feet and supplied
no explicit remaining-time or completion-percentage field. The dashboard
now recalculates the countdown on each authenticated floor-plan read,
using the cached signed estimate and the latest verified stage. The
WebSocket test verifies that the estimate advances between polls, becomes
unknown when the robot pauses, and expires with the timeline. A separate
read with the updated integration verified the current map and cleared
countdown after docking.
[Sanitized live countdown trial](evidence/2026-11-26-live-countdown.json)

## Continuous position and cleaning coverage

A read-only subscription during a separate user-started vacuum-and-mop
mission collected 254 position messages over 416 seconds. The median
interval was one second and the longest observed interval was six seconds.
The stream also announced 48 raw map snapshots. Four shadow reads from
a separate authenticated client completed while the subscription remained
open. Roomba stamped 226 reports one second ahead of reception. The
previous coordinator's clock check accepted 27 of the recorded positions.
After aligning the clock checks, replay accepted 253 valid positions and
still dismissed one malformed report. The continuous coordinator then
delivered 11 positions and resolved the current room in a separate
read-only check of that same mission. The median interval was one second.
The snapshots exposed grid labels and mode-tagged motion. The
provider returned the raw snapshot even when asked for the GeoJSON bundle.
The captured interval mainly contained simultaneous vacuuming and mopping.
[Sanitized position evidence](evidence/2026-11-25-live-timing-and-position.json)

A follow-up read found the same mission completed and the robot on its dock.
The accompanying archive contained combined vacuum-and-mop and travel
coverage. A card replay of the 253 valid position batches animated 251 of
252 transitions. The previous card animated 224. All 27 transitions newly
animated had consecutive indexes and intervals of four to six seconds.
The remaining transition had a missing index. The replay interrupted 83
active animations with new samples and measured zero position jumps at
retargeting. The follow-up sent zero movement commands. The household
dashboard still needs verification with this animation.
[Sanitized replay evidence](evidence/2026-11-25-live-motion-continuity.json)

## Live coverage reconstruction

Three physical Max 700 Combo mission archives contained mode-tagged
trajectories and independent coverage polygons. An exploratory radius fit
compared footprints against those polygons. The production grid then
replayed the same reports. It reached 95.0% intersection over union for
vacuuming, 96.6% and 97.6% for mopping, and 95.3% for simultaneous
cleaning. These measurements quantify fit on the calibration archives.
Two separate vacuum-only archives from the second floor reached 89.2%
and 89.3% without changing the fitted radius.

The final archive from the user-started combined mission supplied
travel and combined vacuum-and-mop polygons. Replaying its last
captured live snapshot with 3,878 positions reached 96.3% intersection
over union against the native combined coverage polygon. The offline
comparison derived its translation from the extents of the two routes.
Their extents agreed within 1 cm. Neither the footprint radius nor the
grid size changed for this comparison.

Replaying two raw map snapshots from a separate physical combined run
increased estimated covered grid rows from 135 to 166. A physical
vacuum-only snapshot produced only the vacuum layer. The live stream
announcements examined here supplied mode-tagged routes. A published
native live coverage polygon layer remains unverified. The raw floor
raster preserved the same room and boundary labels during the run.
Its changes tracked a few cells, while the reported route grew by
thousands of samples. In the active combined mission, the integration
coordinator delivered 14 positions
and painted 66 grid rows in a separate 25-second, read-only verification.
Replaying a late join with 30 positions from that combined mission
aligned 446 earlier snapshot points and expanded the covered grid from
689 cells to 6,241.
Android showed the cleaning route with shaded bands and offered separate
controls for cleaning and travel paths. A household trial displayed live
travel and estimated vacuum coverage before a path error. A completed run
with both cleaning modes is still needed to verify their separate
coverage layers on the household dashboard.
[Household trial](#household-live-coverage-and-active-errors) ·
[Coverage evidence](evidence/2026-11-25-live-coverage.json) ·
[iRobot live and archived map guide](https://homesupport.irobot.com/s/article/20500)

## Live temporary obstacles

During a user-started Max 700 Combo mission, the Android map displayed
orange cones with its temporary-obstacles layer enabled. The initial
snapshot had no detections. Later snapshots provided 2, 11, and 13
records in field 15. Three visible or partially visible markers matched
the projected record coordinates within six pixels on an approximately
360-pixel-wide map. Only the verified coordinates are projected.

Two later snapshots each had two extra route samples beyond their
declared count. Replaying the declared prefix against 315 direct
positions placed all 11 obstacles and recovered 161 missing earlier
positions. In two separate late-join replays, a consistent group of
recent positions placed all 13 obstacles while leaving the original
route samples intact. In a third replay, the positions did not sufficiently
overlap the snapshot and the layer stayed hidden.

An isolated Home Assistant coordinator also projected 13 obstacles
from the active physical mission and received 39 distinct live position
updates with a one-second median interval. Replaying those updates in
the card animated 12 adjacent transitions and 22 more by following
their intermediate positions. Four transitions did not meet the
animation criteria. The household card still
needs verification. [Decoder tests](../tests/test_live_route.py) ·
[Authenticated map tests](../tests/ha/test_roomba_map_api.py) ·
[Card tests](../tests/frontend/map-card.test.cjs)

## Multiple saved floors

A Max 700 Combo point-cleaning report declared its saved floor and user
revision. An untargeted Max 700 Combo cleaning report omitted the pair.
Its completed relocalization event confirmed the saved floor identifier
with an internal revision. The confirmed floor IDs matched the signed
mission archives in both cases.

The production resolver replayed the point-cleaning report alongside an
archived second floor from the same robot's mapping trial. The untargeted
report also resolved correctly with an added synthetic floor. Each robot
had one visible floor at the time of verification. Home Assistant tests
exercised publishing on the confirmed floor, active-floor selection,
visibility after timeline expiry, and route clearing when the bound
revision changed. Card tests checked automatic following, manual
selection, and protection of an open draft. An isolated Chrome profile
also verified the selector and automatic switches at 358 and 900
pixels wide.
[Home Assistant WebSocket tests](../tests/ha/test_roomba_map_api.py) ·
[Card tests](../tests/frontend/map-card.test.cjs)

## Unverified scenarios

- Natural quateness of session and recovery after many hours.
- Renewal with only one Gigya, MFAA or CAPTCHA token for other accounts.
- Continuous reception, reconnection and management of all events MQTT.
- Resumption after recharging the battery and other recovery contexts.
- Cleansing of guarded areas, full range with several rooms and applying adjustments per
  room.
- Compatibility with other families, countries or apps.
- Prolonged production and recovery use after natural expiry on the domestic server.

A reading cloud response doesn't prove a physical action. The monitoring range will be
increased only if the message sent, an application response and a robot's final status can
been related.

## Local code quality

### Telemetry expansion in 0.2.0

- 351 tests pass, 148 Additional 0.1.0 and cover with branches 98,37%.
- The Uninstalled Suite HA passes 264 tests and those from the adapter are omitted in that
  environment.
- The new scenarios check invalid data, partial sources and units as well with basic code
  maintenance.
- The actual Harness of HA preserves the original entities and restores a problem line
  between reloads. No damage to robots are caused
- The actual readings get eight accepted documents and seven consumables per robot with a
  catalogue of 7 pieces. The enlarged coordinator prepares 103 Retirement of a device: 309
  in total, 3 disabled by default.
- The washing system of mop in a robot remains outstanding. It's registered as part
  maintenance without presenting it with an engine malfunction.
- In this historic check of 0.2.0 Control connection with Chrome failed. The next domestic
  installation was 0.3.0.
- The local icon is verified as PNG RGBA without metadata, and 256 and 512 Ask them. Three
  additional checks protect the review of binaries by content and no images are allowed just
  for their extension.

The [evidence of telemetries](evidence/2026-11-23-telemetry.json) retains quantity, classifications and range without names or private IDs. The [inventory](telemetry.md) describes all fields and an example of local warnings. The adjustments are put forward for consultation only and no new textures have been validated.

### First release 0.1.0

- 203 evidence without credentials passing with official HA Harness 2026.11.2.
- Total coverage, including branches: 98,39% and minimum required: 90%.
- Fingg flow and platforms cover selection, identity. Reauth) Unknown states .Isolation with
  recharging or closure of errors 429 and results of uncertain orders.
- Ruff and format pass. Hassfest official valid an integration with no invalids
- Four SDDs and their catalogue pass the validator derived from vypdev / copilot.
- The privacy review checks regular patterns and compares real private values without
  printing them. Captures, keys and bills are out of Git.

The [quality report](evidence/2026-11-23-quality.json) record the reproducible results of local checks.

The five pylTest deprecation notices come from Harness Units and do not impede performance.
The IQ's ready but isn't currently run at GitHub. The actual readings were repeated with
respect to HA package restrictions: botocore 1.42.97 and Peaho 2.1.0.

## Feasibility decision

Authentication, reading and tested orders support local version 0.1.0 with regular consultation. The continuous events and additional capabilities preserve their explicit boundaries. The [catalogue](../specs/CATALOG.md) keeps separate evidence from the native client, MQTT, physical monitoring and HA adapter.
