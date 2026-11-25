"""Resolve fixed and room-specific Roomba cleaning presets."""

from dataclasses import asdict

from ..compatibility import VALIDATED_MODEL
from .capabilities import DeviceCapabilities
from .cleaning import CleaningMode, CleaningProfile

_FIXED_LEVELS = {
    "light": (1, 1, False),
    "normal": (2, 2, False),
    "deep": (4, 3, True),
}


def supports_routine_presets(sku: str, capabilities: DeviceCapabilities) -> bool:
    return sku == VALIDATED_MODEL and capabilities.routine_presets is True


def routine_presets(sku: str, capabilities: DeviceCapabilities) -> dict[str, dict[str, dict]]:
    """Offer only observed recipes that the robot can apply without substitution."""
    if not supports_routine_presets(sku, capabilities):
        return {}
    result = {}
    for mode in CleaningMode:
        recipes = {}
        for name, (suction, wetness, two_pass) in _FIXED_LEVELS.items():
            profile = CleaningProfile(
                mode,
                suction_level=suction if mode.vacuums else None,
                wetness_level=wetness if mode.mops else None,
                two_pass=two_pass,
                smart_scrub=False if mode.mops else None,
            )
            try:
                profile.validate(capabilities.cleaning)
            except ValueError:
                continue
            recipes[name] = asdict(profile)
        if recipes:
            result[mode.value] = recipes
    return result


def smart_routine_presets(
    sku: str, capabilities: DeviceCapabilities, rooms: list[dict]
) -> dict[str, dict[str, dict]]:
    """Adapt the provider's typed room preferences to each compatible selected mode."""
    if not supports_routine_presets(sku, capabilities):
        return {}
    recommendations = {}
    for room in rooms:
        if not (preferences := room.get("preferences")):
            continue
        suggested_mode = CleaningMode(preferences["mode"])
        recipes = {}
        for mode in capabilities.cleaning.modes or ():
            if (mode.vacuums and not suggested_mode.vacuums) or (
                mode.mops and not suggested_mode.mops
            ):
                continue
            profile = CleaningProfile(
                mode,
                suction_level=preferences.get("suction_level") if mode.vacuums else None,
                wetness_level=preferences.get("wetness_level") if mode.mops else None,
                two_pass=preferences.get("two_pass"),
                smart_scrub=preferences.get("smart_scrub") if mode.mops else None,
                carpet_boost=preferences.get("carpet_boost") if mode.vacuums else None,
            )
            try:
                profile.validate(capabilities.cleaning)
            except ValueError:
                continue
            recipe = {
                key: value
                for key, value in asdict(profile).items()
                if key != "mode" and value is not None
            }
            if recipe:
                recipes[mode.value] = recipe
        if recipes:
            recommendations[room["id"]] = recipes
    return recommendations
