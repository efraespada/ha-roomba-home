# Entities, actions, and preferences

Each compatible robot uses one standard Home Assistant `vacuum` entity for
vacuuming and mopping. The examples use synthetic entity and region IDs.
Use your own IDs from the entity registry and the region listing action.
[Capability matrix](capabilities.md)

## Interactive floor plan

Enable **Show saved floor plans and live room updates** in the integration
options, register the JavaScript module from the [README](../README.md#floor-plan-dashboard),
and add the card using your Roomba vacuum entity. The card can switch between
associated floors. The live marker shows the last unexpired position. The
route shows observed segments and leaves gaps where samples were missing.

Use the map or the accessible buttons below it to select rooms and saved
zones. Use the zoom buttons to change scale and drag the map to pan it.
The legend distinguishes keep-out areas and virtual walls from no-mop areas.
The saved map and its restrictions remain managed by Roomba. The card shows
a notice when the map contains zone geometry that Roomba has yet to list for
cleaning, or when a saved zone is selectable from the list without a matching
outline.
Choose **Review selection** to check the robot and destinations, then **Start
cleaning** to submit the selection with the robot's next-cleaning preferences.
A map revision or region inventory change requires a new selection. A user
needs permission to read the vacuum to see its map and permission to control
it to start cleaning.

Choose **Review map dependencies** with one or more areas selected to see
which known routine or weekly schedule targets them. Roomba can return
entries with unresolved destinations, which the review flags for manual checking.

Open **Last mission by room** for the reported result, area, and pass count.
This information is also available from the **Last mission rooms** sensor.
**Current mission measurements** shows in-progress room readings when a fresh
timeline reply provides them.
[Mission telemetry](telemetry.md)

## Choose a cleaning mode and preferences

Select **Next cleaning mode** and choose **Mop**, **Vacuum**,
**Vacuum and mop**, or **Vacuum then mop** where supported. Set the relevant
preferences and start the same vacuum entity.

| Control | Effect |
|---|---|
| Next cleaning mode | Selects the mode for the next start |
| Next suction level | Sets the next vacuuming mission's suction |
| Next mop wetness and SmartScrub | Set the next mopping mission's settings |
| Next two passes and next carpet boost | Request the corresponding settings when supported |
| Suction, default mop wetness, SmartScrub, two passes, and carpet boost | Write the robot's default while idle and confirm it with a later read |
| Reset next cleaning preferences | Clears the local preference and restores the default mode without moving the robot |
| Area for automatic emptying | Sets the dock area threshold in m² when that capability is reported |
| Empty bin | Requests manual emptying at a compatible dock |

Next-cleaning preferences stay local to Home Assistant and survive reloads.
They apply only when relevant to the selected mode. Changing modes preserves
the other preferences for later. With no local override, optional values are
omitted and the robot uses its settings. Reported values are separate sensors.
In one physical trial a request for mop wetness 1 and enabled SmartScrub left
global wetness at 2 and SmartScrub enabled. [Mopping evidence](evidence/2026-11-23-mop-preferences.json)

Home Assistant converts square feet to the nearest whole square meter
for the automatic emptying threshold. Controls become unavailable if their
required capabilities cease to be reported.

## Standard actions

| Action | Behavior |
|---|---|
| `vacuum.start` | Starts with the next-cleaning profile. Resumes an existing paused mission. |
| `vacuum.pause` | Pauses an active mission |
| `vacuum.stop` | Cancels a mission |
| `vacuum.return_to_base` | Requests return and checks arrival |
| `vacuum.set_fan_speed` | Saves the next-cleaning suction level |
| `vacuum.locate` | Requests a sound when the robot supports it |
| `vacuum.clean_area` | Cleans mapped regions linked to Home Assistant areas |

Resuming preserves the current mission and mode. To change modes, cancel the
current mission and start a new one with the desired profile. Before starting,
the integration checks readiness and active errors. A missing bin blocks
vacuuming and emptying. Mopping checks the mop, water system, and dock state.
A water-system-only issue can leave vacuuming available when the robot reports
readiness. [Problem events and codes](telemetry.md#problems-and-events)

Example script for a mop-only mission.

```yaml
sequence:
  - action: select.select_option
    target:
      entity_id: select.example_robot_next_cleaning_mode
    data:
      option: mop
  - action: number.set_value
    target:
      entity_id: number.example_robot_next_wetness_level
    data:
      value: 2
  - action: vacuum.start
    target:
      entity_id: vacuum.example_robot
```

Select options use the stable values `vacuum`, `mop`, `vacuum_mop`, and
`vacuum_then_mop`. Use the options supported by the selected robot.

After a command, the integration checks state every five seconds for up to 40
seconds, or 120 seconds for return to the dock. The `last_command_result`
attribute and last-command sensor report `pending`, `submitted`,
`confirmed`, or `unconfirmed`. Locate remains submitted after the broker
acknowledges it. Mopping can remain submitted during preparation. A later read
can confirm the same mission when floor cleaning begins, for up to five minutes
after preparation. Whole-map vacuum then mop remains submitted while only the
vacuum stage is observed. Refresh an unconfirmed result before retrying.
Commands are serialized per robot. State reads are shared across the account.
Reported cleaning settings are refreshed after a start.

## Telemetry, progress, and problems

The existing battery, mission error, and connectivity IDs are preserved.
**Last Roomba connectivity update** reports the provider's timestamp for the
connection. **Mission finished** can trigger automations when a new result
appears in history.

**Preparing the mop** indicates washing or refilling during a cleaning cycle.
Observed preparation took about 150 seconds. Pause is available once the
robot reports floor cleaning. The dock device controls manual wash.

Use the robot and dock problem event entities for new, changed, or cleared
codes. The entity requires an explicit normal reading before clearing a
previous problem. [Telemetry inventory](telemetry.md)

## Rooms, zones, and dock

Assign the robot's regions to Home Assistant areas in the vacuum entity's
settings. The `vacuum.clean_area` action uses those assignments. Select
regions from one active map. Home Assistant checks the current map version
before sending the command.

**Map data available** indicates whether the last inventory read succeeded.
A failed read preserves known regions and area associations. Starting a
region mission requires a current reading. A successful response that
contains no floors removes the robot's available regions.

`roomba_home.list_cleaning_regions` returns local identifiers that accept
`roomba_home.clean_regions`. The latter action supports an ordered list with
optional settings per region.

```yaml
action: roomba_home.clean_regions
target:
  entity_id: vacuum.example_robot
data:
  regions:
    - id: example_map:rid:room_a
      mode: vacuum
      suction_level: 3
    - id: example_map:rid:room_b
      mode: mop
      wetness_level: 2
      smart_scrub: true
```

Omitted options use the next-cleaning preferences in Home Assistant. The
action supports vacuuming, mopping, and simultaneous vacuuming and mopping
per region, subject to robot capabilities.

Use `roomba_home.list_cleaning_estimates` for Roomba's planned durations by
region and cleaning profile. Supply region IDs from a single map.

```yaml
action: roomba_home.list_cleaning_estimates
target:
  entity_id: vacuum.example_robot
data:
  regions:
    - example_map:rid:room_a
    - example_map:rid:room_b
response_variable: roomba_estimates
```

Each estimate has `duration_seconds` and its reported profile. An empty list
indicates that Roomba returned no usable estimate. Use the results to compare
profiles before starting a mission.

Compatible docks expose buttons to empty the bin, wash the mop, and dry it.
Manual refill requires a dock that reports refill support. Check dock status
and the relevant consumables before starting. The **Last recorded mission
destination** sensor shows the target type and `region_count` when Roomba
reports them. The mission error sensor retains the recorded error code after
the robot docks.

## Vacuum a map point

Use **List cleaning regions** to get the room identifier and call `roomba_home.clean_point`
with robot and two fractions between 0 and 1. Each fraction measures the position from his
or her minimum axis at a rectangle that embraces an area, and onto its motif.

```yaml
action: roomba_home.clean_point
target:
  entity_id: vacuum.example_robot
data:
  region_id: example_map:rid:room_a
  x: 0.4
  y: 0.55
```

The robot needs regular digital cleanup, vacuuming and an active map. The action rejects
points outside the room, about its edge or an exclusion area. The order requested vacuuming
with robot settings. The supplier's coordinates are computed at the time and have been put
out of sensors. The result **Submitted** indicates that the initiation of an vacuuming new
remote. At the end, **Last recorded mission command** can show **Cleanup at a point on the
map** According to his robot's history.

## Cleaning schedules

**Creating a cleaning schedule** keeps an off-date weekly routine. Use **List cleaning regions** identifiers and select regions from the same map. Order and preferences are held by
region.

```yaml
action: roomba_home.create_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  name: Vacuum the entryway
  weekdays: [2, 5]
  time: "10:15:00"
  regions:
    - id: example_map:rid:entryway
      mode: vacuum
      suction_level: 1
      two_pass: false
```

Local and local programs Roomba Home are consulted with separate sensors. Execut **List
editable cleaning schedules** about the entity `vacuum` to check out the weekly schedules
that you can modify. The local response includes name, identifier and date of activation.

Pass the identifier back to **Change the start of a weekly cleanup**. The day goes from 1
(Monday) 7 (Sunday) The hour uses the robot's time zone.

```yaml
action: roomba_home.update_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  schedule_id: example_household:example_schedule
  weekdays: [2, 5]
  time: "10:15:00"
```

Each change reads the current schedule and preserves its routine with their activation. If
Roomba Home does not confirm the result, check with your schedule before repeating. The
identifier and name are only returned to the requested action. Sensors and diagnoses
continue to show summaries.

Use **To activate or turn off a cleaning schedule** to change your activation with the same
identifier. The schedule keeps his day, time and routine

```yaml
action: roomba_home.set_cleaning_schedule_enabled
target:
  entity_id: vacuum.example_robot
data:
  schedule_id: example_household:example_schedule
  enabled: true
```

**Remove a cleaning schedule** Withdrawal of Roomba Home The time associated with the
identifier shall be activated or disabled. The three exchange and release actions confirm
the result by re-viewing his robot's list.

## Saved cleaning routines

Choose **Manage routines** in the floor plan card. Selecting areas on the
map first prepopulates a new routine. For supported routines on that floor,
use the order buttons and per-area controls to edit destinations and cleaning
preferences. **Duplicate** starts a new routine with the current draft's
settings. **Delete** asks for confirmation. A name-only update can preserve
the original settings of a routine with unavailable or unsupported targets.
Routine management sends commands to the saved routines collection and leaves
the robot idle.

Use **List cleaning routines** for a vacuum to get its saved routine names,
identifiers, regions, recognized per-region settings, and editability. The
response includes supported single-robot start routines. Weekly schedules
have separate actions.

**Create a cleaning routine** saves an ordered selection from one current
map. Specify optional cleaning preferences per region. The action saves the
routine without starting the vacuum. List the robot's regions first to get
the identifiers.

```yaml
action: roomba_home.create_cleaning_routine
target:
  entity_id: vacuum.example_robot
data:
  name: Vacuum the entryway
  regions:
    - id: example_map:rid:entryway
      mode: vacuum
      suction_level: 1
```

Use **Update a cleaning routine** with its ID and a new name, replacement
regions, or both. A rename keeps the original destinations and settings.
**Remove a cleaning routine** deletes the selected editable routine. If an
action reports an unconfirmed result, list the routines before retrying.
[Provider contract](api.md#saved-cleaning-routines)

## Current limitations

The vacuuming per room have been verified, the pause and resumption of a two-bedroom mission. Filling, washing and drying buttons have been tested. A number of challenges remained to be met. saved zone The complete course with adjustments per stay, the second stage of after and manual completion. [Capability matrix](capabilities.md)

Current monitoring uses regular consultations. A cloud reading can be old and availability also requires an explicit state of connection. The [validation](validation.md) retains the historic results and current campaign. See also [official documentation of vacuum](https://contributors.home-assistant.io/core/entities/vacuum/).
