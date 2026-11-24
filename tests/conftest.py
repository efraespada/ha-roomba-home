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
