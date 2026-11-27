"""Floor-scoped native routine suggestions and replay draft validation."""

from dataclasses import replace

import pytest

from custom_components.roomba_home.core.capabilities import (
    DeviceCapabilities,
    DigitalSpotCapability,
)
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningMode
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import (
    CleaningRegion,
    FurnitureRegion,
    PersistentMap,
    RegionKind,
)
from custom_components.roomba_home.core.quick_routines import read_quick_routines

ROOM = CleaningRegion("room-a", RegionKind.ROOM, "Example room")
ZONE = CleaningRegion("zone-b", RegionKind.ZONE, "Example zone")
OUTLINE = ((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0))
SOFA = FurnitureRegion("sofa-c", RegionKind.FURNITURE, "Example couch", OUTLINE)
FLOOR = PersistentMap("fixture-floor", "current-version", "Example floor", (ROOM, ZONE, SOFA))
ROBOT = "example-robot"
CAPS = DeviceCapabilities(
    cleaning=CleaningCapabilities(frozenset(CleaningMode), 4, 3, True, True),
    digital_spot=DigitalSpotCapability.SUPPORTED,
)


def row(kind="REPLAY", **values):
    command = {
        "command": "point_clean" if kind == "SPOT_CLEAN" else "start",
        "robot_id": ROBOT,
        "p2map_id": FLOOR.map_id,
        "params": {"routine_type": kind},
    }
    if kind == "REPLAY":
        command |= {
            "user_p2mapv_id": "historical-version",
            "params": {"routine_type": kind, "replay_of": "example-reference", "operatingMode": 2},
            "regions": [{"type": "rid", "region_type": "rid", "region_id": "room-a"}],
        }
    return {"commanddefs": [command | values]}


def poly(points=OUTLINE):
    return {"id": "160", "metadata": {"furniture_id": "sofa-c"}, "poly": [list(p) for p in points]}


def recommendation(**overrides):
    return row(
        "CLEAN_DIRTY",
        **(
            {
                "params": {"routine_type": "CLEAN_DIRTY", "clean_score_id": "private-score"},
                "regions": [
                    {
                        "region_id": ROOM.region_id,
                        "params": {
                            "operatingMode": 6,
                            "suctionLevel": 2,
                            "padWetness": {"padPlate": 3},
                        },
                    }
                ],
            }
            | overrides
        ),
    )


def test_native_recommendation_uses_room_ids_profiles_and_automatic_order():
    (routine,) = read_quick_routines([recommendation()], ROBOT, FLOOR, CAPS)["routines"]
    assert routine["name"] == "Clean recommended rooms"
    assert routine["kind"] == "recommended"
    assert routine["ordered"] is False
    assert routine["target_ids"] == [ROOM.segment_id(FLOOR.map_id)]
    assert routine["region_settings"] == [
        {
            "id": ROOM.segment_id(FLOOR.map_id),
            "mode": "vacuum_mop",
            "suction_level": 2,
            "wetness_level": 3,
            "two_pass": None,
            "smart_scrub": None,
            "carpet_boost": None,
        }
    ]
    assert "private-score" not in repr(routine)


def test_recommendation_can_highlight_known_rooms_with_an_unsupported_profile():
    record = recommendation(
        regions=[{"region_id": ROOM.region_id, "params": {"operatingMode": 99}}]
    )
    (routine,) = read_quick_routines([record], ROBOT, FLOOR, CAPS)["routines"]
    assert routine["target_ids"] == [ROOM.segment_id(FLOOR.map_id)]
    assert routine["region_settings"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"ordered": 1},
        {"params": {"routine_type": "CLEAN_DIRTY"}},
        {"params": {"routine_type": "CLEAN_DIRTY", "clean_score_id": None}},
        {"regions": None},
        {"regions": []},
        {"regions": [None]},
        {"regions": [{"region_id": ROOM.region_id}]},
        {"regions": [{"region_id": [], "params": {}}]},
        {"regions": [{"region_id": ZONE.region_id, "params": {}}]},
        {"regions": [{"region_id": ROOM.region_id, "params": {"operatingMode": 2}}] * 2},
    ],
)
def test_recommendation_rejects_ambiguous_or_non_current_room_inventories(change):
    (routine,) = read_quick_routines([recommendation(**change)], ROBOT, FLOOR, CAPS)["routines"]
    assert "target_ids" not in routine
    assert routine["region_settings"] is None


def test_quick_routines_supply_typed_recent_settings_and_suggested_entry_points():
    recent = row() | {"last_run": 1_800_000_000, "time_estimate_seconds": 0}
    data = read_quick_routines([recent, row("CLEAN_ALL"), row("SPOT_CLEAN")], ROBOT, FLOOR, CAPS)
    assert (data["map_id"], data["version"]) == (FLOOR.map_id, FLOOR.version_id)
    recent, all_rooms, spot = data["routines"]
    assert recent == {
        "name": "Recent cleaning",
        "kind": "recent",
        "last_run": "2027-01-15T08:00:00+00:00",
        "duration_seconds": 0,
        "region_settings": [
            {
                "id": ROOM.segment_id(FLOOR.map_id),
                "mode": "vacuum",
                "suction_level": None,
                "wetness_level": None,
                "two_pass": None,
                "smart_scrub": None,
                "carpet_boost": None,
            }
        ],
        "choose_point": False,
    }
    assert all_rooms["region_settings"] == [{"id": ROOM.segment_id(FLOOR.map_id)}]
    assert spot["choose_point"] and spot["region_settings"] is None


def test_ordered_recent_routine_keeps_region_overrides_and_links_equivalent_furniture():
    geometry = poly(tuple((x + 0.00004, y) for x, y in reversed(OUTLINE)))
    record = row(
        ordered=1,
        id_multipolys=[geometry],
        regions=[
            {"type": "tid", "region_id": "160", "params": {"operatingMode": 4, "twoPass": False}},
            {"type": "rid", "region_id": "room-a", "params": {"suctionLevel": 2}},
            {"type": "zid", "region_id": "zone-b", "params": {"twoPass": True}},
        ],
    )
    (routine,) = read_quick_routines([record], ROBOT, FLOOR, CAPS)["routines"]
    assert [profile["id"] for profile in routine["region_settings"]] == [
        SOFA.segment_id(FLOOR.map_id),
        ROOM.segment_id(FLOOR.map_id),
        ZONE.segment_id(FLOOR.map_id),
    ]
    assert [profile["mode"] for profile in routine["region_settings"]] == [
        "mop",
        "vacuum",
        "vacuum",
    ]
    assert [profile["two_pass"] for profile in routine["region_settings"]] == [False, None, True]


@pytest.mark.parametrize(
    "record",
    [
        None,
        {"commanddefs": None},
        {"commanddefs": [None]},
        {"commanddefs": [{}, {}]},
        row(robot_id="foreign"),
        row(p2map_id="foreign"),
        row(params=None),
        row(params={"routine_type": []}),
        row("unknown"),
        row(command="stop"),
    ],
)
def test_quick_routines_filter_invalid_commands_and_foreign_scope(record):
    assert not read_quick_routines([record], ROBOT, FLOOR, CAPS)["routines"]


def test_quick_routines_bound_the_read_and_reject_a_non_list_response():
    assert len(read_quick_routines([row()] * 9, ROBOT, FLOOR, CAPS)["routines"]) == 5
    with pytest.raises(ProtocolError):
        read_quick_routines({}, ROBOT, FLOOR, CAPS)


def test_suggestions_require_capability_and_a_compatible_selection():
    suggestions = [row("CLEAN_ALL"), row("SPOT_CLEAN"), row("CLEAN_ALL", extra=True)]
    unsupported = read_quick_routines(suggestions, ROBOT, FLOOR, replace(CAPS, digital_spot=None))
    assert not unsupported["routines"][1]["choose_point"]
    assert unsupported["routines"][2]["region_settings"] is None
    empty = read_quick_routines(suggestions, ROBOT, replace(FLOOR, regions=()), CAPS)
    assert all(
        not item["choose_point"] and item["region_settings"] is None for item in empty["routines"]
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra": True},
        {"user_p2mapv_id": None},
        {"params": {"routine_type": "REPLAY"}},
        {"params": {"routine_type": "REPLAY", "replay_of": ""}},
        {"regions": None},
        {"regions": []},
        {"regions": [{"type": "rid", "region_id": "room-a"}] * 2},
        {"ordered": True},
        {"ordered": 2},
        {"id_multipolys": {}},
        {"id_multipolys": [None]},
        {"id_multipolys": [poly()]},
        {"regions": [False]},
        {"regions": [{"type": "rid", "region_id": "room-a", "extra": True}]},
        {"regions": [{"type": "rid", "region_id": "room-a", "region_type": "zid"}]},
        {"regions": [{"type": "rid", "region_id": "room-a", "params": []}]},
        {"regions": [{"type": "tid", "region_id": []}]},
        {"regions": [{"type": "tid", "region_id": "160"}]},
        {"regions": [{"type": "rid", "region_id": "missing"}]},
        {"ordered": 1, "regions": [{"type": "rid", "region_id": "room-a"}] * 2},
        {"regions": [{"type": "rid", "region_id": "room-a", "params": {"extra": True}}]},
        {"regions": [{"type": "rid", "region_id": "room-a", "params": {"suctionLevel": 99}}]},
        {
            "regions": [{"type": "tid", "region_id": "160"}],
            "id_multipolys": [poly(tuple((x + 1, y) for x, y in OUTLINE))],
        },
    ],
)
def test_unsafe_replay_shapes_are_listed_but_cannot_be_used_as_drafts(overrides):
    (item,) = read_quick_routines([row(**overrides)], ROBOT, FLOOR, CAPS)["routines"]
    assert item["region_settings"] is None and not item["choose_point"]


def test_recent_furniture_requires_the_matching_current_destination():
    record = row(regions=[{"type": "tid", "region_id": "160"}], id_multipolys=[poly()])
    (item,) = read_quick_routines([record], ROBOT, replace(FLOOR, regions=(ROOM,)), CAPS)[
        "routines"
    ]
    assert item["region_settings"] is None
