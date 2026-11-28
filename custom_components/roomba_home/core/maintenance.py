"""Project public part references separately from signed consumable counters."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..compatibility import VALIDATED_MODEL
from .telemetry import DOCK_PARTS, PARTS, RESETTABLE_PARTS, maintenance_due

CATALOG_ROOT = "https://content-prod.iot.irobotapi.com/v2"
MARKET = re.compile(r"[A-Z]{2}")
LANGUAGE = re.compile(r"[a-z]{2,3}")
LOCALE = re.compile(r"[a-z]{2,3}-[a-z]{2}")
PART_SKU = re.compile(r"[A-Za-z0-9-]{3,24}")
GUIDE_PATH = re.compile(r"/web/[a-z]{2,3}/[0-9]{4,10}\.html")
SUPPORT_ARTICLE = "https://homesupport.irobot.com/articles/en_US/Knowledge/"
MAX_700_PART_GUIDANCE = {
    "147": (
        "robot_health_bag_dmc",
        "The dust bag collects debris when the dock empties the robot. Replace it when "
        "the dock or Roomba Home indicates that the bag is full.",
        "40350",
    ),
    "71": (
        "robot_health_main_brushes_description_705_dmc",
        "The two main brushes lift debris into the robot's bin. Clear hair and debris "
        "from the brushes and beneath their end caps.",
        "70507",
    ),
    "72": (
        "robot_health_filter_dmc",
        "The filter traps fine debris from the air passing through the bin. Brush it "
        "clean and follow the guide when rinsing its removable mesh screen.",
        "70505",
    ),
    "67": (
        "robot_health_side_brush_dmc",
        "The edge-sweeping brushes move debris from walls and corners into the robot's "
        "path. Fit each brush on the side marked for it in the guide.",
        "31044",
    ),
    "148": (
        "robot_health_roller_description_705_dmc",
        "The mop roller scrubs hard floors. Remove hair and dirt from the roller and "
        "follow the guide for cleaning or replacement.",
        "70508",
    ),
    "212": (
        "robot_health_roller_mop_washing_system_description_705_dmc",
        "The robot removes dirty water from the roller while it mops. Clean the scraper "
        "and the robot's dirty-water path as shown in the guide.",
        None,
    ),
    "202": (
        "robot_health_dock_washing_system_description_705_dmc",
        "The dock washes the mop roller in its wash basin. Remove residue from the basin "
        "and follow the guide to put it back in place.",
        None,
    ),
}


def parts_catalog_url(country: str, language: str, model: str) -> str:
    market = country if MARKET.fullmatch(country) else "ES"
    language_code = language.lower().split("-", 1)[0]
    locale = f"{language_code}-{market.lower()}" if LANGUAGE.fullmatch(language_code) else "en-us"
    return f"{CATALOG_ROOT}/{locale}/{market}/{model}/parts"


def _provider_link(value: object, host: str):
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    return url if url.scheme == "https" and url.netloc == host else None


def _replacement_url(value: object, market: str, sku: str) -> str | None:
    url = _provider_link(value, "directory.irobotapi.com")
    if url is None or not MARKET.fullmatch(market):
        return None
    if url.path != f"/v1/ecom/pdp-app/{market}/{sku}":
        return None
    if market == "ES":
        # The catalog's mobile route can land on the storefront in a normal browser.
        return f"https://www.irobot.es/es_ES/{sku}.html"
    locale = next(
        (
            value
            for name, value in parse_qsl(url.query)
            if name == "locale" and LOCALE.fullmatch(value)
        ),
        None,
    )
    return url._replace(query=urlencode({"locale": locale}) if locale else "", fragment="").geturl()


def _guide_url(value: object) -> str | None:
    url = _provider_link(value, "prod-help-content.care.irobotapi.com")
    if url is not None and GUIDE_PATH.fullmatch(url.path):
        return url._replace(query="", fragment="").geturl()
    return None


def project_part_references(catalog: dict, market: str, *, model: str) -> dict[str, dict]:
    parts = catalog.get("parts")
    if not isinstance(parts, list):
        return {}
    references = {}
    for part in parts:
        if not isinstance(part, dict) or not isinstance(code := part.get("part_id"), str):
            continue
        if code not in PARTS:
            continue
        fields = {}
        if isinstance(sku := part.get("sku"), str) and PART_SKU.fullmatch(sku):
            fields["part_sku"] = sku
            if url := _replacement_url(part.get("buy_url"), market, sku):
                fields["replacement_url"] = url
        if guide := _guide_url(part.get("guide_url")):
            fields["maintenance_guide_url"] = guide
        guidance = MAX_700_PART_GUIDANCE.get(code) if model == VALIDATED_MODEL else None
        if guidance and part.get("robot_health_description_id") == guidance[0]:
            _, description, article = guidance
            fields["part_description"] = description
            if article:
                fields.setdefault("maintenance_guide_url", SUPPORT_ARTICLE + article)
        if fields:
            references[code] = fields
    return references


def maintenance_parts(
    telemetry: dict, *, dock_recognized: bool, counters_available: bool, allow_reset: bool
) -> list[dict]:
    references = telemetry.get("part_references", {})
    parts = []
    for code, name in PARTS.items():
        dock = code in DOCK_PARTS
        if dock and not dock_recognized:
            continue
        prefix = f"part_{code}"
        if f"{prefix}_usage" not in telemetry and code not in references:
            continue
        usage = telemetry.get(f"{prefix}_usage") if counters_available else None
        parts.append(
            {
                "part": name,
                "part_code": code,
                "dock": dock,
                "usage": usage,
                "remaining": telemetry.get(f"{prefix}_remaining") if counters_available else None,
                "count_type": telemetry.get(f"{prefix}_count_type") if counters_available else None,
                "can_reset": allow_reset and usage is not None and name in RESETTABLE_PARTS,
                **references.get(code, {}),
            }
        )
    return parts


def maintenance_reminders(telemetry: dict, *, dock_recognized: bool) -> list[dict]:
    """Describe known parts at their service limit using signed counters."""
    reminders = []
    for code, name in PARTS.items():
        if code in DOCK_PARTS and not dock_recognized:
            continue
        prefix = f"part_{code}"
        remaining = telemetry.get(f"{prefix}_remaining")
        if maintenance_due(telemetry.get(f"{prefix}_usage"), remaining):
            reminders.append(
                {
                    "part": name,
                    "remaining": remaining,
                    "count_type": telemetry.get(f"{prefix}_count_type"),
                    "category": telemetry.get(f"{prefix}_category"),
                }
            )
    return reminders
