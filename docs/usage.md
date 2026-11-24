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
Keep-out areas and virtual walls appear as dashed overlays. The saved map
and its restrictions remain managed by Roomba. Choose **Review selection**
to check the robot and destinations, then **Start cleaning** to submit the
selection with the robot's next-cleaning preferences. A map revision change
requires a new selection. A user needs permission to read the vacuum to see
its map and permission to control it to start cleaning.

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

The standard action `vacuum.send_command` supports an order name and generic parameters. For
specific operations of Roomba Home, typed actions check the robot's capacity and how best
to achieve them.

It partners rooms and areas detected to Home Assistant area from the settings of an entity
vacuum. Then you can choose one or more with `vacuum.clean_area`. To select rooms with a
same map allows you to choose what the robot will use. The integration checks the current
version before start. The names and identifiers are used inside you Home Assistant.

Yeah. Roomba Home Failed to give back the map, Home Assistant preserves known regions and
their associations. **Map data available** indicates whether the last inventory was
available. To start an area or room cleanup you require a proper current reading. A valid
response without maps removes regions offered by the robot.

`roomba_home.list_cleaning_regions` returns local identifiers that accept
`roomba_home.clean_regions`. The latter action supports an ordered list with optional
adjustments per stay. For example:

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

The missed options take the robot's preferences set up in HA. Both actions retain these
preferences. The forms of region admitted are vacuuming, mopping and simultaneous, always
subject to robot capabilities.

`roomba_home.list_cleaning_estimates` how much you estimate Roomba Home that would last the
cleanliness of each room for available profiles. Use the identifiers returned by
`roomba_home.list_cleaning_regions` and select rooms with that map.

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

Each room returns its estimates at `duration_seconds` with the model mode and settings of a
supplier. An empty list indicates that there's no usable estimate. The result serves to
compare profiles before cleaning. The remaining duration of an active mission requires
another reading.

The supported bases add buttons to clear the powder tank, wash mop and dry it up. The
fill-in button requires a base model that advertises manual filled. Before starting check
status of the dock and, depending on the share of its mop. The history of the last mission
shows results, duration and area with information about how. The sensor **Last recorded
mission destination** shows the target type and, as a result of his or her record indicates
that an attribute `region_count`. The historic error sensor retains that mission's code
after return to the dock.

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

Use **List cleaning routines** for a vacuum to get its saved routine names,
identifiers, regions, and editability. The response includes recognized
single-robot start routines. Weekly schedules have separate actions.

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
