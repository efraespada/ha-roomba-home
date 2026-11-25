"""Catalog selection and correlated confirmations for the language installer."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.voice_catalog import (
    VoicePack,
    catalog_voice_pack,
    voice_deployment_id,
    voice_installation,
)


def test_voice_deployment_id_uses_the_observed_utc_timestamp():
    local = datetime(2026, 11, 25, 13, 4, 8, tzinfo=timezone(timedelta(hours=1)))
    assert voice_deployment_id(local) == "LANG261125120408"


def test_catalog_pins_the_selected_model_and_voice_asset():
    pack = {
        "sku": "x185240",
        "languages": ["cs-CZ"],
        "deploymentMpkg": "picea_lang_pack/cs_CZ_v10.zip",
    }
    data = {
        "languagePackItems": [
            pack,
            pack,
            pack | {"sku": "other"},
            pack | {"deploymentMpkg": None},
        ]
    }
    assert catalog_voice_pack(data, "X185240", "cs-cz") == VoicePack(
        "cs-CZ", "picea_lang_pack/cs_CZ_v10.zip"
    )
    assert catalog_voice_pack(data, "X185240", "da-dk") is None
    data["languagePackItems"].append(pack | {"deploymentMpkg": "picea_lang_pack/cs_CZ_v11.zip"})
    assert catalog_voice_pack(data, "X185240", "cs-cz") is None


@pytest.mark.parametrize(
    "package",
    [
        "general_firmware.zip",
        "picea_lang_pack/da_DK_v10.zip",
        "picea_lang_pack/../../cs_CZ_v10.zip",
    ],
)
def test_voice_writer_cannot_use_other_software_or_another_locale(package):
    with pytest.raises(ProtocolError):
        VoicePack("cs-CZ", package)


def test_install_confirmation_requires_the_same_deployment_and_installed_inventory():
    settings = {
        "state": {
            "reported": {
                "langs2": {
                    "aSlots": 1,
                    "sLang": "es-ES",
                    "dLangs": {"langs": ["es-ES"]},
                    "uLangs": {"langs": ["cs-CZ"]},
                }
            }
        }
    }
    firmware = {"state": {"reported": {"deploymentState": 0, "deploymentId": "voice-a"}}}
    result = voice_installation(settings, firmware)
    assert result.installed == ("es-ES", "cs-CZ")
    assert result.selected == "es-ES" and result.slots == 1 and not result.pending
    assert result.result("voice-b", "cs-CZ") is None
    assert result.result("voice-a", "da-DK") is None
    assert result.result("voice-a", "cs-CZ") == "installed"
    firmware["state"]["desired"] = {"deploymentId": "next"}
    firmware["state"]["reported"]["deploymentState"] = 4
    assert voice_installation(settings, firmware).pending
    assert voice_installation(settings, firmware).result("voice-a", "cs-CZ") is None
    firmware["state"]["reported"]["deploymentState"] = 132
    assert voice_installation(settings, firmware).result("voice-a", "cs-CZ") == "failed"
    del firmware["state"]["reported"]["deploymentState"]
    assert voice_installation(settings, firmware).result("voice-a", "cs-CZ") is None
