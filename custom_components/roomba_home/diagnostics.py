"""Diagnostics contain counts, model and classification, never account data."""

from .const import VERSION
from .core.problems import observations


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    states = list((coordinator.data or {}).values())
    return {
        "integration_version": VERSION,
        "transport": "cloud_polling",
        "last_update_success": coordinator.last_update_success,
        "robot_count": len(states),
        "poll_seconds": coordinator.update_interval.total_seconds(),
        "optional_source_counts": coordinator.source_status,
        "robots": [
            {
                "model": s.sku,
                "connected": s.connected,
                "activity": s.activity,
                "mission_error": s.error,
                "digital_spot": s.capabilities.digital_spot,
                "telemetry_fields": len(s.telemetry),
                "problem_codes": observations(s),
            }
            for s in states
        ],
        "command_results": list(coordinator.command_status.values()),
    }
