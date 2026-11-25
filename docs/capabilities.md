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
| Whole-area start | Untargeted native `start` with the selected profile | Confirmed **Clean everywhere** on the card and a Home Assistant action | The action started a physical Max 700 Combo run. Signed history classified the trial as whole-area cleaning. [Validation](validation.md#whole-area-and-directed-cleaning-scope) |
| Mop only | Capability 4, command mode 4 | Selector and profile | Preparation, mopping, pause, resume, cancellation, and return with HA 0.3.0 |
| Vacuum and mop | Capability 32, command mode 6 | Selector and profile | Sustained mode 6, pause, cancellation, and return |
| Vacuum then mop | Capability 512 and mode 512 in regional parameters for directed cleaning | Next-cleaning selector and per-destination settings in saved routines | Whole-floor and Android furniture trials switched from vacuuming to mopping under one mission identity. [Directed trial](validation.md#directed-vacuum-then-mop) |
| Suction | `suctionLvl` 4 and `rw-settings.suctionLevel` | Number controls for the next mission and the default | Independent reads confirmed the default change from 3 to 2 and back to 3 in isolated HA. |
| Mop wetness | `ppWetLvl` 3 | Number controls for the next mission and the default | The default changed from 3 to 1 and back to 3. A mission requesting 1 reported a global value of 2. |
| SmartScrub | `scrub` 3 | Switches for the next mission and the default | Direct enable and disable were confirmed. One mopping run retained the active setting after returning. |
| Two passes | `multiPass` 1, `rw-settings.twoPass`, and the destination's timeline `passCount` | Switches for the next mission and the default, plus requested settings and observed counts per live destination | A directed command echoed `twoPass: true`. The room was ended before Roomba reported a pass. The reported setting was restored after the run. [Trial](validation.md#requested-settings-and-reported-passes) |
| Carpet boost | `carpetBoost` 3 and `rw-settings.carpetBoost` | Switches for the next mission and the default | Default change and restoration confirmed. The response on carpet is still unverified. |
| Resume | SDK enum `resume` | Standard vacuum action preserves the mission | Targeted vacuuming and mopping with HA 0.3.0 |
| Locate | SDK enum `find` and robot audio setting | `vacuum.locate` with submitted result | The shadows do not confirm sound. |
| Skip the current destination | `cap.mc`, basic `skip` command, and correlated finished-area events | Map card confirmation, button, and `roomba_home.skip_current_area` | The Max 700 skipped a furniture target and continued to the next. [Physical validation](validation.md#skip-the-current-destination) |
| Standard fan speed | Robot-reported levels | `vacuum.set_fan_speed` shares the profile with the number entity | The robot reported a change in suction after start. |
| State, battery, and connectivity | State and connectivity shadows | Vacuum, sensor, and binary sensor | Three robots read successfully |
| Voice volume and child and pet lock | `rw-settings.audio.volume` (0–100) and boolean `rw-settings.childLock` | Robot configuration number and switch | The official app and isolated Home Assistant changed both values. Independent Roomba reads confirmed the changes and restoration. [Validation](validation.md#robot-configuration-controls) |
| Robot name and installed voices | `rw-settings.name`, `langs2.sLang`, and the default and downloaded language inventories | Configuration text and select entities on the robot device | The app and integration transport changed and restored both settings on the docked Max 700 Combo. [Validation](validation.md#robot-name-and-voice-language) |
| Robot serial number | Signed asset lookup and matching `RobotID` | Robot device registry metadata | The signed response matches the serial in the Android About screen. [Validation](validation.md#robot-serial-number) |
| Robot reboot | One `reset` command and subsequent `rw-constatus` connection transitions | Reboot configuration button and last command status | The Max 700 Combo disconnected, returned to charging, and retained its map and tested settings. [Validation](validation.md#robot-reboot-and-voice-catalog) |
| Downloadable voice catalog | Public model catalog and the robot's reported installed options | List robot voices action | Roomba returned 25 languages for the Max 700 Combo. [Validation](validation.md#robot-reboot-and-voice-catalog) |
| Voice pack installation | Catalog metapackage, language deployment ID, and reported software and voice settings | Install robot voice action | A confirmed download replaced the single additional voice without changing the map or default voices. [Validation](validation.md#voice-pack-installation) |
| Progress | Phase, cycle, mode, area, start, and elapsed time | Sensors and binary sensor for active cleaning at the dock | Phase and cycle confirmed through real readings. Physical recharge and resume is pending. |
| Live timeline | Correlated report with the current mission number | Stage plus active and finished area measurements when available | Start, relocation, and the transition between two furniture targets were observed. Coverage percentage and live ETA require more evidence. |
| Live route activity | Operating modes in `pos_update.cur_path` | Travel, vacuuming, mopping, and combined activity colors in both map views, plus a live activity sensor | Three localized Max 700 missions matched their active modes to archived routes. [Validation](validation.md#wet-cleaning-route-activity) |
| Live route recovery | Fresh `map_update.livemap_url_raw` and matching incremental positions | Recover earlier route segments when Home Assistant joins late | The same mission recovered 64 positions within 1.12 cm of the directly observed positions. [Validation](validation.md#live-route-recovery) |
| Interactive floor plan | Associated map revision, restriction geometry, and live position batches | Dashboard with zoom, keep-out overlays, room and saved-zone selection, and confirmation | Map and service checks use Home Assistant fixtures. See the current household report for physical results. |
| 3D floor plan | `floorPlan`, `floorTypes`, `dockPoses`, furniture, and current positions from the associated revision | Rotatable 3D view with furniture toggle, carpet and dock overlays, and area selection | Roomba Home displayed the 3D map for the Max 700. The dashboard projects the reported planar geometry. [Archive layers](api.md#floor-plan-display-layers) |
| Advanced dock | `dock.cap` and SDK-confirmed commands and states | Emptying, washing, drying, stopping drying, and manual refill if advertised | Native controls verified in Home Assistant. The official app and integration transport confirmed that a manual wash can interrupt drying on the Max 700 Combo. [Validation](validation.md#washing-during-drying) |
| Saved-floor lifecycle | Native `train` command and map `visible` setting | Confirmed mapping start, mapping status, and reviewed removal from the card | [API and confirmation rules](api.md#mapping-runs-and-floor-removal) |
| Archived cleaning reports | Signed robot history, embedded command, and exact `p2maps` archive | Report list, requested destinations and preferences, final per-area results, timeline, historical zones and restrictions, and coverage and paths in 2D or 3D | [Requested plan validation](validation.md#historical-destination-plans) · [Max 700 report validation](validation.md#archived-cleaning-reports) |
| Room cleaning scores | Signed `/v1/p2maps/clean-score` with the active map revision | Read the score, traffic, score timestamps, and suggested profile in the card or an action | The Max 700 returned one associated room with score 0 and a recognized profile. [Validation](validation.md#room-cleaning-scores) |
| Automatic mop wash settings | `rw-settings.pwHeat`, `pwReturn`, `detergent`, and `padDryDur` | Dock configuration selectors, solution switch, and reported telemetry | The official Android app and isolated Home Assistant verified all choices and restored the original settings while the robot stayed docked. [Validation](validation.md#automatic-mop-wash-settings) |
| Automatic emptying by area | `cap.autoevac` 2, an emptying dock, and `rw-settings.autoevacFreq` in m² | Dock number entity | Change from 25 to 50 m² and back to 25 confirmed. Automatic triggering at this threshold is pending. |
| Consumables | Signed parts resource and model catalog | Usage and quantities with units, plus a confirmed maintenance reset for enabled counters | Seven catalog parts per robot. Six reset controls visible in the official app. Writes verified with simulated cloud responses. [Validation](validation.md#maintenance-counter-reset) |
| Diagnostics and firmware | Typed shadow data and public firmware catalog | Installed robot and dock software, last robot update, on-demand catalog status, and sanitized diagnostics | Last-update date and up-to-date status matched the official app. [Software protocol](api.md#robot-software-status) |
| Maps and rooms | `GET /v1/p2maps` and `rid` regions | `vacuum.clean_area` with region names grouped by map | Targeted vacuuming and resume in one room. A second robot started after HA requested two rooms on the same map. |
| Clean a map point | `cap.dSpot`, `cap.oMode`, and `point_clean` with map version and coordinates | Vacuum, mop, do both together, or vacuum then mop at a reviewed map point. The card and action use the robot's advertised modes. | Roomba's timeline recorded the exact point command and operating mode. The Home Assistant mode selector and map guards have automated coverage. [Validation](validation.md#point-cleaning-from-the-floor-plan) |
| Estimated room duration | Signed `POST /v1/time-estimates` | Read action reporting profile estimates in seconds | 13 rooms and 36 combinations per room in isolated HA, and six rooms and 216 combinations in home HA |
| Routine draft duration | Exact per-area matches from the signed room estimate table on the reviewed floor | Estimate the draft's per-area times before saving and show coverage when the total is partial | Seven Android favorites matched exactly. The mixed room and furniture draft returned only the room's time. [Validation](validation.md#routine-draft-estimates) |
| Zones and per-room preferences | `zid` regions and per-region profiles in favorites | List and clean regions with individual settings | A saved zone completed vacuuming in Android and a full sequence in Home Assistant. The installed editor also started a new zone before inventory publication. The physical application of every regional setting remains open. [Saved-zone validation](validation.md#immediate-saved-zone-selection-in-0250) |
| Temporary zone | `tid` and a command polygon tied to the active map | Target type in mission history | Vacuuming began and history recorded the exact target. Navigation ended with error 48 and zero area. |
| Schedules | Household read, `rw-schedule`, `rw-settings.timezone`, POST, PUT, and DELETE | Weekly and one-time schedules in the floor plan editor and actions. Change timing, order, and recognized per-area settings, and enable or remove schedules. | Real weekly and native one-time entries retained their timing and activation state during settings changes. A previously enabled one-time schedule started on the Max 700. [Editor validation](validation.md#schedule-editor-and-per-area-settings) · [One-time dispatch](validation.md#one-time-cleaning-schedules) |
| Saved cleaning routines | Edition 1 favorites with server-assigned IDs, ordered regions, furniture polygon links, and saved duration estimates | List, save, reorder, duplicate, run, and remove supported single-robot routines with per-area settings. Show the estimate for supported routines saved in the app. | Roomba confirmed reordered furniture and room targets with distinct settings. Android presets saved concrete preferences in a compatible single-area command. [Native app validation](validation.md#native-single-area-routines) |
| Recent and suggested routines | Signed floor-scoped routine list, stable regions, and matching furniture outlines | Load a recent selection or all current rooms, choose a cleaning point, and run a reviewed draft | Android opened a recent furniture destination and the signed response resolved it on the active map. [Quick routine validation](validation.md#recent-and-suggested-routines) |
| Fixed routine presets | Supported Max 700 Combo, `digiCap.cleaningProfiles` and independently verified per-mode preferences | Apply Light, Normal, or Deep to a single destination or to all selected destinations, with per-area modes and order preserved. | Android displayed all twelve settings combinations. [Native preset validation](validation.md#fixed-routine-presets) |
| Map editing | Map-version writes edit rooms, cleaning zones, keep-out areas, no-mop areas, and linear virtual walls. A settings route saves floor names and orientation. | Rename and rotate floors, divide and merge rooms, and edit room names, cleaning zones, and restrictions. Review known routine and schedule dependencies. [Map and zone editor specification](../specs/009-map-zone-editor.md) | A split room and saved zone were usable before the inventory updated. A Max 700 trial created, moved, and removed a wall with signed confirmation. [Saved-zone validation](validation.md#directed-vacuum-then-mop) · [Virtual wall validation](validation.md#editing-virtual-walls) |
| Local map backups | Signed associated revision and private Home Assistant storage | Save, preview offline, pin, retain, and export original archives. Optional automatic capture before map edits or removal. Restore the name, orientation, and recorded cleaning zones of an active floor. | A Max 700 trial recovered the original archive offline and restored signed settings and cleaning zone outlines. [Backup validation](validation.md#local-map-backups) · [Zone recovery validation](validation.md#recovering-cleaning-zones) |
| Furniture | Whole-layer `adjust_furniture` edits, `furniture` archive, and ordered temporary targets | Show, edit, and clean around furniture. Inspect zone and furniture results by mission. | Verified edit lifecycle and natural completion of two ordered destinations. [Completion evidence](evidence/2026-11-25-ordered-furniture-completion.json) |
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

A scheduled room sequence began vacuuming and encountered navigation error
48 before mopping. The regional schedule retains the requested destination
and profile for that trial. [Schedule evidence](evidence/2026-11-23-schedule-dispatch.json)

A `point_clean` command started vacuuming and history recorded its requested
coordinates and map version separately from the generic `clean` cycle. MQTT
acknowledged `spot` while the robot was docked and the robot stayed charging.
`vacuum.clean_spot` requires physical confirmation with the robot idle outside
the dock. [Spot-cleaning evidence](evidence/2026-11-23-spot-and-live-map.json)

A generic temporary-zone command confirmed its destination and return
after a navigation blockage. Native saved zones on the verified map format
use the active archive for selection and cleanup.
[Saved-zone trial](validation.md#directed-vacuum-then-mop) ·
[Temporary-zone evidence](evidence/2026-11-23-temporary-zone-history.json)

The Max 700 firmware notes describe vacuum then mop in a saved zone.
[Max 700 firmware notes](https://homesupport.irobot.com/articles/en_US/Knowledge/70550)

[Physical cleaning-mode evidence](evidence/2026-11-23-cleaning-modes.json) ·
[Entities and actions](usage.md) · [Cleaning-profile SDD](../specs/006-cleaning-profiles.md)
