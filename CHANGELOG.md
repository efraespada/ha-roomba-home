# Changelog

## 0.104.4

- Retain the time reported for earlier visits to a directed room when the
  robot leaves and re-enters it. Include those visits in the card and
  remaining-time sensor, including across a confirmed pause.

## 0.104.3

- Show **Charging during mission** on the robot status and current
  mission when Roomba reports charging with a cleaning cycle still open.

## 0.104.2

- Refresh the mission timeline on the next active poll after Roomba
  confirms a pause or resume and the latest timeline is still behind.
  Mark the affected destination as waiting for a Roomba update.

## 0.104.1

- Carry verified room cleaning time across a pause and resume when Roomba
  replaces its live stage without repeating the earlier room interval.

## 0.104.0

- Keep the remaining-time estimate visible and stable when Roomba confirms
  a pause in a directed room cleaning. Resume the countdown from the
  reported cleaning time after the robot starts cleaning again.

## 0.103.1

- Store weekly schedule days in the same format used by Home Assistant's
  JSON read-back so a successful map backup is confirmed on the card.

## 0.103.0

- Save room-only routines and schedules in local map backups along with
  programs that use zones and furniture. Recreate a saved program on a
  current floor by assigning each old area to a new destination. Review its
  cleaning order, profiles, and schedule timing before saving. New schedules
  start disabled.

## 0.102.0

- Review the routines and schedules that Roomba links to a saved floor
  before removing or replacing it. The card shows each schedule's enabled
  state and identifies any source it could not check.

## 0.101.0

- Replace a saved floor from its removal review. Home Assistant checks
  that the robot can map, verifies removal, and starts the new mapping run.
  The card reports an unconfirmed mapping start separately from removal.

## 0.100.0

- See parts due for service on the robot's dashboard card and open
  **Maintenance** directly from each reminder. The reminders come from
  Roomba's reported usage and remaining counts.

## 0.99.0

- See each floor's recorded map creation and revision dates and open its
  most recent report with positive cleaning area. The matching floor image
  exposes the same timestamp readings to Home Assistant automations.

## 0.98.0

- Show or hide recorded furniture and temporary obstacles independently in
  **Cleaning history**. The 2D and 3D map views, route layers, and legend
  reflect the selected visibility without changing the archived floor.

## 0.97.0

- Open **Connection** in **Device settings** to inspect Roomba's reported
  connection, its last provider update, the last cloud read, and the
  connection code. The panel distinguishes a robot disconnection from
  unavailable cloud data and links iRobot's Wi-Fi reconnection guide.

## 0.96.0

- Review and run **Locate robot** and **Reboot robot** from **Device
  settings**. The card checks the selected robot and action again before
  invoking the existing Home Assistant service. Locate reports submission.
  Reboot waits for a disconnect and reconnection.

## 0.95.0

- Browse and install additional Roomba voices from **Device settings**.
  Review the selection and any voice it will replace. The card checks the
  reviewed inventory before installation and refreshes the installed
  voice selector after Roomba confirms the change.

## 0.94.0

- Open **Device settings** on the card to edit the robot's name, installed
  voice, voice volume, and child and pet lock, as well as the dock's
  emptying, washing, solution, and drying settings. The card uses the
  existing Home Assistant entities and rereads each confirmed change.

## 0.93.0

- Open **Robot software** on the card to see the installed robot and dock
  versions, the last robot update, and the current Roomba catalog status.
  The installed versions remain visible if the catalog is unavailable.

## 0.92.0

- Show the reported part usage as a bar and the remaining time as whole
  hours in **Maintenance**. Expand the card's part descriptions for care
  tips and open the matching iRobot guides.

## 0.91.0

- Review and reset a supported part counter directly in **Maintenance**.
  The card calls the existing Home Assistant action and refreshes the
  displayed counter after Roomba reports the result.

## 0.90.0

- Show the robot activation date from Roomba's signed asset response in
  each robot's diagnostics. The existing asset lookup also supplies the
  serial number, so both values use the same refresh.

## 0.89.0

- Keep the robot's battery, activity, errors, and compatible controls
  visible when a floor plan is unavailable or maps are disabled. The card
  uses the same Roomba account state and permission checks in both views.

## 0.88.0

- Open **Dock controls** on the floor plan card to wash the mop and tray,
  dry the mop, stop drying, empty the bin, or manually refill on supported
  docks. The panel shows active operations and reviews the selected action
  before pressing the existing Home Assistant button.

## 0.87.1

- Keep a Max 700 Combo return pending after Roomba reports final travel for
  the same mission. A sustained return can finish through a later pad wash
  while the robot remains available for commands such as cancellation.

## 0.87.0

- Renew the Roomba live-map announcement during opt-in active missions.
  The integration can request the position feed itself while keeping
  its subscribed topic scoped to the current robot and mission.

## 0.86.1

- Keep **Return to dock** pending when Roomba reports a new automatic
  mop wash for the same mission. Confirm after charging with the mission
  ended. Wait up to five minutes from the first wash observation.

## 0.81.0

- Choose a ten- or thirty-day period in **Cleaning history**. Either
  period can include short canceled runs and open their original report
  maps, routes, and coverage when available.

## 0.80.0

- Include short canceled runs on demand in **Cleaning history** and open
  their original reports, maps, and recorded coverage when available.

## 0.79.0

- Pause, resume, cancel, and return the current mission from the floor plan.
  The card confirms cancellation and return, and each command is bound to
  the mission shown when it was selected.

## 0.78.0

- Show the current mission's reported phase, mode, elapsed time, and
  cleaned area above the floor plan, including runs without a destination plan.

## 0.77.0

- Open saved, recent, and recommended cleaning drafts from **Quick routines**
  above the floor plan. Keep each area's settings and order for review.
- Show **Recommended rooms** above the floor plan. Opening Roomba's
  recommendation highlights its exact rooms in amber, even when selected.

## 0.76.0

- Select or deselect all rooms on the floor plan and in cleaning drafts.
  Keep selected zones, furniture, and individual cleaning settings.
- Pick supported furniture on the map or from the furniture list. Review
  the ordered selection to start cleaning or customize each destination.

## 0.75.0

- Highlight Roomba's recommended rooms in the floor plan. Load the same
  suggestion as a draft with its per-room profiles and automatic order.

## 0.74.0

- Schedule cleaning around mapped furniture and mix furniture, rooms, and
  saved cleaning zones in one ordered schedule. Copy compatible furniture
  routines into schedules and include their links in map backup previews.
- Read Sunday schedules written by Roomba Home and use the native Sunday
  value for new schedules. Home Assistant actions continue to use ISO
  weekdays.

## 0.73.0

- List saved routines in Roomba's display order. Move a routine earlier or
  later from the floor plan card or the new reorder action. Verify the
  updated order and preserve the saved cleaning destinations and settings.

## 0.72.2

- Show the current saved-zone pass in the live plan and area results as
  Pass 1, Pass 2, and so on. Keep the provider's index and confirmed
  completed pass count available separately.

## 0.72.1

- Keep an explicit live mission timeline request open through the MQTT
  deadline, even after state and position replies have arrived. Preserve
  the state replies when the timeline is unavailable.

## 0.72.0

- Show the reported target size and area cleaned across confirmed passes
  separately for saved zones. The card and Home Assistant attributes report
  both measurements in square metres and retain the original provider fields.

## 0.71.2

- Keep confirming a sent command when a successful refresh temporarily
  omits the robot's connection state. Use the existing deadline and send
  the command only once.

## 0.71.1

- Distinguish the recorded bin emptying count from the dock stage in
  cleaning history. Roomba can report a stage with zero counted emptyings.

## 0.71.0

- Show the recorded finish and preserve robot errors and dock operation
  codes in the archived cleaning timeline.

## 0.70.0

- Open a four-step first-clean checklist for the Roomba Max 700 Combo
  under **Robot help**. The card and the read-only help action include
  the same instructions and link to the iRobot unboxing guide.

## 0.69.1

- Keep Robot help visible with the selected article when Home Assistant
  moves its card to another dashboard container.

## 0.69.0

- Open the owner’s manual and setup guides from Robot help. Browse
  Roomba's separate error, charging error, and start-refusal catalogs.
- Link confirmed current robot and dock codes to their support articles.
  Automations can read the same catalog with `roomba_home.get_robot_help`.

## 0.68.0

- Choose automatic dock emptying after each routine, every 25 m², or
  every 50 m². The existing area control also supports custom thresholds,
  including when per-routine emptying is selected.

## 0.67.0

- Show each destination's accumulated cleaning time across passes and
  resumes. Keep the timer steady during pauses and include the recorded
  total in mission history.
- Show when the robot's latest position falls on a carpet recorded in
  the active floor plan. Expose the same reading as a binary sensor.
- Return the robot to its dock if a short cleaning mission ends while
  the return action waits for a pause.

## 0.66.0

- Refresh the map's countdown between robot polls using the latest verified
  room stage and the saved time estimate.
- Show elapsed time for the current destination's cleaning stage when
  Roomba reports a matching start time.
- Count confirmed saved-zone passes from the robot's completion events and
  preserve the original pass value in the API.

## 0.65.0

- Customize saved routines with an emoji and a color. Editing appearance
  preserves the cleaning plan, estimate, and display order.
- Choose any compatible remembered cleaning profile by area, including
  either of the combined vacuum-and-mop variants Roomba has reported.
- Open one-off cleaning preferences from the map selection. Set the order
  and profile for each area, then start cleaning or save the draft as a
  named routine.

## 0.64.0

- Inspect Roomba's remembered cleaning settings by area and reuse them in
  routine or schedule drafts.
- Show iRobot part references, shop links, and care guides alongside robot
  and dock consumable readings.
- Pan 3D floor plans and recorded maps with touch, mouse, or arrow keys.
  Pinch to zoom the map on touch screens.

## 0.63.0

- Pause an active Max 700 Combo cleaning before returning to the dock.
  Home Assistant confirms arrival.
- Add a confirmed **Clean everywhere** action to start an untargeted
  cleaning mission using the next-cleaning preferences.
- Copy a supported routine selection into a new disabled schedule, keeping
  its destination order and individual settings.
- Show the original destination sequence, requested per-area settings, and
  final destination outcomes in recorded cleaning reports.
- Show each live destination's requested cleaning settings and the robot's
  reported pass count in the floor plan and destination sensor.
- Show saved cleaning zones and restrictions from each mission's archived
  floor revision. Toggle travel, cleaning paths, and coverage independently.
- Create, move, and remove virtual walls from the floor plan card. Set their
  two endpoints on the map or with the keyboard.
- Recover a saved room name and type on the same active room after reviewing
  the before and after values. The review identifies removed rooms and
  changed room boundaries.
- Confirm map edits that return a revision acknowledgement by reading the
  corresponding active archive. Keep the edit to one provider write.
- Recover moved or deleted keep-out zones, no-mop zones, and virtual walls
  from a local floor backup after reviewing the changes. Keep restrictions
  added after the backup.
- Preserve distinct virtual wall endpoints when saving the restriction layer.
- Recover saved furniture placements and sources from a floor backup. The
  review shows affected routines and keeps furniture added after the backup.
- Recover missing furniture destinations in surviving routines after the
  backed-up objects return. Preserve the routine's order and area settings.
- Accept the small heading rounding Roomba returns for unchanged furniture
  outlines so a completed map edit is confirmed correctly.

## 0.62.0

- Include compatible routine and schedule destinations in local map backups.
  After restoring a cleaning zone, review the affected program and recover
  its destinations, order, and per-area settings while keeping its current
  name, timing, and enabled state.
- Publish the integration as a versioned GitHub release for HACS. This
  release includes the map editor, schedules, live route and coverage, and
  backup features introduced since 0.14.0.

## 0.61.0

- Recover moved or removed cleaning zones from a backup of the same floor.
  Review each change and currently linked routines and schedules before
  confirming one map update using the original zone identifiers.

## 0.60.0

- Review and restore the backed-up name and orientation of an active floor.
  Home Assistant verifies the current floor settings and sends one update
  with the reviewed changes.

## 0.59.0

- Save, preview, pin, and export local floor backups per Roomba. Backups keep
  the native archive, floor settings, revision, and destination inventory.
- Configure retention and opt in to automatic backups before saving map
  edits or removing a floor. Open existing backups while Roomba is offline.

## 0.58.0

- Manage weekly and one-time Roomba schedules from the floor plan card.
  Create, duplicate, enable, disable, and remove schedules, and edit the name,
  timing, destination order, and recognized per-area cleaning preferences.
- Preserve the existing start and enabled state when only the cleaning
  preferences change. Revalidate the selected floor and areas before saving.

## 0.57.0

- Animate consecutive live positions across reported intervals of up to six
  seconds. Continue from the visible position when a new report arrives
  during an animation and preserve unobserved gaps.
- Preserve per-area settings from verified native multi-area favorites.
  Choose a listed or automatic cleaning order for rooms and saved zones.

## 0.56.0

- Apply Roomba's Smart recommendations to individual rooms or all eligible
  rooms in an ordered routine draft, keeping each area's selected mode.

## 0.55.0

- Follow the active floor for robots with multiple saved maps after
  Roomba identifies the current floor. Keep a manually selected floor
  or reviewed edit in view.

## 0.54.0

- Show the serial number reported by Roomba in the robot's Home Assistant
  device details.

## 0.53.0

- Show Roomba's temporary obstacle detections on the live floor plan with
  an independent visibility toggle.
- Recover earlier coverage from the declared portion of a live map when
  Roomba appends extra route records.
- Animate the marker through all consecutive positions in a batch.
  Keep movement animation running through coverage and obstacle updates.

## 0.52.0

- Shade estimated vacuum and mop coverage on the live floor plan, with
  separate filters for each cleaning mode.
- Toggle cleaning and travel paths independently.
- Accumulate earlier passes for the current mission and recover coverage
  from raw snapshots aligned to the observed route.

## 0.51.0

- Keep an independent Roomba position subscription open during active
  missions and send position and route changes directly to the floor card.
- Preserve valid positions across small clock differences with Roomba.
- Animate the marker between adjacent reported positions and preserve gaps
  in the available path.

## 0.50.0

- Show estimated cleaning time remaining for directed missions with verified
  room estimates and matching live stages.
- Confirm live room outcomes against the requested floor when Roomba sends
  the robot's internal map revision in the same mission.

## 0.49.0

- Show the current mission's declared destinations, order, requested cleaning
  modes, and observed outcomes in the map card.
- Expose the number of destinations Roomba has finished as a Home Assistant
  sensor with the full destination list in its attributes.

## 0.48.0

- Browse Roomba's recent and suggested routines for the active floor.
- Load supported selections into an editable draft or open the point picker.
- Start a reviewed draft with its own per-area settings and order.

## 0.47.0

- Estimate a routine before saving or starting it. Show the planned duration
  for each area and identify incomplete estimates.
- Verify the current floor revision before and after an estimate request.

## 0.46.0

- Apply the verified Max 700 Combo Light, Normal, and Deep presets to one
  area or all selected areas while preserving their modes and order.
- Read Android-created sequential routines that omit the edit marker.

## 0.45.0

- Edit, duplicate, and run supported single-area routines originally saved in
  Roomba Home, including the app's timestamped command format.
- Show Roomba's saved routine duration estimate and its confidence in the
  floor plan editor and the list action.

## 0.44.0

- Read Roomba's room cleaning scores, recorded mission times, traffic
  classification, and suggested cleaning settings for the active floor.
- Open the scores from the floor plan card or read them through the
  Home Assistant action.

## 0.43.0

- Create, reschedule, enable, disable, and remove one-time cleanings in
  Roomba Home. Keep the selected destinations and per-area preferences.
- Include one-time entries in the next-cloud-start calculation when
  Roomba's timestamps establish their upcoming occurrence.

## 0.42.0

- Distinguish mopping and simultaneous vacuuming and mopping in live
  route segments. Use the same activity colors in the card and floor image.
- Expose the last fresh route activity as a sensor on the robot device
  when saved floor plans are enabled.
- Include the provider's stage start timestamp in the live timeline sensor.

## 0.41.0

- Recover earlier parts of the live route from a Roomba map snapshot when
  its positions match the current mission. The live stream still drives the
  robot marker and current room.

## 0.40.0

- Color the live route by reported travel and vacuuming activity. The map
  keeps gaps between missing samples and shows a legend for the visible route.

## 0.39.0

- Browse recent cleaning reports with their recorded metrics and timeline.
- Show the original mission map in 2D or 3D, with coverage and route segments
  by cleaning mode. Keep measurements available when the archive is missing.

## 0.38.0

- Show the reported firmware installation time and check Roomba's public
  catalog for the installed robot and dock software.
- Document the feasibility and roadmap for local map snapshots and recovery.

## 0.37.0

- Start and monitor mapping runs. Review and remove a saved floor from the card.
- Load newly mapped floors while Roomba is still publishing their room inventory.

## 0.36.0

- Allow a manual mop wash to interrupt drying on the Max 700 Combo dock.

## 0.35.0

- Reset supported maintenance counters after the operator confirms the work.

## 0.34.0

- Install downloadable robot voices and confirm the result from Roomba.

## 0.33.0

- Reboot a robot with connection-cycle confirmation and list catalog voices.

## 0.32.0

- Rename the robot and select an installed voice.

## 0.31.0

- Use all four supported point-cleaning modes and display the active target.

## 0.30.0

- Mark a spot to vacuum on the floor plan or enter its room-relative
  position with the keyboard. Confirm the marked point before sending the
  command. Home Assistant checks the reviewed map revision and room inventory.

## 0.29.0

- Configure automatic mop washing on a compatible dock. The dock device
  exposes water temperature, wash frequency, automatic cleaning solution,
  and drying duration. Roomba confirms each change through its settings
  shadow.

## 0.28.0

- Add a **Voice volume** slider and a **Child and pet lock** switch to the
  robot's configuration entities. Both update after Roomba reports the
  requested value.
- Report the installed integration version in diagnostics.

## 0.27.0

- Show a rotatable 3D floor plan on maps with Roomba wall geometry. Keep
  destination selection and live position aligned as the camera rotates.
- Show detected carpets and dock locations reported in the map archive. Use
  the overhead view while editing the map.

## 0.26.1

- Show the pending and confirmed skip result in the map card.

## 0.26.0

- Skip the current destination during an active mission from the floor plan,
  a robot button, or a Home Assistant action. Confirm the result using the
  matching skip event reported by Roomba.
- Accept vacuum then mop in the direct per-region cleaning action.

## 0.25.0

- Use the active floor plan to offer newly saved native cleaning zones and
  remove deleted destinations when Roomba's inventory is still updating.
- Keep a routine confirmation open while the destination inventory catches
  up to the same selectable floor plan.

## 0.24.1

- Resolve saved-zone names in live and finished results from the exact
  map revision used by the mission, including zones removed after that run.

## 0.24.0

- Run directed cleaning with **Vacuum then mop**, including saved routines
  with a sequence assigned to an individual destination. Send the mode and
  preferences with that destination in the ordered Roomba command.
- Use a new remote mission to confirm the start of a directed sequence.
  A submitted start leaves completion to the mission history.
- Resolve live destination names from the map revision used to start the
  mission if the robot is already advertising a different revision.

## 0.23.0

- Show cleaning results for zones and furniture alongside rooms. The card
  displays Roomba's reported outcome, area, and pass count for each result.
- Expose zone and furniture history in a dedicated sensor and include
  zone results in correlated live mission timeline data when Roomba reports them.

## 0.22.0

- Select both rooms directly on the floor plan when merging. Pick a room
  on the map before placing the divider for a split.
- Keep room edit drafts open while Roomba publishes destination metadata
  for the same map revision. Validate the selected rooms and the requested
  edit against the active archive when saving.

## 0.21.0

- Add furniture, rooms, and saved zones to the same ordered routine with
  individual cleaning settings. Read and edit supported furniture routines
  created in Roomba Home.
- Run a saved routine from the map card or with
  `roomba_home.run_cleaning_routine`. Resolve its destinations against the
  active map when starting the robot.

## 0.20.0

- Show furniture on supported Max 700 maps and add, move, resize, rotate, or
  remove it from the Home Assistant floor plan. Saving checks the active
  revision and preserves the source and geometry of untouched objects.

## 0.19.0

- Create, move, resize, or remove keep-out and no-mop areas on a supported
  Max 700 floor plan. Preview each change and verify the saved restrictions
  against the active map. Existing virtual walls are preserved.
- Keep a reviewed cleaning selection when Roomba publishes room metadata
  and the map revision and available cleaning targets stay the same.

## 0.18.0

- Rename a floor or preview and save its orientation from the map card.
- Apply the saved orientation to map geometry, overlays, and live position in
  the card, and to the native Home Assistant floor image and trajectory.

## 0.17.0

- Rename a room and set its Roomba room type from the floor plan card. Preview
  the label on the map and confirm the updated revision with the same room ID.

## 0.16.1

- Allow a cleaning zone to extend beyond a room boundary when part of it still
  overlaps a visible room, matching the saved shapes observed in Roomba Home.

## 0.16.0

- Create, move, resize, rename, and remove rectangular cleaning zones from a
  supported Max 700 floor plan. Preview the shape and confirm the saved map
  revision in Roomba.
- Display saved zone outlines while Roomba updates the list of cleaning
  destinations. The editor identifies which zones are ready to select.

## 0.15.0

- Divide one room or merge two adjacent rooms from the floor plan card.
  Review the divider or room pair before saving and confirm the new
  active revision through Roomba.
- Select visible rooms from the active map on the supported Max 700 even
  while Roomba is updating the destination inventory. Hide room IDs the
  active map no longer contains. Refresh the map inventory after a mission.

## 0.14.0

- Refresh the floor plan when Roomba changes its region inventory, even if the
  map revision stays the same. Recheck the inventory before starting a reviewed
  cleaning selection.
- Identify map zones that Roomba has yet to list for cleaning and saved zones
  that can be selected from the list without a matching outline.
- Display no-mop geometry separately from keep-out areas and virtual walls.
- List, create, rename, reorder, duplicate, and remove supported cleaning
  routines in the floor plan card. Preserve the saved settings per area.
- Review saved routines and weekly schedules that reference selected areas.
  Report entries whose destinations could not be established.

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
