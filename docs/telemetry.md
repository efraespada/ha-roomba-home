# Telemetry, progress, and problems

Each robot has a device with its own sensors, binary sensors, and events.
When the robot reports a recognized dock, a child device groups its controls,
maintenance data, and problem events. Existing entity IDs are preserved.

**Last cloud read** records when Home Assistant received a fresh state or
connectivity reply for that robot. It is disabled by default to avoid recording
every poll. **Last Roomba connectivity update** is the provider timestamp for the
attribute that determines the connection state. It uses `connectedv2` when
valid and `connected` as the fallback. It stays readable when Roomba explicitly
reports a disconnection. Missing or invalid metadata leaves the sensor unknown.
Both sensors use Roomba data.

On the map card, open **Device settings** and expand **Connection** to see
these readings together without enabling the **Last cloud read** sensor.
The card shows the reported status and connection code separately, retains
the last available timestamps during a cloud outage, and follows each
diagnostic entity's read permissions. The supported shadow provides cloud
connectivity. The observed fields do not provide Wi-Fi signal level, channel,
or access point identity. [Card usage](usage.md#robot-settings)

## What can be consulted

- Mission activity, phase, cycle, operating mode, origin, area, start time,
  elapsed time, number, and conditions that prevent a start.
- Robot battery, connectivity, installed bins and tanks, detected mop, firmware
  and module versions, and operating, charge, and mission counts.
- Dock emptying, refilling, washing, drying, firmware, capabilities, and error
  codes.
- Reported settings for suction, mop wetness, passes, carpet boost, volume,
  child lock, eco charging, automatic emptying, detergent, washing, drying,
  voice language, and schedule count.
- Consumable usage percentage, quantity remaining, and count used.
- Problem status and a problem event entity with codes by source.
- History counts and the last mission's origin, start, end, active, paused, and
  charging times, recharge and emptying counts, duration, area, and terminal
  error when reported. The terminal error remains available after return to the
  dock and changes with the next recorded mission.
- **Last recorded mission command** identifies regular cleaning, spot cleaning,
  and cleaning a map point. **Last recorded mission destination** distinguishes
  the whole floor, rooms or zones, a map point, and the current position.
  It reports the count of recognized regions in `region_count`.
- Active map, room, and zone counts. **Map data available** reports the success
  of the last read. Known area associations survive a failed read, with counts
  unknown until the next successful read.
- Local and cloud schedule counts and the next active cloud start. Weekly
  and one-time entries use Monday as day 1. The next start requires a
  valid robot time zone and a known occurrence. The cloud schedule count
  publishes weekly times and one-time summaries. A one-time occurrence
  is anchored by its provider creation timestamp.
- Mop presence, dock maintenance, clean water, and consumable alerts. Clean
  water alerts use refill and mop-wash codes.

Missing or invalid fields remain unknown. A valid zero or false is preserved.
Negative remaining quantities are unavailable. The observed catalog disables the
dust bag counter. **Cleaning history available** and **Roomba Home schedules
available** report whether the source was read successfully. A successful empty
response leaves the count at zero. A failed read leaves the count unknown.

## How to interpret progress

The robot reports cleaned area in square feet, converted to m². The elapsed
time includes pauses and the return to the dock. It measures elapsed time since
mission start. **Docked with active cleaning** tracks a `charge` phase with an
open cleaning cycle. The vacuum stays `docked` while polling continues at the
active rate. Physical recharge and resume remains a separate test.
[Max 700 recharge and resume](https://homesupport.irobot.com/articles/en_US/Knowledge/70501)

The most recent historical result includes `mode_statistics`, duration and
area by mode, and whether the run began at the dock. Total duration, active
duration, and per-mode readings measure different intervals.

Enable **Show saved floor plans and live room updates** in the integration
options to add a native image for each active, visible saved map. For a robot
with one such map, the image can show the observed mission path and heading.
**Current room** requires a current position that falls strictly inside exactly
one labeled room. **Last live position update** is the timestamp supplied by
Roomba. **Last live route activity** reports the latest recognized activity
along the route, with states `traveling`, `vacuuming`, `mopping`, and
`vacuum_mop`. A different configured cleaning mode can remain selected
while the robot travels to or from an area. **On mapped carpet** compares
the latest position to Roomba's saved carpet polygons on that floor.
It is unknown without a classified carpet layer or a position on the
matched floor. This reading describes location relative to the saved
map. The **Carpet boost** setting reports the configured preference.
The live sensors and position
marker expire at the provider deadline. An active mission's earlier route
can remain until the mission ends. The image leaves gaps in the drawing
when consecutive positions are unavailable. Home Assistant can record room
names and route activity when this feature is enabled. Floor geometry and
positions are omitted from diagnostics.
The continuous position subscription updates the room, route activity, and
position timestamp independently of state polling. The floor card animates
between adjacent reported positions and leaves the route open at a missing
sample. With reduced motion enabled, the marker updates directly.
Its **Estimated coverage** layer accumulates vacuum and mop footprints for
the current mission and clips the display to the floor's rooms. Coverage
uses Roomba's reported activity and retains gaps where a path is unavailable.
The **Mission area** sensor continues to expose Roomba's reported area.
Floor plan labels use bundled Noto Sans. The image can shorten labels to fit
within a room or omit them when no placement fits. The current-room sensor
keeps the full name reported by Roomba.

**Last mission rooms** counts rooms with a recorded outcome or measurement.
Its `rooms` attribute includes the provider outcome and code, pass count,
and reported area and total area. A later room result supersedes an earlier
one for the same room and revision. Labels appear only with map opt-in and an
exact match in the current associated map inventory. Room area values retain
their provider units, which have yet to be verified.

**Last live timeline update** appears after a matched active-mission reply.
The `stage_started_at` attribute contains the reported UTC start of the
recognized current stage when that timestamp falls inside the mission.
Its `stage`, `rooms`, and `active_rooms` attributes expose the recognized
stage, final room results, and in-progress room measurements. The
`zones` and `active_zones` attributes preserve the equivalent zone and
furniture measurements. The **Zones and furniture in the last mission**
sensor exposes completed-mission results separately as `zones`.
`active_zones` includes `current_pass_number` for an open saved-zone event
matched to the current stage. This number starts at one. `pass_count`
preserves the reported index.
For a signed saved-zone destination, `target_area_m2` reports Roomba's
target size. `completed_passes_area_m2` sums the area measured in confirmed
passes. Both are optional and use square metres. The raw fields `area`
and `total_area` remain available in each reported result.
Labels depend on map opt-in and the availability of the relevant revision.
The integration requests a timeline at most once per 45 seconds for a mission
and treats it as stale after 100 seconds. The timestamp, stage, and results
clear on a mission change or after expiry. Bounded position polling still
provides updates if the continuous subscription is unavailable.

**Completed destinations in the current mission** counts the destinations
with a finished outcome in the same active timeline. Its `total`,
`ordered`, and `destinations` attributes describe the provider's
declared targets and their statuses, with names and requested cleaning
modes when available. A destination can also include `requested_settings`
from its command and `reported_pass_count` from its timeline event. The
verified current saved-zone destination includes `current_pass_number`.
Omitted command preferences use the robot's defaults. Unfinished, skipped,
and revisited destinations
keep a separate status. Whole-floor and point runs have their own views.
The count becomes unknown after the mission ends or the report expires.

**Estimated cleaning time remaining** combines the provider's planned
duration for each directed room with the live mission stage and its time.
The state is in seconds. The `estimated_duration_seconds` attribute is
available for a complete plan. Remaining time is approximate and may
differ from Roomba Home's displayed value. The card updates the countdown
between robot polls from the verified stage timestamp. The estimate becomes
unknown on an interrupted stage or when an unfinished destination lacks a
duration. Global coverage and percentage still require verification.
[View estimates](usage.md#rooms-zones-and-dock) ·
[Live map evidence](evidence/2026-11-24-live-progress.json)

The normal poll interval is 15 seconds during cleaning, pausing, returning,
emptying, refilling, washing, or drying, and 60 seconds at rest. Settings,
software, statistics, and schedules refresh every five minutes. Consumables,
the parts catalog, and history refresh every 30 minutes. Maps refresh every
15 minutes and before area actions. Mission confirmation checks run every five
seconds. Mission history is also checked at a detected finish, with one retry
when the record has not yet appeared. The integration respects provider rate
limits.

## Problems and events

The **Problem** binary sensor includes connectivity, mission errors, start
blockers, dock errors, and maintenance alerts. Known dock update phases are
classified separately. A problem clears when its source reports a normal state.

The **Device problems** entity emits:

| event_type | When |
| --- | --- |
| `problem_detected` | The first time an active code appears |
| `problem_changed` | The same source goes to another active code |
| `problem_cleared` | That origin explicitly indicates a normal state |

His attributes are `source`, `code`, `previous_code`, `reason` and the baseline
`problem_codes`. To repeat the same code doesn't generate another event. The base line
remains with recharges so as to avoid re-announcing errors that have been activated.
Simultaneous changes from different backgrounds generate separate events.

On the tab **Base** Section 3 **challenges of the dock** emits the faults of emptying,
filling up and washing them with their common code or maintenance. The entity **Device
problems** of the robot retains its complete set. In an automation only for the base, use
your entity. Each component resolves its alert with a status of their own table.

Each alert identifies the origin. The equipment has independent sensors for mission error,
jamming and loading problem. The error sensor keeps its numerical value and adds an
attribute `meaning` for the active code.

| Origin | Information and effect on orders |
| --- | --- |
| `connection` | The remote robot keeps previous warnings and prevents sending orders. |
| `mission` | Codes such as clicked brush or wheel, navigation and battery with a map mop while an error prevents them from starting to re-cleanup. |
| `firmware` | The SDK identifies installation malfunctions, WiFi and packages at `rw-software.deploymentState`. The sensor indicates the phase of downloading and installation. The orders check the current readiness and misconduct. |
| `readiness`, `readiness_conditions` | The production code and list `condNotReady` can block the start. |
| `stuck`, `charging_problem` | The phases of the SDK indicate shortcut or load failure, even with no mission code. |
| `bin_missing`, `bin_full` | The explicit absence blocks vacuum and emptying. The full sign generates a alert The robot's status of preparation determines if it can start. |
| `dock` | Common errors such as communications, drains or overloaded tray. A common malfunction or an currently occurring update block the mopping and start of manual operations of the dock. |
| `refill`, `pad_wash` | Insufficient water, absent tanks or tracks-- pump and actuator. If the water system indicates a malfunction, start or resume with mopping are blocked. |
| `evacuation`, `pad_dry` | Absence or full bag, obstruction and drying engine with other malfunctions per component. A separate defect prevents them from starting that operation |
| `part_<part code>` | The counter points to maintenance. Robot production and active malfunctions govern the start of a mission |

To `readiness_conditions`, `code` and `previous_code` count the active conditions. The code of origin are at `condition_codes` and `previous_condition_codes`. Any change of the set generates alert, even if it remains as big. For jamming, loading and storage the value `1` indicates that a sign is activated. Unknown numeric codes are preserved for diagnosis. The table of iRobot helps to identify causes and check components. [Roomba Max's official error table 700](https://homesupport.irobot.com/articles/en_US/Knowledge/10502)

If the robot reports code 1026 as an error of mission, the attribute `meaning` indicates `mop_stuck`. If the mission reports a code from its table of the dock, as 451 or 670, keeps his source `mission` with documented meaning. [Code 1026 at Max 700](https://homesupport.irobot.com/articles/en_US/Knowledge/10527) · [Max firmware notes 700](https://homesupport.irobot.com/articles/en_US/Knowledge/70550)

Connectivity uses states 0 and 1 of `rw-constatus.connectedv2` as defined by the SDK. If
that data lacks or brings an unknown value, use the boolean `connected` while present. A
reading malfunction keeps the above warnings.

The child blockade is shown as an adjustment. iRobot confirms that it applies to the physical buttons and allows you continue using app controls. [Children's and pets' blockade](https://homesupport.irobot.com/articles/en_US/Knowledge/64000)

Consultation may omit short mistakes between two readings. A clear or optional malfunction
does not remove the base line from an earlier problem. If the source of consumables remains
missing, an added sensor does not declare that everything is healthy. No physical
malfunctions have been caused: error transitions are tested with synthetic data at the
official HA Harness.

No warnings are sent to mobile phones, mail or other services automatically. The following
optional automation shows and removes warnings **Local** in HA. Replace the generic entity
with an event of your robots:

```yaml
alias: Local Roomba problem alerts
triggers:
  - trigger: state
    entity_id: event.example_robot_device_problems
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state is not none
         and trigger.to_state.state not in ['unknown', 'unavailable']
         and (trigger.from_state is none
              or trigger.from_state.state != trigger.to_state.state)
         and trigger.to_state.attributes.get('event_type') in
             ['problem_detected', 'problem_changed', 'problem_cleared'] }}
actions:
  - variables:
      notice_id: >-
        roomba_{{ trigger.entity_id }}_{{ trigger.to_state.attributes.source }}
  - choose:
      - conditions: >-
          {{ trigger.to_state.attributes.event_type == 'problem_cleared' }}
        sequence:
          - action: persistent_notification.dismiss
            data:
              notification_id: "{{ notice_id }}"
    default:
      - action: persistent_notification.create
        data:
          notification_id: "{{ notice_id }}"
          title: "Roomba problem detected"
          message: >-
            {{ trigger.to_state.attributes.friendly_name }}:
            {{ trigger.to_state.attributes.source }},
            {% if trigger.to_state.attributes.source == 'readiness_conditions' %}
              codes {{ trigger.to_state.attributes.condition_codes | join(', ') }}
            {% else %}
              code {{ trigger.to_state.attributes.code }}
            {% endif %}
            ({{ trigger.to_state.attributes.reason }}).
mode: queued
max: 20
```

The example follows the pattern of [HA event entities](https://contributors.home-assistant.io/core/entities/event/). Do not erase robot errors or reset teller. Check the source and app before maintenance; a reinitiation of an attester does not fix malfunction.

### Mission finished event

The **Mission finished** event entity emits `mission_finished` when a newer
result with a recognized outcome appears in Roomba mission history. It includes
`outcome`, `cleaning_modes`, `area_m2`, `duration_minutes`, and `error_code`
when reported. The first successful history read establishes a baseline.
Repeating a result or reloading the integration does not repeat an event.
A failed read or an unpublished result leaves the cursor unchanged.

## Validated model consumables

**Usage percentage** measures consumption. The remaining quantity uses the
counter's own unit. The `category` attribute distinguishes maintenance and
replacement. The following are catalog part codes shared by the validated model.
The model catalog supplies optional `part_sku`, `replacement_url`, and
`maintenance_guide_url` attributes for these sensors. **Maintenance** on
the card includes the dust bag reference even when its usage counter is
disabled. [Maintenance and replacement parts](usage.md#maintenance-and-replacement-parts)

| Part | Code | Used / remaining unit |
|---|---|---|
| Side brush | `67` | min |
| Main brushes | `71` | min |
| Filter | `72` | min |
| Dust bag | `147` | emptying cycles |
| Mop roller | `148` | combined missions |
| Dock washing system | `202` | wash cycles |
| Mop washing system | `212` | m² |

## Field inventory

A field is exposed once the robot provides evidence for it. Boolean fields use
binary sensors. Code and level sensors retain the provider's scale. The
`nMssnC` and `nMssnF` counters retain their provider names.

| Entity | Type or Unit | Source |
| --- | --- | --- |
| Mission phase | Informed Value | `ro-currentstate` → `cleanMissionStatus.phase` |
| Mission cycle | Informed Value | `ro-currentstate` → `cleanMissionStatus.cycle` |
| Cleanup Mode (code) | Informed Value | `ro-currentstate` → `cleanMissionStatus.operatingMode` |
| Mission area | m² | `ro-currentstate` → `cleanMissionStatus.sqft` |
| Last start of mission | UTC date | `ro-currentstate` → `cleanMissionStatus.mssnStrtTm` |
| Mission number | Informed Value | `ro-currentstate` → `cleanMissionStatus.nMssn` |
| Start block (code) | Informed Value | `ro-currentstate` → `cleanMissionStatus.notReady` |
| Dust tank installed | bool | `ro-currentstate` → `bin.present` |
| Full powder tank | bool | `ro-currentstate` → `bin.full` |
| Water tank installed | bool | `ro-currentstate` → `tankPresent` |
| Mop detected | Informed Value | `ro-currentstate` → `detectedPad` |
| Dock recognized | bool | `ro-currentstate` → `dock.known` |
| Base error | Informed Value | `ro-currentstate` → `dock.error` |
| Filling status (code) | Informed Value | `ro-currentstate` → `dock.state` |
| Filling status (code) | Informed Value | `ro-currentstate` → `dock.frState` |
| washing status of mop | Informed Value | `ro-currentstate` → `dock.pwState` |
| Drying status of mop | Informed Value | `ro-currentstate` → `dock.pdState` |
| Base firmware | Informed Value | `ro-currentstate` → `dock.fwVer` |
| Base Deposit Level (code) | Informed Value | `ro-currentstate` → `dock.tankLvl` |
| Operation: hours | h | `ro-currentstate` → `runtimeStats.hr` |
| Operation: minutes | min | `ro-currentstate` → `runtimeStats.min` |
| Connection (code) | Informed Value | `rw-constatus` → `connectedv2` |
| Robot's firmware | Informed Value | `rw-software` → `softwareVer` |
| Robot firmware last updated | Timestamp | `rw-software` → `lastSwUpdate` in UTC |
| Driver's firmware | Informed Value | `rw-software` → `subModSwVer.con` |
| MCU's firmware | Informed Value | `rw-software` → `subModSwVer.mcu` |
| Navigation firmware | Informed Value | `rw-software` → `subModSwVer.nav` |
| Updating (code) | Informed Value | `rw-software` → `deploymentState` |
| Cumulative load errors | Informed Value | `ro-stats` → `bbchg.nChgErr` |
| Acumulated correct charges | Informed Value | `ro-stats` → `bbchg.nChgOk` |
| Cumulated hours at base | h | `ro-stats` → `bbchg3.hOnDock` |
| Cumulated missions | Informed Value | `ro-stats` → `bbmssn.nMssn` |
| Contingency of missions nMssnC | Informed Value | `ro-stats` → `bbmssn.nMssnC` |
| Contingency of missions nMssnF | Informed Value | `ro-stats` → `bbmssn.nMssnF` |
| Accrued proper missions | Informed Value | `ro-stats` → `bbmssn.nMssnOk` |
| Retirement of navigation | Informed Value | `ro-stats` → `bbrstinfo.nNavRst` |
| System: hours | h | `ro-stats` → `bbsys.hr` |
| System: minutes | min | `ro-stats` → `bbsys.min` |
| Configure volume | Informed Value | `rw-settings` → `audio.volume` |
| Automatic evacuation frequency code | 0 after each routine, or threshold in m² for the verified Max 700 Combo scheme | `rw-settings` → `autoevacFreq` |
| Carpet boost | bool | `rw-settings` → `carpetBoost` |
| Children's registration | bool | `rw-settings` → `childLock` |
| Green Loading | bool | `rw-settings` → `ecoCharge` |
| Expand allowed | bool | `rw-settings` → `evacAllowed` |
| Mapping allowed | bool | `rw-settings` → `mapUploadAllowed` |
| Automatic passes disabled | bool | `rw-settings` → `noAutoPasses` |
| Obstacle prevention (code) | Informed Value | `rw-settings` → `odoaMode` |
| Retirement mop | bool | `rw-settings` → `padDryAllowed` |
| Retirement duration (code) | Informed Value | `rw-settings` → `padDryDur` |
| mop permitted washing | bool | `rw-settings` → `padWashAllowed` |
| mop | Informed Value | `rw-settings` → `padWetness.padPlate` |
| Surface washing interval (code) | Informed Value | `rw-settings` → `pwAreaInterval` |
| Wash temperature (code) | Informed Value | `rw-settings` → `pwHeat` |
| Retirement for washing (code) | Informed Value | `rw-settings` → `pwReturn` |
| Time-washing interval (code) | Informed Value | `rw-settings` → `pwTimeInterval` |
| Failed schedule | bool | `rw-settings` → `schedHold` |
| Suction power | Informed Value | `rw-settings` → `suctionLevel` |
| Mopping Intensive | Informed Value | `rw-settings` → `swScrub` |
| Two passes | bool | `rw-settings` → `twoPass` |
| Detergent (code) | Informed Value | `rw-settings` → `detergent` |
| Voice language | Informed Value | `rw-settings` → `langs2.sLang` |
| Filling capacity (code) | Informed Value | `ro-currentstate` → `dock.cap.evac` |
| Filling capacity (code) | Informed Value | `ro-currentstate` → `dock.cap.fr` |
| Drying capacity (code) | Informed Value | `ro-currentstate` → `dock.cap.pd` |
| Wash capacity (code) | Informed Value | `ro-currentstate` → `dock.cap.pw` |
| pwo (code) base capacity | Informed Value | `ro-currentstate` → `dock.cap.pwo` |
| Detergent capacity (code) | Informed Value | `ro-currentstate` → `dock.cap.detergent` |

The number of programs, the quantity and their code's blocking conditions have been added.
Mapping, credentials and private identifiers are omitted from them. Transport malfunctions
are distinguished from physical problems.
