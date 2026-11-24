"""Version-independent semantic profile values for a persistence adapter."""

from dataclasses import asdict

from .cleaning import CleaningMode, CleaningProfile


def profile_preferences(profile: CleaningProfile) -> dict:
    return {
        **{key: value for key, value in asdict(profile).items() if value is not None},
        "mode": profile.mode.value,
    }


def restore_profile(value: object) -> CleaningProfile:
    if not isinstance(value, dict) or set(value) - set(CleaningProfile.__dataclass_fields__):
        raise ValueError("Invalid saved cleaning preferences.")
    try:
        return CleaningProfile(**{**value, "mode": CleaningMode(value.get("mode", "vacuum"))})
    except ValueError, TypeError:
        raise ValueError("Invalid saved cleaning preferences.") from None
