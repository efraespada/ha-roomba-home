# Capabilities, implementation, and evidence

This matrix distinguishes provider discovery, implemented behavior, simulated
provider tests, and physical robot evidence. The initial model inventory was
recorded on 2026-11-23.

## Detected models

| Model / SKU | Associations | Available evidence | Supported scope |
|---|---:|---|---|
| X185240 | 3 | Native access, capabilities, eight accepted shadows, and seven consumables per robot | Validated family, with movement tests on two authorized robots |
| R981040 | 1 | Account association | Modern protocol remains unverified for this model. The integration excludes it. |

Cleaning capabilities come from `robots.*.cap` fields `oMode`, `suctionLvl`,
`ppWetLvl`, `scrub`, `multiPass`, and `carpetBoost`. Firmware is reported by
the robot and `rw-software`. The capability model combines these fields with
dock, active map, scheduling, history, consumables, and state data. It
distinguishes unknown capabilities from disabled capabilities and supported
values. Each robot has its own entity coordinator fed by shared account
polling. Selection and transport support X185240.

iRobot lists the 100/1000, 200/2000, Plus 400, Plus 500, and Max 700 series for
Roomba Home. Other models require their own captures and tests.
[Published iRobot compatibility](https://homesupport.irobot.com/articles/en_US/Knowledge/10500)

## Supported functions

| Function | Protocol or capability | Home Assistant surface | Physical evidence |
|---|---|---|---|
| Vacuum | Capability 2, command mode 2 | Vacuum entity and profile | Native and HA 0.1.0 and 0.3.0 cycles |
| Mop only | Capability 4, command mode 4 | Selector and profile | Preparation, mopping, pause, resume, cancellation, and return with HA 0.3.0 |
| Vacuum and mop | Capability 32, command mode 6 | Selector and profile | Sustained mode 6, pause, cancellation, and return |
| Vacuum then mop | Capability 512, whole-map command mode 512, regional mode 512 observed in schedules | Whole-map selector. Result remains submitted while only vacuuming has been observed. | A whole-map mission switched from vacuuming to mopping with the same mission start. A separate scheduled room mission ended with navigation error 48 before mopping. |
| Suction | `suctionLvl` 4 and `rw-settings.suctionLevel` | Number controls for the next mission and the default | Independent reads confirmed the default change from 3 to 2 and back to 3 in isolated HA. |
| Mop wetness | `ppWetLvl` 3 | Number controls for the next mission and the default | The default changed from 3 to 1 and back to 3. A mission requesting 1 reported a global value of 2. |
| SmartScrub | `scrub` 3 | Switches for the next mission and the default | Direct enable and disable were confirmed. One mopping run retained the active setting after returning. |
| Two passes | `multiPass` 1 and `rw-settings.twoPass` | Switches for the next mission and the default | Default change and restoration confirmed. The actual second pass is still unverified. |
| Carpet boost | `carpetBoost` 3 and `rw-settings.carpetBoost` | Switches for the next mission and the default | Default change and restoration confirmed. The response on carpet is still unverified. |
| Resume | SDK enum `resume` | Standard vacuum action preserves the mission | Targeted vacuuming and mopping with HA 0.3.0 |
| Locate | SDK enum `find` and robot audio setting | `vacuum.locate` with submitted result | The shadows do not confirm sound. |
| Standard fan speed | Robot-reported levels | `vacuum.set_fan_speed` shares the profile with the number entity | The robot reported a change in suction after start. |
| State, battery, and connectivity | State and connectivity shadows | Vacuum, sensor, and binary sensor | Three robots read successfully |
| Progress | Phase, cycle, mode, area, start, and elapsed time | Sensors and binary sensor for active cleaning at the dock | Phase and cycle confirmed through real readings. Physical recharge and resume is pending. |
| Live timeline | Correlated mission report with current mission number | Optional stage and completed room measurements with freshness | Start and relocation observed. Coverage and live ETA require more evidence. |
| Interactive floor plan | Associated map revision, restriction geometry, and live position batches | Dashboard with zoom, keep-out overlays, room and saved-zone selection, and confirmation | Map and service checks use Home Assistant fixtures. See the current household report for physical results. |
| Advanced dock | `dock.cap` and SDK-confirmed commands and states | Emptying, washing, drying, stopping drying, and manual refill if advertised | Emptying, washing, drying, and stopping drying confirmed in the home HA installation |
| Automatic emptying by area | `cap.autoevac` 2, an emptying dock, and `rw-settings.autoevacFreq` in m² | Dock number entity | Change from 25 to 50 m² and back to 25 confirmed. Automatic triggering at this threshold is pending. |
| Consumables | Signed read and parts catalog | Usage and quantities with units | Seven consumables per robot |
| Diagnostics and firmware | Typed shadow data | Sensors and sanitized diagnostics | Real reads and privacy tests |
| Maps and rooms | `GET /v1/p2maps` and `rid` regions | `vacuum.clean_area` with region names grouped by map | Targeted vacuuming and resume in one room. A second robot started after HA requested two rooms on the same map. |
| Vacuum a map point | `cap.dSpot` and `point_clean` with map version and coordinates | `roomba_home.clean_point` validates a point in an active room | The robot started vacuuming and history recorded the point. |
| Estimated room duration | Signed `POST /v1/time-estimates` | Read action reporting profile estimates in seconds | 13 rooms and 36 combinations per room in isolated HA, and six rooms and 216 combinations in home HA |
| Zones and per-room preferences | SDK `zid` regions and per-region profiles in favorites | Actions to list and clean regions with individual settings | A mission with two requested suction values started and returned after cancellation. The path, settings applied to each room, and saved zones remain unverified. |
| Temporary zone | `tid` and a command polygon tied to the active map | Target type in mission history | Vacuuming began and history recorded the exact target. Navigation ended with error 48 and zero area. |
| Schedules | Household read, `rw-schedule`, `rw-settings.timezone`, POST, PUT, and DELETE | Schedule and next-start sensors, plus create, list, change start, enable, disable, and delete actions | Creation as disabled, deletion, and a real scheduled vacuum run with origin `cloud` |
| Saved cleaning routines | Edition 1 favorites collection with server-assigned IDs | List, create, update, and remove actions for one associated vacuum | A temporary routine was created, renamed, updated with a different suction setting, and removed. Existing routines were preserved. |
| Map editing | The SDK provides several editor paths. The v1 route changed active geometry. | [Map and zone editor specification](../specs/009-map-zone-editor.md) | The disposable zone appeared in active geometry. Its associated region entry and completed cleaning still require verification. |
| History | Observed mission history GET | Start, end, active time, pause and recharge time, recharge and emptying counts, result, and breakdown by mode | Six real records from the authorized robot |
| Room history | Final room events with exact map revision | Room outcome, passes, and provider area values | Observed in Roomba history. Area units remain unverified. |

A new control requires a known source field, command and parameters, validated
capabilities, and evidence of the resulting state. Fault paths use synthetic
data in the Home Assistant harness.

## Pending verification

The suite checks serialization and omission of inactive settings across 384
valid profiles spanning four modes, four suction levels, three wetness levels,
and three booleans. The physical effect of several advanced preferences and
automatic recharge and resume still need verification.

Two direct regional vacuum-then-mop attempts produced no confirmed start. A
mission using regional value 32 reported mode 6. Schedule creation accepts
active map destinations and retains each region's preferences. The actual
route and second stage remain to be checked.

A `point_clean` command started vacuuming and history recorded its requested
coordinates and map version separately from the generic `clean` cycle. MQTT
acknowledged `spot` while the robot was docked and the robot stayed charging.
`vacuum.clean_spot` requires physical confirmation with the robot idle outside
the dock. [Spot-cleaning evidence](evidence/2026-11-23-spot-and-live-map.json)

A saved-zone test requires an available region and confirmation of its
destination in the mission history. A temporary-zone command confirmed the
destination, blockage, and return. A complete route remains pending.
[Temporary-zone evidence](evidence/2026-11-23-temporary-zone-history.json)

The Max 700 firmware notes describe vacuum then mop in a saved zone. The
exact directed command still needs to be captured.
[Max 700 firmware notes](https://homesupport.irobot.com/articles/en_US/Knowledge/70550)

[Physical cleaning-mode evidence](evidence/2026-11-23-cleaning-modes.json) ·
[Entities and actions](usage.md) · [Cleaning-profile SDD](../specs/006-cleaning-profiles.md)
