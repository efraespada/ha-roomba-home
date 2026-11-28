"""Capture map destination links and review repairs without altering other settings."""

from dataclasses import replace

from .cleaning import CleaningMode, CleaningProfile
from .furniture_edits import matching_furniture_placement
from .furniture_targets import furniture_regions
from .maps import SAVED_ZONE_IDS, AreaTarget, PersistentMap, resolve_segments
from .point_maps import FloorPlan, MapFurniture, with_archive_destinations
from .zone_edits import matching_saved_zone


def saved_zone_destinations(map_id: str, plan: FloorPlan) -> dict:
    return {
        f"{map_id}:zid:{zone.region_id}": zone
        for zone in plan.zone_outlines
        if zone.region_id in SAVED_ZONE_IDS
    }


def saved_furniture_destinations(map_id: str, plan: FloorPlan) -> dict:
    usable = {region.region_id for region in furniture_regions(plan)}
    return {
        f"{map_id}:furniture:{item.identifier}": item
        for item in plan.furniture or ()
        if item.identifier in usable
    }


def program_selection(program: dict) -> tuple | None:
    if program.get("editable") is False or not (settings := program.get("region_settings")):
        return None
    return settings, program.get("ordered", True)


def capture_map_programs(
    floor: PersistentMap, plan: FloorPlan, sources: dict, unchecked: list[str]
) -> dict:
    areas = {
        region.segment_id(floor.map_id): region.name or f"Area {index}"
        for index, region in enumerate(
            (*with_archive_destinations(floor, plan).regions, *furniture_regions(plan)), 1
        )
    }
    programs = []
    incomplete = set(unchecked)
    for kind, rows in sources.items():
        for row in rows:
            regions = row.get("regions") or ()
            if regions and not any(region.startswith(f"{floor.map_id}:") for region in regions):
                continue
            if (selection := program_selection(row)) is None:
                incomplete.add(kind)
                continue
            settings, ordered = selection
            record = {
                "kind": kind,
                "id": row["id"],
                "name": row.get("name"),
                "ordered": ordered,
                "region_settings": settings,
            }
            if all(region["id"] in areas for region in settings):
                if (draft := _copy_fields(kind, row)) is not None:
                    record["draft"] = draft | {
                        "area_names": [areas[region["id"]] for region in settings]
                    }
            programs.append(record)
    return {
        "items": sorted(programs, key=lambda program: (program["kind"], program["id"])),
        "unchecked": sorted(incomplete),
    }


def _copy_fields(kind: str, row: dict) -> dict | None:
    if kind == "routine":
        return {key: row[key] for key in ("icon", "color") if key in row}
    if row.get("time") and (row.get("weekdays") or row.get("frequency") == "once"):
        draft = {
            key: row[key]
            for key in ("frequency", "weekdays", "weekday", "time", "enabled")
            if key in row
        }
        if "weekdays" in draft:
            draft["weekdays"] = list(draft["weekdays"])
        return draft
    return None


def review_map_program(
    saved: dict,
    current: dict | None,
    saved_areas: dict,
    matching_areas: set[str],
    floor: PersistentMap,
    capabilities,
) -> tuple[str, AreaTarget | None, list[dict]]:
    """Allow only the exact loss of backed-up targets from an intact selection."""
    if current is None:
        return "missing_program", None, []
    if (selection := program_selection(current)) is None:
        return "unsupported_selection", None, []
    active, ordered = selection
    recorded = saved["region_settings"]
    active_ids = {region["id"] for region in active}
    missing = {region["id"] for region in recorded} - active_ids
    if (
        ordered != saved["ordered"]
        or active != [region for region in recorded if region["id"] in active_ids]
        or not missing.issubset(saved_areas)
    ):
        return "changed_selection", None, []
    if not missing:
        return "unchanged", None, []
    if pending := missing - matching_areas:
        status = (
            "restore_areas_first"
            if any(isinstance(saved_areas[region], MapFurniture) for region in pending)
            else "restore_zones_first"
        )
        return status, None, []
    try:
        target = resolve_segments((floor,), [region["id"] for region in recorded])
        profiles = tuple(_saved_profile(region) for region in recorded)
        for profile in profiles:
            profile.validate(capabilities)
    except ValueError:
        return "unavailable_destination", None, []
    destinations = [
        {**region, "name": item.name, "restore": region["id"] in missing}
        for item, region in zip(target.regions, recorded, strict=True)
    ]
    return "ready", replace(target, profiles=profiles, ordered=ordered), destinations


def matching_backup_destinations(
    saved: FloorPlan, current: FloorPlan, saved_areas: dict, current_areas: dict
) -> set[str]:
    if not saved.border_digest or saved.border_digest != current.border_digest:
        return set()
    return {
        key
        for key in saved_areas.keys() & current_areas.keys()
        if _matching_destination(saved_areas[key], current_areas[key])
    }


def _matching_destination(saved, current) -> bool:
    if isinstance(saved, MapFurniture):
        return matching_furniture_placement(saved, current)
    return matching_saved_zone(saved, current)


def _saved_profile(region: dict) -> CleaningProfile:
    options = dict(region)
    options.pop("id")
    options["mode"] = CleaningMode(options["mode"])
    return CleaningProfile(**options)
