# Roomba Home for Home Assistant

<img src="custom_components/roomba_home/brand/icon.png" alt="Roomba Home" width="96" height="96">

Control modern Roomba robots managed by the **Roomba Home** app. Follow
cleaning missions, pick rooms or saved zones from an interactive floor plan,
and use robot and dock readings in Home Assistant automations. The integration
uses Roomba's own cloud services for device data and control.

## Quick start

The verified model is **Roomba Max 700 Combo (X185240)**, linked to a Roomba Home
account. The latest household test used Home Assistant Core 2026.11.2 and
integration version 0.14.0. [Capability matrix](docs/capabilities.md) ·
[Physical validation](docs/validation.md)

1. Copy `custom_components/roomba_home` from this repository to
   `<config_dir>/custom_components/roomba_home`.
2. Restart Home Assistant. Open **Settings → Devices & services → Add
   integration** and select **Roomba Home**.
3. Enter the account credentials you use in Roomba Home and a two-letter
   country code, such as `ES`. Select the robots you want to manage.
4. Open a robot's device page to find its vacuum, next-cleaning controls,
   sensors, and linked dock. Enable maps in the integration options if you
   want the interactive dashboard.

Keep a backup of the component folder before upgrading. The integration keeps
the existing config entry and entity IDs across upgrades. [Installation and troubleshooting](docs/installation.md)

## Features

- **Robot and dock controls.** Start, pause, resume, cancel, or return to the
  dock. Select vacuuming, mopping, simultaneous cleaning, or sequential
  vacuuming and mopping where available. Supported models expose suction,
  mop wetness, SmartScrub, passes, carpet boost, and manual dock actions.
- **Room and zone cleaning.** Select regions and review the robot and
  destinations before sending a command. The map supports zoom and shows
  keep-out areas, no-mop areas, virtual walls, and the observed route. The integration
  also exposes actions for selecting regions, estimating planned duration,
  and vacuuming a verified point within a room.
- **Mission progress and history.** See the reported phase, mode, surface,
  elapsed time, connectivity timestamp, and recent position. The last
  mission includes outcomes, area values, and pass counts per reported room.
  Fresh timeline replies add the current stage and in-progress room readings.
- **Routines and schedules.** List, create, edit, duplicate, and remove supported
  cleaning routines from the floor plan. Manage weekly schedules with
  independent calendar triggers and review dependencies for selected areas.
  [Saved routine actions](docs/usage.md#saved-cleaning-routines)
- **Maintenance and alerts.** Inspect consumables and automate robot and dock
  problem alerts and mission-finished events.
- **Multiple robots.** Choose the robots to manage in a single account.
  Preferences and entity IDs survive deselection and re-enabling.

Capabilities and entity availability depend on the robot and dock. **Connected**
and the connectivity timestamp reflect the values reported by Roomba. The
optional **Last cloud read** sensor records when Home Assistant read the account.
[Telemetry reference](docs/telemetry.md)

## Floor plan dashboard

![Roomba Home card with an interactive floor plan, live path, region selection, and per-room outcomes](docs/screenshots/roomba-map-live.png)

![Roomba Home card showing the robot and selected areas in the confirmation dialog](docs/screenshots/roomba-map-confirm.png)

![Saved routine editor with cleaning order and per-area settings](docs/screenshots/roomba-routines.png)

Screenshots use a synthetic floor plan and mission.

1. Enable **Show saved floor plans and live room updates** in the integration
   options. This also creates the native floor plan image and live room sensors.
2. Add `/roomba_home/roomba-home-map-card.js?v=0.14.0` as a **JavaScript module**
   in **Settings → Dashboards → Resources**. Enable Advanced Mode in your user
   profile if Resources is hidden. [Home Assistant resource setup](https://contributors.home-assistant.io/frontend/custom-ui/resources/)
3. Add a manual card with your robot's vacuum entity.

```yaml
type: custom:roomba-home-map-card
entity: vacuum.example_robot
```

On upgrade, update the existing module URL to the version shown above and
reload the dashboard. Use one card per robot.

- **Review selection** shows the robot and destinations before cleaning with
  the next-cleaning preferences saved in Home Assistant.
- **Manage routines** opens the saved routines list. Select areas on the map
  before opening it to prefill a new routine. The editor can reorder supported
  targets and change their individual modes and settings.
- **Review map dependencies** shows known saved routines and schedules for
  the selected areas. It flags entries with unresolved destinations.
- **Last mission by room** shows reported area values, pass counts, and
  outcomes. **Current mission measurements** appears when Roomba supplies a
  fresh timeline report.

Use Roomba Home to change room names and boundaries or to save and move zones.
The card displays the room, zone, and restriction information Roomba supplies.
The map editor SDD tracks validation of provider writes. A live mission
percentage and countdown also require provider evidence. [Map and mission details](docs/usage.md#interactive-floor-plan) ·
[Map editor SDD](specs/009-map-zone-editor.md)

## Copyable examples

Replace the example entity IDs with the ones shown on your devices. Use
**Developer tools → Actions** to try a single action. Put the same actions in
a script or automation to reuse them.

### Mop with a saved wetness setting

Add this sequence to a Home Assistant script. Start on an idle robot. A start
request on a paused robot resumes its existing mission.

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

The mode options are `vacuum`, `mop`, `vacuum_mop`, and `vacuum_then_mop`
where supported. [Cleaning modes and preferences](docs/usage.md#choose-a-cleaning-mode-and-preferences)

### Vacuum one room and mop another

Run `roomba_home.list_cleaning_regions` for the vacuum and copy IDs from its
response. Select rooms or saved zones on the same active map in the order you
want to clean them.

```yaml
action: roomba_home.clean_regions
target:
  entity_id: vacuum.example_robot
data:
  regions:
    - id: example_map:rid:entryway
      mode: vacuum
      suction_level: 2
    - id: example_map:rid:kitchen
      mode: mop
      wetness_level: 2
```

You can also assign vacuum regions to Home Assistant areas and use
`vacuum.clean_area`. [Region and dock actions](docs/usage.md#rooms-zones-and-dock)

### Create a weekly schedule in the disabled state

```yaml
action: roomba_home.create_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  name: Weekday kitchen
  weekdays: [1, 3, 5]
  time: "08:30"
  regions:
    - id: example_map:rid:kitchen
      mode: vacuum_then_mop
```

Review the returned schedule ID and weekday/time before using
`roomba_home.set_cleaning_schedule_enabled`. The action uses ISO weekdays,
where Monday is `1`. [Schedules and saved routine examples](docs/usage.md#cleaning-schedules)

### Notify Home Assistant when a mission finishes

```yaml
alias: Roomba mission finished
triggers:
  - trigger: state
    entity_id: event.example_robot_mission_finished
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none and trigger.to_state is not none and
         trigger.from_state.state != trigger.to_state.state and
         trigger.to_state.attributes.get('event_type') == 'mission_finished' }}
actions:
  - action: persistent_notification.create
    data:
      title: Roomba mission finished
      message: >-
        Result: {{ trigger.to_state.attributes.get('outcome') or 'Unknown' }}
mode: queued
```

This event follows Roomba's mission history. It can arrive after the robot has
docked. [Robot and dock problems](docs/telemetry.md#problems-and-events) ·
[Mission finished event](docs/telemetry.md#mission-finished-event)

## Documentation and development

- [Usage, entities, and actions](docs/usage.md)
- [Roomba API reference](docs/api.md)
- [Development and testing](docs/development.md)
- [Specification catalog](specs/CATALOG.md)
- [Release notes](CHANGELOG.md)
- [Privacy and captures](SECURITY.md)

The project follows the architecture of [My Verisure](https://github.com/efraespada/my_verisure)
and the SDD structure from [vypdev/copilot](https://github.com/vypdev/copilot).
Automated tests use synthetic devices and maps. The full adapter suite runs
with Home Assistant's test harness.
