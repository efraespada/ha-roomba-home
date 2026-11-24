# Changelog

## 0.13.0

- Add Home Assistant actions to list, create, rename, update, and remove
  saved Roomba Home routines for an associated robot.
- Confirm changes from a fresh read, use the provider-assigned ID, and reuse
  an exact match when repeating the same creation.

## 0.12.1

- Show Roomba's in-progress room area and pass readings while the current
  mission timeline is fresh. These have their own attributes and card section.

## 0.12.0

- Add the optional interactive floor plan card with zoom, room and saved-zone
  selection, keep-out geometry, the observed route, and explicit confirmation.
- Expose the last recorded mission's room results and pass counts. Preserve
  Roomba's reported area values and match room names by exact map revision.
- Retain more position samples during active missions and expose fresh,
  correlated timeline reports with stage and completed room details.
- Verify map revisions and entity permissions before accepting selections
  from the dashboard. Preserve existing devices, entities, and preferences.

## 0.11.1 — unreleased

- Use bundled Noto Sans for floor plan labels, including accented characters
  and canonically equivalent Unicode spellings.
- Keep labels within room geometry. Shorten long labels and omit labels that
  cannot fit. Leave clearance around the live marker and draw it above the labels.

## 0.11.0 — unreleased

- Select managed robots in the integration options. Home Assistant retains
  device and entity identities and saved preferences when you reselect a robot.
- Report Roomba's own connectivity update timestamp, including when the robot
  reports a disconnection.
- Emit a deduplicated **Mission finished** event using mission history.
- Add opt-in saved floor plan images with observed path and heading, a
  current-room sensor, and the last live position timestamp.
- Use English for repository documentation and integration strings.

## 0.10.0 - destination and result of last mission

- The sensor **Last recorded mission destination** shows the target type and, where
  available with number of regions.
- When you complete a cleanup, check that robot's history to update the result and error
  code. If the mission doesn't come up yet, it's retrying once before returning to its usual
  range.

## 0.9.0 - Exits, carpets and automatic emptying

- The switches **Two passes** and **Carpet boost Default** Reforms the values saved by a
  robot.
- **Area for automatic emptying** allows to tipple the threshold at device of the dock When
  the robot and base are supported by surface adjustment.

## 0.8.0 - preset

- **Suction power** allows to change the level stored in a robot. The check checks the
  confirmation reading and keeps next cleanup preference set at Home Assistant.

## 0.7.0 — vacuuming by point

- The action **Vacuum a map point** leads the robot to a relative position within an inner
  room. Valids the active version and exclusion zones before issuing an order.

- The record distinguishes the order of last cleanup, including that directed at a point on
  his map. The diagnoses reflect the tiptooling capacity that a robot announces.

## 0.6.1 - diagnoses of the dock

- The device of the dock includes its own event entity.
- Each component confirms the resolution of a decision with its own status. Reported
  incompatible components are outside health calculation
- The bug sensors show their code and meaning. Documented mission errors include the mop
  jammed and advertised of the dock.
- Connectivity prioritizes `connectedv2` and preserves earlier boolean as backrest when code
  missing or unknown.

## 0.6.0 - adjustments of mopping of the robot

- Configure entities **Default mop** and **SmartScrub Default** They read and put up with
  the values that have been preserved by a robot. The writing is confirmed with a later
  reading.
- The next cleanup controls preserve their local identifiers and overlays.
- A room's estimate remains associated with its type and identifier. One saved zone with the
  same identifier remains without an estimate until his own reading exists.

## 0.5.0 - high and retirement

- actions to create weekly schedules from an active map with a mode and preferences by
  region, as well how we withdraw the chosen schedule.
- The new schedule remains disabled. Integration confirms release and retirement with a
  later reading. Repeat an identical release returns the existing deactivated schedule.
- The domestic installation preserved all 6 devices and 431 entities. Two identical
  applications for discharge returned the same schedule disabled.

## 0.4.1 - timings and mission origin

- Action to activate or deactivate a weekly schedule while maintaining its start and
  routine. A later reading confirms the change
- Separate sensors for the origin of his mission and its last registered assignment. A
  schedule's physical evidence published `cloud`
- The track record remains `stuck` and the last reported error code at end of mission. It
  was checked with a navigation block
- The domestic installation shown 431 entities and confirmed the activation or deactivation
  of a time schedule with historic error after his return.

## 0.4.0 - weekly cleaning hours

- Home Assistant actions to check weekly editable hours and change their local time, while
  maintaining the robot's command of cleanliness with its activation status.
- The editing relays the schedule associated with his robot before saving and requires later
  confirmation. The issue was checked from the domestic installation with a time-frame
  disabled and its withdrawal tested.

## 0.3.1 - status correction during manual washing

- When the base confirms a manual washing mop and the robot report an inactive soil cycle,
  entity `vacuum` preserves status At the dock.
- The start of a mission remains blocked while that washing is confirmed.
- Reported domestic update with three robots, 3 bases and 425 entities.

## 0.3.0 - local version, 2026-11-23

- Mode select for next cleaning, limited by announced capacity.
- Power, moisture SmartScrub Two passing and carpet boost as local preferences.
- Robot persistency and button to remove overlays without moving the robot.
- Cases of use and independent semantic ports with HA MQTT.
- To start with a paused mission, she requested to resume his existing assignment.
- Confirmation by mode, phase of preparation mop and update adjustments after start.
- Alert and preparations mop and delayed confirmation at the start of his clearance phase.
- Tests of mopping and simultaneous mode at authorized robot with pause, cancellation or
  confirmed base.
- Required cover of complete component: 100% judgements and branches.
- Central capacity discovery and device co-ordination with shared session.
- Reading of active maps and history with separate cadences or private summaries.
- The activity, pause and recharge times have been emptied with statistics by way of the
  last mission. Robot indicator with an active cleaning cycle.
- Local and family programs with counts independent weekly schedules.
- Next weekly start of Roomba Home computed with the robot's time zone.
- Targeted vacuuming and re-establishment directly verified on the robot.
- Standard HA areas, actions with regional adjustments and basic monitoring by capacity.
- Exponential recovery after reading malfunctions. A response MQTT absent preserves the
  other robot's readings and previous mark of an affected device.
- Retirement of orders by robot, concurrent confirmations between robots and shared readings
  that respect the retest period.
- Proof by source diagnosis for jammings, loads and production conditions with documented
  motif to known mission codes.
- Specific checks before vacuum, mop or to operate the base with an observed recovery at all
  ads of a simulated suite.
- Each recognised base brings its buttons and diagnoses together into a child device with an
  indicator of maintenance by consumables. Institutions retain their identities as they
  change groups.
- The areas preserve their association during misreading of maps. A current reading remains
  obligatory before sending a directed cleanup.
- Robot Indicators for Readings of History and Timelines. The diagnoses distinguish the
  empty results of a failed consultation and detect invalid consumer responses.
- Readying only to check the intended duration per room, mode and cleaning settings.
- Updatingand re-startup verified at Home Assistant Green with three robots, 3 bases. 415
  visible entities and icon. Timely cycle of vacuuming pause, cancellation and return
  checked from Home Assistant. The mopping passing from washing mop and resumed after a
  pause.
- The emptying button of the dock confirmed the passing from resting to empty and back at
  rest.
- The recharging retained all 6 devices and 415 entities. Manual washing, manual drying and
  his arrest with the coupled robot were checked.
- A second robot initiated a mission that requested two rooms from Home Assistant.
  Reconfirmed pause, cancellation and return to the dock.
- To complete physical validation of the sequential, zones and options mopping.

## 0.2.0 - local version, 2026-11-23

- Icon Roomba Home for iOS and provided by the incumbent in local NGPs of 256 and 512 demand
  them with transparency.
- Mission, surface and time from start to lock conditions.
- Base information: emptied, filled up and washed.
- Information adjustments, module firmware and statistics.
- Use and remaining quantity per consumable. No disabled conttors have been shown as
  wholesome
- Added problem sensor and source events with detection, change or resolution.
- Maintenance of information between recharges and absence from false data loss solved.
- Active consultation of 15 seconds, rest from 60, slow data every 5 minutes and pieces
  every 30.
- Reactual reading compatible with 103 entities per robot and pending domestic update.
- It keeps the identifiers and controls from its previous version.

## 0.1.0 - local version, 2026-11-23

- Native Access Gigya / iRobot, AWS signature and shared session renewal.
- HTTP and MQTT with an account of several modern robots.
- Vacuuming, pause and cancellation or return verified at an authorized physical cycle.
- HA integration with configuration, robot selection and stable identities.
- Check each 60 seconds and confirm status after orders.
- Vacuum, battery and mission error. Connectivity with robot-censored diagnoses
- SDDs following vypdev / copilot, validated catalogue and documentation with no
  credentials.
- HA Green installation and recharging 2026.11.2: 3 devices with 12 entities.
- Home, pause and cancellation with confirmed return from standard HA controls.

Without remote publication. It includes no resumption, fringes and zones with interactive
maps or persistent stream of events
