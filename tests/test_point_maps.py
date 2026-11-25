"""Point cleaning follows a linked map version and GeoJSON room geometry."""

import gzip
import tarfile
from dataclasses import replace
from types import SimpleNamespace

import pytest

from custom_components.roomba_home.core import point_maps
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import AreaTarget, CleaningRegion, RegionKind
from custom_components.roomba_home.core.point_maps import PointTarget, resolve_room_point

AREA = AreaTarget("map-a", "version.42", (CleaningRegion("room-a", RegionKind.ROOM, None),))


@pytest.mark.parametrize("fraction", [(0.1, 0.1), (0.3, 0.3), (0.8, 0.1)])
def test_room_fractions_resolve_into_the_actual_map(make_point_bundle, fraction):
    point = resolve_room_point(make_point_bundle(), AREA, *fraction)
    assert point.center == tuple(value * 10 for value in fraction)
    assert (point.map_id, point.version_id) == ("map-a", "version.42")
    assert "map-a" not in repr(point)


@pytest.mark.parametrize(
    "fraction",
    [(0.8, 0.8), (0.95, 0.1), (0.9, 0.1), (0.2, 0.3), (0.25, 0.3), (0.15, 0.75), (0.1, 0.75)],
)
def test_rejects_room_holes_polygon_boundaries_and_keep_outs(make_point_bundle, fraction):
    with pytest.raises(ValueError, match="outside the room"):
        resolve_room_point(make_point_bundle(), AREA, *fraction)


def test_no_mop_zone_applies_only_to_wet_point_cleaning(make_point_bundle):
    def add_outline(documents):
        zone = documents["policyZones.geojson"]["features"][1]
        zone["geometry"] = {
            "type": "Polygon",
            "coordinates": [[[5, 1], [7, 1], [7, 3], [5, 3], [5, 1]]],
        }

    bundle = make_point_bundle(mutate=add_outline)
    assert resolve_room_point(bundle, AREA, 0.6, 0.2).center == (6, 2)
    assert resolve_room_point(bundle, AREA, 0.1, 0.1, mops=True).center == (1, 1)
    for x in (0.5, 0.6):
        with pytest.raises(ValueError, match="no-mop zone"):
            resolve_room_point(bundle, AREA, x, 0.2, mops=True)


def test_missing_no_mop_outline_blocks_only_wet_point_cleaning(make_point_bundle):
    bundle = make_point_bundle()
    assert resolve_room_point(bundle, AREA, 0.1, 0.1).center == (1, 1)
    with pytest.raises(ProtocolError):
        resolve_room_point(bundle, AREA, 0.1, 0.1, mops=True)


@pytest.mark.parametrize("value", [True, "0.3", None, 0, 1, float("inf"), float("nan")])
def test_fractions_must_be_strict_numeric_values(make_point_bundle, value):
    with pytest.raises(ValueError, match="fraction"):
        resolve_room_point(make_point_bundle(), AREA, value, 0.3)


@pytest.mark.parametrize(
    "args",
    [
        ("..", "v", (1, 1)),
        ("m", ".", (1, 1)),
        ("m", "v", [1, 1]),
        ("m", "v", (1,)),
        ("m", "v", (True, 1)),
        ("m", "v", (1, float("inf"))),
    ],
)
def test_point_target_validates_wire_types(args):
    with pytest.raises(ValueError, match="active map version"):
        PointTarget(*args)


@pytest.mark.parametrize(
    "area",
    [
        replace(AREA, regions=()),
        replace(AREA, regions=(replace(AREA.regions[0], kind=RegionKind.ZONE),)),
    ],
)
def test_point_must_reference_one_room(make_point_bundle, area):
    with pytest.raises(ValueError, match="mapped room"):
        resolve_room_point(make_point_bundle(), area, 0.1, 0.1)


@pytest.mark.parametrize(
    "area",
    [
        replace(AREA, version_id="stale"),
        replace(AREA, map_id="wrong-map"),
        replace(AREA, regions=(replace(AREA.regions[0], region_id="wrong-room"),)),
    ],
)
def test_point_bundle_must_match_map_version_and_room(make_point_bundle, area):
    with pytest.raises(ProtocolError):
        resolve_room_point(make_point_bundle(), area, 0.1, 0.1)


def test_no_policy_layer_is_valid_and_experimental_fallback_is_used(make_point_bundle):
    def alternate(documents, experimental=False):
        manifest = documents["manifest.json"]
        policy = manifest["features"].pop()
        if experimental:
            manifest["experimentalFeatures"] = [policy]
        manifest["features"].append({"type": "floorPlan"})

    point = resolve_room_point(make_point_bundle(mutate=alternate), AREA, 0.22, 0.3)
    assert point.center == (2.2, 3.0)
    with pytest.raises(ValueError, match="keep-out"):
        resolve_room_point(
            make_point_bundle(mutate=lambda docs: alternate(docs, True)), AREA, 0.22, 0.3
        )


@pytest.mark.parametrize("coordinates", [None, [[1, 2]], [[1, 2], [3, 4]]])
def test_point_commands_remain_guarded_when_a_virtual_wall_is_present(
    make_point_bundle, coordinates
):
    def with_wall(documents):
        zone = documents["policyZones.geojson"]["features"][0]
        zone["geometry"] = {"type": "LineString", "coordinates": coordinates}

    with pytest.raises(ProtocolError, match="virtual wall"):
        resolve_room_point(make_point_bundle(mutate=with_wall), AREA, 0.1, 0.1)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda docs: docs.pop("manifest.json"),
        lambda docs: docs["manifest.json"].pop("metadata"),
        lambda docs: docs["manifest.json"]["features"].pop(0),
        lambda docs: docs["manifest.json"]["features"].append(docs["manifest.json"]["features"][0]),
        lambda docs: docs.update({"metadata.json": []}),
        lambda docs: docs["rooms.geojson"].update({"features": {}}),
        lambda docs: docs["rooms.geojson"].update({"features": [42]}),
        lambda docs: docs["rooms.geojson"]["features"].append(docs["rooms.geojson"]["features"][0]),
        lambda docs: docs["borders.geojson"].update({"type": "Point"}),
        lambda docs: docs["borders.geojson"].pop("geometry"),
        lambda docs: docs["borders.geojson"]["geometry"].update({"type": "Point"}),
        lambda docs: docs["borders.geojson"]["geometry"].update({"coordinates": []}),
        lambda docs: docs["borders.geojson"]["geometry"].update({"coordinates": [[]]}),
        lambda docs: docs["borders.geojson"]["geometry"].update({"coordinates": [[[1, 2]]]}),
        lambda docs: docs["borders.geojson"]["geometry"]["coordinates"][0][0].__setitem__(
            1, [4, float("inf")]
        ),
        lambda docs: docs["policyZones.geojson"]["features"][0].pop("properties"),
        lambda docs: docs["policyZones.geojson"]["features"][0]["properties"].pop("type"),
    ],
)
def test_bad_bundles_fail_closed(make_point_bundle, mutate):
    with pytest.raises(ProtocolError):
        resolve_room_point(make_point_bundle(mutate=mutate), AREA, 0.1, 0.1)


@pytest.mark.parametrize("payload", [b"not gzip", gzip.compress(b"not tar")])
def test_wrong_binary_media_is_rejected(payload):
    with pytest.raises(ProtocolError, match="bundle"):
        resolve_room_point(payload, AREA, 0.1, 0.1)


def test_rejects_duplicate_and_link_documents(make_point_bundle):
    member = tarfile.TarInfo("manifest.json")
    with pytest.raises(ProtocolError, match="regular"):
        resolve_room_point(make_point_bundle(add=member), AREA, 0.1, 0.1)
    member.type = tarfile.SYMTYPE
    member.linkname = "metadata.json"
    with pytest.raises(ProtocolError, match="regular"):
        resolve_room_point(
            make_point_bundle(mutate=lambda docs: docs.pop("manifest.json"), add=member),
            AREA,
            0.1,
            0.1,
        )


def test_rejects_decompression_limit_and_sparse_member_size(make_point_bundle, monkeypatch):
    monkeypatch.setattr(point_maps, "MAX_MAP_BYTES", 100)
    with pytest.raises(ProtocolError, match="decompression"):
        resolve_room_point(make_point_bundle(), AREA, 0.1, 0.1)
    large = SimpleNamespace(name="metadata.json", size=101, isfile=lambda: True)
    with pytest.raises(ProtocolError, match="regular"):
        point_maps._document(None, [large], large.name)
