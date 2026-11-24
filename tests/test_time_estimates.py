import pytest

from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import AreaTarget, CleaningRegion, RegionKind
from custom_components.roomba_home.core.time_estimates import parse_time_estimates

ROBOT = "fixture-robot"
ROOM_A = CleaningRegion("room-a", RegionKind.ROOM, "Example room")
ROOM_B = CleaningRegion("room-b", RegionKind.ROOM, None)
TARGET = AreaTarget("fixture-map", "fixture-version", (ROOM_A, ROOM_B))
CAPABILITIES = CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True)


def response(rows):
    return {
        "api_version": "v1",
        "robot_id": ROBOT,
        "smart_maps": [
            {
                "smart_map_id": TARGET.map_id,
                "areas": [{"area_id": ROOM_A.region_id, "area_type": "region", "estimates": rows}],
            }
        ],
    }


def estimate(**params):
    return {"unit": "seconds", "value": 145, "params": {"twoPass": False, **params}}


def test_estimates_are_scoped_to_the_requested_map_and_rooms():
    data = response(
        [
            estimate(operatingMode=2, suctionLevel=2, twoPass=True),
            estimate(operatingMode=4, swScrub=0),
            estimate(operatingMode=32, suctionLevel=3, swScrub=1),
            estimate(operatingMode=512, suctionLevel=4, swScrub=0),
        ]
    )
    data["smart_maps"].extend([None, {"smart_map_id": "other-map"}])
    data["smart_maps"][0]["areas"].extend(
        [
            None,
            {"area_type": "zone", "area_id": ROOM_B.region_id, "estimates": []},
            {"area_type": "region", "area_id": [], "estimates": []},
            {"area_type": "region", "area_id": ROOM_B.region_id, "estimates": "invalid"},
        ]
    )
    a, b = parse_time_estimates(data, ROBOT, TARGET, CAPABILITIES)["regions"]
    assert a == {
        "id": "fixture-map:rid:room-a",
        "estimates": [
            {"mode": "vacuum", "duration_seconds": 145, "two_pass": True, "suction_level": 2},
            {"mode": "mop", "duration_seconds": 145, "two_pass": False, "smart_scrub": False},
            {
                "mode": "vacuum_mop",
                "duration_seconds": 145,
                "two_pass": False,
                "suction_level": 3,
                "smart_scrub": True,
            },
            {
                "mode": "vacuum_then_mop",
                "duration_seconds": 145,
                "two_pass": False,
                "suction_level": 4,
                "smart_scrub": False,
            },
        ],
    }
    assert b == {"id": "fixture-map:rid:room-b", "estimates": []}


def test_zone_does_not_inherit_a_room_estimate_with_the_same_id():
    zone = CleaningRegion(ROOM_A.region_id, RegionKind.ZONE, None)
    target = AreaTarget(TARGET.map_id, TARGET.version_id, (ROOM_A, zone))
    data = response([estimate(operatingMode=2, suctionLevel=1)])

    room_result, zone_result = parse_time_estimates(data, ROBOT, target, CAPABILITIES)["regions"]

    assert len(room_result["estimates"]) == 1
    assert zone_result == {"id": zone.segment_id(TARGET.map_id), "estimates": []}


@pytest.mark.parametrize(
    "row",
    [
        None,
        {**estimate(operatingMode=2, suctionLevel=1), "unit": "minutes"},
        {**estimate(operatingMode=2, suctionLevel=1), "value": True},
        {**estimate(operatingMode=2, suctionLevel=1), "value": -1},
        {**estimate(operatingMode=2, suctionLevel=1), "params": []},
        estimate(operatingMode=2, suctionLevel=1, newSetting=True),
        estimate(operatingMode=[]),
        estimate(operatingMode=6),
        estimate(operatingMode=2, twoPass=1, suctionLevel=1),
        estimate(operatingMode=2, suctionLevel="1"),
        estimate(operatingMode=2, suctionLevel=5),
        estimate(operatingMode=2, suctionLevel=1, swScrub=0),
        estimate(operatingMode=4, suctionLevel=1, swScrub=0),
        estimate(operatingMode=4, swScrub=True),
        estimate(operatingMode=4, swScrub=2),
    ],
)
def test_unknown_estimate_rows_are_omitted(row):
    result = parse_time_estimates(response([row]), ROBOT, TARGET, CAPABILITIES)
    assert all(region["estimates"] == [] for region in result["regions"])


def test_only_advertised_robot_options_are_returned():
    capabilities = CleaningCapabilities(frozenset({CleaningMode.VACUUM, CleaningMode.MOP}), 1)
    data = response(
        [
            estimate(operatingMode=2, suctionLevel=1),
            estimate(operatingMode=2, suctionLevel=1, twoPass=True),
            estimate(operatingMode=32, suctionLevel=1, swScrub=0),
            estimate(operatingMode=4, swScrub=1),
        ]
    )
    result = parse_time_estimates(data, ROBOT, TARGET, capabilities)
    assert result["regions"][0]["estimates"] == [
        {"mode": "vacuum", "duration_seconds": 145, "two_pass": False, "suction_level": 1}
    ]
    result = parse_time_estimates(data, ROBOT, TARGET, CleaningCapabilities())
    assert all(region["estimates"] == [] for region in result["regions"])


@pytest.mark.parametrize(
    "document",
    [
        None,
        {**response([]), "api_version": "v2"},
        {**response([]), "robot_id": "other-robot"},
        {**response([]), "smart_maps": False},
        {**response([]), "smart_maps": [{"smart_map_id": TARGET.map_id}]},
        {**response([]), "smart_maps": response([])["smart_maps"] * 2},
        {
            **response([]),
            "smart_maps": [
                {
                    "smart_map_id": TARGET.map_id,
                    "areas": response([])["smart_maps"][0]["areas"] * 2,
                }
            ],
        },
    ],
)
def test_malformed_estimate_documents_are_rejected(document):
    with pytest.raises(ProtocolError):
        parse_time_estimates(document, ROBOT, TARGET, CAPABILITIES)


def test_valid_response_without_a_map_has_no_estimates():
    result = parse_time_estimates({**response([]), "smart_maps": []}, ROBOT, TARGET, CAPABILITIES)
    assert all(region["estimates"] == [] for region in result["regions"])
