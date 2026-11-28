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
| Two passes | `multiPass` 1, `rw-settings.twoPass`, and saved-zone completion events | Switches for the next mission and the default, plus requested settings, raw pass values, and confirmed saved-zone completions | The signed history confirmed two completed passes for a saved zone and one for an interrupted run with the same requested settings. [Physical validation](validation.md#saved-zone-passes-and-live-stage-timing) |
| Carpet boost | `carpetBoost` 3 and `rw-settings.carpetBoost` | Switches for the next mission and the default | Signed missions confirmed both requested values while the robot vacuumed over mapped carpet. Effective motor power remains unverified. [Carpet trial](validation.md#carpet-boost-and-mapped-surface) |
| Resume | SDK enum `resume` | Standard vacuum action preserves the mission | Targeted vacuuming and mopping with HA 0.3.0 |
| Return to base | Staged `pause` and `dock` from active Max 700 Combo cleaning | Standard vacuum action confirms arrival | One Home Assistant action paused the mission and returned the physical robot to its dock. [Validation](validation.md#return-during-active-cleaning) |
| Current mission controls | Reviewed mission identity and existing native pause, resume, stop, and dock commands | Phase-specific controls in the map card with cancellation and return confirmation | The installed 0.79.0 card paused, resumed, canceled, and returned a physical Max 700 Combo during one trial. [Household verification](validation.md#reviewed-mission-controls) |
| Active map errors | Current mission error code and component faults from Roomba's robot and dock shadows | Keep the affected source and code visible above the floor plan independently of mission phase | A Max 700 Combo continued reporting error 48 after returning to charge. [Household comparison](validation.md#household-live-coverage-and-active-errors) |
| Connection diagnostics | `rw-constatus`, its provider metadata, and the last fast Roomba read | Read-only **Connection** section in Device settings, the existing Cloud connectivity binary sensor and diagnostics | Android exposes a Wi-Fi reconnection entry. The card displays Roomba's cloud status and timestamps. [Connection validation](validation.md#connection-details-in-device-settings) |
| Locate | SDK enum `find` and robot audio setting | Reviewed **Locate robot** in Device settings and `vacuum.locate` | The card displays the submitted outcome from the command. [Card validation](validation.md#locate-and-reboot-from-device-settings) |
| Skip the current destination | `cap.mc`, basic `skip` command, and correlated finished-area events | Map card confirmation, button, and `roomba_home.skip_current_area` | The Max 700 skipped a furniture target and continued to the next. [Physical validation](validation.md#skip-the-current-destination) |
| Standard fan speed | Robot-reported levels | `vacuum.set_fan_speed` shares the profile with the number entity | The robot reported a change in suction after start. |
| State, battery, and connectivity | State and connectivity shadows | Vacuum, sensor, and binary sensor | Three robots read successfully |
| Voice volume and child and pet lock | `rw-settings.audio.volume` (0–100) and boolean `rw-settings.childLock` | Robot configuration number and switch | The official app and isolated Home Assistant changed both values. Independent Roomba reads confirmed the changes and restoration. [Validation](validation.md#robot-configuration-controls) |
| Robot name and installed voices | `rw-settings.name`, `langs2.sLang`, and the default and downloaded language inventories | Configuration text and select entities on the robot device | The app and integration transport changed and restored both settings on the docked Max 700 Combo. [Validation](validation.md#robot-name-and-voice-language) |
| Robot serial number | Signed asset lookup and matching `RobotID` | Robot device registry metadata | The signed response matches the serial in the Android About screen. [Validation](validation.md#robot-serial-number) |
| Robot activation date | Signed asset `min_utc_reg_date` and matching `RobotID` | Date sensor in robot diagnostics | The signed registration day matched the date in the Android About screen for a Max 700 Combo. [Validation](validation.md#robot-activation-date) |
| Robot reboot | One `reset` command and subsequent `rw-constatus` connection transitions | Reviewed **Reboot robot** in Device settings, the configuration button, and last command status | The Max 700 Combo disconnected, returned to charging, and retained its map and tested settings. [Transport validation](validation.md#robot-reboot-and-voice-catalog) · [Card validation](validation.md#locate-and-reboot-from-device-settings) |
| Downloadable voice catalog | Public model catalog and the robot's reported installed options | **Download voices** in Device settings and the List robot voices action | Roomba returned 25 downloadable locale codes for the Max 700 Combo. [Validation](validation.md#robot-reboot-and-voice-catalog) |
| Voice pack installation | Catalog metapackage, language deployment ID, and reported software and voice settings | Reviewed installation from the card and the Install robot voice action | A confirmed download replaced the single additional voice without changing the map or default voices. [Validation](validation.md#voice-pack-installation) |
| Progress | Phase, cycle, mode, area, start, and elapsed time | Sensors, binary sensor for active cleaning at the dock, and current mission readout above the floor plan | Phase and cycle confirmed through real readings. Physical recharge and resume is pending. [Current mission readout](usage.md#current-mission-readout) |
| Live timeline | Correlated report with the current mission number | Accumulated destination cleaning time, area measurements, and a countdown for directed rooms with matching durations | Android's zone timer stayed steady through a physical pause and advanced across passes. The integration recovered those times from the captured events. Overall progress percentage remains unverified. [Elapsed cleaning time](validation.md#accumulated-destination-cleaning-time) · [Real countdown trial](validation.md#estimated-time-during-a-directed-mission) |
| Live route activity | Operating modes in `pos_update.cur_path` | Travel, vacuuming, mopping, and combined activity colors in both map views, plus a live activity sensor | Three localized Max 700 missions matched their active modes to archived routes. [Validation](validation.md#wet-cleaning-route-activity) |
| On mapped carpet | Fresh position and `floorTypes` carpet polygons on the active revision | Binary sensor and floor plan label | The Max 700 reported vacuuming positions on the saved carpet and position samples outside it. Home Assistant matched both to the signed floor. [Carpet trial](validation.md#carpet-boost-and-mapped-surface) |
| Live route recovery | Fresh `map_update.livemap_url_raw` and matching incremental positions | Recover earlier route segments when Home Assistant joins late | The same mission recovered 64 positions within 1.12 cm of the directly observed positions. [Validation](validation.md#live-route-recovery) |
| Interactive floor plan | Associated map revision, restriction geometry, and live position batches | Dashboard with zoom, keep-out overlays, room and saved-zone selection, and confirmation | Map and service checks use Home Assistant fixtures. See the current household report for physical results. |
| 3D floor plan | `floorPlan`, `floorTypes`, `dockPoses`, furniture, and current positions from the associated revision | Rotate, pan, and zoom the 3D view with furniture, carpet and dock overlays, and area selection | Roomba Home displayed the 3D map for the Max 700. Chrome verified touchscreen navigation on the live floor and archived reports. [Archive layers](api.md#floor-plan-display-layers) · [Touch validation](validation.md#touch-navigation-for-floor-plans-and-reports) |
| Advanced dock | `dock.cap` and SDK-confirmed commands and states | Emptying, washing, drying, stopping drying, and manual refill if advertised | Native controls verified in Home Assistant. The official app and integration transport confirmed that a manual wash can interrupt drying on the Max 700 Combo. [Validation](validation.md#washing-during-drying) |
| Saved-floor lifecycle | Native `train` command and map `visible` setting | Confirmed mapping start, mapping status, and reviewed removal from the card | [API and confirmation rules](api.md#mapping-runs-and-floor-removal) |
| Archived cleaning reports | Signed robot history, embedded command, and exact `p2maps` archive | Report list, requested destinations and preferences, final per-area results, timeline, historical zones and restrictions, and coverage and paths in 2D or 3D | [Requested plan validation](validation.md#historical-destination-plans) · [Max 700 report validation](validation.md#archived-cleaning-reports) |
| Short canceled cleaning reports | The signed history query with `filterType` omitted | Expand the recent report list and open any available original archive | An expanded Max 700 Combo read added eight canceled reports. One included an exact furniture target, positive cleaned area, trajectory, and coverage. [Validation](validation.md#expanded-cleaning-history) |
| Room cleaning scores | Signed `/v1/p2maps/clean-score` with the active map revision | Read the score, traffic, score timestamps, and suggested profile in the card or an action | The Max 700 returned one associated room with score 0 and a recognized profile. [Validation](validation.md#room-cleaning-scores) |
| Recommended rooms | Signed `CLEAN_DIRTY` targets and profiles with the matching `smart_clean_id` score record | Highlight recommended rooms in amber when the map opens. Refresh while the card is visible and load their profiles as an editable draft with automatic order. | The installed card initially highlighted the same five rooms as Smart cleaning in Android. [Validation](validation.md#automatic-smart-cleaning-overlay) |
| Automatic mop wash settings | `rw-settings.pwHeat`, `pwReturn`, `detergent`, and `padDryDur` | Dock configuration selectors, solution switch, and reported telemetry | The official Android app and isolated Home Assistant verified all choices and restored the original settings while the robot stayed docked. [Validation](validation.md#automatic-mop-wash-settings) |
| Automatic emptying by routine or area | `cap.autoevac` 2, a recognized emptying dock, and `rw-settings.autoevacFreq` equal to 0 or a supported threshold in m² | Dock selector and area number | Android and Home Assistant changes confirmed through signed reads. A short routine reported zero evacuations with per-routine mode selected. [Physical validation](validation.md#physical-emptying-after-a-short-routine) |
| Consumables | Signed parts resource and localized model catalog | Usage bars and remaining quantities, part descriptions and guides, and reviewed counter resets from the card or the Home Assistant action | Seven verified care descriptions, five shop links, and two regional guides. Android's hours and usage bars matched the signed API for three timed parts. [Catalog validation](validation.md#maintenance-catalog-and-links) · [Reset validation](validation.md#maintenance-counter-reset) |
| Diagnostics and firmware | Typed shadow data and public firmware catalog | Installed robot and dock software, last robot update, and on-demand catalog status in **Robot software**, with diagnostics and a response-only action | Android and Roomba agreed on the reported versions, update day, and up-to-date status. [Software protocol](api.md#robot-software-status) |
| Device settings panel | The selected robot's linked configuration entities and their confirmed Roomba services | Adjust the robot name, installed voice, volume and lock, and the dock's emptying, washing, solution and drying settings from the card | Uses the same entity checks, units and provider readback as the device pages. [Validation](validation.md#device-settings-on-the-card) |
| Robot help | Public model and regional help catalog and fresh problem codes | Owner’s manual, setup and control guides, separate code lookup, and links for recognized current errors | Spanish manual matched Android, with three diagnostic families available. [Validation](validation.md#robot-help-catalog) |
| First-clean preparation | Android walkthrough and public Max 700 Combo instructions | Four ordered preparation steps under Robot help and in the help action response | [Validation](validation.md#first-clean-preparation) |
| Maps and rooms | `GET /v1/p2maps` and `rid` regions | `vacuum.clean_area` with region names grouped by map | Targeted vacuuming and resume in one room. A second robot started after HA requested two rooms on the same map. |
| Clean a map point | `cap.dSpot`, `cap.oMode`, and `point_clean` with map version and coordinates | Vacuum, mop, do both together, or vacuum then mop at a reviewed map point. The card and action use the robot's advertised modes. | Roomba's timeline recorded the exact point command and operating mode. The Home Assistant mode selector and map guards have automated coverage. [Validation](validation.md#point-cleaning-from-the-floor-plan) |
| Estimated room duration | Signed `POST /v1/time-estimates` | Read action reporting profile estimates in seconds | 13 rooms and 36 combinations per room in isolated HA, and six rooms and 216 combinations in home HA |
| Routine draft duration | Exact per-area matches from the signed room estimate table on the reviewed floor | Estimate the draft's per-area times before saving and show coverage when the total is partial | Seven Android favorites matched exactly. The mixed room and furniture draft returned only the room's time. [Validation](validation.md#routine-draft-estimates) |
| Remembered area preferences | `rooms_metadata` mode defaults and last mode matched to the active archive | Inspect the profiles and pick any compatible settings for a one-off, routine, or schedule draft | Separate temporary routines confirmed the distinct suction and liquid values of both combined variants on a Max 700 Combo. [Validation](validation.md#remembered-area-cleaning-preferences) |
| One-off area cleaning | Reviewed start command with current floor revision and per-area profiles | Open **Customize cleaning** from the map selection, edit destinations and order, and confirm start. The same draft can become a named routine. | Verified from the card through its service boundary and on a Max 700 Combo. [Validation](validation.md#one-off-area-cleaning) |
| Zones and per-room preferences | `zid` regions and per-region profiles in favorites | List and clean regions with individual settings | A saved zone completed vacuuming in Android and a full sequence in Home Assistant. The installed editor also started a new zone before inventory publication. The physical application of every regional setting remains open. [Saved-zone validation](validation.md#immediate-saved-zone-selection-in-0250) |
| Temporary zone | `tid` and a command polygon tied to the active map | Target type in mission history | Vacuuming began and history recorded the exact target. Navigation ended with error 48 and zero area. |
| Schedules | Household read, `rw-schedule`, `rw-settings.timezone`, POST, PUT, and DELETE | Weekly and one-time schedules in the floor plan editor and actions. Order rooms, saved zones, and furniture and change each target's settings. | A native Sunday rule stored a furniture target and a room. Signed writes preserved the mixed order, profiles and timing. A separate scheduled furniture run matched the exact target and cleaned area in the signed archive. [Furniture schedules](validation.md#scheduled-furniture-cleaning) · [One-time dispatch](validation.md#one-time-cleaning-schedules) |
| Saved cleaning routines | Edition 1 favorites with server-assigned IDs, list ranks, ordered regions, furniture polygon links, and saved duration estimates | List, save, move, duplicate, run, and remove supported single-robot routines with per-area settings. Change the order of destinations within a routine and see the saved estimate when available. | Roomba confirmed both list move directions and reordered furniture and room targets with distinct settings. [List order validation](validation.md#saved-routine-display-order) · [Native app validation](validation.md#native-single-area-routines) |
| Routine appearance | Edition 1 favorite `icon` and `color` fields | Choose an emoji and a color when creating, editing, or duplicating a saved routine | Android confirmed one custom appearance. An isolated Home Assistant trial created and updated another, retaining the command and provider metadata. [Validation](validation.md#routine-appearance) |
| Recent and suggested routines | Signed floor-scoped routine list, stable regions, and matching furniture outlines | Load a recent selection or all current rooms, choose a cleaning point, and run a reviewed draft | Android opened a recent furniture destination and the signed response resolved it on the active map. [Quick routine validation](validation.md#recent-and-suggested-routines) |
| Floor plan routine shortcuts | Signed floor-scoped routine list and edition 1 favorites | Open compatible saved, recent, and suggested routines from the floor plan in the one-off draft editor | The signed read returned two compatible favorites and three loadable native options for the same floor. [Validation](validation.md#quick-routines-and-smart-recommendations-on-the-floor-plan) |
| Fixed routine presets | Supported Max 700 Combo, `digiCap.cleaningProfiles` and independently verified per-mode preferences | Apply Light, Normal, or Deep to a single destination or to all selected destinations, with per-area modes and order preserved. | Android displayed all twelve settings combinations. [Native preset validation](validation.md#fixed-routine-presets) |
| Map editing | Map-version writes edit rooms, cleaning zones, keep-out areas, no-mop areas, and linear virtual walls. A settings route saves floor names and orientation. | Rename and rotate floors, divide and merge rooms, and edit room names, cleaning zones, and restrictions. Review known routine and schedule dependencies. [Map and zone editor specification](../specs/009-map-zone-editor.md) | A split room and saved zone were usable before the inventory updated. A Max 700 trial created, moved, and removed a wall with signed confirmation. [Saved-zone validation](validation.md#directed-vacuum-then-mop) · [Virtual wall validation](validation.md#editing-virtual-walls) |
| Local map backups | Signed associated revision and private Home Assistant storage | Save, preview offline, pin, retain, and export original archives. Optional automatic capture before map edits or removal. Restore the name, orientation, and recorded cleaning zones of an active floor. | A Max 700 trial recovered the original archive offline and restored signed settings and cleaning zone outlines. [Backup validation](validation.md#local-map-backups) · [Zone recovery validation](validation.md#recovering-cleaning-zones) |
| Furniture | Whole-layer `adjust_furniture` edits, `furniture` archive, and ordered temporary targets | Show and edit furniture. Select supported objects on the map or from the furniture list, review the order, and clean around them. Inspect zone and furniture results by mission. | Verified edit lifecycle and natural completion of two ordered destinations. [Completion evidence](evidence/2026-11-25-ordered-furniture-completion.json) |
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
