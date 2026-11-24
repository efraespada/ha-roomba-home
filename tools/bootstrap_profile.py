"""Extract application configuration only; create a separate private client identity."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.roomba_home.core.models import AppProfile  # noqa: E402
from tools.validate_api import private_json  # noqa: E402


def profile_from_capture(capture):
    entries = capture["log"]["entries"]
    entry = next(
        e
        for e in reversed(entries)
        if e["request"]["method"] == "POST"
        and urlsplit(e["request"]["url"]).path == "/v2/login"
        and urlsplit(e["request"]["url"]).hostname == "unauth1.prod.iot.irobotapi.com"
    )
    raw = json.loads(entry["request"]["postData"]["text"])
    if not re.fullmatch(r"ANDROID-PRIME-[0-9a-fA-F-]{36}", raw["app_id"]):
        raise ValueError("Unrecognized client identity format.")
    value = AppProfile.native()
    return {
        "app_id": value.app_id,
        "authorizer_params": raw["authorizer_params"],
        "multiple_authorizer_token_support": raw["multiple_authorizer_token_support"],
        "app_info": {**value.app_info, "version": raw["app_info"]["version"]},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.capture:
        profile = profile_from_capture(private_json(a.capture))
    else:
        value = AppProfile.native()
        profile = {
            "app_id": value.app_id,
            "app_info": value.app_info,
            "authorizer_params": value.authorizer_params,
            "multiple_authorizer_token_support": value.multiple_authorizer_token_support,
        }
    fd = os.open(a.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(profile, f)
    print("Private client profile created; no account assertions were copied.")


if __name__ == "__main__":
    main()
