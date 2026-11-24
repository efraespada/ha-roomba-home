# Roomba Home

Home Assistant Green with Core 2026.11.2 Expand the version 0.10.0. The monitoring of 24 November shown three robots X185240 its 3 associated bases and 470 Institutions. The live reading was connected and coupled to the robot of his last test with an active error 0. The record was shown **Temporary zones** and error 48. The update was checked without sending orders to robots and a copy of the version been retained 0.7.0. [Validation](validation.md)

In Home Assistant The same mission of temporary zone and with an error of navigation 48 and surface zero. The test update preserved identities and customization. They passed 1.489 with 100 % cover of judgements and branches. [Evidence of temporary zone](evidence/2026-11-23-temporary-zone-history.json)

The version 0.6.0 adds two configuration entities to robots that publish moisture and SmartScrub. Your values are stored in the robot and require a confirmation reading. The next cleanup preferences are still at HA. The client of 0.6.0 verified both tours and restoration of values with an actual robot at the dock. [Evidence of adjustments](evidence/2026-11-23-mop-preferences.json)

The version 0.6.1 adds events to the device of the dock and verifies resolution with states of the affected component. The test and added three event entities. [Evidence of diagnoses](evidence/2026-11-23-dock-diagnostics.json)

The version 0.7.0 incorporates vacuuming by coordinates inside an active map room. The record identifies the last clearance order without publishing geometry. [Evidence of vacuuming per point](evidence/2026-11-23-point-clean.json)

The local version 0.8.0 adds the default robot power number. The change and restoration were confirmed with an independent reading after they run `number.set_value` in a Home Assistant Isolated. [Undetermined power evidence](evidence/2026-11-23-default-suction.json)

The local version 0.9.0 adds two passes and carpet boost and with the threshold of automatic emptying by surface. The three controls were checked with the robot at the dock and his values were restored. [Evidence of persistent adjustments](evidence/2026-11-23-persistent-cleaning-options.json)

## 1.

Each robot has a device of Home Assistant and an entity `vacuum`. The recognized base appears as a child device with its buttons, states and breakages. Robot coordinators share the session and account reading. The controls are found from observed capabilities and states. The commands are serialised by robot and confirmed with subsequent transition. The production and development of mop followed by regular reading. [Architecture](architecture.md) · [SDD capacity](../specs/007-device-capabilities.md)

## 2.

| Model | Observed inventory | Cleansing | Advanced database and data |
| --- | ---: | --- | --- |
| X185240 | 3 | Vacuuming, mopping and simultaneously confirmed physically in a robot. The complete sequential began vacuuming. | 3 recognized bases. Mapping, history and programs with consumables or progress as advertised by each computer |
| R981040 | 1 | Reported account association. The transport of Roomba Home remains to be validated for this model | The integration setup filters this model. |

Power and moisture have their stated levels. SmartScrub and two passing carpet boost they are created according to the modality and capabilities of each robot. The physical tests were performed in two authorized robots. [Function matrix](capabilities.md)

## 3. Entities and actions of Home Assistant

| Platform | Duties |
| --- | --- |
| `vacuum` | To start, pause and cancel or resume with `vacuum.start` about a paused mission, come back to the dock, to locate and title power with an associated area. |
| `select`, `number`, `switch` | Mode, power and moisture SmartScrub with two passing points to strengthen the next mission. Default power and moisture adjustments SmartScrub, passing or carpeting as the robot reports them. Meter of automatic emptying as the base and robot support surface. |
| `button` | Reput local preferences, empty up and wash out. Filling manual if the base announces them |
| `sensor`, `binary_sensor` | Batteries, phases and models. Reforms of production with advanced technologies as well have been found to be useful for monitoring how best we can achieve these challenges while at the same time applying them so that they will get more information about their jobs or what's going on in this area? |
| `event` | Appearing, changing and solving problems by source. |
| Regional actions | `roomba_home.list_cleaning_regions`, `roomba_home.list_cleaning_estimates` and `roomba_home.clean_regions` with individual configuration of regions from the same map. |
| Vacuuming per point | `roomba_home.clean_point` with room and relative position, validated against an active map or its exclusions. |
| Timing actions | `roomba_home.create_cleaning_schedule`, `list_cleaning_schedules`, `update_cleaning_schedule`, `set_cleaning_schedule_enabled` and `remove_cleaning_schedule`. |

To mop, select `mop` at the next cleanup selector and run `vacuum.start`. The options `vacuum_mop` and `vacuum_then_mop` allow the other profiles when they are advertised. Regional clearance supports the three most direct modes. [Examples and use](usage.md) · [Telemetery inventory](telemetry.md)

## 4.

| Source | Use in integration | Evidence |
| --- | --- | --- |
| Discovery, Gigya and `/v2/login` | independent profile, temporary session and association of devices. | App capture and independent access with forced renewal. |
| Shadows MQTT | Current status, connection and settings with software as well at local time. | Authentic reading from the three modern robots. |
| Command Channel MQTT | Cleansing, pausing and resuscitation. | SDK and state transitions at available physical tests. |
| `/v1/p2maps` | Active maps, room groups and saved areas. Version before sending a dedicated mission | Real inventory, re-establishment and start of a mission that requested two rooms at another robot. |
| `/v1/time-estimates` | Cleaning times per room and profile before starting. | 167 responses 200 at the app catches with duration in seconds. |
| `/v1/{id}/missionhistory` | Summary history, times and area. | Physical and vacuuming per room, point and temporary zone and so forth. |
| Households and programs | GER of households and schedules, POST from new schedule with PUTS or DELETE by the group associated to robot. | Edit from HA, shooting after activates an hour and high with withdrawal confirmed by the supplier. |
| `/v1/robots/{id}/parts` and catalogue | Consumption, remaining quantity and maintenance. | Seven pieces per model observed. |

The diagnoses retain typed values and code by source. Private catches are held out of distribution [API contracts](api.md) · [Privacy](../SECURITY.md)

## 5.

- 1.278 automated tests for 0.5.0 with 100 % cover of judgements and branches. The profile
  matrix verifies 384 combinations with a simulated supplier.
- `hassfest`, Ruff and monitoring of the seven SDDs with complete privacy control for a test
  package.
- Vacuuming pause, cancellation and return to the dock have been checked at the domestic HA
  with 0.1.0 His test from HA exceeded his 4 minutes.
- Vacuuming timinized from domestic HA with 0.3.0. They passed 221 seconds between
  confirmation of vacuuming and pause. Cancellation and return were confirmed. The icon and
  reading of rooms with profile durations from that robot were also tested.
- Mopping from domestic HA with 0.3.0. The mop was prepared during 153 seconds. It was
  observed mopping of the ground, pause and renewal with cancellation or return to the dock
  with mission error 0.
- Manual emptying from child device of the dock. The state passed from 301 a 302 and came
  back to 301. Home Assistant confirmed the warrant and shown error 0.
- The domestic recharge retained 6 devices, 415 entities and the links of a test robot with
  its base. From the base manual washing, manually drying and monitoring of dry were
  confirmed with its error code at zero.
- A second robot from HA began a mission applying for two rooms. He put his foot at a pause.
  205 seconds of vacuuming confirmed, cancelled and returned to the dock. The first robot
  reported that it remained coupled during the test.
- The version 0.3.1 have been configuration check and charged after re-start. The two test
  robots again reported that they were connected and coupled. The correspondence between
  manual washing, coupled status and mission blockade was found with the data observed at
  HA's Harness.
- Two temporary weekly hours were established, published and withdrawn but remained deactivated. The second found his client 0.4.0 against the actual service. The issue of a time schedule disabled from the domestic installation was repeated. The interface and an independent consultation confirmed the change. The account returned to its earlier five hours. [Performance of schedules](evidence/2026-11-23-schedule-writes.json)
- The programmer started a vacuuming room after activating an hour schedule. Origin confirmed `cloud`, pause and return from the schedule. [Evidence of shooting](evidence/2026-11-23-schedule-dispatch.json)
- A modeling schedule 512 by region vacuuming. The robot reported error 48 before mop and
  came back to the dock. The record retained the result `stuck` and error code. The last
  mission contributes this information even though the current error has been returned to 0.
- The domestic installation 0.4.1 shown the historic error 48 next to current error 0. The
  interface and an independent reading confirmed that a time schedule from another robot
  could be activated or deactivated while maintaining its routine with their hour. The
  account returned to the five starting hours.
- At 0.5.0, the domestic server returned an same schedule as after repeated release. The independent reading confirmed the mode and adjustments of mopping. The client withdrew his time schedule and the absence from Home Assistant. [Evidence of 0.5.0](evidence/2026-11-23-schedule-crud.json)
- Targeted vacuuming Relaunch, mopping and simultaneously observed at authorized robot with
  independent client. The development of mopping Reproduced with a capture where `padWash`
  after `run` in 150,9 seconds.
- Another robot completed his production and moan during 25,9 seconds before we get back to the dock. SmartScrub passed from 0 a 1 and global moisture 3 a 2 at applying for level 1. A separate reading confirmed the restoration of both original adjustments. [Evidence of mopping](evidence/2026-11-23-mop-preferences.json)
- Local correction that separates estimates by type of region exceeded 1.279 with 100 %
  cover of judgements and branches.
- The version 0.6.0 That's better. 1.303 with 100 % cover of judgements and branches. The
  default adjustments were tested with standard HA services and the simulated supplier. The
  package loaded into an isolated instance and the same services both moved to a true robot
  with independent confirmation.
- The version 0.6.1 That's better. 1.316 with 100 % cover of judgements and branches.
  Isolated update preserved 378 and 0.6.0, the custom name of a sensor and preferences. A
  direct update from 0.5.0 have been 372 its entities test and registered the six default
  controls with three base events.
- A Test of `point_clean` confirmed order and destination in the with 1,95 m² reported. The live status announced the generic cycle `clean`. The return was confirmed and the previous power restored. [Evidence of clearance by point](evidence/2026-11-23-point-clean.json)
- The version 0.7.0 That's better. 1.417 with 100 % cover of judgements and branches.
  Isolated update preserved 372 identities of 0.5.0 and 381 of 0.6.1. The two routes
  remained a custom name and next cleanup preferences.
- Test insulated with installation files 0.1.0 and 0.3.0, persistently recorded and status
  data reproduced from the three robots. The update preserved the 12 original entities and
  their customization. The recharge remained unchanged. 369 entities registered with test.
  The endpoint of brands served both icon sizes and its variants for dark theme. The turn to
  0.1.0 regained the 12 The information referred to in Article 3 (1) of Regulation No 1065 /
  2012 shall be published as: A second update regained preferences of mopping and the area
  associated with their saved identities.
- Real reading with final installation file 0.3.0 in a Home Assistant Isolated. The
  configuration assistant registered three connected robots, 3 bases and 415 entities. The
  action of Home Assistant returned regions for all three robots and the six information
  about their history or schedule confirmed available readings. The action of durations
  returned 36 combinations per room at 13 rooms. The privacy of his diagnoses was
  established. The orders to the robots were blocked during that test.
- Failed map consultation at Home Assistant. Configure areas were preserved and the order
  was blocked until an actual Map has been obtained
- Simultaneous record, time and consumable reading with empty results. Indicators identified
  the robot-affected source and valid readings preserved zero count.
- Simultaneous loss of responses MQTT within a shared real connection. The other robot
  remained visible. The robot concerned retained its last reading mark and regained status
  at the following consultation. The automated suite verified that a robot with no confirmed
  connection rejects the cleanup start.
- Temporary sequence in the Home Assistant script engine with clock and simulated commands.
  Six scenarios have passed, including recovery when the start or pause isn't confirmed.

[Results, times and reach](validation.md) · [Quality monitoring](evidence/2026-11-23-cleaning-quality.json)

## 6.

The remaining physical tests include checking the complete course across several rooms and applying adjustments to each, a saved zone, second stage of sequential and effect from mopping and reload with resumption. The checked maps offer rooms. One also offered a temporary region. The change of start and timings have been verified while maintaining the routine. [Function limits](capabilities.md)

## 7. Evidence necessary to extend monitoring

| Function | Unpending evidence |
| --- | --- |
| Retirement and advanced adjustments by region | Order, mode and transition to mopping of the same mission. |
| Closed areas, time zones and several maps | Inventory with a persistent area or several maps and mission that will identify select destinations. For a temporary zone, to observe a mission with clear area and destination `tid` confirmed in the record. |
| Persistent adjustments in operation | Two passing ride, vacuuming carpet modulation and automatic emptying as you reach the set surface. The saved value has been checked with the robot. |
| Manual filled | A database that adverties manual and after-command reading. |
| Mode shooting | Scheduled missions of mopping or simultaneous and confirmed mode information at first. |
| Timely cleaning | The record confirmed `point_clean` with the map, version and coordinates. `spot` received an accused with his robot at the dock and this one remained loaded. It's necessary to check `spot` at rest outside of the dock and observe the natural end of `point_clean`. |
| Live map and current room | Two robots have been co-ordinated and directed. The positions have been put into the polygons of an active map. The performance and validation of live mapping packages remains to be implemented. |
| Percentage progress and remaining time | The app had been shown about seven minutes and the service estimated 397 seconds for the room and profile of test. The native timeline responded during a mission. The evolution of cover and calculation have to be confirmed during a cleanup. |

[Evidence of means and needs for extension](evidence/2026-11-23-cleaning-modes.json) [Map and progress evidence](evidence/2026-11-24-live-progress.json)
