"""Project the public, model-specific Roomba help catalog."""

import re
from urllib.parse import urlsplit

from .dock import DOCK_FIELDS
from .errors import ProtocolError
from .problems import DOCUMENTED_DOCK_MESSAGE_CODES

MEDIA_HOST = "prod-help-content.care.irobotapi.com"
MANUAL_PATH = re.compile(r"/files/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.pdf")
ARTICLE_PATH = re.compile(r"/web/[a-z]{2,3}(?:-[A-Za-z]{2})?/[0-9]{1,10}\.html")
SUPPORT_PATH = re.compile(r"/appanswers/?")
ARTICLE_ID = re.compile(r"(Error|Charging Error|Start-Refuse) ([1-9][0-9]{0,5})")
FAMILIES = {
    "Error": "error",
    "Charging Error": "charging_error",
    "Start-Refuse": "start_refusal",
}
DEVICE_GUIDES = {
    "Provisioning_help": "wifi_setup",
    "Provisioning_reconnect": "wifi_reconnect",
    "Provisioning_MAC_address": "mac_address",
    "child_lock_setting": "child_lock",
    "Robot_reboot": "reboot",
    "Serial_number": "serial_number",
}

MAX_700_COMBO_SETUP = (
    (
        "brushes",
        "Fit both side brushes",
        "Match the letter on each brush to the corresponding A or B mount on the robot.",
    ),
    (
        "water",
        "Fill the clean water tank",
        "Add water to the dock’s right-hand tank. The separate detergent reservoir is optional "
        "and only takes StayClean concentrate.",
    ),
    (
        "charge",
        "Charge the robot",
        "Place it on the dock and let it charge before starting the first cleaning run.",
    ),
    (
        "rooms",
        "Prepare the rooms",
        "Open the doors to the areas you want to clean and pick up loose items from the floor.",
    ),
)


def setup_guide_for(sku: str) -> dict | None:
    """Return preparation steps for a model verified in Roomba Home."""
    if sku.upper() != "X185240":
        return None
    return {
        "steps": [
            {"id": key, "title": title, "instructions": instructions}
            for key, title, instructions in MAX_700_COMBO_SETUP
        ],
        "reference_url": "https://homesupport.irobot.com/articles/en_US/Knowledge/20503",
    }


def _link(value: object, host: str, path: re.Pattern[str]) -> str | None:
    if not isinstance(value, str) or len(value) > 512 or any(c.isspace() for c in value):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme != "https" or url.netloc != host or not path.fullmatch(url.path):
        return None
    return url._replace(query="", fragment="").geturl()


def project_help_catalog(data: object) -> dict:
    if not isinstance(data, dict) or not isinstance(entries := data.get("otherContent"), list):
        raise ProtocolError("Expected a Roomba help catalog.")
    articles = {}
    guides = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(key := entry.get("id"), str):
            continue
        if not (url := _link(entry.get("content"), MEDIA_HOST, ARTICLE_PATH)):
            continue
        if match := ARTICLE_ID.fullmatch(key):
            family, code = match.groups()
            articles[FAMILIES[family], int(code)] = url
        elif guide := DEVICE_GUIDES.get(key):
            guides[guide] = url

    return {
        "manual_url": _link(data.get("ownersManual"), MEDIA_HOST, MANUAL_PATH),
        "support_url": _link(data.get("customerCareWeb"), "answers.irobot.com", SUPPORT_PATH),
        "device_guides": guides,
        "articles": [
            {"family": family, "code": code, "url": url}
            for (family, code), url in sorted(articles.items())
        ],
    }


def current_help_articles(articles: list[dict], problems: dict) -> list[dict]:
    """Link current codes only when their provider family is established."""
    mission = problems.get("mission")
    mission_matches = [
        article
        for article in articles
        if article["family"] in ("error", "charging_error") and article["code"] == mission
    ]
    dock_codes = {
        code
        for source in ("dock", *DOCK_FIELDS)
        if (code := problems.get(source)) in DOCUMENTED_DOCK_MESSAGE_CODES
    }
    matches = mission_matches if len(mission_matches) == 1 else []
    return [
        article
        for article in articles
        if article in matches or (article["family"] == "error" and article["code"] in dock_codes)
    ]
