"""Home Assistant composition constants."""

from .compatibility import VALIDATED_MODEL

DOMAIN = "roomba_home"
CONF_PROFILE = "client_profile"
CONF_ROBOTS = "robots"
CONF_SHOW_MAPS = "show_maps"
SUPPORTED_SKU = VALIDATED_MODEL
PLATFORMS = (
    "vacuum",
    "sensor",
    "binary_sensor",
    "event",
    "select",
    "number",
    "switch",
    "button",
    "image",
)
POLL_SECONDS = 60
ACTIVE_POLL_SECONDS = 15
DETAIL_SECONDS = 300
PARTS_SECONDS = 1800
MAPS_SECONDS = 900
HISTORY_SECONDS = 1800
VERSION = "0.14.0"


def selected_robots(entry):
    return entry.options.get(CONF_ROBOTS, entry.data[CONF_ROBOTS])
