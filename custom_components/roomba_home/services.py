"""Validated Home Assistant actions for maps, cleaning preferences and schedules."""

import probatio as vol
from homeassistant.components.vacuum import DOMAIN as VACUUM_DOMAIN
from homeassistant.components.vacuum import VacuumEntityFeature
from homeassistant.core import SupportsResponse
from homeassistant.helpers import service

from .const import DOMAIN
from .core.cleaning import CleaningMode
from .core.point_maps import room_fraction
from .core.routines import ROUTINE_ID
from .core.schedules import SCHEDULE_FREQUENCIES, SCHEDULE_ID, WALL_TIME
from .core.telemetry import RESETTABLE_PARTS

REGION_ID = vol.All(str, vol.Length(min=1, max=270))
MAP_REVIEW = {
    vol.Required("map_id"): vol.All(str, vol.Length(min=1, max=128)),
    vol.Required("version"): vol.All(str, vol.Length(min=1, max=128)),
    vol.Optional("inventory_id"): vol.All(str, vol.Match(r"[0-9a-f]{64}\Z")),
}
CLEANING_SCHEDULE_ID = vol.All(str, vol.Match(SCHEDULE_ID.pattern + r"\Z"))
SAVED_ROUTINE_ID = vol.All(str, vol.Match(ROUTINE_ID.pattern + r"\Z"))
REGION_FIELDS = {
    vol.Required("id"): REGION_ID,
    vol.Optional("suction_level"): vol.All(int, vol.Range(min=1, max=99)),
    vol.Optional("wetness_level"): vol.All(int, vol.Range(min=1, max=99)),
    vol.Optional("smart_scrub"): bool,
    vol.Optional("two_pass"): bool,
    vol.Optional("carpet_boost"): bool,
}
REGION = vol.Schema(
    REGION_FIELDS | {vol.Optional("mode"): vol.In(tuple(mode.value for mode in CleaningMode))}
)
ROUTINE_REGION = vol.Schema(
    {
        field: vol.Any(None, validator) if isinstance(field, vol.Optional) else validator
        for field, validator in REGION_FIELDS.items()
    }
    | {vol.Optional("mode"): vol.In(tuple(mode.value for mode in CleaningMode))}
)
SCHEDULE_FREQUENCY = vol.In(SCHEDULE_FREQUENCIES)
SCHEDULE_DAYS = vol.All(
    [vol.All(int, vol.Range(min=1, max=7))], vol.Length(min=1, max=7), vol.Unique()
)
SCHEDULE_TIME = vol.All(str, vol.Match(WALL_TIME.pattern + r"\Z"))


def async_setup_services(hass):
    identifier = vol.All(str, vol.Length(min=1, max=128))
    name = vol.All(str, vol.Length(min=1, max=120))
    regions = vol.All([ROUTINE_REGION], vol.Length(min=1, max=32))
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_map_routines",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Optional("map_id"): identifier, vol.Optional("version"): identifier},
        func="async_list_map_routines",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "get_map_cleaning_scores",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Optional("map_id"): vol.All(str, vol.Length(min=1, max=128))},
        func="async_get_map_cleaning_scores",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "get_software_status",
        entity_domain=VACUUM_DOMAIN,
        schema=None,
        func="async_get_software_status",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "start_mapping",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Required("confirmed"): vol.All(bool, vol.In([True]))},
        func="async_start_mapping",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "reset_maintenance_counter",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("part"): vol.In(tuple(RESETTABLE_PARTS)),
            vol.Required("confirmed"): vol.All(bool, vol.In([True])),
        },
        func="async_reset_maintenance_counter",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_voice_languages",
        entity_domain=VACUUM_DOMAIN,
        schema=None,
        func="async_list_voice_languages",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "install_voice_language",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("language"): vol.All(str, vol.Match(r"[a-z]{2}(?:[-_][a-z]{2})?\Z")),
        },
        func="async_install_voice_language",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "skip_current_area",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Optional("review_id"): vol.All(str, vol.Match(r"[0-9a-f]{64}\Z"))},
        func="async_skip_current_area",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_cleaning_regions",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema=None,
        func="async_list_cleaning_regions",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_cleaning_estimates",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema={vol.Required("regions"): vol.All([REGION_ID], vol.Length(min=1, max=32))},
        func="async_list_cleaning_estimates",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "clean_regions",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema={vol.Required("regions"): vol.All([REGION], vol.Length(min=1, max=32))},
        func="async_clean_regions",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "clean_map_selection",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema=MAP_REVIEW
        | {vol.Required("regions"): vol.All([REGION_ID], vol.Length(min=1, max=32), vol.Unique())},
        func="async_clean_map_selection",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "clean_point",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("region_id"): REGION_ID,
            vol.Required("x"): room_fraction,
            vol.Required("y"): room_fraction,
            vol.Optional("mode"): vol.In(tuple(mode.value for mode in CleaningMode)),
            vol.Optional("review"): vol.Schema(MAP_REVIEW),
        },
        func="async_clean_point",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_cleaning_schedules",
        entity_domain=VACUUM_DOMAIN,
        schema=None,
        func="async_list_cleaning_schedules",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "update_cleaning_schedule",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("schedule_id"): CLEANING_SCHEDULE_ID,
            vol.Optional("frequency"): SCHEDULE_FREQUENCY,
            vol.Optional("weekdays"): SCHEDULE_DAYS,
            vol.Optional("time"): SCHEDULE_TIME,
            vol.Optional("name"): name,
            vol.Optional("regions"): regions,
            vol.Optional("floor"): vol.Schema(MAP_REVIEW),
        },
        func="async_update_cleaning_schedule",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "set_cleaning_schedule_enabled",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Required("schedule_id"): CLEANING_SCHEDULE_ID, vol.Required("enabled"): bool},
        func="async_set_cleaning_schedule_enabled",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "create_cleaning_schedule",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema={
            vol.Optional("frequency", default="weekly"): SCHEDULE_FREQUENCY,
            vol.Optional("weekdays"): SCHEDULE_DAYS,
            vol.Required("time"): SCHEDULE_TIME,
            vol.Required("name"): name,
            vol.Required("regions"): regions,
            vol.Optional("floor"): vol.Schema(MAP_REVIEW),
        },
        func="async_create_cleaning_schedule",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "remove_cleaning_schedule",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Required("schedule_id"): CLEANING_SCHEDULE_ID},
        func="async_remove_cleaning_schedule",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "list_cleaning_routines",
        entity_domain=VACUUM_DOMAIN,
        schema=None,
        func="async_list_cleaning_routines",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "estimate_cleaning_routine",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Required("regions"): regions, vol.Optional("floor"): vol.Schema(MAP_REVIEW)},
        func="async_estimate_cleaning_routine",
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "run_cleaning_draft",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("regions"): regions,
            vol.Required("floor"): vol.Schema(MAP_REVIEW),
            vol.Optional("ordered"): bool,
        },
        func="async_run_cleaning_draft",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "create_cleaning_routine",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema={
            vol.Required("name"): name,
            vol.Required("regions"): regions,
            vol.Optional("ordered"): bool,
        },
        func="async_create_cleaning_routine",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "update_cleaning_routine",
        entity_domain=VACUUM_DOMAIN,
        schema={
            vol.Required("routine_id"): SAVED_ROUTINE_ID,
            vol.Optional("name"): name,
            vol.Optional("regions"): regions,
            vol.Optional("ordered"): bool,
        },
        func="async_update_cleaning_routine",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "remove_cleaning_routine",
        entity_domain=VACUUM_DOMAIN,
        schema={vol.Required("routine_id"): SAVED_ROUTINE_ID},
        func="async_remove_cleaning_routine",
        supports_response=SupportsResponse.OPTIONAL,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "run_cleaning_routine",
        entity_domain=VACUUM_DOMAIN,
        required_features=[VacuumEntityFeature.CLEAN_AREA],
        schema={vol.Required("routine_id"): SAVED_ROUTINE_ID},
        func="async_run_cleaning_routine",
    )
