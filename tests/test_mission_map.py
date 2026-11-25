"""Archived mission geometry uses the same bounded map archive reader."""

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.mission_map import read_mission_map


def test_mission_history_geometry_keeps_mode_coverage_order_and_gaps(make_point_bundle):
    polygon = {"type": "Polygon", "coordinates": [[[0, 0], [3, 0], [3, 3], [0, 0]]]}

    def feature(geometry, **properties):
        return {"type": "Feature", "geometry": geometry, "properties": properties}

    def line(*points):
        return {"type": "LineString", "coordinates": list(points)}

    def modify(documents):
        layers = {
            "coverage": [feature(polygon, operatingModes=["mopping", "mopping", "bad", 1])],
            "trajectories": [
                feature(line([8, 8], [9, 9]), index=5, operatingModes=["mopping"]),
                feature(line([1, 1], [2, 2]), index=1, operatingModes=["traveling"]),
                feature(line([1, 1], [2, 2]), index=2),
                feature(line([1, 1]), index=3),
                feature(polygon, index=4),
                feature(line([5, 5], [6, 6]), index="wrong"),
            ],
            "hazard": [feature({"type": "Point", "coordinates": [3, 5]})],
            "adHocCleanZones": [feature(polygon)],
        }
        for name, features in layers.items():
            documents["manifest.json"]["features"].append(
                {"type": name, "filepath": f"{name}.geojson"}
            )
            documents[f"{name}.geojson"] = {"type": "FeatureCollection", "features": features}

    bundle = make_point_bundle(mutate=modify)
    floor, report = read_mission_map(bundle, "map-a", "version.42")
    assert floor.map_id == "map-a"
    assert report["coverage"][0]["modes"] == ("mopping",)
    assert [path["index"] for path in report["trajectories"]] == [1, 2, 5]
    assert [path["modes"] for path in report["trajectories"]] == [("traveling",), (), ("mopping",)]
    assert report["trajectories"][-1]["points"] == ((8, 8), (9, 9))
    assert report["hazards"] == ((3, 5),) and report["temporary_zones"]
    with pytest.raises(ProtocolError, match="active version"):
        read_mission_map(bundle, "map-a", "other-revision")
