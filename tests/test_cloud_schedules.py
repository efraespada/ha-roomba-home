from copy import deepcopy
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.roomba_home.core.cleaning import CleaningMode, CleaningProfile
from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.maps import (
    AreaTarget,
    CleaningRegion,
    FurnitureRegion,
    RegionKind,
)
from custom_components.roomba_home.core.schedules import (
    associated_households,
    cleaning_schedule_start,
    editable_schedules,
    new_cleaning_schedule,
    next_schedule_start,
    once_weekday,
    schedule_command,
    schedule_metrics,
    schedule_removed,
    weekly_start,
)


def test_weekly_routine_saves_ordered_profiles_without_starting_the_schedule():
    rooms = (
        CleaningRegion("living", RegionKind.ROOM, "Living room"),
        CleaningRegion("hall", RegionKind.ROOM, "Hallway"),
        CleaningRegion("door", RegionKind.ROOM, "Entrance"),
        CleaningRegion("counter", RegionKind.ZONE, "Counter"),
    )
    profiles = (
        CleaningProfile(CleaningMode.VACUUM, suction_level=1),
        CleaningProfile(CleaningMode.MOP, wetness_level=2),
        CleaningProfile(CleaningMode.VACUUM_MOP, suction_level=3, wetness_level=1),
        CleaningProfile(CleaningMode.VACUUM_THEN_MOP, two_pass=False),
    )
    target = AreaTarget("map", "version", rooms, profiles)
    opts = new_cleaning_schedule("first", " Test routine ", weekly_start([5, 1], "10:40"), target)
    assert opts == {
        "robot_id": "first",
        "name": "Test routine",
        "enabled": False,
        "frequency": "WEEKLY",
        "start": {"day": [1, 5], "hour": 10, "min": 40},
        "commands": [
            {
                "command": {
                    "robot_id": "first",
                    "command": "start",
                    "ordered": 1,
                    "p2map_id": "map",
                    "user_p2mapv_id": "version",
                    "params": {"routine_modified": True},
                    "regions": [
                        {
                            "region_id": "living",
                            "type": "rid",
                            "params": {"operatingMode": 2, "suctionLevel": 1},
                        },
                        {
                            "region_id": "hall",
                            "type": "rid",
                            "params": {"operatingMode": 4, "padWetness": {"padPlate": 2}},
                        },
                        {
                            "region_id": "door",
                            "type": "rid",
                            "params": {
                                "operatingMode": 32,
                                "suctionLevel": 3,
                                "padWetness": {"padPlate": 1},
                            },
                        },
                        {
                            "region_id": "counter",
                            "type": "zid",
                            "params": {
                                "operatingMode": 512,
                                "twoPass": False,
                                "routine_modified": True,
                            },
                        },
                    ],
                }
            }
        ],
    }


@pytest.mark.parametrize(
    "name,target",
    [
        (None, None),
        ("", None),
        ("line\nfeed", None),
        (" " * 5, None),
        ("x" * 121, None),
        ("fixture", None),
        ("fixture", AreaTarget("map", "version", ())),
        ("fixture", AreaTarget("map", "version", (CleaningRegion("room", RegionKind.ROOM, None),))),
    ],
)
def test_weekly_routine_rejects_invalid_names_and_incomplete_targets(name, target):
    with pytest.raises(ValueError):
        new_cleaning_schedule("first", name, {}, target)


@pytest.mark.parametrize(
    "groups,removed",
    [
        ([], True),
        ([None], False),
        ([{"household_schedule_id": ".."}], False),
        ([{"household_schedule_id": "other", "schedules": [{}]}], True),
        ([{"household_schedule_id": "fixture"}], False),
        ([{"household_schedule_id": "fixture", "schedules": [None]}], False),
        ([{"household_schedule_id": "fixture", "schedules": [{}]}], False),
        ([{"household_schedule_id": "fixture", "schedules": [{"options": {}}]}], False),
        (
            [{"household_schedule_id": "fixture", "schedules": [{"options": {"deleted": True}}]}],
            True,
        ),
    ],
)
def test_removal_confirmation_requires_an_absent_group_or_explicit_deleted_flag(groups, removed):
    assert schedule_removed({"household_schedules": groups}, "fixture") is removed


def test_household_routes_are_bound_to_selected_associations():
    document = [
        None,
        {},
        {"household_id": "../invalid", "household_robots": []},
        {"household_id": "no-members", "household_robots": {}},
        {"household_id": "empty-house", "household_robots": [{"robot_id": "other"}]},
        {
            "household_id": "fixture.house",
            "household_robots": [
                {},
                None,
                {"robot_id": ["invalid"]},
                {"robot_id": "first"},
                {"robot_id": "other"},
            ],
        },
        {"household_id": "fixture.house", "household_robots": [{"robot_id": "second"}]},
    ]
    assert associated_households(document, frozenset({"first", "second"})) == {
        "fixture.house": frozenset({"first", "second"})
    }
    with pytest.raises(ProtocolError):
        associated_households({}, frozenset())


def entry(**options):
    return {
        "schedule_id": "fixture.schedule",
        "options": {
            "robot_id": "first",
            "enabled": True,
            "frequency": "WEEKLY",
            "start": {"day": [7, 1, 7], "hour": 8, "min": 10},
            "name": "fixture-private",
            **options,
        },
    }


def edit_document(rows, group_id="fixture.group"):
    return {"household_schedules": [{"household_schedule_id": group_id, "schedules": rows}]}


def edit_entry(**options):
    command = {"command": {"command": "start", "robot_id": "first"}}
    return entry(**({"commands": [command]} | options))


@pytest.fixture
def furniture_selection():
    table = FurnitureRegion(
        "table", RegionKind.FURNITURE, "Table", ((0, 0), (1, 0), (1, 1), (0, 1))
    )
    hall = CleaningRegion("hall", RegionKind.ROOM, "Hall")
    return AreaTarget(
        "map",
        "version",
        (table, hall),
        (
            CleaningProfile(CleaningMode.VACUUM, suction_level=1),
            CleaningProfile(CleaningMode.MOP, wetness_level=2),
        ),
    )


@pytest.mark.parametrize("frequency", ["weekly", "once"])
def test_timed_schedule_preserves_furniture_links_and_room_order(furniture_selection, frequency):
    start = cleaning_schedule_start([7], "08:10", frequency)
    options = new_cleaning_schedule(
        "first", "Furniture schedule", start, furniture_selection, frequency=frequency, timestamp=42
    )
    command = options["commands"][0]["command"]
    assert command == {
        "command": "start",
        "ordered": 1,
        "initiator": "rmtApp",
        "time": 42,
        "p2map_id": "map",
        "user_p2mapv_id": "version",
        "params": {},
        "regions": [
            {"region_id": "160", "type": "tid", "params": {"operatingMode": 2, "suctionLevel": 1}},
            {
                "region_id": "hall",
                "type": "rid",
                "params": {"operatingMode": 4, "padWetness": {"padPlate": 2}},
            },
        ],
        "id_multipolys": [
            {
                "id": "160",
                "metadata": {"furniture_id": "table"},
                "poly": [[0, 0], [1, 0], [1, 1], [0, 1]],
            },
        ],
    }
    assert options["enabled"] is False
    # A disabled Sunday rule from an earlier release has the same public timing.
    stored = {**options, "start": {**start, "day": [7]}}
    [row] = editable_schedules(edit_document([entry(**stored)]), "first").values()
    response = row.action_response()
    assert response["regions"] == ["map:furniture:table", "map:rid:hall"]
    assert [
        (item["mode"], item["suction_level"], item["wetness_level"])
        for item in response["region_settings"]
    ] == [("vacuum", 1, None), ("mop", None, 2)]
    assert row.matches_creation(
        new_cleaning_schedule(
            "first",
            "Furniture schedule",
            start,
            furniture_selection,
            frequency=frequency,
            timestamp=99,
        )
    )
    assert row.replace_selection(furniture_selection, 99) == options["commands"]
    assert not row.matches_creation(options | {"name": "Another entry"})


@pytest.mark.parametrize("timestamp", [0, False])
def test_furniture_schedule_requires_a_valid_timestamp(furniture_selection, timestamp):
    with pytest.raises(ValueError, match="positive timestamp"):
        schedule_command("first", furniture_selection, timestamp=timestamp)


@pytest.mark.parametrize("polygons", ["missing", "extra", "empty"])
def test_unmatched_furniture_polygons_do_not_offer_destination_edits(furniture_selection, polygons):
    command = schedule_command("first", furniture_selection, timestamp=42)
    if polygons == "missing":
        command["id_multipolys"].clear()
    if polygons == "extra":
        command["id_multipolys"].append({**command["id_multipolys"][0], "id": "161"})
    if polygons == "empty":
        command["regions"].pop(0)
        command["id_multipolys"].clear()
    [row] = editable_schedules(
        edit_document([edit_entry(commands=[{"command": command}])]), "first"
    ).values()
    assert "region_settings" not in row.action_response()


def test_sunday_forecast_understands_the_native_zero_and_legacy_seven():
    weekly = edit_entry(start={"day": [0, 7], "hour": 11, "min": 10})
    values = schedule_metrics(edit_document([weekly]), frozenset({"first"}))["first"]
    assert values["cloud_schedule_times"] == ({"weekdays": (7,), "time": "11:10", "enabled": True},)
    assert next_schedule_start(values, UTC, datetime(2026, 11, 27, tzinfo=UTC)) == datetime(
        2026, 11, 29, 11, 10, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "name,expected",
    [("Routine", "Routine"), (None, None), ("line\nbreak", None), ("x" * 121, None)],
)
def test_schedule_action_returns_names_only_when_safe(name, expected):
    [schedule] = editable_schedules(edit_document([edit_entry(name=name)]), "first").values()
    assert schedule.action_response() == {
        "id": "fixture.group:fixture.schedule",
        "name": expected,
        "enabled": True,
        "regions": None,
        "weekdays": (1, 7),
        "time": "08:10",
    }
    assert "options" not in repr(schedule)


@pytest.mark.parametrize(
    "rows,group",
    [
        ([], "good"),
        ([None], "good"),
        ([edit_entry(), edit_entry()], "good"),
        ([{**edit_entry(), "schedule_id": "../invalid"}], "good"),
        ([{"schedule_id": "item", "options": None}], "good"),
        ([edit_entry(robot_id="other")], "good"),
        ([edit_entry(enabled=None)], "good"),
        ([edit_entry(deleted=True)], "good"),
        ([edit_entry(frequency="ONCE")], "good"),
        ([edit_entry(commands=None)], "good"),
        ([edit_entry(commands=[])], "good"),
        ([edit_entry(commands=[None])], "good"),
        ([edit_entry(commands=[{}])], "good"),
        ([edit_entry(commands=[{"command": {"command": "dock", "robot_id": "first"}}])], "good"),
        ([edit_entry(commands=[{"command": {"command": "start", "robot_id": "other"}}])], "good"),
        ([edit_entry(end_commands=[{}])], "good"),
        ([edit_entry()], None),
    ],
)
def test_only_verified_single_robot_weekly_schedule_groups_can_be_edited(rows, group):
    assert editable_schedules(edit_document(rows, group), "first") == {}


def test_duplicate_schedule_groups_make_edits_ambiguous():
    group = edit_document([edit_entry()])["household_schedules"][0]
    with pytest.raises(ProtocolError):
        editable_schedules({"household_schedules": [group, group]}, "first")


@pytest.mark.parametrize(
    "days,time",
    [
        ((1, 2), "00:05"),
        ([], "00:05"),
        ([True], "00:05"),
        ([8], "00:05"),
        ([1, 1], "00:05"),
        ([1], None),
        ([1], "1:00"),
        ([1], "24:00"),
        ([1], "23:60"),
        ([1], "23:59:01"),
    ],
)
def test_weekly_start_rejects_unknown_days_or_time(days, time):
    with pytest.raises(ValueError):
        weekly_start(days, time)


def test_weekly_start_serializes_native_days_from_iso_weekdays():
    assert weekly_start([7, 2], "23:59:00") == {"day": [0, 2], "hour": 23, "min": 59}


@pytest.mark.parametrize(("clock", "expected_day"), [("22:39", 3), ("08:30", 4), ("15:42", 4)])
def test_one_time_clock_uses_today_or_tomorrow(clock, expected_day):
    now = datetime(2026, 11, 25, 14, 42, tzinfo=UTC)
    assert once_weekday(clock, ZoneInfo("Europe/Madrid"), now) == expected_day


def test_one_time_clock_rejects_an_ambiguous_local_time():
    now = datetime(2026, 10, 24, 22, tzinfo=UTC)
    with pytest.raises(ValueError, match="clock change"):
        once_weekday("02:30", ZoneInfo("Europe/Madrid"), now)


@pytest.mark.parametrize(("frequency", "days"), [("daily", [3]), ("once", [3, 4])])
def test_schedule_frequency_matches_one_time_day_count(frequency, days):
    with pytest.raises(ValueError, match="supported frequency"):
        cleaning_schedule_start(days, "08:30", frequency)


def test_native_one_time_command_can_rely_on_the_options_robot():
    draft = edit_entry(frequency="ONCE", start={"day": [3], "hour": 22, "min": 39})
    command = draft["options"]["commands"][0]["command"]
    command.pop("robot_id")
    [schedule] = editable_schedules(edit_document([draft]), "first").values()
    assert schedule.start == {"frequency": "once", "weekday": 3, "time": "22:39"}
    command["robot_id"] = "other"
    assert editable_schedules(edit_document([draft]), "first") == {}


def test_schedule_summaries_skip_old_or_deleted_rows_and_hide_names_and_identifiers():
    original = entry()
    disabled = {**entry(enabled=False), "schedule_id": "fixture.disabled"}
    values = [
        None,
        {},
        {"options": False},
        original,
        deepcopy(original),
        disabled,
        {**entry(deleted=True), "schedule_id": "deleted"},
        entry(robot_id="second"),
        {**entry(), "schedule_id": ".."},
    ]
    data = {"household_schedules": [None, {}, {"schedules": values}]}
    result = schedule_metrics(data, frozenset({"first", "empty"}))
    assert result["first"] == {
        "cloud_schedule_count": 2,
        "cloud_enabled_schedule_count": 1,
        "cloud_schedule_times": (
            {"weekdays": (1, 7), "time": "08:10", "enabled": True},
            {"weekdays": (1, 7), "time": "08:10", "enabled": False},
        ),
    }
    assert result["empty"]["cloud_schedule_count"] == 0
    assert result["empty"]["cloud_enabled_schedule_count"] == 0
    assert "fixture" not in repr(result)


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": "false"},
        {"frequency": "future"},
        {"start": None},
        {"start": {"hour": 24, "min": 0, "day": [1]}},
        {"start": {"hour": 0, "min": -1, "day": [1]}},
        {"start": {"hour": 0, "min": 0, "day": True}},
        {"start": {"hour": 0, "min": 0, "day": []}},
        {"start": {"hour": 0, "min": 0, "day": [8]}},
    ],
)
def test_untrusted_or_unknown_schedule_times_are_not_fabricated(change):
    data = {"household_schedules": [{"schedules": [entry(**change)]}]}
    values = schedule_metrics(data, frozenset({"first"}))["first"]
    assert values["cloud_schedule_times"] == ()
    assert values["cloud_schedule_count"] == 1
    assert values["cloud_enabled_schedule_count"] == (None if "enabled" in change else 1)


@pytest.mark.parametrize("value", [None, {}, {"household_schedules": {}}])
def test_bad_cloud_schedule_document_does_not_look_empty(value):
    with pytest.raises(ProtocolError):
        schedule_metrics(value, frozenset({"first"}))


def schedule_for(*starts):
    schedules = [
        {**entry(**options), "schedule_id": f"fixture-{index}"}
        for index, options in enumerate(starts)
    ]
    return schedule_metrics(
        {"household_schedules": [{"schedules": schedules}]}, frozenset({"first"})
    )["first"]


@pytest.mark.parametrize(
    ("day", "hour", "created_at", "now", "expected"),
    [
        (3, 23, "2026-11-25T14:42:00+00:00", (25, 15), (25, 22)),
        (4, 8, "2026-11-25T14:42:00+00:00", (25, 22), (26, 7)),
        (3, 23, "2026-11-25T14:42:00+00:00", (26, 0), None),
        (3, 23, None, (25, 15), None),
        (7, 23, "2026-11-25T14:42:00+00:00", (25, 15), None),
        (3, 8, "2026-11-25T14:42:00+00:00", (25, 15), None),
    ],
)
def test_one_time_next_start_uses_one_provider_date(day, hour, created_at, now, expected):
    summary = schedule_for(
        {
            "frequency": "ONCE",
            "start": {"day": [day], "hour": hour, "min": 0},
            "created_time": created_at,
        }
    )
    actual = next_schedule_start(
        summary, ZoneInfo("Europe/Madrid"), datetime(2026, 11, *now, tzinfo=UTC)
    )
    assert actual == (datetime(2026, 11, *expected, tzinfo=UTC) if expected else None)


def test_one_time_schedule_competes_with_weekly_start():
    summary = schedule_for(
        {"frequency": "WEEKLY", "start": {"day": [3], "hour": 22, "min": 30}},
        {
            "frequency": "ONCE",
            "start": {"day": [3], "hour": 23, "min": 0},
            "created_time": "2026-11-25T14:42:00+00:00",
        },
    )
    now = datetime(2026, 11, 25, 16, tzinfo=UTC)
    assert next_schedule_start(summary, ZoneInfo("Europe/Madrid"), now) == datetime(
        2026, 11, 25, 21, 30, tzinfo=UTC
    )


def test_next_weekly_time_uses_robot_zone_ignores_disabled_and_wraps_the_week():
    summary = schedule_for(
        {"start": {"day": [1], "hour": 8, "min": 15}},
        {"start": {"day": [1], "hour": 8, "min": 5}, "enabled": False},
    )
    zone = ZoneInfo("Europe/Paris")
    assert next_schedule_start(summary, zone, datetime(2026, 11, 23, 7, tzinfo=UTC)) == datetime(
        2026, 11, 23, 7, 15, tzinfo=UTC
    )
    assert next_schedule_start(
        summary, zone, datetime(2026, 11, 23, 7, 15, tzinfo=UTC)
    ) == datetime(2026, 11, 30, 7, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    "unresolved", [{"enabled": "true"}, {"frequency": "ONCE"}, {"start": None}]
)
def test_incomplete_enabled_schedules_leave_the_next_start_unknown(unresolved):
    assert (
        next_schedule_start(schedule_for({}, unresolved), UTC, datetime(2026, 11, 23, tzinfo=UTC))
        is None
    )


def test_no_enabled_schedule_has_no_next_start():
    assert (
        next_schedule_start(
            schedule_for({"enabled": False}), UTC, datetime(2026, 11, 23, tzinfo=UTC)
        )
        is None
    )


@pytest.mark.parametrize("month,day", [(3, 29), (10, 25)])
def test_next_start_is_unknown_if_the_earliest_time_is_affected_by_a_clock_change(month, day):
    summary = schedule_for(
        {"start": {"day": [7], "hour": 2, "min": 30}},
        {"start": {"day": [7], "hour": 6, "min": 0}},
    )
    zone = ZoneInfo("Europe/Paris")
    assert next_schedule_start(summary, zone, datetime(2026, month, day, 0, 0, tzinfo=UTC)) is None
    # The offset change cannot affect the next occurrence after the entire interval has passed.
    assert (
        next_schedule_start(summary, zone, datetime(2026, month, day, 2, 0, tzinfo=UTC)) is not None
    )


def test_unambiguous_earlier_event_can_still_be_reported_before_clock_change():
    summary = schedule_for(
        {"start": {"day": [7], "hour": 2, "min": 30}},
        {"start": {"day": [7], "hour": 1, "min": 0}},
    )
    zone = ZoneInfo("Europe/Paris")
    assert next_schedule_start(summary, zone, datetime(2026, 3, 28, 23, tzinfo=UTC)) == datetime(
        2026, 3, 29, 0, tzinfo=UTC
    )
