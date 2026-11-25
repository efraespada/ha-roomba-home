"""Capture cleaning-zone links and review repairs without altering other settings."""

from dataclasses import replace

from .cleaning import CleaningMode, CleaningProfile
from .maps import SAVED_ZONE_IDS, AreaTarget, PersistentMap, resolve_segments
from .point_maps import FloorPlan
from .zone_edits import matching_saved_zone


def saved_zone_destinations(map_id: str, plan: FloorPlan) -> dict:
    return {
        f"{map_id}:zid:{zone.region_id}": zone
        for zone in plan.zone_outlines
        if zone.region_id in SAVED_ZONE_IDS
    }


def program_selection(program: dict) -> tuple | None:
    if program.get("editable") is False or not (settings := program.get("region_settings")):
        return None
    return settings, program.get("ordered", True)


def capture_zone_programs(zones: dict, sources: dict, unchecked: list[str]) -> dict:
    programs = []
    incomplete = set(unchecked)
    for kind, rows in sources.items():
        for row in rows:
            if not zones.keys() & (row.get("regions") or ()):
                continue
            if (selection := program_selection(row)) is None:
                incomplete.add(kind)
                continue
            settings, ordered = selection
            programs.append(
                {
                    "kind": kind,
                    "id": row["id"],
                    "name": row.get("name"),
                    "ordered": ordered,
                    "region_settings": settings,
                }
            )
    return {
        "items": sorted(programs, key=lambda program: (program["kind"], program["id"])),
        "unchecked": sorted(incomplete),
    }


def review_zone_program(
    saved: dict,
    current: dict | None,
    saved_zones: dict,
    matching_zones: set[str],
    floor: PersistentMap,
    capabilities,
) -> tuple[str, AreaTarget | None, list[dict]]:
    """Allow only the exact loss of saved zones from an otherwise intact selection."""
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
        or not missing.issubset(saved_zones)
    ):
        return "changed_selection", None, []
    if not missing:
        return "unchanged", None, []
    if not missing.issubset(matching_zones):
        return "restore_zones_first", None, []
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


def matching_zone_destinations(
    saved: FloorPlan, current: FloorPlan, saved_zones: dict, current_zones: dict
) -> set[str]:
    if not saved.border_digest or saved.border_digest != current.border_digest:
        return set()
    return {
        key
        for key in saved_zones.keys() & current_zones.keys()
        if matching_saved_zone(saved_zones[key], current_zones[key])
    }


def _saved_profile(region: dict) -> CleaningProfile:
    options = dict(region)
    options.pop("id")
    options["mode"] = CleaningMode(options["mode"])
    return CleaningProfile(**options)
