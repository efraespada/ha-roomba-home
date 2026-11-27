# Entities, actions, and preferences

Each compatible robot uses one standard Home Assistant `vacuum` entity for
vacuuming and mopping. The examples use synthetic entity and region IDs.
Use your own IDs from the entity registry and the region listing action.
[Capability matrix](capabilities.md)

## Interactive floor plan

Enable **Show saved floor plans and live room updates** in the integration
options, register the JavaScript module from the [README](../README.md#floor-plan-dashboard),
and add the card using your Roomba vacuum entity. The card can switch between
associated floors. With multiple maps saved, **Follow active floor** switches
to the floor Roomba identifies for the current mission. Select a named floor
to keep it in view. An in-progress selection or edit also keeps its floor
until you finish or close it. The live marker shows the last unexpired position. The
route shows observed segments and leaves gaps where samples were missing.
The live route legend distinguishes travel, vacuuming, mopping, and their
simultaneous use. The native image uses the same colors for recognized
activities. When Home Assistant joins a mission in progress, it can
recover earlier segments if a Roomba snapshot matches the current route.
Segments with an unrecognized mode use the generic route color.
The marker follows intermediate positions in each update when the
reported samples form a continuous path. If another report arrives while
the marker is moving, it continues from the point shown on screen.

During a cleaning run, **Estimated coverage** shades the observed vacuum
and mop passes. Uncheck **Mop** to isolate where Roomba vacuumed, or
uncheck **Vacuum** to inspect mopping. With both selected, purple indicates
where both activities were observed. The card clears the estimate when
the mission ends. Open **Cleaning history** to see the coverage polygons
Roomba published for the completed mission.
Use **Cleaning path** and **Travel path** to show or hide each trace.
These controls leave the coverage and position layers visible.
When Roomba reports temporary obstacles on the displayed floor, orange
triangles mark their positions. Use **Temporary obstacles** to hide or
show them. The markers expire with the snapshot and clear when the
mission or floor revision changes. Saved keep-out and no-mop zones have
their own overlays.

### Current mission readout

While Roomba reports an active cleaning mission, the top of the card
shows its **Phase**, **Mode**, **Time since start**, and **Reported area**
in square metres. The same summary appears for a mapped plan, a point
clean, or a whole-floor run. Missing readings stay hidden.

For example, a paused run can show **Paused**, **Vacuum**, **2:05**, and
**1.39 m²**. Time since start includes travel and pauses. The separate
destination timeline shows cleaning time in each area when its events
are available. The current readout clears when the mission ends or the
robot disconnects. Completed measurements remain in **Cleaning history**.

### Control the current mission

Use **Pause mission** above the floor plan while Roomba is cleaning, and
**Resume mission** when it is paused. **Cancel mission** ends the current
work. **Return to dock** sends the robot to its base. Both ask for
confirmation and show the robot's name. The controls follow the robot's
verified phase, including an active mapping run or a pause before the
first floor has been saved. **Return to dock** stays available after
cancellation if Roomba reports that it is idle off the dock and still
identifies the run. A user needs control permission for the linked
vacuum. If the mission changes while a confirmation is open, the card
closes it and displays the available commands for the new state.

### Select destinations and navigate

Use the map or the accessible buttons below it to select rooms and saved
zones. Pinch or use the zoom buttons to change scale. Drag a zoomed floor
or the 3D view to pan it. With the map focused, use the arrow keys to pan.
On an overhead map fitted to the card, a one-finger drag can still scroll
the dashboard. **Reset map view** fits the floor and centers it again.
The legend distinguishes keep-out areas and virtual walls from no-mop areas.
The card shows a notice for zone outlines that cannot be resolved as a
cleaning destination, or legacy destinations without a matching outline.
Choose **Review selection** to check the robot and destinations, then **Start
cleaning** to submit the selection with the robot's next-cleaning preferences.
A change to the map revision or available destinations requires a new selection.
A room inventory update that leaves the available destinations and their labels
the same keeps the cleaning confirmation open. A user
needs permission to read the vacuum to see its map and permission to control
it to start cleaning.

Choose **Review map dependencies** with one or more areas selected to see
which known routine or weekly schedule targets them. Roomba can return
entries with unresolved destinations, which the review flags for manual checking.

Choose **Edit rooms** on a supported Max 700 map. For a division, pick the
room on the map or in the list. Choose **Place divider on map**, then pick
two points to preview the divider. Expand **Divider coordinates** to adjust
the points with the keyboard. For a merge, select two adjacent rooms on the
map or in the lists. The map highlights both selections. Choose **Review
map edit** and **Save map** to publish the change.
Editing requires control permission and an idle or docked robot. A boundary
change may reset the affected room preferences. Review routines and schedules that
refer to those rooms. [Roomba map settings](https://homesupport.irobot.com/s/article/20500)

For a new name, choose **Rename a room**, then pick the room on the map or
from the list. Enter up to 31 characters and choose the room type. For
example, use `Guest bathroom` with **Bathroom**, or `Reading nook` with
**Other**. The new label appears on the draft map. Review the room, name,
and type before choosing **Save map**. Existing routine and schedule targets
keep the room's identifier. [Room naming contract](api.md#room-naming)

New visible rooms can be selected from the active map before Roomba updates
its room inventory. A room edit stays open through that metadata update as
long as the active map revision stays the same. Use the usual cleaning
confirmation when you are ready to clean a newly divided room. After a merge,
the removed room disappears from the card even while Roomba's separate
inventory still lists it. Saving boundaries leaves the robot idle.
[Room edit validation](validation.md#installed-room-editor-validation-in-0220)

Choose **Floor settings** while the robot is idle or docked. **Rename floor**
accepts up to 20 characters for a newly mapped unnamed floor and up to 16
to rename a named floor. Use **Floor settings** to give a new floor its name.
**Rotate floor**
previews left or right quarter-turns. **Cancel** discards the preview. Choose
**Review floor edit** and **Save floor** to apply it across Home Assistant and
Roomba Home. The room and zone destinations keep their saved identifiers.
[Floor settings protocol](api.md#floor-name-and-orientation)

Choose **Edit cleaning zones** with the robot idle or docked. To add a zone,
enter a name of up to 16 characters, select **Place rectangle on map**, and
choose two opposite corners. You can also enter those points under
**Rectangle coordinates**. Place at least part of the rectangle on a visible
room and keep it clear of keep-out areas and virtual walls. Review the shape
and choose **Save map**.

Choose **Edit a cleaning zone** to rename it or place new corners to move or
resize it. A rename preserves the existing outline. Choose **Remove a cleaning zone**,
select the zone, and confirm the removal. On supported Max 700 maps, the
cleaning area list updates as soon as Roomba confirms the new map revision.
[Saved-zone validation](validation.md#directed-vacuum-then-mop)
[Cleaning-zone protocol](api.md#cleaning-zone-edits)

### Edit map restrictions

Choose **Edit restrictions** while the robot is idle or docked. A
**Keep-out zone** excludes the marked area from vacuuming and mopping.
A **No-mop zone** excludes it from mopping. Select **Place rectangle on map**
and choose opposite corners, or enter them under **Rectangle coordinates**.
At least part of the rectangle must overlap a mapped room.

To add a line across a doorway, choose **Add a restriction → Virtual wall**,
select **Place wall on map**, and pick its first and second endpoints. You
can also enter them under **Endpoint coordinates**. A wall can be horizontal,
vertical, or diagonal. Part of the segment must pass inside a mapped room.
Choose **Review restriction**, then **Save map**.

Use **Move or resize a restriction** to draw replacement corners or
endpoints for the selected restriction. You can select a wall directly by
clicking its line on the map. Use **Remove a restriction** to remove it
after review. Each operation preserves the other restrictions. If Roomba
returns a restriction the editor cannot preserve, the controls are disabled
and the stored shapes remain visible.
[Restriction write protocol](api.md#restriction-edits)

### Edit furniture

Choose **Show furniture** to see the objects stored on a supported map.
Use **Edit furniture** when the robot is idle or docked. Choose a type
and enter the object's width, depth, and rotation. Use **Place on map**
to choose its center or enter **Center X** and **Center Y** with the
keyboard. The highlighted edge shows orientation, including for square
objects. Choose **Review furniture edit** and **Save map**.

Use **Move, resize, or rotate** to change one object while retaining its
type and identifier. Select the object on the map or in the list, which
labels objects as **Detected** or **Added**. Use **Remove furniture** to
review a deletion. Other objects retain their original provenance and
geometry. [Furniture write protocol](api.md#furniture-edits)

Open **Last mission by area** for the reported result, area, and pass count.
For a saved zone, the card shows the reported target size and the area
cleaned across confirmed passes in square metres. A second pass can make
the cleaned area larger than the target size.
The **Zones and furniture in the last mission** sensor counts the reported
zone events. Its `zones` attribute includes the type, label when available,
status, area, total area, and pass count of each destination. The existing
room results sensor continues to count rooms. When an older map revision
is unavailable, history still shows the result and destination type.
**Current mission measurements** shows in-progress room and zone readings
when a fresh timeline reply provides them. A saved zone can show its
reported target size as soon as the pass starts. The measured area for
a completed pass appears when Roomba supplies its completion event.
[Mission telemetry](telemetry.md)

## Room cleaning scores

Choose **Room cleaning scores** on the floor plan card. For rooms with a
current reading, the card shows the value on Roomba's own scale, traffic
classification, when the score was updated, and the settings Roomba
suggested. Recorded mission times belong to the score record and can
differ from the latest cleaning report.

Choose **Recommended rooms** to highlight the rooms Roomba has selected
for a suggested cleaning. The legend also lists their names. Switching
floors or loading a new revision clears the layer. Choose the button
again to load the recommendation for that floor.

Use the **Get room cleaning scores** action to read the same values in an
automation. Enable saved floor plans first. Omit `map_id` for a robot with
one active floor. For multiple floors, use the floor plan response's map
ID or the map prefix of a region ID from **List cleaning regions**.

```yaml
action: roomba_home.get_map_cleaning_scores
target:
  entity_id: vacuum.example_robot
response_variable: room_scores
```

Read the room list from `room_scores["vacuum.example_robot"].rooms`.
The action returns an empty list when Roomba has no scores for the current
revision. [Cleaning score API](api.md#room-cleaning-score-reads)

## Cleaning history

Open **Cleaning history** in the floor plan card. Select a report to see the
recorded duration, area, outcome, available per-mode measurements, and
timeline. The list can include signed cleaning reports with no map that
Roomba Home omits. Its totals use the measurements on the reports it lists.
Use **Period** to choose **Last 10 days** or **Last 30 days**. The list and
original reports use that period, and the card keeps the selected report
when it is available in the new list.
Select **Include short canceled runs** to load additional reports that
Roomba's usual history filter omits in either period. The report picker and totals reflect
the expanded list. Select a canceled report to inspect its outcome,
cleaned area, and archived route and coverage when available. Opening
**Cleaning history** starts with ten days and the usual filter.
Expand **Timeline** to see the order and times of recorded actions, including
the bin emptying stage and the end of the run. **Recorded bin emptyings**
shows the count reported by Roomba, which can be zero even when the timeline
contains that stage. The card identifies reported robot errors and lists
dock state and fault codes beside the relevant operation.
[Android comparison](validation.md#android-history-list-and-totals)

Pinch, drag, or use the map controls to inspect the original report. The
arrow keys pan the recorded map when it has focus. The legend identifies
travel, vacuuming, mopping, and simultaneous cleaning. Use **Travel path**,
**Cleaning path**, and **Coverage** to show or hide the layers present in
the report. If the report includes travel coverage, it stays visible until
you turn off **Coverage**. The final recorded position stays visible. The
card shows room names, saved cleaning zones, and restrictions from the archived revision
when Roomba includes them. Turn on **3D view**
when the archive provides walls or furniture. Drag to pan and use the rotate
button to inspect it from another angle. The archive is scoped to the mission's
original revision. A report can still show its measurements and timeline
after its map becomes unavailable. [Report protocol](api.md#archived-cleaning-reports)

For directed runs, **Requested order** shows the requested sequence,
cleaning settings, and final outcome for each room, zone, or furniture
target. When Roomba chose the order, the section is **Requested
destinations**. A destination can have a different outcome from the overall
mission. In one report, Roomba returned an overall success and recorded
that the user ended the room before a pass was reported.
[Validation](validation.md#historical-destination-plans)

## Map a floor

Choose **Map a floor** in the card and confirm once the robot is on its dock
and the area is ready to explore. This action is also available before the
first map is saved. Roomba explores the floor in a mapping-only cycle and
publishes the completed map after returning to the dock. At the model's map
limit, Roomba may replace the oldest map.
[iRobot ClearView guide](https://homesupport.irobot.com/articles/en_US/Knowledge/20500)

The **Mapping in progress** binary sensor stays on if a mapping run is
paused. Use `vacuum.pause` to pause it and `vacuum.start` to resume it.
Use `vacuum.stop` to cancel and `vacuum.return_to_base` to send the robot to
the dock. The next saved floor list is refreshed at the end of the run.

```yaml
action: roomba_home.start_mapping
target:
  entity_id: vacuum.roomba
data:
  confirmed: true
```

To remove a saved floor, select it and choose **Remove floor**. Review the
name before confirming. Saved routines and schedules that reference its
rooms or zones may need new destinations. Removing the floor uses Roomba's
map visibility setting, and the card refreshes the floor list after Roomba
confirms the change. [Provider contract](api.md#mapping-runs-and-floor-removal)

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
| Auto-empty frequency | Selects after each routine, every 25 m², or every 50 m² on the linked dock |
| Auto-empty area | Sets a custom area threshold on the linked dock |
| Empty bin | Requests manual emptying at a compatible dock |

Next-cleaning preferences stay local to Home Assistant and survive reloads.
They apply only when relevant to the selected mode. Changing modes preserves
the other preferences for later. With no local override, optional values are
omitted and the robot uses its settings. Reported values are separate sensors.
In one physical trial a request for mop wetness 1 and enabled SmartScrub left
global wetness at 2 and SmartScrub enabled. [Mopping evidence](evidence/2026-11-23-mop-preferences.json)
In another trial, the robot reported two passes enabled after a directed
run that requested it. Use the default switch to set that value explicitly
when the robot is idle. [Two-pass trial](validation.md#requested-settings-and-reported-passes)
The Max 700 Combo also reported its routine's suction level as the robot
default after starting a saved zone. Use the default suction control while
the robot is idle to set a different level for later runs.
[Saved-zone trial](validation.md#saved-routine-dock-frequency-comparison)

For directed **Vacuum then mop**, choose the mode and confirm the selected
areas on the floor plan, or call `vacuum.clean_area` with linked areas. Set
the mode beside an individual destination in **Manage routines** to use it
only for that destination. Other destinations keep their own settings and
order. A submitted start confirms the robot began the mission. Its current
cleaning mode and mission history show the two physical phases.
[Physical validation](validation.md#directed-vacuum-then-mop)

Home Assistant converts square feet to the nearest whole square meter
for the automatic emptying threshold. Controls become unavailable if their
required capabilities cease to be reported.

## Standard actions

| Action | Behavior |
|---|---|
| `vacuum.start` | Starts with the next-cleaning profile. Resumes an existing paused mission. |
| `roomba_home.clean_everywhere` | Starts a new untargeted cleaning with the next-cleaning profile after explicit confirmation. |
| `vacuum.pause` | Pauses an active mission |
| `vacuum.stop` | Cancels a mission |
| `vacuum.return_to_base` | Pauses active Max 700 Combo cleaning before sending the robot to the dock. Confirms arrival. |
| `vacuum.set_fan_speed` | Saves the next-cleaning suction level |
| `vacuum.locate` | Requests a sound when the robot supports it |
| `vacuum.clean_area` | Cleans mapped regions linked to Home Assistant areas |

Resuming preserves the current mission and mode. To change modes, cancel the
current mission and start a new one with the desired profile.

**Return to base** waits for the same cleaning mission to pause before
asking the Max 700 Combo to dock. An already paused robot can return
directly. If the robot starts returning while the pause is pending, Home
Assistant observes the arrival. [Return validation](validation.md#return-during-active-cleaning)

### Customize a one-off cleaning

Select rooms, saved cleaning zones, or supported furniture on the floor
plan. With **Show furniture** enabled, select the object on the map or
choose it from **Furniture destinations**. The dashed outline shows the
requested area around the chosen object. Choose **Select all rooms** to add
the remaining rooms in map order. Existing picks keep their order, and
**Deselect all rooms** removes only rooms. A selection can contain up to
32 destinations.

Choose **Review selection → Start cleaning** to use the current cleaning
preferences. Choose **Review selection → Customize cleaning** to set each
area's mode and settings. The draft starts in selection order. Use the order
buttons to move areas, or use **Select all rooms** to add the remaining rooms
while keeping individual settings. For example, vacuum around the dining
table first and give the kitchen two mop passes. **Estimate draft** shows
available room estimates.

Choose **Start cleaning**, review the order, and select **Confirm start**.
The card returns to the map after Roomba accepts the request. To keep the
same settings for another day, choose **Save as routine**, enter a name,
then choose **Save routine**. Closing the editor discards a one-off draft.
[One-off cleaning validation](validation.md#one-off-area-cleaning)

### Clean everywhere

Choose **Clean everywhere** on the floor plan card and confirm the robot.
Roomba cleans its reachable surroundings using the next-cleaning
preferences. The action applies to the robot's physical location. The
displayed floor and selected room list do not constrain it. It is available
while the robot is idle or docked, including before it has a saved map.
For a paused mission, use `vacuum.start` to resume it.

```yaml
action: roomba_home.clean_everywhere
target:
  entity_id: vacuum.example_robot
data:
  confirmed: true
```

**Clean all rooms** under **Recent and suggested routines** still loads a
directed draft with the rooms on the displayed floor. Use that draft to
exclude rooms or assign settings to individual destinations.
[Scope validation](validation.md#whole-area-and-directed-cleaning-scope)

### Skip the current destination

Enable live floor plans to use **Skip current area** on the card or robot
device. The card asks for confirmation. If Roomba moves to a different
destination before confirmation, review the new destination first. Roomba
continues the current mission and reports the omitted area in its timeline.

```yaml
action: roomba_home.skip_current_area
target:
  entity_id: vacuum.example_robot
```

The action confirms only a new skipped result for the current area. Allow
the robot to report the new destination before issuing another skip.
[Physical validation](validation.md#skip-the-current-destination)

Before starting a new mission,
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

### Command confirmation

After a command, the integration checks state every five seconds for up to 40
seconds, or 120 seconds for return to the dock. The `last_command_result`
attribute and last-command sensor report `pending`, `submitted`,
`confirmed`, or `unconfirmed`. Locate remains submitted after the broker
acknowledges it. Mopping can remain submitted during preparation. A later read
can confirm the same mission when floor cleaning begins, for up to five minutes
after preparation. Whole-map vacuum then mop reports submitted after the
vacuum phase begins. A directed sequence reports submitted after a new
remote mission starts. Use mission history to verify both phases completed.
Refresh an unconfirmed result before retrying.
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

With floor plans enabled, **Last live route activity** identifies what the
robot reported along its latest fresh position. Use `mopping` or
`vacuum_mop` as state conditions for an automation that needs to know
whether the robot is using the mop. The entity reads as unknown when the
position expires or the mission ends. [Route telemetry](telemetry.md)
The **On mapped carpet** binary sensor and map label show when the
latest position falls on a carpet recorded in the active floor plan.
The sensor becomes unknown when the live position expires or the floor
cannot be matched. [Map and carpet readings](telemetry.md)
The **Last live mission timeline update** sensor exposes the reported
`stage_started_at` timestamp for the current stage. This can anchor elapsed
time for a selected cleaning area, including a localized point.

For a directed cleaning run, the floor plan card lists the destinations
and shows how many have finished. **Planned order** appears when Roomba
commits to an order. **Two passes on** describes the requested preference.
**Pass 1** and **Pass 2** display the current saved-zone pass when Roomba
identifies the active event.
**Completed passes** counts the completion events Roomba supplied for a
saved zone. A row without confirmed passes can show **Reported pass
value** from the current or most recent destination event. The
**cleaning** clock totals the time Roomba reported cleaning that
destination, continues across passes, and holds steady during a pause.
The same total appears in mission history when the report has timed area
events. If Roomba only supplies the current stage's start, the live row
shows **In current stage**.

The **Completed destinations in the current mission**
sensor can trigger an automation as soon as the first destination finishes.
Replace the example entity ID with the one shown for your robot.

```yaml
alias: Notify when Roomba completes a destination
triggers:
  - trigger: numeric_state
    entity_id: sensor.roomba_completed_destinations_in_the_current_mission
    above: 0
actions:
  - action: persistent_notification.create
    data:
      message: Roomba reported its first completed destination.
```

**Estimated cleaning time remaining** reports seconds for ongoing directed
cleaning with a verified estimate for each remaining destination. The card
rounds up to minutes and shows each available planned duration. It refreshes
the countdown between robot polls from the last verified room stage. The
reading becomes unknown on pause, once the estimate is exhausted, or when the
mission ends. [Timing and telemetry](telemetry.md#how-to-interpret-progress)

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
On the Max 700 Combo dock, **Wash mop** can interrupt active drying. The
wash starts from the dock and the component state reports its progress.
Use **Dry mop** to start drying again after a manual wash finishes.
Manual refill requires a dock that advertises the manual action. Check dock
status and the relevant consumables before starting. The **Last recorded mission
destination** sensor shows the target type and `region_count` when Roomba
reports them. The mission error sensor retains the recorded error code after
the robot docks.

## Local map backups

Open **Map backups** on the floor plan card and choose **Back up current
floor**. Home Assistant verifies the current revision and saves the original
Roomba archive with its name, orientation, destination inventory, and capture
time. Repeating a backup of the same archive and settings reuses the copy.

Choose a backup to see its rooms, zones, restrictions, furniture, and dock.
When that floor is open on the live map, the backup panel identifies changes
to its revision, name, or rotation. The panel can show saved floors even if
Roomba has gone offline or removed the floor from its inventory. Choose
**Export backup** to download a JSON file with the exact archive and metadata.
The export includes private floor geometry and names.

**Backup settings** defaults to retaining five unpinned copies per robot.
Pin a copy to protect it from retention. Storage limits are 20 backups and
approximately 16 MiB of compressed archives per robot. Enable **Back up
before saving map edits or removing a floor** to save the reviewed floor
before the confirmed write to Roomba. If that backup fails, the edit stops
and the card reports the error. Unload and reload keep the stored copies.
Removing the integration entry removes its stored copies.

To recover the backed-up name or rotation, display the same floor on the
live map and choose a saved copy in **Map backups**. Select **Restore floor
settings**, review the current and backed-up values, and confirm while
Roomba is idle. For example, use a backup saved before a rename and a
rotation to restore both settings in one operation. Home Assistant checks
the active floor again before sending the change.

Use **Restore room names and types** to review room details in the selected
backup. Select the room and confirm its previous name and type. For example,
restore a kitchen label and category after a temporary rename. The room must
have the same identifier and footprint on the active map. The review
explains when the saved room is missing or its boundary has changed.
[Room recovery validation](validation.md#recovering-room-names-and-types)

Choose **Restore cleaning zones** to review moved, renamed, or removed
zones from the same floor. The preview shows the backed-up zones and the
current routines and schedules that refer to the affected targets. The
confirmed change writes the backed-up outlines with their original zone
identifiers. For example, recover a moved reading-area zone by selecting
the copy saved before the move. Deleting a zone can remove its references
from routines and schedules, and those references can stay absent after
recreating the zone.

Choose **Restore restrictions** to review and recover keep-out zones,
no-mop zones, and virtual walls from the selected backup. For example,
recover a removed no-mop zone without deleting another zone added later.
The preview identifies moved and missing restrictions. Confirmation applies
the saved geometry to the active floor by identifier. Recovery requires
the same floor boundary and supported restriction types in both versions.

Choose **Restore furniture** to preview moved or missing objects and the
saved routines that reference them. For example, restore the position and
angle of a chair moved in the editor while keeping a table added after the
backup. Recovery restores the saved object IDs, types, and sources on the
same floor. The preview identifies objects Roomba detected and objects
added by a user.

For a backup captured with program destinations, choose **Recover program
destinations** after recovering the matching zones or furniture. Select a routine or schedule,
review the destination order and the settings for each area, and choose
**Restore destinations**. For example, a schedule can recover the removed
entryway at its original position with **Mop** and wetness level 2 while
keeping a later start time and its current disabled state. The action
requires the saved zone name and outline or furniture placement, the same coordinate frame, and
unchanged settings and order for the areas the program still contains.
The review lists programs with missing zones, changed settings, or
unsupported selections so you can inspect them before editing the program.
[Recovery roadmap](roadmap.md#local-map-history-and-recovery)

## Clean a map point

Choose **Clean a point** on a supported floor plan and select a cleaning
mode. The available choices are **Vacuum**, **Mop**, **Vacuum and mop**,
and **Vacuum then mop**, according to the robot's capabilities. Click
inside a room and choose **Review selection**. For keyboard
placement, expand **Enter a position in a room** and enter X and Y percentages from
the minimum axes of that room's bounding rectangle. Choose **Place point**
to preview it before reviewing.

During a localized run, the card shows the reported target and cleaning mode
when the live timeline matches the viewed map revision.

The card binds the point to the reviewed map revision and destination
inventory. Home Assistant rechecks the room and map boundary at dispatch.
Choose the point again if Roomba updates the map. Floors with virtual walls
are excluded because the map cannot establish which side is reachable.

For an automation, use **List cleaning regions** to get the room ID and
call `roomba_home.clean_point`. Specify each coordinate as a fraction
strictly between 0 and 1, measured from that room's minimum X and Y axes.

```yaml
action: roomba_home.clean_point
target:
  entity_id: vacuum.example_robot
data:
  region_id: example_map:rid:room_a
  x: 0.4
  y: 0.55
  mode: mop
```

The action requires map-based spot cleaning support. It rejects points on
or outside the room boundary and inside keep-out areas. Wet modes also
require usable no-mop outlines and a point outside those areas. Omitting
`mode` defaults to vacuuming. **Submitted** indicates that the robot
reported a new remote mission. **Last recorded mission command** shows
the point-cleaning command after Roomba records it in mission history.

## Robot settings

Open the robot's **Device info** in Home Assistant to find its reported
serial number and installed software version.

On the robot device page, open **Configuration**. **Robot name** changes
the name stored in Roomba and preserves Home Assistant entity IDs and
custom device names. Enter up to 63 characters. **Voice language** lists
the voices already installed on this robot, including downloaded voices.
Automations use lowercase option codes such as `en-gb` and `es-es`.

Use **List robot voices** to see the current code, installed options,
and additional downloads published for the selected model.

```yaml
action: roomba_home.list_voice_languages
target:
  entity_id: vacuum.example_robot
response_variable: robot_voices
```

The response contains `current`, `installed`, and `downloadable` for each
selected vacuum. To add a voice, keep the robot on its charging dock
and pass a code from that list to **Install robot voice**.

```yaml
action: roomba_home.install_voice_language
target:
  entity_id: vacuum.example_robot
data:
  language: cs-cz
```

The action installs and selects the voice. It replaces the current
additional package when the robot has one download slot. The installed
voice selector updates after Roomba reports the new inventory.
The **Last command result** sensor shows whether Roomba confirmed the
deployment, and the software deployment sensor reports progress and errors.
[iRobot voice settings](https://homesupport.irobot.com/articles/en_US/Knowledge/11189)

Use **Reboot robot** for a normal restart. The **Last command result**
sensor confirms the restart when Roomba reports the robot disconnecting
and then coming back online. A reboot can interrupt dock drying.
[iRobot reboot instructions](https://homesupport.irobot.com/articles/en_US/Knowledge/9087)

**Voice volume** accepts whole percentages from 0 to
100. The lock applies to the robot's physical buttons. Remote controls remain
available. [iRobot child and pet lock](https://homesupport.irobot.com/articles/en_US/Knowledge/64000)

The controls appear when Roomba reports valid settings for that robot. Adjust
them while the robot is connected and idle or docked. Home Assistant waits for
the reported value to match the request. Changing either setting leaves the
next-cleaning preferences intact.

```yaml
actions:
  - action: text.set_value
    target:
      entity_id: text.example_robot_robot_name
    data:
      value: Loft vacuum
  - action: select.select_option
    target:
      entity_id: select.example_robot_voice_language
    data:
      option: en-gb
  - action: number.set_value
    target:
      entity_id: number.example_robot_voice_volume
    data:
      value: 35
  - action: switch.turn_on
    target:
      entity_id: switch.example_robot_child_and_pet_lock
```

## Robot software status

The robot's diagnostics show its installed firmware and the last update time
reported by Roomba. The linked dock has its own reported firmware sensor.
Use **Get robot software status** to check the provider catalog for that
installed version and model.

```yaml
action: roomba_home.get_software_status
target:
  entity_id: vacuum.roomba
response_variable: roomba_software
```

The response includes `installed_version`, `last_installed_at`,
`dock_version`, `status`, and `catalog_versions`. An empty applicable catalog
returns `up_to_date`. A nonempty list of other versions returns
`catalog_candidates`. Roomba manages the device's staged firmware rollout.
[iRobot update behavior](https://homesupport.irobot.com/articles/en_US/Knowledge/550) · [Max 700 release notes](https://homesupport.irobot.com/articles/en_US/Knowledge/70550)

## Dock settings

Open the robot's linked dock device and find these configuration entities.

| Entity | Choices |
| --- | --- |
| Auto-empty frequency | After each routine, Every 25 m², or Every 50 m² |
| Auto-empty area | 10–1000 m², with Home Assistant unit conversion |
| Mop wash temperature | Room temperature, Hot, Very hot |
| Mop wash frequency | Standard washes before and after cleaning. Medium adds washes during refills. High also washes between rooms. |
| Automatic cleaning solution | Enable or disable the dock's automatic StayClean dispensing |
| Mop drying duration | 3, 4, or 5 hours |

Choose a setting while the robot is connected and idle or docked. Home
Assistant confirms the new value from Roomba. Use the separate dock buttons
to run a wash or dry cycle. [Max 700 firmware notes](https://homesupport.irobot.com/articles/en_US/Knowledge/70550)

The area entity keeps its existing ID and shows an unknown value when
**After each routine** is active. Setting an area switches back to emptying
by area. When a verified threshold differs from both presets, the selector
shows **Custom area**. Set the threshold on the number entity.

For example, set emptying after each routine on your linked dock. Replace
the example entity ID with the one from the dock's device page.

```yaml
action: select.select_option
target:
  entity_id: select.example_dock_auto_empty_frequency
data:
  option: after_each_routine
```

```yaml
actions:
  - action: select.select_option
    target:
      entity_id: select.example_dock_mop_wash_frequency
    data:
      option: medium
  - action: select.select_option
    target:
      entity_id: select.example_dock_mop_drying_duration
    data:
      option: three_hours
```

## Robot help

Choose **Robot help** on the card to open the owner’s manual, iRobot support
and setup guides. **Current errors** appears when a fresh robot or dock
code has a matching article. Use **Look up an error code** to browse the
catalog by error, charging error or start refusal, then open the article.
The lookup works with maps disabled and while the configured robot is
offline. The displayed guides follow your Home Assistant language and
the Roomba account country.

On a Max 700 Combo, expand **Prepare for the first clean** for the four
preparation steps shown in Roomba Home. Check the two side brushes, clean
water tank, charge, and rooms. The checklist is in English and opens the
manufacturer's unboxing guide for details. Opening the checklist sends
no commands to the robot.

```yaml
action: roomba_home.get_robot_help
target:
  entity_id: vacuum.example_robot
response_variable: robot_help
```

Replace the example entity ID with the one from your device. Read the
report at `robot_help['vacuum.example_robot']`. Each article contains
`family`, `code` and `url`. Use `current_articles` in an automation to
include a matching provider article with a robot problem notification.
The report includes `setup_guide.steps` and `setup_guide.reference_url`
for the verified Max 700 Combo model. Other models return a null
`setup_guide`.
[Provider contract](api.md#robot-help-catalog)

## Maintenance and replacement parts

Choose **Maintenance** on the dashboard card to see Roomba's usage percentage
and remaining count for each reported part. The dust bag has a replacement
reference even though its catalog counter is disabled. The mop and dock
washing systems link to their care guides. Existing consumable sensors
include the available reference and link attributes.

The **iRobot shop** link uses the market configured for the account. In
Spain it opens the official product page by part number. In other markets
the catalog link may open the regional storefront, where you can look up
the printed part number. The card can read this view before the robot has
a saved map.

## Reset a maintenance counter

After replacing a part or cleaning a washing system, run **Reset maintenance
counter** on the robot's vacuum entity. Choose the part and confirm that the
work is complete. The integration rereads the selected counter from Roomba
and updates the corresponding robot or dock sensor after confirmation.

```yaml
action: roomba_home.reset_maintenance_counter
target:
  entity_id: vacuum.roomba
data:
  part: filter
  confirmed: true
```

The Max 700 Combo offers the edge-sweeping brush, multi-surface brushes, filter,
mop roller, robot mop-washing system, and dock mop-washing system. The dust
bag status comes from the dock, and Roomba's parts catalog disables its
usage counter. The washer reset records completed maintenance. Use the
dock's wash action to start a wash cycle.

## Cleaning schedules

Open **Manage schedules** on the floor plan to list this robot's schedules.
Choose **New schedule** or select an existing entry. Set the start time,
select **Weekly** with one or more days or **Once**, then choose the areas
and their cleaning modes and preferences. The order buttons set the sequence
for rooms, saved zones, and supported furniture. A furniture target cleans
around the selected object on the current map. Saving a new entry keeps it disabled until you
choose **Enable schedule**. Select **Delete** and confirm to remove it.

To schedule an existing ordered selection, open it under **Manage
routines** and choose **Use in schedule**. The editor copies the name,
rooms, saved zones, and furniture, their order, and their individual preferences into
a new draft. Set the time and recurrence, then choose **Save schedule**.
The routine stays available and the new schedule starts disabled. This
option appears for selections on the current floor with **Use listed order**.

Editing only the name or cleaning settings keeps the existing start and
enabled state. For a schedule on another saved floor, switch to that floor
before editing its areas. If the card cannot resolve the current destinations
or preferences, you can still change timing, enable or disable, and remove
the schedule.

**Create a cleaning schedule** saves a disabled entry in Roomba Home. Use
**List cleaning regions** to pick rooms or saved zones. For furniture IDs,
select the objects in a disabled schedule from the card, then call **List
editable cleaning schedules** to read their IDs. The schedule preserves
the destinations' order and preferences. Weekly schedules use ISO weekdays
from 1 (Monday) to 7 (Sunday).

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

To vacuum around furniture on Sundays before mopping a room, use an ordered
mixed selection. Query the selected map for the IDs before using the example.

```yaml
action: roomba_home.create_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  name: Sunday kitchen
  weekdays: [7]
  time: "10:30:00"
  regions:
    - id: example_map:furniture:example_table
      mode: vacuum
      suction_level: 1
    - id: example_map:rid:entryway
      mode: mop
      wetness_level: 2
```

For a one-time cleaning, set `frequency: once` and provide its local time.
Home Assistant uses the time zone reported by the robot to select today's
or tomorrow's occurrence. Omit `weekdays` for one-time cleaning.

```yaml
action: roomba_home.create_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  name: Vacuum the entryway once
  frequency: once
  time: "16:45:00"
  regions:
    - id: example_map:rid:entryway
      mode: vacuum
```

**List editable cleaning schedules** returns the IDs, names, targets,
frequencies, local times, enabled status, and any recognized per-area
settings of entries you can change.
A one-time entry reports `frequency: once` and the single planned
`weekday`. Weekly entries report `weekdays`. Use the ID with **Update a
cleaning schedule** to change timing, name, or `regions`. Send `time` to
change the occurrence, or omit it to keep the current start. For example,
change the entryway to mop on its existing schedule.

```yaml
action: roomba_home.update_cleaning_schedule
target:
  entity_id: vacuum.example_robot
data:
  schedule_id: example_household:example_schedule
  regions:
    - id: example_map:rid:entryway
      mode: mop
      wetness_level: 2
```

Both actions accept a `floor` object with the reviewed `map_id`, `version`,
and optional `inventory_id` to catch a stale area selection. Use **Enable
or disable a cleaning schedule** to change its enabled state.

```yaml
action: roomba_home.set_cleaning_schedule_enabled
target:
  entity_id: vacuum.example_robot
data:
  schedule_id: example_household:example_schedule
  enabled: true
```

**Remove a cleaning schedule** removes the selected entry. Schedule writes
are confirmed against a fresh read. The schedule-count sensors expose
aggregate schedule information.

## Saved cleaning routines

Choose **Manage routines** in the floor plan card. Selecting areas on the
map first prepopulates a new routine. For supported routines on that floor,
use the order buttons and per-area controls to edit destinations and cleaning
preferences. **Add a cleaning area** includes the floor's supported
furniture alongside rooms and saved zones. **Duplicate** starts a new
routine with the current draft's
settings. **Delete** asks for confirmation. A name-only update can preserve
the original settings of a routine with unavailable or unsupported targets.
For rooms and saved zones, select **Let Roomba choose** to keep per-area
settings while leaving the route order to the robot. The order buttons
switch the draft to **Use listed order**. Furniture uses listed order.
The card shows the estimate saved by Roomba and its confidence when available.
Saving changes and removing routines leave the robot idle. **Run saved
routine** asks for confirmation and displays the saved order preference.

Select a saved routine and use **Move earlier** or **Move later** to change
its position in the list. Home Assistant verifies the new order through
Roomba. The saved sequence of rooms, zones, or furniture and their cleaning
preferences stay with the routine. Use **List cleaning routines** to obtain
identifiers for the same action in an automation.

```yaml
action: roomba_home.reorder_cleaning_routine
target:
  entity_id: vacuum.example_robot
data:
  routine_id: "0123456789abcdef0123456789abcdef"
  anchor_id: "abcdef0123456789abcdef0123456789"
  position: before
```

Use **Appearance** when creating or editing a saved routine. Enter an
emoji and choose a color from the seven Roomba Home presets or the color
picker. The preview updates as you edit. An appearance-only save preserves
the destinations, cleaning settings, and saved estimate. **Duplicate**
copies the appearance along with the draft.

To update an existing routine from an automation, use the ID from **List
cleaning routines**.

```yaml
action: roomba_home.update_cleaning_routine
target:
  entity_id: vacuum.example_robot
data:
  routine_id: "0123456789abcdef0123456789abcdef"
  icon: "🧹"
  color: "#CBCBFB"
```

[Routine appearance validation](validation.md#routine-appearance)

On a supported Max 700 Combo, use **Cleaning preset** to apply Light, Normal,
or Deep to one destination. **Apply preset to all areas** applies the same
preset to every destination, keeping each area's cleaning mode and the order
you set. For example, choose Mop in the kitchen and Vacuum in the hallway,
then apply Light to both. You can still fine-tune individual settings before
saving. The levels use the robot's own scale.

| Preset | Suction when vacuuming | Liquid when mopping | Passes |
| --- | --- | --- | --- |
| Light | 1 | 1 | 1 |
| Normal | 2 | 2 | 1 |
| Deep | 4 | 3 | 2 |

The verified settings turn SmartScrub off in wet modes and leave carpet
boost to the firmware. The card offers a preset when the robot supports
its required settings. [Max 700 preset validation](validation.md#fixed-routine-presets)

Choose **Smart recommendations** to load the selected room's current
preferences from Roomba. The same option in **Apply preset to all areas**
uses each eligible room's own recommendation. The draft keeps the order
and the cleaning mode you chose for every area. Furniture, saved zones,
and rooms without compatible recommendations keep their settings.
For example, a room set to **Vacuum** can receive its recommended suction
and passes while a room set to **Mop** receives its recommended liquid
and scrubbing settings. Review or adjust the values before saving.
[Smart recommendation validation](validation.md#smart-routine-recommendations)

Open **Roomba's remembered settings** on a destination to see its last
reported mode and the settings Roomba saved for each available mode. A combined
vacuum-and-mop profile can have more than one recorded variant.
Choose **Remembered by Roomba** under **Cleaning preset** to copy the compatible
settings for the mode you chose. If you left the mode for the robot to choose,
the card tries the area's last reported mode and uses the next-cleaning
mode when Roomba supplied no last mode. For example, leave the entry hall's
mode unset to reuse its last vacuum settings and explicitly choose **Mop**
for the kitchen to reuse its saved mopping settings.

Choose **Use these settings** next to an individual compatible profile to
copy the variant you reviewed. On the verified Max 700 Combo, two
combined profiles held suction and liquid levels of 1 and 1 or 3 and 2.
An individual choice can change the area's mode and copies the settings
Roomba reported. The other destinations keep their order and preferences.

**Apply preset to all areas** keeps their order and applies each eligible
area's own settings. Review and adjust the draft before saving. The same
controls are available in schedule drafts for eligible rooms and saved zones.
[Remembered settings validation](validation.md#remembered-area-cleaning-preferences)

Choose **Estimate draft** after selecting areas and settings. The card shows
the planned time for each area. When some areas lack an estimate, **Known
time** shows the subtotal and the number of areas it covers. Changing the
selection, order, settings, or floor clears the result. The estimate uses
Roomba's duration table for the current floor.

The corresponding response-only action accepts the same regional settings
as **Create a cleaning routine**.

```yaml
action: roomba_home.estimate_cleaning_routine
target:
  entity_id: vacuum.example_robot
data:
  regions:
    - id: example_map:rid:kitchen
      mode: mop
      smart_scrub: false
      two_pass: false
    - id: example_map:rid:hall
      mode: vacuum
      suction_level: 2
      two_pass: true
response_variable: draft_estimate
```

The response has the complete `duration_seconds` when every area has a
reliable estimate, `partial_duration_seconds` for the known areas in an
incomplete selection, and per-area details in selection order.
[Draft estimate validation](validation.md#routine-draft-estimates)

### Quick routines from the floor plan

Open **Quick routines** above the map. It lists compatible saved routines
in Roomba's display order, followed by recent and suggested options for
the displayed floor. Choose a routine to open **Cleaning preferences**
with its destinations, order and per-area settings. Changes apply to
the draft. Choose **Start cleaning** and confirm to dispatch it. Use
**Refresh quick routines** to pick up changes made in Roomba Home.

For example, choose **Clean recommended rooms** to shade those rooms in
amber and review the modes and settings Roomba suggested for them. The
selected outline remains visible over the shading. Use **Recommended rooms**
to view the same layer by itself. If Roomba offers a point-cleaning shortcut,
choose a point and review the target before confirming the start.
[Smart cleaning comparison](validation.md#quick-routines-and-smart-recommendations-on-the-floor-plan)

### Recent and suggested routines

Choose **Recent and suggested routines** inside **Manage routines**. The
card shows the latest entries Roomba provides for the current floor.
Choose **Load draft** to reuse a recent selection and its settings. A
suggestion to clean all rooms loads the current rooms with your configured
cleaning defaults. **Choose point** opens the floor plan's point picker.
When available, **Clean recommended rooms** loads the destinations and
per-room settings from Roomba's current recommendation. Its draft starts
with **Let Roomba choose** for the order.

Review the areas, their order, and their individual preferences before
choosing **Run draft** and **Confirm start**. You can save the draft as a
routine from the same editor. A missing area or a changed furniture outline
can make a recent selection unavailable on the current floor.

Automations can read the same entries through **List recent and suggested
routines**. **Run a cleaning draft** accepts `regions`, optional `ordered`, and a
reviewed `floor` object with `map_id`, `version`, and optional `inventory_id`.
[Quick routines protocol](api.md#recent-and-suggested-floor-routines)

Use **List cleaning routines** for a vacuum to get its saved routine names,
identifiers, regions, recognized per-region settings, and editability. The
response includes the supported single-robot start routines used by
Roomba Home, including multi-area favorites. It reports `ordered: false`
when Roomba chooses the order. Its optional `estimate`
contains `duration_minutes` and `confidence` for the saved configuration.
Weekly schedules have separate actions.

**Create a cleaning routine** saves a selection from one current map.
Specify optional cleaning preferences per region. Set `ordered: false` to
let Roomba choose the order for rooms and saved zones. The action saves the
routine without starting the vacuum. List the robot's regions first to get
the identifiers.

```yaml
action: roomba_home.create_cleaning_routine
target:
  entity_id: vacuum.example_robot
data:
  name: Clean the entryway and sofa
  regions:
    - id: example_map:rid:entryway
      mode: vacuum_then_mop
      suction_level: 1
      wetness_level: 2
    - id: example_map:furniture:17
      mode: vacuum
      suction_level: 3
```

Create a routine from the card first to find your furniture identifiers in
**List cleaning routines**. **Run a cleaning routine** accepts the saved
routine ID. Launch resolves the selected objects again against the active
map and requires the existing per-area cleaning capabilities.

Use **Update a cleaning routine** with its ID and a new name, replacement
regions, or both. To use automatic order for a replacement, send
`ordered: false` with the regions. A rename keeps the original settings,
destinations, and order preference.
**Remove a cleaning routine** deletes the selected editable routine. If an
action reports an unconfirmed result, list the routines before retrying.
[Provider contract](api.md#saved-cleaning-routines)

## Current limitations

The integration polls Roomba's cloud. The latest reading can lag behind the
robot, and entity availability relies on its reported connection state. The
capability matrix tracks which controls and measurements have been verified
on each supported model. [Capability matrix](capabilities.md)

The validation log records trials on the physical robot and the Home
Assistant test environment. [Validation log](validation.md)
