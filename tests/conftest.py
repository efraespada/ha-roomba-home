import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def make_point_bundle():
    """Build a synthetic Roomba map with a concave room and a keep-out zone."""

    def make(*, mutate=None, add=None):
        room = [[0, 0], [10, 0], [10, 5], [5, 5], [5, 10], [0, 10], [0, 0]]
        room_hole = [[1, 7], [2, 7], [2, 8], [1, 8], [1, 7]]
        bounds = [[0, 0], [9, 0], [9, 10], [0, 10], [0, 0]]
        restricted = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]
        restricted_hole = [[2.5, 2.5], [3.5, 2.5], [3.5, 3.5], [2.5, 3.5], [2.5, 2.5]]
        features = [
            {"type": name, "filepath": f"{name}.geojson", "schemaVersion": 1}
            for name in ("rooms", "borders", "policyZones")
        ]
        documents = {
            "manifest.json": {"metadata": "metadata.json", "features": features},
            "metadata.json": {"id": "map-a", "version": "version.42"},
            "rooms.geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "id": "room-a",
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": [room, room_hole]},
                    }
                ],
            },
            "borders.geojson": {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": [[bounds]]},
            },
            "policyZones.geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"type": "KeepOutZone"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [restricted, restricted_hole],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"type": "NoMopZone"},
                    },
                ],
            },
        }
        if mutate:
            mutate(documents)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for name, document in documents.items():
                content = json.dumps(document).encode()
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if add:
                archive.addfile(add)
        return buffer.getvalue()

    return make


@pytest.fixture
def picea_archive(make_point_bundle):
    def build(
        *,
        split=False,
        version="version.42",
        map_id="map-a",
        zones=(),
        restrictions=None,
        furniture=None,
        mutate=None,
    ):
        def update(documents):
            documents["metadata.json"].update(id=map_id, version=version, sourceFormat="picea")
            rooms = documents["rooms.geojson"]["features"]
            rooms[0]["properties"] = {
                "visibility": {"type": "visible"},
                "name": "Office north" if split else "Office",
                "adjacentRoomIDs": ["room-b"] if split else [],
            }
            if split:
                rooms[0]["geometry"]["coordinates"] = [[[0, 4], [5, 4], [5, 9], [0, 4]]]
                rooms.append(
                    {
                        "id": "room-b",
                        "type": "Feature",
                        "properties": {
                            "visibility": {"type": "visible"},
                            "name": "Office south",
                            "adjacentRoomIDs": ["room-a"],
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [5, 4], [0, 4], [0, 0]]],
                        },
                    }
                )
            if zones:
                documents["manifest.json"]["features"].append(
                    {"type": "cleanZones", "filepath": "cleanZones.geojson"}
                )
                documents["cleanZones.geojson"] = {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "id": identifier,
                            "type": "Feature",
                            "properties": None if name is None else {"name": name},
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        }
                        for identifier, name, ring in zones
                    ],
                }
            if restrictions is not None:
                documents["policyZones.geojson"]["features"] = list(restrictions)
            if furniture is not None:
                documents["manifest.json"]["features"].append(
                    {"type": "furniture", "filepath": "furniture.geojson"}
                )
                documents["furniture.geojson"] = {
                    "type": "FeatureCollection",
                    "features": list(furniture),
                }
            if mutate is not None:
                mutate(documents)

        return make_point_bundle(mutate=update)

    return build


@pytest.fixture
def map_display_layers():
    """Add synthetic wall, carpet, and dock layers to a map archive."""

    def update(documents):
        for name, kind, coordinates, properties in (
            ("floorPlan", "MultiLineString", [[[0, 0], [10, 0]]], {"type": "exterior"}),
            ("floorTypes", "Polygon", [[[4, 0], [6, 0], [6, 2], [4, 0]]], {"type": "carpet"}),
            ("dockPoses", "Point", [8, 1], {"orientation": 0}),
        ):
            documents["manifest.json"]["features"].append(
                {"type": name, "filepath": f"{name}.geojson"}
            )
            documents[f"{name}.geojson"] = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": kind, "coordinates": coordinates},
                        "properties": properties,
                    }
                ],
            }

    return update


@pytest.fixture
def furniture_feature():
    def build(identifier, kind, source, points, orientation=0, area=None):
        properties = {"type": kind, "source": source, "orientation": orientation}
        if area is not None:
            properties["cleaningArea"] = {"type": "Polygon", "coordinates": [area]}
        return {
            "type": "Feature",
            "id": identifier,
            "properties": properties,
            "geometry": {"type": "Polygon", "coordinates": [[*points, points[0]]]},
        }

    return build


@pytest.fixture
def policy_feature():
    def build(identifier, kind, coordinates, *, geometry_type="Polygon"):
        return {
            "type": "Feature",
            "id": identifier,
            "properties": {"type": kind},
            "geometry": {"type": geometry_type, "coordinates": coordinates},
        }

    return build


@pytest.fixture
def make_raw_route_bundle():
    import struct
    import zlib

    def varint(value):
        if value < 128:
            return bytes((value,))
        return bytes((128 | (value & 127),)) + varint(value >> 7)

    def blob(tag, content):
        return bytes((tag,)) + varint(len(content)) + content

    def build(points, *, count=None, obstacles=(), prefix=b"", suffix=b""):
        packed = b"".join(
            blob(
                18,
                b"\x08"
                + varint(mode)
                + b"\x15"
                + struct.pack("<f", x)
                + b"\x1d"
                + struct.pack("<f", y),
            )
            for x, y, mode in points
        )
        detections = b"".join(
            blob(
                122,
                b"\x08"
                + varint(index)
                + b"\x2d"
                + struct.pack("<f", x)
                + b"\x35"
                + struct.pack("<f", y),
            )
            for index, (x, y) in enumerate(obstacles, start=1)
        )
        size = len(points) if count is None else count
        return zlib.compress(
            prefix + blob(50, b"\x08" + varint(size) + packed) + detections + suffix
        )

    return build


@pytest.fixture
def make_raw_route_document():
    from datetime import UTC, datetime
    from urllib.parse import urlencode

    def build(timestamp, robot="fixture-robot"):
        query = urlencode(
            {
                "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
                "X-Amz-Credential": "fixture/read-only",
                "X-Amz-Date": datetime.fromtimestamp(timestamp, UTC).strftime("%Y%m%dT%H%M%SZ"),
                "X-Amz-Expires": "3600",
                "X-Amz-Security-Token": "fixture-token",
                "X-Amz-Signature": "a" * 64,
                "X-Amz-SignedHeaders": "host",
            }
        )
        object_path = f"example-pmaptransferbucket-fixture/p2maps/v007/fixture-scope/{robot}/rawmap"
        return {
            "timestamp": timestamp,
            "map_update": {"livemap_url_raw": f"https://s3.amazonaws.com/{object_path}?{query}"},
        }

    return build
