"""Provider metadata is parsed into associated maps and typed capabilities."""

import json
from dataclasses import replace

import pytest

from custom_components.roomba_home.core.capabilities import (
    DeviceCapabilities,
    DigitalSpotCapability,
    DockCapabilities,
)
from custom_components.roomba_home.core.capability_protocol import project_capabilities
from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.commands import Command, command_body
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import AreaTarget, parse_maps, resolve_segments


def shadow(**values):
    return {"state": {"reported": values}}


def regions():
    return [
        {"room_id": "room-a", "room_metadata": {"region_type": "rid", "name": "Example"}},
        {"room_id": "zone-b", "room_metadata": {"region_type": "zid"}},
        {"room_id": "adhoc", "room_metadata": {"region_type": "tid"}},
        {},
        None,
    ]


def one_map(**fields):
    return {
        "robot_id": "example-robot",
        "p2map_id": "map-a",
        "active_p2mapv_id": "version.42",
        "state": "active",
        "visible": True,
        "name": "Example map",
        "rooms_metadata": regions(),
        **fields,
    }


def test_nested_capabilities_combine_independent_api_sources():
    caps = project_capabilities(
        {"cap": {"oMode": 550, "p2maps": 3}, "digiCap": {"timeline": 1}, "softwareVer": "26.4"},
        {
            "ro-currentstate": shadow(
                dock={"known": True, "cap": {"evac": 1, "pw": 3, "pd": 3, "fr": 2}},
                tankPresent=False,
            ),
            "ro-stats": shadow(example=5),
            "rw-schedule": shadow(cleanSchedule2=[]),
            "rw-constatus": shadow(connected=False),
        },
    )
    assert caps.cleaning.modes == frozenset(CleaningMode)
    assert caps.dock == DockCapabilities(True, True, True, True, True, False)
    assert all(
        item is True
        for item in (
            caps.persistent_maps,
            caps.schedules,
            caps.history,
            caps.statistics,
            caps.firmware,
            caps.connectivity,
            caps.water_tank,
            caps.diagnostics,
        )
    )
    assert caps.maintenance is None and caps.zone_cleaning is None


def test_absent_or_invalid_capabilities_remain_unknown():
    assert project_capabilities({}, {}) == DeviceCapabilities()
    caps = project_capabilities(
        {"cap": True, "digiCap": "unexpected"},
        {"ro-currentstate": shadow(dock={"known": None, "cap": []})},
    )
    assert caps == replace(DeviceCapabilities(), diagnostics=True)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, DigitalSpotCapability.UNSUPPORTED),
        (1, DigitalSpotCapability.SUPPORTED),
        (2, DigitalSpotCapability.HEATED_WATER),
        (3, None),
        (True, None),
        ("1", None),
    ],
)
def test_digital_spot_capability_accepts_only_advertised_device_codes(code, expected):
    caps = project_capabilities({"cap": {"dSpot": code}}, {})
    assert caps.digital_spot is expected


def test_dock_and_map_capabilities_can_be_explicitly_unsupported():
    caps = project_capabilities(
        {"cap": {"p2maps": 0}, "digiCap": {"timeline": 0}},
        {"ro-currentstate": shadow(dock={"known": False, "cap": {"evac": 1}})},
    )
    assert caps.dock == DockCapabilities(False, False, False, False, False, False)
    assert caps.persistent_maps is False and caps.history is False


def test_unknown_advanced_dock_codes_do_not_advertise_support():
    caps = project_capabilities(
        {},
        {"ro-currentstate": shadow(dock={"known": True, "cap": {"evac": 99, "fr": 1, "pw": 0}})},
    )
    assert caps.dock == DockCapabilities(True, None, False, None, True, True)


def test_unbounded_provider_levels_cannot_produce_huge_feature_lists():
    caps = project_capabilities({"cap": {"oMode": 550, "suctionLvl": 10**20, "ppWetLvl": 100}}, {})
    assert caps.cleaning.maximum_level("suction_level") == 0
    assert caps.cleaning.maximum_level("wetness_level") == 0


def test_map_association_visibility_and_region_types():
    maps = parse_maps(
        [
            None,
            one_map(robot_id="other"),
            one_map(visible=False),
            one_map(state="archived"),
            one_map(rooms_metadata=[*regions(), {"room_id": "bad", "room_metadata": None}]),
        ],
        "example-robot",
    )
    assert len(maps) == 1
    room, zone = maps[0].regions
    assert room.name == "Example" and zone.name is None
    assert room.segment_id(maps[0].map_id) == "map-a:rid:room-a"
    assert zone.segment_id(maps[0].map_id) == "map-a:zid:zone-b"
    assert "Example" not in repr(room) and "map-a" not in repr(maps[0])


@pytest.mark.parametrize(
    "raw",
    [
        {},
        [one_map(p2map_id="http://test")],
        [one_map(active_p2mapv_id=None)],
        [one_map(rooms_metadata={})],
        [one_map(rooms_metadata=[regions()[0]] * 2)],
        [one_map(), one_map()],
    ],
)
def test_invalid_or_ambiguous_maps_are_rejected(raw):
    with pytest.raises(ProtocolError):
        parse_maps(raw, "example-robot")


@pytest.mark.parametrize(
    "ids",
    [
        (),
        [],
        ["x"] * 33,
        [None],
        ["map-a:rid:room-a"] * 2,
        ["map-b:rid:room-a", "map-a:rid:room-a"],
        ["foreign:rid:room-a"],
    ],
)
def test_areas_cannot_include_unknown_duplicate_or_cross_map_ids(ids):
    maps = parse_maps([one_map(), one_map(p2map_id="map-b")], "example-robot")
    with pytest.raises(ValueError):
        resolve_segments(maps, ids)


def test_command_serializes_resolved_room_and_zone_in_input_order():
    maps = parse_maps([one_map()], "example-robot")
    target = resolve_segments(maps, ["map-a:zid:zone-b", "map-a:rid:room-a"])
    payload = json.loads(command_body(Command.VACUUM, 123, CleaningProfile(), target))
    assert payload["p2map_id"] == "map-a" and payload["user_p2mapv_id"] == "version.42"
    assert payload["regions"] == [
        {"region_id": "zone-b", "type": "zid", "region_type": "zid"},
        {"region_id": "room-a", "type": "rid", "region_type": "rid", "region_name": "Example"},
    ]
    assert payload["params"]["operatingMode"] == 2


def test_projected_native_regional_profiles_do_not_leak_to_global_settings():
    areas = resolve_segments(
        parse_maps([one_map()], "example-robot"), ["map-a:rid:room-a", "map-a:zid:zone-b"]
    )
    target = replace(
        areas,
        profiles=(
            CleaningProfile(CleaningMode.VACUUM, suction_level=3),
            CleaningProfile(CleaningMode.MOP, wetness_level=2, smart_scrub=True),
        ),
    )
    payload = json.loads(command_body(Command.VACUUM, 123, CleaningProfile(), target))
    assert payload["params"] == {} and payload["ordered"] == 1
    assert [region["params"] for region in payload["regions"]] == [
        {"operatingMode": 2, "suctionLevel": 3},
        {"operatingMode": 4, "padWetness": {"padPlate": 2}, "swScrub": 1},
    ]
    with pytest.raises(ValueError):
        command_body(Command.VACUUM, 123, target=replace(target, profiles=target.profiles[:1]))


@pytest.mark.parametrize(
    "command,target",
    [
        (Command.VACUUM, {}),
        (Command.VACUUM, AreaTarget("map", "version", ())),
        (
            Command.PAUSE,
            AreaTarget("map", "version", parse_maps([one_map()], "example-robot")[0].regions),
        ),
    ],
)
def test_map_targets_require_a_nonnempty_new_mission(command, target):
    with pytest.raises(ValueError):
        command_body(command, 123, target=target)
