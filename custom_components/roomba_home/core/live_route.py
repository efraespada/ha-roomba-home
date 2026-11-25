"""Decode corroborated route and obstacle layers in Roomba's live map object."""

import re
import zlib
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import islice
from math import hypot
from statistics import fmean
from struct import unpack
from urllib.parse import parse_qs, urlsplit

from .errors import ProtocolError
from .live_maps import LIVE_CLOCK_SKEW_SECONDS, MAX_PATH_POINTS, MissionPath, Position, RoutePoint
from .telemetry import integer

RAW_ROUTE_MAX_AGE = 60
MAX_MAP_BYTES = 8 * 1024 * 1024
MAX_OBSTACLES = 512
ANCHOR_TOLERANCE = 0.03
_BUCKET = re.compile(r"[a-z0-9-]+-pmaptransferbucket-[a-z0-9]+")
_OBJECT_SCOPE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SIGNATURE_FIELDS = {
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "X-Amz-Date",
    "X-Amz-Expires",
    "X-Amz-Security-Token",
    "X-Amz-Signature",
    "X-Amz-SignedHeaders",
}


@dataclass(frozen=True, repr=False)
class RawRouteReference:
    url: str
    timestamp: int


@dataclass(frozen=True, repr=False)
class RawLiveSnapshot:
    route: tuple[tuple[int, RoutePoint], ...]
    obstacles: tuple[tuple[float, float], ...] | None


def raw_route_reference(document, robot_id: str, now: int) -> RawRouteReference | None:
    if not isinstance(document, dict) or not isinstance(update := document.get("map_update"), dict):
        return None
    timestamp = integer(document.get("timestamp"), 32_503_680_000)
    url = update.get("livemap_url_raw")
    if (
        not timestamp
        or not now - RAW_ROUTE_MAX_AGE <= timestamp <= now + LIVE_CLOCK_SKEW_SECONDS
        or not isinstance(url, str)
        or not re.fullmatch(r"https://[!-~]{1,8184}", url)
    ):
        return None
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query, strict_parsing=True, max_num_fields=len(_SIGNATURE_FIELDS))
    except ValueError:
        return None
    path = parts.path.split("/")
    if (
        parts.netloc != "s3.amazonaws.com"
        or parts.fragment
        or len(path) != 7
        or not _BUCKET.fullmatch(path[1])
        or path[2:4] != ["p2maps", "v007"]
        or not _OBJECT_SCOPE.fullmatch(path[4])
        or path[5:] != [robot_id, "rawmap"]
        or not _OBJECT_SCOPE.fullmatch(robot_id)
        or query.keys() != _SIGNATURE_FIELDS
        or query["X-Amz-Algorithm"] != ["AWS4-HMAC-SHA256"]
        or query["X-Amz-SignedHeaders"] != ["host"]
        or query["X-Amz-Date"]
        != [datetime.fromtimestamp(timestamp, UTC).strftime("%Y%m%dT%H%M%SZ")]
        or query["X-Amz-Expires"] != ["3600"]
        or not re.fullmatch(r"[0-9a-f]{64}", query["X-Amz-Signature"][0])
    ):
        return None
    return RawRouteReference(url, timestamp)


def _varint(data, start):
    value = 0
    for shift in range(0, 64, 7):
        if start >= len(data):
            break
        byte = data[start]
        start += 1
        value |= (byte & 127) << shift
        if byte < 128 and value < 1 << 64:
            return value, start
    raise ProtocolError("Invalid live route integer.")


def _fields(data):
    start = 0
    while start < len(data):
        tag, start = _varint(data, start)
        number, wire = divmod(tag, 8)
        if not 0 < number < 1 << 29 or wire not in (0, 1, 2, 5):
            raise ProtocolError("Invalid live route field.")
        if wire == 0:
            value, start = _varint(data, start)
        else:
            if wire == 2:
                size, start = _varint(data, start)
            else:
                size = 4 if wire == 5 else 8
            end = start + size
            if end > len(data):
                raise ProtocolError("Truncated live route field.")
            value, start = data[start:end], end
        yield number, wire, value


def _point(data):
    fields = {(number, wire): value for number, wire, value in _fields(data)}
    try:
        modes = fields[1, 0]
        x = unpack("<f", fields[2, 5])[0]
        y = unpack("<f", fields[3, 5])[0]
    except KeyError:
        raise ProtocolError("Incomplete live route point.") from None
    if integer(modes) is None or not all(-1e9 <= value <= 1e9 for value in (x, y)):
        raise ProtocolError("Invalid live route point.")
    return RoutePoint(x, y, modes)


def decode_raw_snapshot(data: bytes, max_points=None) -> RawLiveSnapshot:
    """Read the bounded route and optional temporary obstacles."""
    try:
        decompressor = zlib.decompressobj()
        unpacked = decompressor.decompress(data, MAX_MAP_BYTES + 1)
    except zlib.error:
        raise ProtocolError("Invalid compressed live map.") from None
    if len(unpacked) > MAX_MAP_BYTES or not decompressor.eof or decompressor.unused_data:
        raise ProtocolError("Incomplete or oversized live map.")
    route = None
    obstacles = []
    for number, wire, value in _fields(unpacked):
        if (number, wire) == (6, 2):
            if route is not None:
                raise ProtocolError("Expected one live route layer.")
            route = value
        elif number == 15 and len(obstacles) <= MAX_OBSTACLES:
            obstacles.append(value if wire == 2 else b"")
    if route is None:
        raise ProtocolError("Expected one live route layer.")
    return RawLiveSnapshot(_route_layer(route, max_points), _obstacle_layer(obstacles))


def decode_raw_route(data: bytes, max_points=None) -> tuple[tuple[int, RoutePoint], ...]:
    """Read the bounded, one-based route from a snapshot."""
    return decode_raw_snapshot(data, max_points).route


def _route_layer(data, max_points):
    declared = None
    actual = 0
    for number, wire, value in _fields(data):
        if (number, wire) == (1, 0):
            if declared is not None:
                raise ProtocolError("Repeated live route point count.")
            declared = value
        elif (number, wire) == (2, 2):
            actual += 1
    if declared is None or declared > actual or (declared == 0 < actual):
        raise ProtocolError("Live route point count did not match.")
    # Some snapshots include points beyond the declared count while cleaning.
    # Only the declared prefix is used to anchor the trail and obstacles.
    points = deque(maxlen=MAX_PATH_POINTS if max_points is None else max_points)
    entries = (value for number, wire, value in _fields(data) if (number, wire) == (2, 2))
    for index, value in enumerate(islice(entries, declared), start=1):
        points.append((index, _point(value)))
    return tuple(points)


def _obstacle_layer(records):
    if len(records) > MAX_OBSTACLES:
        return None
    points = set()
    for data in records:
        try:
            fields = {(number, wire): value for number, wire, value in _fields(data)}
            x, y = (unpack("<f", fields[number, 5])[0] for number in (5, 6))
        except KeyError, ProtocolError:
            return None
        if not all(-1e9 <= coordinate <= 1e9 for coordinate in (x, y)):
            return None
        points.add((x, y))
    return tuple(sorted(points))


def _route_translation(anchors):
    if len(anchors) < 4 or any(live.modes != raw.modes for _, live, raw in anchors):
        return None
    first = anchors[0][1]
    if all(hypot(live.x - first.x, live.y - first.y) < 0.5 for _, live, _ in anchors):
        return None
    dx = fmean(live.x - raw.x for _, live, raw in anchors)
    dy = fmean(live.y - raw.y for _, live, raw in anchors)
    if any(
        hypot(live.x - raw.x - dx, live.y - raw.y - dy) > ANCHOR_TOLERANCE
        for _, live, raw in anchors
    ):
        return None
    return dx, dy


def _obstacle_translation(anchors):
    # Late snapshots can revise parts of the recorded trail. Use agreeing
    # recent positions for the overlay without backfilling a revised trail.
    offsets = []
    for anchor in anchors[-64:]:
        _, live, raw = anchor
        if live.modes == raw.modes:
            offsets.append((anchor, live.x - raw.x, live.y - raw.y))
    strongest = 4
    translation = None
    for _, dx, dy in offsets:
        group = [anchor for anchor, x, y in offsets if hypot(x - dx, y - dy) <= ANCHOR_TOLERANCE]
        if len(group) > strongest and (candidate := _route_translation(group)) is not None:
            strongest = len(group)
            translation = candidate
    return translation


def reconcile_live_snapshot(path: MissionPath, snapshot: RawLiveSnapshot):
    """Anchor the optional obstacle layer and fill trail gaps within the verified prefix."""
    known = dict(path.points)
    anchors = [
        (index, live, raw)
        for index, raw in snapshot.route
        if isinstance(live := known.get(index), Position)
    ]
    alignment = _route_translation(anchors)
    supplement = ()
    if alignment is not None and path.needs_backfill():
        dx, dy = alignment
        boundary = anchors[-1][0]
        supplement = tuple(
            (index, RoutePoint(raw.x + dx, raw.y + dy, raw.modes))
            for index, raw in snapshot.route
            if index < boundary and index not in known
        )
    if supplement:
        known.update(supplement)
        path = replace(path, points=tuple(sorted(known.items())[-MAX_PATH_POINTS:]))
    obstacles = None
    if snapshot.obstacles is not None:
        obstacle_alignment = alignment or _obstacle_translation(anchors)
        if obstacle_alignment is not None:
            dx, dy = obstacle_alignment
            obstacles = tuple((x + dx, y + dy) for x, y in snapshot.obstacles)
    return path, supplement, obstacles


def backfill_route(
    path: MissionPath, route: tuple[tuple[int, RoutePoint], ...]
) -> tuple[MissionPath, tuple[tuple[int, RoutePoint], ...]]:
    """Restore the visible trail and hand off the full aligned prefix."""
    path, supplement, _ = reconcile_live_snapshot(path, RawLiveSnapshot(route, None))
    return path, supplement
