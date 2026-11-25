"""Project the public model-specific Roomba language catalog."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import ProtocolError
from .telemetry import at, convert, integer, project_telemetry, reported

VOICE_INSTALL_TIMEOUT = 600
VOICE_DEPLOYMENT_ID = re.compile(r"LANG[0-9]{12}")
_VOICE_METAPACKAGE = re.compile(r"picea_lang_pack/([A-Za-z]{2}_[A-Za-z]{2})_v[0-9]+\.zip")


@dataclass(frozen=True)
class VoicePack:
    language: str
    metapackage: str

    def __post_init__(self):
        match = _VOICE_METAPACKAGE.fullmatch(self.metapackage)
        if match is None or match[1].replace("_", "-").lower() != self.language.lower():
            raise ProtocolError("Expected a catalog metapackage for the selected voice.")


@dataclass(frozen=True, repr=False)
class VoiceInstallation:
    installed: tuple[str, ...]
    selected: str | None
    slots: int | None
    state: int | None
    deployment_id: str | None
    pending: bool

    def result(self, deployment_id: str, language: str) -> str | None:
        if self.deployment_id != deployment_id:
            return None
        if self.state is not None and self.state >= 100:
            return "failed"
        return "installed" if self.state == 0 and language in self.installed else None


def catalog_voice_languages(response: object, sku: str) -> tuple[str, ...]:
    codes = {code.lower() for languages, _ in _catalog_rows(response, sku) for code in languages}
    return tuple(sorted(codes))


def catalog_voice_pack(response: object, sku: str, requested: str) -> VoicePack | None:
    matches = {
        VoicePack(code, path)
        for codes, path in _catalog_rows(response, sku)
        for code in codes
        if code.lower() == requested and isinstance(path, str)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _catalog_rows(response: object, sku: str):
    if not isinstance(response, dict) or not isinstance(
        packs := response.get("languagePackItems"), list
    ):
        raise ProtocolError("Expected a Roomba voice catalog.")
    for pack in packs:
        if (
            not isinstance(pack, dict)
            or not isinstance(model := pack.get("sku"), str)
            or model.casefold() != sku.casefold()
            or not isinstance(codes := pack.get("languages"), list)
        ):
            continue
        yield (
            tuple(code for raw in codes if (code := convert("language", raw))),
            pack.get("deploymentMpkg"),
        )


def voice_installation(settings: dict, software: dict) -> VoiceInstallation:
    settings_values = project_telemetry({"rw-settings": settings})
    firmware = reported(software)
    deployment_id = firmware.get("deploymentId")
    pending = at(software, "state.desired.deploymentId")
    return VoiceInstallation(
        installed=settings_values.get("installed_voice_languages", ()),
        selected=settings_values.get("voice_language"),
        slots=integer(at(reported(settings), "langs2.aSlots")),
        state=integer(firmware.get("deploymentState")),
        deployment_id=deployment_id if isinstance(deployment_id, str) else None,
        pending=isinstance(pending, str) and bool(pending),
    )


def voice_deployment_id(now: datetime) -> str:
    return now.astimezone(UTC).strftime("LANG%y%m%d%H%M%S")
