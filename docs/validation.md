# Roomba Home validation

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
during targeted cleaning. Live countdown, coverage percentage, and room area
units still require provider evidence.
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
