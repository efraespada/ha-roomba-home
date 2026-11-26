"""Read the cleaning preferences Roomba remembers for a map destination."""

from dataclasses import asdict, dataclass
from datetime import datetime

from .cleaning import CleaningCapabilities, CleaningProfile
from .cleaning_protocol import MODE_CODES, parse_regional_profile, requested_region_mode
from .telemetry import convert

_MODE_KEYS = {str(code): code for code in (*MODE_CODES.values(), 32)}
_PROFILE_METADATA = frozenset({"profile", "updated_at", "routine_modified"})
_PRESETS = ("light", "normal", "deep", "smart", "custom")


@dataclass(frozen=True, repr=False)
class RememberedProfile:
    code: int
    profile: CleaningProfile
    preset: str | None
    updated_at: datetime | None

    def action_response(self) -> dict:
        return {
            "mode_code": self.code,
            "settings": {
                key: value for key, value in asdict(self.profile).items() if value is not None
            },
            "preset": self.preset,
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,
        }


@dataclass(frozen=True, repr=False)
class AreaDefaults:
    last_mode_code: int | None
    profiles: tuple[RememberedProfile, ...]

    def action_response(self, capabilities: CleaningCapabilities) -> dict:
        compatible = {}
        for saved in self.profiles:
            try:
                saved.profile.validate(capabilities)
            except ValueError:
                continue
            compatible.setdefault(saved.profile.mode, []).append(saved)
        last_mode = requested_region_mode(self.last_mode_code)
        preferred = {}
        for mode, candidates in compatible.items():
            if code := _preferred_profile(candidates, self.last_mode_code):
                preferred[mode] = code
        return {
            "last_mode": last_mode,
            "last_mode_code": self.last_mode_code,
            "profiles": [saved.action_response() for saved in self.profiles],
            "preferred": preferred,
        }


def _preferred_profile(candidates: list[RememberedProfile], last_code: int | None) -> int | None:
    if len(candidates) == 1:
        return candidates[0].code
    if exact := next((profile for profile in candidates if profile.code == last_code), None):
        return exact.code
    dated = [profile for profile in candidates if profile.updated_at is not None]
    if not dated:
        return None
    newest = max(profile.updated_at for profile in dated)
    matching = [profile.code for profile in dated if profile.updated_at == newest]
    return matching[0] if len(matching) == 1 else None


def read_area_defaults(metadata: dict) -> AreaDefaults | None:
    raw_last = metadata.get("last_operating_mode")
    last = raw_last if type(raw_last) is int and requested_region_mode(raw_last) else None
    options = metadata.get("operating_mode_defaults")
    profiles = []
    if isinstance(options, dict):
        for key, code in _MODE_KEYS.items():
            params = options.get(key)
            if not isinstance(params, dict) or "operatingMode" in params:
                continue
            settings = {
                name: value for name, value in params.items() if name not in _PROFILE_METADATA
            }
            if (
                not settings
                or (profile := parse_regional_profile(settings | {"operatingMode": code})) is None
            ):
                continue
            tag = params.get("profile")
            profiles.append(
                RememberedProfile(
                    code,
                    profile,
                    tag if tag in _PRESETS else None,
                    convert("timestamp", params.get("updated_at")),
                )
            )
    return AreaDefaults(last, tuple(profiles)) if last is not None or profiles else None
