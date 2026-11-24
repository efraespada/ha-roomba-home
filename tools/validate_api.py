"""Opt-in live reads using private runtime inputs; output contains counts, not identities."""

import argparse
import asyncio
import json
import os
import re
import stat
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.roomba_home.core import AppProfile, LoginDetails, RoombaClient  # noqa: E402
from custom_components.roomba_home.core.errors import RoombaError  # noqa: E402
from custom_components.roomba_home.core.transport import AiohttpTransport  # noqa: E402


def private_json(path: Path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise ValueError("A regular private input file is required.") from error
    with os.fdopen(fd) as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("A regular private input file is required.")
        if os.name == "posix" and info.st_mode & 0o077:
            raise ValueError("Private input files must have owner-only permissions (0600).")
        return json.load(f)


def safe_route(path: str) -> str:
    path = re.sub(r"/households/[^/]+", "/households/{household_id}", path)
    path = re.sub(r"/[0-9A-Fa-f]{16,}(?:-\d+)?(?=/|$)", "/{id}", path)
    return re.sub(r"/versions/[^/]+", "/versions/{version}", path)


def reference_reads(capture: dict):
    """Replay only successful, observed JSON GETs at the authenticated provider."""
    seen = set()
    for e in capture["log"]["entries"]:
        r = e["request"]
        u = urlsplit(r["url"])
        content = e["response"].get("content", {})
        if (
            r["method"] != "GET"
            or e["response"]["status"] != 200
            or u.hostname != "auth1.prod.iot.irobotapi.com"
            or "json" not in content.get("mimeType", "")
        ):
            continue
        key = (u.path, u.query)
        if key in seen:
            continue
        seen.add(key)
        yield u.path, dict(parse_qsl(u.query, keep_blank_values=True))


async def validate(args):
    account = private_json(args.account_file)
    profile = AppProfile.from_mapping(private_json(args.profile_file))
    rows = []
    async with aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as http:
        client = RoombaClient(
            AiohttpTransport(http),
            LoginDetails(account["username"], account["password"]),
            profile,
            country=args.country,
        )
        session = await client.ensure_session()
        robots = await client.robots()
        models = Counter(v.get("sku", "unknown") for v in robots.values())
        rows.append({"check": "fresh_native_login_and_signed_catalog", "result": "passed"})
        if args.reference_capture:
            capture = private_json(args.reference_capture)
            for path, params in reference_reads(capture):
                try:
                    value = await client.request("GET", path, params=params)
                    row = {
                        "route": safe_route(path),
                        "result": "passed",
                        "type": type(value).__name__,
                    }
                except RoombaError as error:
                    row = {
                        "route": safe_route(path),
                        "result": "failed",
                        "error": type(error).__name__,
                    }
                rows.append(row)
                await asyncio.sleep(0.15)
        old_key = session.raw["credentials"]["AccessKeyId"]
        client.invalidate_session()
        renewed = await client.ensure_session()
        after = await client.robots()
        rows.append(
            {
                "check": "renew_session_and_read_catalog",
                "result": "passed",
                "credentials_rotated": renewed.raw["credentials"]["AccessKeyId"] != old_key,
                "same_robot_inventory": set(after) == set(robots),
            }
        )
        if args.private_session_out:
            p = args.private_session_out
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as f:
                os.fchmod(f.fileno(), 0o600)
                json.dump({"session": renewed.raw, "discovery": renewed.discovery}, f)
            p.chmod(0o600)
    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "country": args.country.upper(),
        "robot_count": len(robots),
        "sku_counts": dict(models),
        "checks": rows,
        "scope": "Authentication, signed reads and forced renewal; no robot commands.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "checks": len(rows),
                "failed": sum(r["result"] != "passed" for r in rows),
                "robot_count": len(robots),
                "sku_counts": dict(models),
            }
        )
    )
    return int(any(r["result"] != "passed" for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--account-file", type=Path, required=True)
    p.add_argument("--profile-file", type=Path, required=True)
    p.add_argument("--reference-capture", type=Path)
    p.add_argument("--private-session-out", type=Path)
    p.add_argument("--country", default="ES")
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    try:
        inputs = [args.account_file, args.profile_file, args.reference_capture]
        if any(v and args.report.resolve() == v.resolve() for v in inputs):
            raise ValueError("The report must not replace an input file.")
        return asyncio.run(validate(args))
    except (RoombaError, ValueError, KeyError, OSError, aiohttp.ClientError, TimeoutError) as error:
        print(json.dumps({"result": "failed", "error": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
