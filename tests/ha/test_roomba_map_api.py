import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import floor, pi
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components.vacuum.const import DATA_COMPONENT
from homeassistant.core import Context
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_registry

from custom_components.roomba_home.const import CONF_SHOW_MAPS, DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.actions import Command
from custom_components.roomba_home.core.area_preferences import read_area_defaults
from custom_components.roomba_home.core.capabilities import DigitalSpotCapability, SkipCapability
from custom_components.roomba_home.core.capability_protocol import project_capabilities
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.client import MapEditAcknowledgement
from custom_components.roomba_home.core.commands import command_body
from custom_components.roomba_home.core.errors import (
    ApiError,
    AuthenticationError,
    ProgramSelectionChanged,
    ProtocolError,
    RateLimited,
)
from custom_components.roomba_home.core.history import mission_reports
from custom_components.roomba_home.core.live_coverage import CELL_SIZE
from custom_components.roomba_home.core.live_maps import (
    MissionPath,
    MissionPoint,
    MissionTimeline,
    Position,
    PositionBatch,
    mission_timeline,
)
from custom_components.roomba_home.core.live_route import RawRouteReference
from custom_components.roomba_home.core.map_snapshots import capture_snapshot
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.core.point_maps import PointTarget
from custom_components.roomba_home.live_stream import MapWatch
from custom_components.roomba_home.map_api import live_geometry
from custom_components.roomba_home.map_history import map_history

MAP = PersistentMap(
    "map-a",
    "version.42",
    "Ground floor",
    (
        CleaningRegion("room-a", RegionKind.ROOM, "Office"),
        CleaningRegion("zone-a", RegionKind.ZONE, "Dining zone"),
    ),
)
ENTITY = "vacuum.robot_0"
CAPTURE_BACKUP = {
    "type": "roomba_home/capture_map_backup",
    "entity_id": ENTITY,
    "map_id": MAP.map_id,
    "version": MAP.version_id,
    "inventory_id": MAP.inventory_id,
    "settings_id": MAP.settings_id,
}
HISTORY = {"id": 1, "type": "roomba_home/mission_history", "entity_id": ENTITY}
MAINTENANCE = {"id": 1, "type": "roomba_home/maintenance", "entity_id": ENTITY}
SCORES = {
    "id": 1,
    "type": "roomba_home/cleaning_scores",
    "entity_id": ENTITY,
    "map_id": MAP.map_id,
    "version": MAP.version_id,
}
DIVIDE = {
    "id": 1,
    "type": "roomba_home/edit_rooms",
    "entity_id": ENTITY,
    "map_id": MAP.map_id,
    "version": MAP.version_id,
    "inventory_id": MAP.inventory_id,
    "operation": "split",
    "room_ids": ["room-a"],
    "split_points": [-1, 4, 11, 4],
}
RENAME_FLOOR = {
    "id": 1,
    "type": "roomba_home/edit_floor_settings",
    "entity_id": ENTITY,
    "map_id": MAP.map_id,
    "version": MAP.version_id,
    "inventory_id": MAP.inventory_id,
    "settings_id": MAP.settings_id,
    "operation": "rename",
    "name": "Ático",
}


@pytest.fixture
async def configured(hass, entry, robot_states, make_point_bundle, map_display_layers):
    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_MAPS: True})
    robot = replace(
        robot_states["fixture-0"],
        telemetry={"maps_available": True},
        capabilities=replace(robot_states["fixture-0"].capabilities, persistent_maps=True),
    )

    def with_zone(documents):
        map_display_layers(documents)
        documents["manifest.json"]["features"].append(
            {"type": "cleanZones", "filepath": "clean-zones.geojson"}
        )
        zone = {
            "type": "Feature",
            "id": "zone-a",
            "geometry": {"type": "Polygon", "coordinates": [[[3, 3], [6, 3], [6, 5], [3, 3]]]},
        }
        documents["clean-zones.geojson"] = {
            "type": "FeatureCollection",
            "features": [
                zone,
                zone | {"id": "pending-zone", "properties": {"name": "Pending zone"}},
            ],
        }
        policy_file = next(
            layer["filepath"]
            for layer in documents["manifest.json"]["features"]
            if layer["type"] == "policyZones"
        )
        documents[policy_file]["features"].append(
            {
                "type": "Feature",
                "properties": {"type": "KeepOutZone"},
                "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 2]]},
            }
        )
        documents[policy_file]["features"].append(
            {
                "type": "Feature",
                "properties": {"type": "NoMopZone"},
                "geometry": zone["geometry"],
            }
        )

    async def initial(account):
        account._maps = {robot.robot_id: (MAP,)}
        account._maps_available = {robot.robot_id: True}
        account.client.map_geometry = AsyncMock(return_value=make_point_bundle(mutate=with_zone))
        account.client.maps = AsyncMock(return_value=(MAP,))
        return {robot.robot_id: robot}

    with patch.object(RoombaCoordinator, "_async_update_data", initial):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry.runtime_data


@pytest.fixture
def history_reports(configured):
    row = {"robot_id": "fixture-0", "timestamp": 1700000500, "cmd": {"command": "start"}}
    recent = {**row, "p2maps": [{"p2map_id": MAP.map_id, "p2mapv_id": "mission-revision"}]}
    reports = mission_reports([recent, {**row, "timestamp": 1700000000}], "fixture-0")
    configured.client.mission_reports = AsyncMock(return_value=reports)
    return reports


async def test_history_reads_the_exact_archive_using_read_permission(
    configured, history_reports, picea_archive, hass_ws_client, hass_admin_user
):
    zone = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    wall = [[3, 3], [4, 3]]
    configured.client.map_geometry.return_value = picea_archive(
        version="mission-revision",
        zones=[("125", "Archived zone", zone)],
        restrictions=[
            {
                "id": "127",
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": wall},
                "properties": {"type": "KeepOutZone"},
            }
        ],
    )
    socket = await hass_ws_client()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity, policy: policy == POLICY_READ,
    ):
        await socket.send_json(HISTORY)
        records = (await socket.receive_json())["result"]["missions"]
        assert [record["map_count"] for record in records] == [1, 0]
        configured.client.map_geometry.assert_not_awaited()
        await socket.send_json(HISTORY | {"id": 2, "report_id": records[0]["id"]})
        report = (await socket.receive_json())["result"]
        assert report["geometry"]["rooms"]
        assert report["geometry"]["saved_zones"] == [[zone]]
        assert report["geometry"]["virtual_walls"] == [wall]
        assert report["mission"] == records[0]
        configured.client.map_geometry.assert_awaited_once_with(MAP.map_id, "mission-revision")
        assert configured.maps_for_robot("fixture-0") == (MAP,)
        assert "mission-revision" not in repr(report)


@pytest.mark.parametrize("counters_available", [True, False])
async def test_maintenance_requires_only_read_access_and_works_without_maps(
    configured, hass_ws_client, hass_admin_user, counters_available
):
    robot = configured.data["fixture-0"]
    catalog = {
        "147": {"part_sku": "4849916"},
        "72": {
            "part_sku": "4849940",
            "replacement_url": "https://directory.irobotapi.com/v1/ecom/pdp-app/ES/4849940",
        },
    }
    configured.show_maps = False
    configured.last_update_success = counters_available
    configured.data["fixture-0"] = replace(
        robot,
        telemetry={
            "part_references": catalog,
            "part_72_usage": 0,
            "part_72_remaining": 10,
            "part_72_count_type": "minutes",
            "parts_available": True,
        },
        capabilities=replace(
            robot.capabilities, dock=replace(robot.capabilities.dock, recognized=True)
        ),
    )
    socket = await hass_ws_client()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda entity, policy: entity == ENTITY and policy == POLICY_READ,
    ):
        await socket.send_json(MAINTENANCE)
        report = (await socket.receive_json())["result"]
    assert report["robot"] == robot.name
    assert report["counters_available"] is counters_available
    assert [part["part"] for part in report["parts"]] == ["filter", "dust_bag"]
    assert report["parts"][0]["replacement_url"] == catalog["72"]["replacement_url"]
    assert report["parts"][0]["usage"] == (0 if counters_available else None)
    assert report["parts"][1]["usage"] is None and report["parts"][1]["dock"] is True
    configured.client.map_geometry.assert_not_awaited()


async def test_maintenance_rejects_denied_missing_or_unrelated_entities(
    hass, configured, hass_ws_client, hass_admin_user
):
    socket = await hass_ws_client()
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(MAINTENANCE)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(MAINTENANCE | {"id": 2, "entity_id": "vacuum.other"})
    assert (await socket.receive_json())["error"]["code"] == "maintenance_unavailable"
    with patch.dict(hass.data, {DATA_COMPONENT: None}):
        await socket.send_json(MAINTENANCE | {"id": 3})
        assert (await socket.receive_json())["error"]["code"] == "maintenance_unavailable"
    configured.data = {}
    await socket.send_json(MAINTENANCE | {"id": 4})
    assert (await socket.receive_json())["error"]["code"] == "maintenance_unavailable"


async def test_remembered_preferences_follow_verified_destinations_and_refresh_without_geometry(
    configured,
    hass_ws_client,
    hass_admin_user,
    picea_archive,
):
    def current_floor(level):
        remembered = read_area_defaults(
            {"last_operating_mode": 2, "operating_mode_defaults": {"2": {"suctionLevel": level}}}
        )
        return replace(
            MAP,
            regions=(
                replace(MAP.regions[0], remembered=remembered),
                replace(MAP.regions[1], remembered=remembered),
                CleaningRegion(
                    "former-room", RegionKind.ROOM, "Former room", remembered=remembered
                ),
            ),
        )

    robot = configured.data["fixture-0"]
    configured.data["fixture-0"] = replace(
        robot,
        capabilities=replace(
            robot.capabilities,
            cleaning=CleaningCapabilities(frozenset({CleaningMode.VACUUM}), suction_levels=4),
        ),
    )
    configured._maps["fixture-0"] = (current_floor(1),)
    configured.client.map_geometry.return_value = picea_archive(
        zones=[("zone-a", "Dining zone", [[3, 3], [6, 3], [6, 5], [3, 3]])]
    )
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}

    def verify(result, level):
        preferences = result["remembered_cleaning"]
        assert set(preferences) == {"map-a:rid:room-a", "map-a:zid:zone-a"}
        for saved in preferences.values():
            assert saved["last_mode"] == "vacuum"
            assert saved["preferred"] == {"vacuum": 2}
            assert saved["profiles"][0]["can_apply"] is True
            assert saved["profiles"][0]["settings"] == {"mode": "vacuum", "suction_level": level}

    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity, permission: permission == POLICY_READ,
    ):
        await socket.send_json(request)
        first = (await socket.receive_json())["result"]
        verify(first, 1)
        assert "geometry" in first

        configured._maps["fixture-0"] = (current_floor(3),)
        await socket.send_json(
            request | {"id": 2, "known_map_id": "map-a", "known_version": "version.42"}
        )
        second = (await socket.receive_json())["result"]
        verify(second, 3)
        assert second["inventory_id"] == first["inventory_id"]
        assert "geometry" not in second

        with patch.object(configured, "async_floor_plan", return_value=None):
            await socket.send_json(
                request | {"id": 3, "known_map_id": "map-a", "known_version": "version.42"}
            )
            result = (await socket.receive_json())["result"]
            assert "remembered_cleaning" not in result
    configured.client.map_geometry.assert_awaited_once()


@pytest.mark.parametrize("archive_available", [True, False])
async def test_history_keeps_the_requested_order_and_final_destination_results(
    configured, picea_archive, hass_ws_client, archive_available
):
    revision = "report-archive"
    row = {
        "robot_id": "fixture-0",
        "timestamp": 1700000500,
        "done": "ok",
        "p2maps": [{"p2map_id": MAP.map_id, "p2mapv_id": revision}],
        "cmd": {
            "command": "start",
            "p2map_id": MAP.map_id,
            "user_p2mapv_id": "requested-revision",
            "ordered": 1,
            "regions": [
                {
                    "type": "zid",
                    "region_id": "125",
                    "params": {"operatingMode": 4, "padWetness": {"padPlate": 3}},
                },
                {
                    "type": "rid",
                    "region_id": "room-a",
                    "params": {"operatingMode": 2, "twoPass": False},
                },
                {"type": "tid", "region_id": "unvisited-region"},
            ],
        },
        "timeline": {
            "finEvents": [
                {
                    "type": "room",
                    "ts": 1700000200,
                    "room": {
                        "p2mapId": MAP.map_id,
                        "p2mapvId": revision,
                        "rid": "room-a",
                        "status": 5,
                        "passCount": 0,
                    },
                },
                {
                    "type": "zone",
                    "ts": 1700000150,
                    "zone": {
                        "p2mapId": MAP.map_id,
                        "p2mapvId": revision,
                        "zid": "125",
                        "status": 0,
                    },
                },
            ]
        },
    }
    reports = mission_reports([row], "fixture-0")
    configured.client.mission_reports = AsyncMock(return_value=reports)
    if archive_available:
        configured.client.map_geometry.return_value = picea_archive(
            version=revision,
            zones=[("125", "Old cleaning zone", [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]])],
        )
    else:
        configured.client.map_geometry.side_effect = ApiError(404)
    socket = await hass_ws_client()
    await socket.send_json(HISTORY | {"report_id": reports[0].key})
    report = (await socket.receive_json())["result"]
    assert (report["geometry"] is not None) is archive_available
    assert report["mission"]["outcome"] == "completed"
    assert report["plan"] == {
        "ordered": True,
        "total": 3,
        "completed": 1,
        "destinations": [
            {
                "kind": "saved_zone",
                "name": "Old cleaning zone" if archive_available else None,
                "mode": "mop",
                "status": "finished",
                "requested_settings": {"wetness_level": 3},
            },
            {
                "kind": "room",
                "name": "Office" if archive_available else None,
                "mode": "vacuum",
                "status": "user_ended",
                "requested_settings": {"two_pass": False},
                "reported_pass_count": 0,
            },
            {"kind": "temporary_zone", "name": None, "status": "unreported"},
        ],
    }
    assert "requested-revision" not in repr(report) and "unvisited-region" not in repr(report)
    configured.client.map_geometry.assert_awaited_once_with(MAP.map_id, revision)


@pytest.mark.parametrize(
    "fallback", ["available", "unavailable", "bad_revision", "same_revision", "other_floor"]
)
async def test_history_checks_the_requested_revision_for_a_missing_destination_name(
    configured, picea_archive, fallback
):
    archive_revision = "archived"
    requested_revision = archive_revision if fallback == "same_revision" else "requested"
    archived_floor = "other-map" if fallback == "other_floor" else MAP.map_id
    row = {
        "robot_id": "fixture-0",
        "timestamp": 1700000500,
        "p2maps": [{"p2map_id": archived_floor, "p2mapv_id": archive_revision}],
        "cmd": {
            "command": "start",
            "p2map_id": MAP.map_id,
            "user_p2mapv_id": requested_revision,
            "regions": [{"type": "rid", "region_id": "room-a"}],
        },
    }
    reports = mission_reports([row], "fixture-0")
    configured.client.mission_reports = AsyncMock(return_value=reports)

    def unnamed(documents):
        del documents["rooms.geojson"]["features"][0]["properties"]["name"]

    archive = picea_archive(map_id=archived_floor, version=archive_revision, mutate=unnamed)
    second_read = {
        "available": picea_archive(version=requested_revision),
        "unavailable": ApiError(404),
        "bad_revision": picea_archive(version="wrong"),
    }
    configured.client.map_geometry.side_effect = [archive, second_read.get(fallback)]
    detail = await configured.async_mission_history("fixture-0", reports[0].key)
    assert detail["geometry"]["rooms"][0]["name"] is None
    target = detail["plan"]["destinations"][0]
    assert target["name"] == ("Office" if fallback == "available" else None)
    assert target["status"] == "unreported"
    calls = [(archived_floor, archive_revision)]
    if fallback in second_read:
        calls.append((MAP.map_id, requested_revision))
    assert [call.args for call in configured.client.map_geometry.await_args_list] == calls


async def test_history_rejects_unauthorized_or_stale_requests_before_fetching_geometry(
    configured, history_reports, hass_ws_client, hass_admin_user
):
    socket = await hass_ws_client()
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(HISTORY)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    configured.client.mission_reports.assert_not_awaited()
    await socket.send_json(HISTORY | {"id": 2, "entity_id": "vacuum.other"})
    assert (await socket.receive_json())["error"]["code"] == "history_unavailable"
    await socket.send_json(HISTORY | {"id": 3, "report_id": "a" * 64})
    assert (await socket.receive_json())["error"]["code"] == "report_not_found"
    await socket.send_json(HISTORY | {"id": 4, "report_id": history_reports[0].key, "map_index": 1})
    assert (await socket.receive_json())["error"]["code"] == "report_not_found"
    configured.client.map_geometry.assert_not_awaited()


@pytest.mark.parametrize("missing", ["no_reference", "expired", "bad_archive"])
async def test_history_keeps_measurements_when_geometry_is_unavailable(
    configured, history_reports, missing
):
    report = history_reports[-1 if missing == "no_reference" else 0]
    if missing == "expired":
        configured.client.map_geometry.side_effect = ApiError(404)
    else:
        configured.client.map_geometry.return_value = b"invalid archive"
    detail = await configured.async_mission_history("fixture-0", report.key)
    assert detail["geometry"] is None and detail["mission"] == report.summary()
    assert configured.client.map_geometry.await_count == (missing != "no_reference")


async def test_history_does_not_report_a_rate_limited_map_as_missing(configured, history_reports):
    configured.client.map_geometry.side_effect = RateLimited(60)
    with pytest.raises(HomeAssistantError) as error:
        await configured.async_mission_history("fixture-0", history_reports[0].key)
    assert error.value.translation_key == "map_rate_limited"


@pytest.mark.parametrize("cause", ["closed", "disabled", "unselected"])
async def test_history_requires_enabled_maps_and_a_selected_robot(
    configured, history_reports, cause
):
    robot_id = "fixture-0"
    if cause == "closed":
        configured._closed = True
    elif cause == "disabled":
        configured.show_maps = False
    else:
        robot_id = "unknown"
    with pytest.raises(HomeAssistantError) as error:
        await configured.async_mission_history(robot_id)
    assert error.value.translation_key == "history_unavailable"
    configured.client.mission_reports.assert_not_awaited()


async def test_history_handles_absent_platform_and_authentication(
    hass, configured, history_reports, hass_ws_client, monkeypatch
):
    from homeassistant.components.vacuum.const import DATA_COMPONENT

    socket = await hass_ws_client()
    configured.client.mission_reports.side_effect = AuthenticationError()
    await socket.send_json(HISTORY)
    assert (await socket.receive_json())["error"]["message"] == "Authentication is required."
    with monkeypatch.context() as fixture:
        fixture.delitem(hass.data, DATA_COMPONENT)
        await socket.send_json(HISTORY | {"id": 2})
        assert (await socket.receive_json())["error"]["code"] == "history_unavailable"


async def test_history_sanitizes_unclassified_local_errors(configured, hass_ws_client):
    socket = await hass_ws_client()
    with patch.object(
        configured,
        "async_mission_history",
        AsyncMock(side_effect=HomeAssistantError("History is unavailable.")),
    ):
        await socket.send_json(HISTORY)
        assert (await socket.receive_json())["error"]["code"] == "history_unavailable"


async def test_cleaning_scores_can_be_read_by_service_and_with_read_only_permission(
    hass, configured, hass_ws_client, hass_admin_user
):
    reading = {"rooms": [{"id": "map-a:rid:room-a", "score": 0, "name": "Office"}]}
    configured.client.map_cleaning_scores = AsyncMock(return_value=reading)
    response = await hass.services.async_call(
        DOMAIN,
        "get_map_cleaning_scores",
        {"entity_id": ENTITY},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert response == {ENTITY: reading}
    socket = await hass_ws_client()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity, policy: policy == POLICY_READ,
    ):
        await socket.send_json(SCORES)
        assert (await socket.receive_json())["result"] == reading
    assert configured.client.map_cleaning_scores.await_count == 2
    robot_id, floor = configured.client.map_cleaning_scores.await_args.args
    assert robot_id == "fixture-0" and floor.version_id == MAP.version_id
    assert MAP.regions[0] in floor.regions


async def test_score_websocket_rejects_unassociated_maps_and_old_revisions(
    configured, hass_ws_client, hass_admin_user
):
    configured.client.map_cleaning_scores = AsyncMock()
    socket = await hass_ws_client()
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(SCORES)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    for identifier, overrides, code in (
        (2, {"entity_id": "vacuum.other"}, "map_unavailable"),
        (3, {"map_id": "other-map"}, "map_changed"),
        (4, {"version": "older"}, "map_changed"),
    ):
        await socket.send_json(SCORES | {"id": identifier} | overrides)
        assert (await socket.receive_json())["error"]["code"] == code
    configured.client.map_cleaning_scores.assert_not_awaited()
    configured.client.map_geometry.assert_not_awaited()


async def test_score_reads_offer_mode_scoped_recommendations_when_supported(
    configured, hass_ws_client
):
    robot_id = "fixture-0"
    state = configured.data[robot_id]
    capabilities = project_capabilities(
        {
            "cap": {"oMode": 550, "suctionLvl": 4, "ppWetLvl": 3, "multiPass": 1, "scrub": 2},
            "digiCap": {"cleaningProfiles": 2},
        },
        {},
    )
    configured.async_set_updated_data({robot_id: replace(state, capabilities=capabilities)})
    reading = {
        "map": {"id": MAP.map_id, "version": MAP.version_id},
        "rooms": [
            {
                "id": "map-a:rid:room-a",
                "score": 0.5,
                "preferences": {
                    "mode": "vacuum_mop",
                    "suction_level": 3,
                    "wetness_level": 2,
                    "two_pass": True,
                },
            }
        ],
    }
    configured.client.map_cleaning_scores = AsyncMock(return_value=reading)
    socket = await hass_ws_client()
    await socket.send_json(SCORES)
    response = (await socket.receive_json())["result"]
    preset = response.pop("smart_presets")["map-a:rid:room-a"]
    assert response == reading
    assert preset["vacuum"] == {"suction_level": 3, "two_pass": True}
    assert preset["mop"] == {"wetness_level": 2, "two_pass": True}
    assert preset["vacuum_then_mop"] == {
        "wetness_level": 2,
        "suction_level": 3,
        "two_pass": True,
    }
    configured.async_set_updated_data({})
    assert await configured.async_map_cleaning_scores(robot_id) == reading


async def test_score_queries_distinguish_authentication_and_local_errors(
    hass, configured, hass_ws_client, monkeypatch
):
    from homeassistant.components.vacuum.const import DATA_COMPONENT

    configured.client.map_cleaning_scores = AsyncMock(side_effect=AuthenticationError())
    socket = await hass_ws_client()
    await socket.send_json(SCORES)
    assert (await socket.receive_json())["error"]["message"] == "Authentication is required."
    with pytest.raises(ConfigEntryAuthFailed):
        await hass.services.async_call(
            DOMAIN,
            "get_map_cleaning_scores",
            {"entity_id": ENTITY},
            blocking=True,
            return_response=True,
        )
    with patch.object(
        configured,
        "async_map_cleaning_scores",
        AsyncMock(side_effect=HomeAssistantError("Unavailable")),
    ):
        await socket.send_json(SCORES | {"id": 2})
        assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    monkeypatch.delitem(hass.data, DATA_COMPONENT)
    await socket.send_json(SCORES | {"id": 3})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"


@pytest.mark.parametrize(
    ("cause", "error"),
    [
        ("closed", "map_unavailable"),
        ("disabled", "map_unavailable"),
        ("unselected", "map_unavailable"),
        ("stale refresh", "map_unavailable"),
        ("unavailable inventory", "map_unavailable"),
        ("ambiguous floor", "map_selection_required"),
        ("invalid geometry", "map_unavailable"),
    ],
)
async def test_score_queries_only_use_a_current_opted_in_floor(configured, cause, error):
    robot_id = "fixture-0"
    if cause == "closed":
        configured._closed = True
    elif cause == "disabled":
        configured.show_maps = False
    elif cause == "unselected":
        robot_id = "unknown"
    elif cause == "stale refresh":
        configured.last_update_success = False
    elif cause == "unavailable inventory":
        configured._maps_available[robot_id] = False
    elif cause == "ambiguous floor":
        configured._maps[robot_id] = (MAP, replace(MAP, map_id="other"))
    else:
        configured.client.map_geometry.return_value = b"malformed geometry"
    configured.client.map_cleaning_scores = AsyncMock()
    with pytest.raises(HomeAssistantError) as failure:
        await configured.async_map_cleaning_scores(robot_id)
    assert failure.value.translation_key == error
    configured.client.map_cleaning_scores.assert_not_awaited()


async def test_skip_service_and_robot_button_are_exposed_for_reported_support(
    hass, entry, configured
):
    robot_id = "fixture-0"
    robot = configured.data[robot_id]
    state = replace(
        robot, capabilities=replace(robot.capabilities, skip=SkipCapability.CURRENT_AREA)
    )
    configured.async_set_updated_data({robot_id: state})
    await hass.async_block_till_done()
    entity_id = entity_registry.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.unique_id}_{robot_id}_skip_current_area"
    )
    assert entity_id is not None and hass.states.get(entity_id).state == "unavailable"
    with patch.object(configured, "async_command", new_callable=AsyncMock) as command:
        await hass.services.async_call(
            DOMAIN, "skip_current_area", {"entity_id": ENTITY, "review_id": "a" * 64}, blocking=True
        )
    command.assert_awaited_once_with(robot_id, Command.SKIP, reviewed_skip="a" * 64)


async def test_websocket_floor_uses_reported_routine_presets_and_saved_default_mode(
    hass_ws_client, configured
):
    robot_id = "fixture-0"
    state = configured.data[robot_id]
    capabilities = project_capabilities(
        {
            "cap": {"oMode": 550, "suctionLvl": 4, "ppWetLvl": 3, "multiPass": 1, "scrub": 2},
            "digiCap": {"cleaningProfiles": 2},
        },
        {},
    )
    configured.profiles[robot_id] = CleaningProfile(CleaningMode.MOP)
    configured.async_set_updated_data({robot_id: replace(state, capabilities=capabilities)})
    socket = await hass_ws_client()
    await socket.send_json({"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    response = await socket.receive_json()
    assert response["success"]
    cleaning = response["result"]["cleaning"]
    assert cleaning["default_mode"] == "mop"
    assert cleaning["supports_smart_presets"] is True
    assert set(cleaning["presets"]) == {mode.value for mode in CleaningMode}
    assert cleaning["presets"]["vacuum_then_mop"]["deep"] == {
        "mode": "vacuum_then_mop",
        "suction_level": 4,
        "wetness_level": 3,
        "smart_scrub": False,
        "two_pass": True,
        "carpet_boost": None,
    }


async def test_websocket_map_returns_selectable_geometry_and_only_sends_it_when_changed(
    hass_ws_client, configured, hass_admin_user
):
    socket = await hass_ws_client()
    initial = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(initial)
    message = await socket.receive_json()
    assert message["success"], message
    result = message["result"]
    assert result["map"] == {"id": MAP.map_id, "version": MAP.version_id}
    assert result["can_clean_point"] is False
    assert result["cleaning"]["presets"] == {}
    assert result["maps"] == [{"id": MAP.map_id, "name": MAP.name}]
    assert result["geometry"]["keep_out"]
    assert result["geometry"]["virtual_walls"] == [[[1, 1], [2, 2]]]
    assert result["geometry"]["no_mop"] == [[[[3, 3], [6, 3], [6, 5], [3, 3]]]]
    assert result["geometry"]["presentation"] == {
        "walls": [{"kind": "exterior", "points": [[0, 0], [10, 0]]}],
        "carpets": [[[[4, 0], [6, 0], [6, 2], [4, 0]]]],
        "docks": [[8, 1]],
    }
    assert result["geometry"]["unlinked_zone_count"] == 1
    assert [(r["name"], r["kind"], bool(r["polygons"])) for r in result["geometry"]["regions"]] == [
        ("Office", "room", True),
        ("Dining zone", "zone", True),
    ]
    assert result["live"] == {"trail": [], "position": None}
    cached = initial | {
        "id": 2,
        "map_id": MAP.map_id,
        "known_version": MAP.version_id,
        "known_inventory": result["inventory_id"],
    }
    await socket.send_json(cached)
    assert "geometry" not in (await socket.receive_json())["result"]

    await socket.send_json(initial | {"id": 3, "entity_id": "vacuum.other"})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    configured.show_maps = False
    await socket.send_json(initial | {"id": 4})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    configured.show_maps = True
    configured._maps_available["fixture-0"] = False
    await socket.send_json(initial | {"id": 5})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    configured.last_update_success = False
    await socket.send_json(initial | {"id": 6})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"

    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(initial | {"id": 7})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"


async def test_mapping_status_is_available_before_the_first_saved_floor(
    configured, hass_ws_client, hass_admin_user
):
    robot_id = "fixture-0"
    configured._maps[robot_id] = ()
    old = configured.data[robot_id]
    configured.data[robot_id] = replace(old, cycle="train", phase="stop")
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(request)
    snapshot = (await socket.receive_json())["result"]
    assert snapshot["map"] is None and snapshot["maps"] == []
    assert snapshot["mapping"] == {"can_start": True, "activity": "paused"}
    assert "geometry" not in snapshot
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, policy: policy == "read",
    ):
        await socket.send_json(request | {"id": 2})
        snapshot = (await socket.receive_json())["result"]
        assert snapshot["mapping"] == {"can_start": False, "activity": "paused"}


@pytest.mark.parametrize(
    ("connected", "phase", "cycle", "modes", "can_control", "available"),
    [
        (True, "charge", "none", frozenset({CleaningMode.VACUUM}), True, True),
        (True, "charge", "clean", frozenset({CleaningMode.VACUUM}), True, False),
        (True, "stop", "clean", frozenset({CleaningMode.VACUUM}), True, False),
        (False, "charge", "none", frozenset({CleaningMode.VACUUM}), True, False),
        (True, "charge", "none", frozenset(), True, False),
        (True, "charge", "none", frozenset({CleaningMode.VACUUM}), False, False),
    ],
)
async def test_clean_everywhere_is_only_offered_for_an_idle_controllable_robot(
    configured,
    hass_ws_client,
    hass_admin_user,
    connected,
    phase,
    cycle,
    modes,
    can_control,
    available,
):
    robot_id = "fixture-0"
    state = configured.data[robot_id]
    capabilities = replace(
        state.capabilities, cleaning=replace(state.capabilities.cleaning, modes=modes)
    )
    configured.data[robot_id] = replace(
        state, connected=connected, phase=phase, cycle=cycle, capabilities=capabilities
    )
    configured._maps[robot_id] = ()
    socket = await hass_ws_client()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, policy: policy == POLICY_READ or can_control,
    ):
        await socket.send_json({"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
        response = (await socket.receive_json())["result"]
    assert response["map"] is None
    assert response["can_clean_everywhere"] is available


async def test_mapping_completion_refreshes_saved_floors_before_the_regular_poll(configured):
    robot_id = "fixture-0"
    ready = configured.data[robot_id]
    configured.data[robot_id] = replace(ready, cycle="train", phase="run")
    configured._maps_due = 999
    await configured._refresh_maps({robot_id: replace(ready, cycle="none")}, 100)
    configured.client.maps.assert_awaited_once_with(robot_id)
    assert configured._maps_due == 130


async def test_remove_floor_requires_control_and_confirmed_current_review(
    configured, hass_ws_client, hass_admin_user
):
    other = replace(MAP, map_id="other-floor")
    robot_id = "fixture-0"
    configured.client.maps.side_effect = [(MAP, other), (MAP, other), (other,)]
    configured.client.remove_floor = AsyncMock(side_effect=ProtocolError("lost reply"))
    configured._sleep = AsyncMock()
    socket = await hass_ws_client()
    request = {
        "id": 1,
        "type": "roomba_home/remove_floor",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "inventory_id": MAP.inventory_id,
        "settings_id": MAP.settings_id,
    }
    await socket.send_json(request)
    assert not (await socket.receive_json())["success"]
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(request | {"id": 2, "confirmed": True})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    configured.client.remove_floor.assert_not_awaited()
    await socket.send_json(request | {"id": 3, "confirmed": True})
    assert (await socket.receive_json())["success"]
    configured.client.remove_floor.assert_awaited_once_with(MAP.map_id)
    assert configured.maps_for_robot(robot_id) == (other,)
    assert configured.data[robot_id].telemetry["map_count"] == 1


async def test_remove_floor_rejects_stale_settings_before_writing(configured):
    configured.client.remove_floor = AsyncMock()
    with pytest.raises(HomeAssistantError) as error:
        await configured.async_remove_floor(
            "fixture-0", MAP.map_id, MAP.version_id, MAP.inventory_id, "stale-settings"
        )
    assert error.value.translation_key == "map_changed"
    configured.client.remove_floor.assert_not_awaited()


@pytest.mark.parametrize("failed_read", [False, True])
async def test_floor_removal_does_not_resend_an_unconfirmed_write(configured, failed_read):
    configured.client.remove_floor = AsyncMock()
    configured._sleep = AsyncMock()
    if failed_read:
        configured.client.maps.side_effect = [(MAP,), ProtocolError("read failed")]
    with pytest.raises(HomeAssistantError, match="Removal could not be confirmed"):
        await configured.async_remove_floor(
            "fixture-0", MAP.map_id, MAP.version_id, MAP.inventory_id, MAP.settings_id
        )
    configured.client.remove_floor.assert_awaited_once_with(MAP.map_id)


async def test_point_cleaning_control_requires_reported_capability_and_control_permission(
    configured, hass_ws_client, hass_admin_user
):
    state = configured.data["fixture-0"]
    configured.async_set_updated_data(
        {
            **configured.data,
            "fixture-0": replace(
                state,
                capabilities=replace(
                    state.capabilities, digital_spot=DigitalSpotCapability.SUPPORTED, schedules=True
                ),
            ),
        }
    )
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(request)
    result = (await socket.receive_json())["result"]
    assert result["can_clean_point"] is True
    assert result["can_manage_schedules"] is True
    assert result["point_modes"] == ["vacuum", "mop", "vacuum_mop", "vacuum_then_mop"]
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, permission: permission == POLICY_READ,
    ):
        await socket.send_json(request | {"id": 2})
        result = (await socket.receive_json())["result"]
        assert result["can_clean_point"] is False
        assert result["can_manage_schedules"] is False
        assert result["point_modes"] == []
    state = configured.data["fixture-0"]
    cleaning = replace(state.capabilities.cleaning, modes=frozenset({CleaningMode.MOP}))
    configured.async_set_updated_data(
        {"fixture-0": replace(state, capabilities=replace(state.capabilities, cleaning=cleaning))}
    )
    await socket.send_json(request | {"id": 3})
    assert (await socket.receive_json())["result"]["point_modes"] == ["mop"]


async def test_live_point_requires_a_current_mission_and_matching_map_revision(
    configured, hass_ws_client
):
    robot_id = "fixture-0"
    now = datetime.now(UTC)
    started = now - timedelta(seconds=20)
    ready = configured.data[robot_id]
    active = replace(
        ready,
        phase="run",
        cycle="clean",
        telemetry={**ready.telemetry, "mission_started": started, "mission_number": 50},
    )
    configured.async_set_updated_data({robot_id: active})
    assert configured.live_point("invalid", now) is None
    target = PointTarget(MAP.map_id, MAP.version_id, (5.0, 2.0))
    point = MissionPoint(target, CleaningMode.MOP)
    timeline = MissionTimeline(50, now, "room", (), point=point)
    socket = await hass_ws_client()
    request = {"type": "roomba_home/floor_plan", "entity_id": ENTITY}

    async def read_point(request_id):
        await socket.send_json(request | {"id": request_id})
        return (await socket.receive_json())["result"]["active_point"]

    configured._live_timelines[robot_id] = started, timeline
    reading = await read_point(1)
    assert reading["center"] == [5, 2]
    assert reading["mode"] == "mop"
    assert reading["expires_at"] > now.timestamp()

    configured._live_timelines[robot_id] = (
        started,
        replace(timeline, point=replace(point, target=replace(target, version_id="prior"))),
    )
    assert await read_point(2) is None
    configured._live_timelines[robot_id] = (
        started,
        replace(timeline, observed_at=now - timedelta(minutes=5)),
    )
    assert await read_point(3) is None
    configured._live_timelines[robot_id] = started, replace(timeline, point=None)
    assert await read_point(4) is None
    configured._live_timelines[robot_id] = started, timeline
    configured.async_set_updated_data({robot_id: ready})
    assert await read_point(5) is None


async def test_floor_plan_reports_current_declared_itinerary_only_for_its_revision(
    configured, hass_ws_client
):
    robot = "fixture-0"
    now = datetime.now(UTC)
    started = now - timedelta(seconds=20)
    ready = configured.data[robot]
    state = replace(
        ready,
        phase="run",
        cycle="clean",
        telemetry=ready.telemetry | {"mission_started": started, "mission_number": 50},
    )
    document = {
        "timelineRequestId": 17,
        "nMssn": 50,
        "cmd": {
            "command": "start",
            "p2map_id": MAP.map_id,
            "user_p2mapv_id": MAP.version_id,
            "regions": [{"type": "rid", "region_id": "room-a"}],
        },
        "event": [],
        "finEvents": [
            {
                "type": "room",
                "ts": int(now.timestamp()) - 2,
                "room": {
                    "p2mapId": MAP.map_id,
                    "p2mapvId": MAP.version_id,
                    "rid": "room-a",
                    "status": 0,
                },
            }
        ],
    }
    report = mission_timeline(document, 17, 50, int(now.timestamp()))
    metrics = await configured._timeline_metrics(state, report, now)
    assert metrics["live_destinations_completed"] == 1
    configured.async_set_updated_data({robot: replace(state, telemetry=state.telemetry | metrics)})
    assert configured.live_plan(state, replace(MAP, version_id="older"), now) is None

    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(request)
    assert (await socket.receive_json())["result"]["live_plan"] == {
        "ordered": True,
        "completed": 1,
        "total": 1,
        "destinations": [{"kind": "room", "name": "Office", "status": "finished"}],
    }
    configured._live_timelines[robot] = (
        started,
        replace(report, observed_at=now - timedelta(minutes=5)),
    )
    await socket.send_json(request | {"id": 2})
    assert (await socket.receive_json())["result"]["live_plan"] is None
    configured._live_timelines[robot] = started, replace(report, plan=None)
    await socket.send_json(request | {"id": 3})
    assert (await socket.receive_json())["result"]["live_plan"] is None


async def test_floor_plan_reports_estimated_time_and_reuses_the_same_mission_read(
    configured, hass_ws_client
):
    robot = "fixture-0"
    now = datetime.now(UTC).replace(microsecond=0)
    started = now - timedelta(seconds=70)
    ready = configured.data[robot]
    state = replace(
        ready,
        phase="run",
        cycle="clean",
        telemetry=ready.telemetry | {"mission_started": started, "mission_number": 51},
    )
    document = {
        "timelineRequestId": 17,
        "nMssn": 51,
        "cmd": {
            "command": "start",
            "p2map_id": MAP.map_id,
            "user_p2mapv_id": MAP.version_id,
            "regions": [
                {
                    "type": "rid",
                    "region_id": "room-a",
                    "params": {"operatingMode": 2, "suctionLevel": 3, "twoPass": False},
                }
            ],
        },
        "event": [
            {
                "type": "room",
                "ts": int(now.timestamp()) - 23,
                "room": {
                    "p2mapId": MAP.map_id,
                    "p2mapvId": "robot-revision",
                    "rid": "room-a",
                    "area": 6,
                    "passCount": 0,
                },
            }
        ],
    }
    report = mission_timeline(document, 17, 51, int(now.timestamp()))
    configured.client.cleaning_time_estimates = AsyncMock(
        return_value={
            "regions": [
                {
                    "id": "map-a:rid:room-a",
                    "estimates": [
                        {
                            "duration_seconds": 502,
                            "mode": "vacuum",
                            "suction_level": 3,
                            "two_pass": False,
                        }
                    ],
                }
            ],
        }
    )
    result = await configured._timeline_metrics(state, report, now)
    assert result["live_estimated_remaining"] == 479
    assert configured.live_plan(state, MAP, now) is None
    reading = replace(state, telemetry=state.telemetry | result)
    configured.async_set_updated_data({robot: reading})
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}

    async def snapshot(clock, request_id):
        with patch("custom_components.roomba_home.map_api.datetime", wraps=datetime) as clock_api:
            clock_api.now.return_value = clock
            await socket.send_json(request | {"id": request_id})
            return (await socket.receive_json())["result"]["live_plan"]

    reply = await snapshot(now, 1)
    assert reply["estimated_remaining_seconds"] == 479
    assert reply["estimated_duration_seconds"] == 502
    assert reply["destinations"][0]["estimated_duration_seconds"] == 502
    assert reply["destinations"][0]["status"] == "in_progress"
    assert reply["destinations"][0]["requested_settings"] == {"suction_level": 3, "two_pass": False}
    assert reply["destinations"][0]["reported_pass_count"] == 0
    assert reply["destinations"][0]["stage_elapsed_seconds"] == 23

    later = now + timedelta(seconds=39)
    next_snapshot = await snapshot(later, 2)
    assert next_snapshot["estimated_remaining_seconds"] == 440
    assert next_snapshot["destinations"] == [
        reply["destinations"][0] | {"stage_elapsed_seconds": 62}
    ]
    assert reading.telemetry["live_timeline_plan"]["estimated_remaining_seconds"] == 479
    assert "stage_elapsed_seconds" not in reading.telemetry["live_timeline_plan"]["destinations"][0]
    configured.async_set_updated_data({robot: replace(reading, phase="stop")})
    paused_snapshot = await snapshot(later, 3)
    assert paused_snapshot["estimated_remaining_seconds"] is None
    assert "stage_elapsed_seconds" not in paused_snapshot["destinations"][0]
    configured.async_set_updated_data({robot: reading})
    assert await snapshot(now + timedelta(seconds=101), 4) is None

    advanced = await configured._timeline_metrics(state, None, later)
    assert advanced["live_estimated_remaining"] == 440
    paused = await configured._timeline_metrics(replace(state, phase="stop"), None, now)
    assert paused["live_estimated_remaining"] is None
    assert paused["live_timeline_plan"]["estimated_duration_seconds"] == 502
    configured.client.cleaning_time_estimates.assert_awaited_once()
    document["cmd"]["regions"].append({"type": "zid", "region_id": "zone-a"})
    mixed = mission_timeline(document, 17, 51, int(now.timestamp()))
    partial = await configured._timeline_metrics(state, mixed, now)
    assert partial["live_estimated_remaining"] is None
    assert "estimated_duration_seconds" not in partial["live_timeline_plan"]
    assert partial["live_timeline_plan"]["destinations"][0]["estimated_duration_seconds"] == 502
    await configured._timeline_metrics(replace(state, cycle="none"), None, now)
    assert configured._live_estimates == {}


@pytest.mark.parametrize("failure", ["rate limit", "unavailable", "changed map"])
async def test_unverified_live_estimates_keep_the_itinerary(configured, failure):
    robot = "fixture-0"
    now = datetime.now(UTC)
    clock = 20.0
    configured._clock = lambda: clock
    ready = configured.data[robot]
    state = replace(
        ready,
        phase="run",
        cycle="clean",
        telemetry=ready.telemetry | {"mission_started": now, "mission_number": 21},
    )
    document = {
        "timelineRequestId": 17,
        "nMssn": 21,
        "event": [],
        "cmd": {
            "command": "start",
            "p2map_id": MAP.map_id,
            "user_p2mapv_id": MAP.version_id,
            "regions": [{"type": "rid", "region_id": "room-a", "params": {"operatingMode": 2}}],
        },
    }
    report = mission_timeline(document, 17, 21, int(now.timestamp()))
    configured.client.cleaning_time_estimates = AsyncMock()
    if failure == "rate limit":
        configured.client.cleaning_time_estimates.side_effect = RateLimited(95)
    elif failure == "unavailable":
        configured.client.cleaning_time_estimates.side_effect = TimeoutError
    else:
        configured.client.maps.return_value = (replace(MAP, version_id="new-version"),)
    for _ in range(2):
        result = await configured._timeline_metrics(state, report, now)
        assert "live_estimated_remaining" not in result
        assert result["live_destinations_completed"] == 0
    configured.client.cleaning_time_estimates.assert_awaited_once()

    if failure == "rate limit":
        clock += 70
        assert configured._estimates_retry_until == 115
        await configured._timeline_metrics(state, report, now)
        configured.client.cleaning_time_estimates.assert_awaited_once()


async def test_live_positions_stream_only_sends_changes_for_the_subscribed_floor(
    hass_ws_client, configured, hass_admin_user
):
    robot = "fixture-0"
    now = datetime.now(UTC).replace(microsecond=0)
    stamp = int(now.timestamp())
    started = now - timedelta(seconds=30)
    ready = configured.data[robot]
    active = replace(
        ready,
        connected=True,
        phase="run",
        cycle="clean",
        telemetry=ready.telemetry | {"mission_started": started, "mission_number": 88},
    )
    configured.async_set_updated_data({robot: active})
    socket = await hass_ws_client()
    request = {
        "id": 1,
        "type": "roomba_home/live_positions",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": MAP.version_id,
    }
    await socket.send_json(request | {"id": 2, "version": "unknown"})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    await socket.send_json(request | {"id": 3, "entity_id": "vacuum.missing"})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(request | {"id": 4})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(request | {"id": 5})
    assert (await socket.receive_json())["success"]
    watch = MapWatch(robot, started, (MAP.map_id, MAP.version_id))
    first = PositionBatch(10, stamp - 2, stamp + 30, (Position(2, 3, 0, 5),))
    configured._receive_live_map_sample(watch, first)
    reading = await socket.receive_json()
    assert reading["id"] == 5 and reading["type"] == "event"
    event = reading["event"]
    covered = event.pop("coverage")
    assert covered["cell_size"] == CELL_SIZE
    vacuum_row = dict(covered["rows"])[floor(3 / CELL_SIZE)]
    assert any(start <= floor(2 / CELL_SIZE) < end and mask == 1 for start, end, mask in vacuum_row)
    assert event == {
        "trail": [[10, 2, 3, "vacuuming"]],
        "reset": True,
        "position": {
            "index": 10,
            "timestamp": stamp - 2,
            "expires_at": stamp + 30,
            "x": 2,
            "y": 3,
            "orientation": 0,
        },
    }
    second = PositionBatch(11, stamp + 1, stamp + 30, (Position(3, 3, 0, 4),))
    configured._receive_live_map_sample(watch, first)
    configured.async_update_listeners()
    configured._receive_live_map_sample(replace(watch, map_version=(MAP.map_id, "other")), second)
    configured._receive_live_map_sample(watch, replace(second, timestamp=stamp - 90))
    configured._receive_live_map_sample(watch, second)
    event = (await socket.receive_json())["event"]
    assert event["trail"] == [[11, 3, 3, "mopping"]] and not event["reset"]
    mop_row = dict(event["coverage"]["rows"])[floor(3 / CELL_SIZE)]
    assert any(start <= floor(2 / CELL_SIZE) < end and mask == 1 for start, end, mask in mop_row)
    assert any(start <= floor(3 / CELL_SIZE) < end and mask == 2 for start, end, mask in mop_row)
    await socket.send_json({"id": 6, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    snapshot = (await socket.receive_json())["result"]["live"]
    assert snapshot["coverage"]["cell_size"] == CELL_SIZE
    assert dict(snapshot["coverage"]["rows"])[floor(3 / CELL_SIZE)] == mop_row
    traveling = PositionBatch(12, stamp + 2, stamp + 30, (Position(4, 3, 0, 0),))
    configured._receive_live_map_sample(watch, traveling)
    travel_event = (await socket.receive_json())["event"]
    assert travel_event["trail"] == [[12, 4, 3, "traveling"]]
    assert "coverage" not in travel_event
    configured._live_obstacles[robot] = (started, watch.map_version), stamp, ((2, 3),)
    configured.async_update_listeners()
    obstacle_event = (await socket.receive_json())["event"]
    assert obstacle_event["obstacles"] == [[2, 3]]
    assert obstacle_event["trail"] == [] and not obstacle_event["reset"]
    assert obstacle_event["position"] == travel_event["position"]
    configured.async_update_listeners()
    await socket.send_json({"id": 7, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    snapshot = (await socket.receive_json())["result"]["live"]
    assert snapshot["obstacles"] == [[2, 3]]
    configured._live_obstacles[robot] = (started, watch.map_version), stamp - 61, ((2, 3),)
    configured.async_update_listeners()
    cleared = (await socket.receive_json())["event"]
    assert cleared["obstacles"] == [] and cleared["trail"] == []
    reference = RawRouteReference("https://example.test/mutable", stamp - 1)
    older = replace(reference, timestamp=stamp - 2)
    configured._receive_live_map_sample(watch, reference)
    configured._receive_live_map_sample(watch, older)
    assert configured._stream_route_references[robot] == (watch, reference)
    recover = AsyncMock(side_effect=lambda _, path, reference, now: path)
    with patch.object(configured, "_recover_live_route", recover):
        await configured._update_live_paths(configured.data, {}, now, {robot: older})
    assert recover.await_args.args[2] == reference
    configured._live_paths.pop(robot)
    configured.async_update_listeners()
    assert (await socket.receive_json())["event"] == {"reset": True, "trail": [], "position": None}
    await socket.send_json({"id": 8, "type": "unsubscribe_events", "subscription": 5})
    assert (await socket.receive_json())["success"]


async def test_live_floor_is_resolved_and_pinned_across_multiple_saved_floors(
    hass_ws_client, configured, make_point_bundle
):
    robot = "fixture-0"
    other = replace(MAP, map_id="map-b", version_id="version.b", name="Upper floor")
    configured._maps[robot] = (other, MAP)
    primary_geometry = configured.client.map_geometry.return_value

    def upstairs_metadata(documents):
        documents["metadata.json"] = {"id": other.map_id, "version": other.version_id}

    upstairs_geometry = make_point_bundle(mutate=upstairs_metadata)
    configured.client.map_geometry.side_effect = lambda map_id, _: (
        upstairs_geometry if map_id == other.map_id else primary_geometry
    )
    now = datetime.now(UTC).replace(microsecond=0)
    stamp = int(now.timestamp())
    started = now - timedelta(seconds=30)
    ready = configured.data[robot]
    active = replace(
        ready,
        connected=True,
        phase="run",
        cycle="clean",
        telemetry=ready.telemetry
        | {
            "mission_started": started,
            "mission_number": 88,
            "live_timeline_active_rooms": [{"room": "Office"}],
        },
    )
    batch = PositionBatch(10, stamp, stamp + 30, (Position(2, 3, 0, 5),))
    robots = {robot: active}
    await configured._update_live_paths(robots, {robot: [batch]}, now)
    assert configured.live_path(robot) is None
    assert configured._map_watch(active) is None

    report = MissionTimeline(88, now, "room", (), localized_maps=frozenset({MAP.map_id}))
    await configured._timeline_metrics(active, report, now)
    await configured._update_live_paths(robots, {robot: [batch]}, now)
    configured.async_set_updated_data(robots)
    assert configured.live_floor(active) == MAP
    assert configured.live_path(robot).map_version == (MAP.map_id, MAP.version_id)
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(request)
    selected = (await socket.receive_json())["result"]
    assert selected["map"]["id"] == MAP.map_id
    assert selected["live"]["position"]["index"] == 10
    assert selected["current_room"] == "Office"
    assert selected["active_rooms"] == [{"room": "Office"}]
    await socket.send_json(request | {"id": 2, "map_id": other.map_id})
    unselected = (await socket.receive_json())["result"]
    assert unselected["map"]["id"] == other.map_id
    assert unselected["live"] == {"trail": [], "position": None}
    assert unselected["current_room"] is None and unselected["active_rooms"] == []
    assert unselected["skip_review"] is None
    await socket.send_json(
        request | {"id": 3, "known_map_id": MAP.map_id, "known_version": MAP.version_id}
    )
    cached = (await socket.receive_json())["result"]
    assert cached["map"]["id"] == MAP.map_id and "geometry" not in cached
    watch = configured._map_watch(active)
    configured._receive_live_map_sample(
        replace(watch, map_version=(other.map_id, other.version_id)), replace(batch, index=11)
    )
    assert configured.live_path(robot).latest.index == 10

    assert await configured._timeline_metrics(active, None, now + timedelta(seconds=120)) == {}
    assert configured.live_floor(active) == MAP
    updated = replace(MAP, version_id="new-version")
    configured._maps[robot] = (other, updated)
    await configured._update_live_paths(robots, {robot: [batch]}, now)
    assert configured.live_floor(active) is None
    assert configured.live_path(robot) is None
    idle = {robot: replace(active, phase="charge", cycle="none")}
    await configured._update_live_paths(idle, {}, now)
    configured.async_set_updated_data(idle)
    assert not configured._live_floor_pins
    await socket.send_json(
        request | {"id": 4, "known_map_id": updated.map_id, "known_version": updated.version_id}
    )
    idle_view = (await socket.receive_json())["result"]
    assert idle_view["map"]["id"] == updated.map_id and "geometry" not in idle_view


async def test_websocket_refreshes_geometry_when_inventory_changes_in_the_same_version(
    hass_ws_client, configured
):
    socket = await hass_ws_client()
    request = {"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(request)
    original = (await socket.receive_json())["result"]
    updated = replace(
        MAP,
        regions=(
            replace(MAP.regions[0], name="Kitchen"),
            MAP.regions[1],
            CleaningRegion("pending-zone", RegionKind.ZONE, "Breakfast nook"),
            CleaningRegion("list-only-zone", RegionKind.ZONE, "Reading nook"),
        ),
    )
    configured.client.maps.return_value = (updated,)
    await configured._read_maps("fixture-0")
    await socket.send_json(
        request
        | {
            "id": 2,
            "map_id": MAP.map_id,
            "known_version": MAP.version_id,
            "known_inventory": original["inventory_id"],
        }
    )
    latest = (await socket.receive_json())["result"]
    assert latest["map"] == original["map"]
    assert latest["inventory_id"] != original["inventory_id"]
    assert latest["geometry"]["unlinked_zone_count"] == 0
    office, _, zone, list_only_zone = latest["geometry"]["regions"]
    assert office["name"] == "Kitchen"
    assert zone["id"] == "map-a:zid:pending-zone"
    assert zone["polygons"]
    assert list_only_zone == {
        "id": "map-a:zid:list-only-zone",
        "kind": "zone",
        "name": "Reading nook",
        "polygons": [],
    }


async def test_room_editor_splits_and_merges_with_delayed_destination_inventory(
    hass_ws_client, configured, picea_archive
):
    split = replace(MAP, version_id="version.43")
    merged = replace(
        split,
        version_id="version.44",
        regions=(*split.regions, CleaningRegion("room-b", RegionKind.ROOM, "Office south")),
    )
    archives = {
        MAP.version_id: picea_archive(),
        split.version_id: picea_archive(split=True, version=split.version_id),
        merged.version_id: picea_archive(version=merged.version_id),
    }
    configured.client.map_geometry.side_effect = lambda _map, version: archives[version]
    configured.client.edit_map = AsyncMock(
        side_effect=[archives[split.version_id], archives[merged.version_id]]
    )
    configured.client.maps.side_effect = [(MAP,), (split,)]
    socket = await hass_ws_client()
    await socket.send_json(DIVIDE)
    split_result = await socket.receive_json()
    assert split_result["success"], split_result
    assert split_result["result"] == {"version": split.version_id}
    view = {"id": 2, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(view)
    updated = (await socket.receive_json())["result"]
    assert updated["can_edit_rooms"]
    assert len(updated["geometry"]["editable_rooms"]) == 2
    assert any(region["id"] == "map-a:rid:room-b" for region in updated["geometry"]["regions"])
    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (split,)
    target = await configured._resolve_areas(
        "fixture-0", ["map-a:rid:room-b"], (MAP.map_id, split.version_id, split.inventory_id)
    )
    assert target.regions == (CleaningRegion("room-b", RegionKind.ROOM, "Office south"),)
    assert target.version_id == split.version_id

    # The same revision gains its second listed room while confirmation is open.
    # The provider's room labels and ordering can differ from the card.
    published = replace(
        split,
        regions=(
            CleaningRegion("room-b", RegionKind.ROOM, "Old cloud label"),
            *split.regions,
        ),
    )
    configured.client.maps.return_value = (published,)
    selection_id = updated["geometry"]["selection_id"]
    reviewed = (split.map_id, split.version_id, selection_id)
    assert await configured._resolve_areas("fixture-0", ["map-a:rid:room-b"], reviewed) == target
    await socket.send_json(
        view
        | {
            "id": 3,
            "map_id": split.map_id,
            "known_version": split.version_id,
            "known_inventory": split.inventory_id,
        }
    )
    caught_up = (await socket.receive_json())["result"]
    assert caught_up["inventory_id"] == published.inventory_id != split.inventory_id
    assert caught_up["geometry"]["selection_id"] == selection_id

    configured.client.maps.return_value = (replace(published, regions=published.regions[:2]),)
    with pytest.raises(HomeAssistantError) as error:
        await configured._resolve_areas("fixture-0", ["map-a:rid:room-b"], reviewed)
    assert error.value.translation_key == "map_changed"

    await socket.send_json(DIVIDE | {"id": 4})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    assert configured.client.edit_map.await_count == 1

    # The draft was opened before publication. Room writes are scoped to the active
    # archive revision and still revalidate the two room IDs and their adjacency.
    configured.client.maps.side_effect = [(published,), (merged,)]
    merge = {key: value for key, value in DIVIDE.items() if key != "split_points"} | {
        "id": 5,
        "version": split.version_id,
        "operation": "merge",
        "room_ids": ["room-a", "room-b"],
        "inventory_id": split.inventory_id,
    }
    await socket.send_json(merge)
    merge_result = await socket.receive_json()
    assert merge_result["success"], merge_result
    assert merge_result["result"] == {"version": merged.version_id}
    await socket.send_json(view | {"id": 6})
    restored = (await socket.receive_json())["result"]["geometry"]
    assert [room["id"] for room in restored["regions"] if room["kind"] == "room"] == [
        "map-a:rid:room-a"
    ]


async def test_room_rename_updates_the_card_and_keeps_cleaning_selection(
    hass_ws_client, configured, picea_archive
):
    updated = replace(MAP, version_id="version.43")
    original = picea_archive()

    def rename(documents):
        feature = documents["rooms.geojson"]["features"][0]
        feature["properties"].update(name="Baño de invitados", type={"value": "bathroom"})

    renamed = picea_archive(version=updated.version_id, mutate=rename)
    configured.client.map_geometry.side_effect = lambda _, v: (
        original if v == MAP.version_id else renamed
    )
    configured.client.maps.side_effect = [(MAP,), (updated,)]
    configured.client.edit_map = AsyncMock(return_value=renamed)
    socket = await hass_ws_client()
    rename_request = {key: value for key, value in DIVIDE.items() if key != "split_points"}
    rename_request.update(operation="rename", name="Baño de invitados", room_type="bathroom")
    await socket.send_json(rename_request)
    assert (await socket.receive_json())["result"] == {"version": updated.version_id}
    _, edit = configured.client.edit_map.await_args.args
    assert edit.request_body()["edit_cmd"]["params"] == {
        "room_id": "room-a",
        "room_metadata": {"name": "Baño de invitados", "type": "bathroom"},
    }

    await socket.send_json({"id": 2, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    view = (await socket.receive_json())["result"]
    assert view["inventory_id"] == MAP.inventory_id
    assert view["geometry"]["editable_rooms"][0]["room_type"] == "bathroom"
    assert view["geometry"]["room_naming"]["max_length"] == 31
    room = view["geometry"]["regions"][0]
    assert (room["id"], room["name"]) == ("map-a:rid:room-a", "Baño de invitados")

    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (updated,)
    target = await configured._resolve_areas(
        "fixture-0", [room["id"]], (MAP.map_id, updated.version_id, updated.inventory_id)
    )
    assert target.regions == (CleaningRegion("room-a", RegionKind.ROOM, "Baño de invitados"),)
    assert target.version_id == updated.version_id


async def test_floor_settings_update_without_reloading_geometry_or_changing_regions(
    hass_ws_client, configured, picea_archive
):
    named = replace(MAP, name="Ático")
    rotated = replace(named, orientation=-pi / 2)
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.maps.side_effect = [(MAP,), (named,), (named,), (rotated,)]
    configured.client.update_floor_settings = AsyncMock()
    socket = await hass_ws_client()
    await socket.send_json(RENAME_FLOOR)
    assert (await socket.receive_json())["success"]
    configured.client.update_floor_settings.assert_awaited_once()
    assert configured.client.update_floor_settings.await_args.args[2].request_body() == {
        "name": named.name
    }
    request = {
        "id": 2,
        "type": "roomba_home/floor_plan",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "known_version": MAP.version_id,
        "known_inventory": MAP.inventory_id,
    }
    await socket.send_json(request)
    first = (await socket.receive_json())["result"]
    assert first["floor_settings"] == {
        "id": named.settings_id,
        "name": named.name,
        "name_max_length": 16,
        "orientation": None,
    }
    assert "geometry" not in first

    rotate = {key: value for key, value in RENAME_FLOOR.items() if key != "name"}
    rotate.update(id=3, operation="rotate", settings_id=named.settings_id, quarter_turns=1)
    await socket.send_json(rotate)
    assert (await socket.receive_json())["success"]
    assert configured.client.update_floor_settings.await_args.args[2].request_body() == {
        "user_orientation_rad": pytest.approx(-pi / 2)
    }
    await socket.send_json(request | {"id": 4})
    second = (await socket.receive_json())["result"]
    assert second["map"] == first["map"]
    assert second["inventory_id"] == first["inventory_id"]
    assert second["floor_settings"] == {
        "id": rotated.settings_id,
        "name": named.name,
        "name_max_length": 16,
        "orientation": -pi / 2,
    }
    assert "geometry" not in second
    cached = await configured.async_floor_plan("fixture-0", rotated)
    assert cached and cached.source_format == "picea"
    assert configured.cleaning_maps_for_robot("fixture-0")[0].orientation == -pi / 2
    configured.client.map_geometry.assert_awaited_once()

    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (rotated,)
    await socket.send_json(rotate | {"id": 5})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    assert configured.client.update_floor_settings.await_count == 2


async def test_floor_settings_reject_unsupported_map_invalid_name_and_unauthorized_user(
    hass_ws_client, configured, picea_archive, hass_admin_user
):
    configured.client.update_floor_settings = AsyncMock()
    socket = await hass_ws_client()
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(RENAME_FLOOR)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(RENAME_FLOOR | {"id": 2})
    assert "map format" in (await socket.receive_json())["error"]["message"]
    configured._floor_plans.clear()
    configured.client.map_geometry.return_value = picea_archive()
    await socket.send_json(RENAME_FLOOR | {"id": 3, "name": "   "})
    assert "Enter a floor name" in (await socket.receive_json())["error"]["message"]
    await socket.send_json(RENAME_FLOOR | {"id": 4, "name": MAP.name})
    assert (await socket.receive_json())["success"]
    configured.client.update_floor_settings.assert_not_awaited()


@pytest.mark.parametrize(
    "read_back", ["delayed", "changed revision", "missing map", "unreachable", "not published"]
)
async def test_floor_settings_reconcile_lost_response_using_reads_only(
    hass_ws_client, configured, picea_archive, read_back
):
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.update_floor_settings = AsyncMock(side_effect=ProtocolError("Response lost"))
    updated = replace(MAP, name=RENAME_FLOOR["name"])
    outcomes = {
        "delayed": [(MAP,), (updated,)],
        "changed revision": [(replace(updated, version_id="version.43"),)],
        "missing map": [()],
        "unreachable": [OSError("Read failed")],
        "not published": [(MAP,)] * 3,
    }
    configured.client.maps.side_effect = [(MAP,), *outcomes[read_back]]
    socket = await hass_ws_client()
    await socket.send_json(RENAME_FLOOR)
    result = await socket.receive_json()
    assert result["success"] is (read_back == "delayed"), result
    if read_back != "delayed":
        assert "Save could not be confirmed" in result["error"]["message"]
    configured.client.update_floor_settings.assert_awaited_once()


async def test_restriction_editor_keeps_other_zones_and_rejects_stale_rewrites(
    hass_ws_client, configured, picea_archive, policy_feature
):
    added = replace(MAP, version_id="version.43")
    both = replace(MAP, version_id="version.44")
    cleared = replace(MAP, version_id="version.45")
    bath = policy_feature("100", "NoMopZone", [[[8, 1], [8, 3], [6, 3], [6, 1], [8, 1]]])
    obstacle = policy_feature("101", "KeepOutZone", [[[4, 6], [4, 7], [3, 7], [3, 6], [4, 6]]])
    archives = {
        MAP.version_id: picea_archive(restrictions=[]),
        added.version_id: picea_archive(version=added.version_id, restrictions=[bath]),
        both.version_id: picea_archive(version=both.version_id, restrictions=[obstacle, bath]),
        cleared.version_id: picea_archive(version=cleared.version_id, restrictions=[bath]),
    }
    configured.client.map_geometry.side_effect = lambda _, version: archives[version]
    configured.client.edit_map = AsyncMock(
        side_effect=[
            archives[version] for version in (added.version_id, both.version_id, cleared.version_id)
        ]
    )
    configured.client.maps.side_effect = [(MAP,), (added,), (added,), (both,), (both,), (cleared,)]
    socket = await hass_ws_client()
    request = {
        "id": 1,
        "type": "roomba_home/edit_restrictions",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "inventory_id": MAP.inventory_id,
        "operation": "create",
        "kind": "no_mop",
        "bounds": [6, 1, 8, 3],
    }
    await socket.send_json(request)
    assert (await socket.receive_json())["result"] == {"version": added.version_id}
    await socket.send_json(
        request | {"id": 2, "kind": "keep_out", "bounds": [3, 6, 4, 7], "version": added.version_id}
    )
    assert (await socket.receive_json())["result"] == {"version": both.version_id}
    latest = {"id": 3, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(latest)
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert [(shape["id"], shape["kind"]) for shape in geometry["editable_restrictions"]] == [
        ("101", "keep_out"),
        ("100", "no_mop"),
    ]
    assert geometry["keep_out"] and geometry["no_mop"]
    delete = {key: value for key, value in request.items() if key not in ("kind", "bounds")}
    delete.update(id=4, operation="delete", zone_id="101", version=both.version_id)
    await socket.send_json(delete)
    assert (await socket.receive_json())["result"] == {"version": cleared.version_id}
    await socket.send_json(latest | {"id": 5})
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert len(geometry["editable_restrictions"]) == 1
    assert not geometry["keep_out"] and geometry["no_mop"]

    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (cleared,)
    await socket.send_json(delete | {"id": 6})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    assert configured.client.edit_map.await_count == 3


async def test_cleaning_zone_editor_uses_archive_before_and_after_inventory_changes(
    hass_ws_client, configured, picea_archive
):
    added = replace(MAP, version_id="version.43")
    listed = CleaningRegion("100", RegionKind.ZONE, "Desk")
    edited = replace(added, version_id="version.44", regions=(*MAP.regions, listed))
    removed = replace(edited, version_id="version.45")
    rectangle = ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))
    archives = {
        MAP.version_id: picea_archive(),
        added.version_id: picea_archive(
            version=added.version_id, zones=[("100", "Desk", rectangle)]
        ),
        edited.version_id: picea_archive(
            version=edited.version_id, zones=[("100", "Office", rectangle)]
        ),
        removed.version_id: picea_archive(version=removed.version_id),
    }
    configured.client.map_geometry.side_effect = lambda _map, version: archives[version]
    configured.client.edit_map = AsyncMock(
        side_effect=[archives[item.version_id] for item in (added, edited, removed)]
    )
    configured.client.maps.side_effect = [
        (MAP,),
        (added,),
        (added,),
        (edited,),
        (edited,),
        (removed,),
    ]
    socket = await hass_ws_client()
    create = {
        "id": 1,
        "type": "roomba_home/edit_zones",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "operation": "create",
        "version": MAP.version_id,
        "inventory_id": MAP.inventory_id,
        "name": "Desk",
        "bounds": [6, 1, 8, 3],
    }
    await socket.send_json(create)
    assert (await socket.receive_json())["result"] == {
        "version": added.version_id,
        "destination_available": True,
    }
    read = {"id": 2, "type": "roomba_home/floor_plan", "entity_id": ENTITY}
    await socket.send_json(read)
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert geometry["editable_zones"][0]["id"] == "100"
    assert geometry["editable_zones"][0]["destination_available"] is True
    assert geometry["unlinked_zone_count"] == 0
    assert any(
        zone["name"] == "Desk" and zone["id"] == "map-a:zid:100" for zone in geometry["regions"]
    )

    update = {key: value for key, value in create.items() if key != "bounds"} | {
        "id": 3,
        "operation": "update",
        "version": added.version_id,
        "name": "Office",
        "zone_id": "100",
    }
    await socket.send_json(update)
    assert (await socket.receive_json())["result"] == {
        "version": edited.version_id,
        "destination_available": True,
    }
    await socket.send_json(read | {"id": 4})
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert geometry["editable_zones"][0]["name"] == "Office"
    assert geometry["editable_zones"][0]["destination_available"] is True
    assert any(zone["id"] == "map-a:zid:100" for zone in geometry["regions"])

    delete = {key: value for key, value in update.items() if key != "name"} | {
        "id": 5,
        "operation": "delete",
        "version": edited.version_id,
        "inventory_id": edited.inventory_id,
    }
    await socket.send_json(delete)
    assert (await socket.receive_json())["result"] == {
        "version": removed.version_id,
        "destination_available": False,
    }
    await socket.send_json(read | {"id": 6})
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert geometry["editable_zones"] == []
    assert all(zone["id"] != "map-a:zid:100" for zone in geometry["regions"])
    assert configured.client.edit_map.await_count == 3


async def test_room_edit_requires_control_before_reading_or_writing(
    hass_ws_client, configured, hass_admin_user
):
    socket = await hass_ws_client()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, permission: permission == POLICY_READ,
    ):
        await socket.send_json(DIVIDE)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    configured.client.maps.assert_not_awaited()


async def test_room_edit_rejects_missing_entities_and_reports_authentication_errors(
    hass_ws_client, configured
):
    socket = await hass_ws_client()
    await socket.send_json(DIVIDE | {"entity_id": "vacuum.missing"})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"

    configured.client.maps.side_effect = AuthenticationError("fixture authentication required")
    await socket.send_json(DIVIDE | {"id": 2})
    error = (await socket.receive_json())["error"]
    assert error["code"] == "room_edit_failed" and "Authentication" in error["message"]


async def test_room_edit_requires_enabled_maps_an_idle_robot_and_valid_divider(
    hass_ws_client, configured, picea_archive
):
    socket = await hass_ws_client()
    configured.show_maps = False
    await socket.send_json(DIVIDE)
    assert "unavailable" in (await socket.receive_json())["error"]["message"]

    configured.show_maps = True
    docked = configured.data["fixture-0"]
    configured.data = {"fixture-0": replace(docked, phase="run", cycle="clean")}
    await socket.send_json(DIVIDE | {"id": 2})
    assert "active mission" in (await socket.receive_json())["error"]["message"]
    configured.client.maps.assert_not_awaited()

    configured.data = {"fixture-0": docked}
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.edit_map = AsyncMock()
    await socket.send_json(DIVIDE | {"id": 3, "split_points": [-1, 20, 11, 20]})
    assert "crosses two room boundaries" in (await socket.receive_json())["error"]["message"]
    configured.client.edit_map.assert_not_awaited()


@pytest.mark.parametrize("result", ["invalid archive", "version not active", "map removed"])
async def test_uncertain_room_edit_never_repeats_the_write(
    hass_ws_client, configured, picea_archive, result
):
    configured.client.map_geometry.return_value = picea_archive()
    result_archive = picea_archive(split=True, version="version.43")
    configured.client.edit_map = AsyncMock(
        return_value=b"invalid archive" if result == "invalid archive" else result_archive
    )
    if result == "map removed":
        configured.client.maps.side_effect = [(MAP,), ()]
    socket = await hass_ws_client()
    await socket.send_json(DIVIDE)
    assert "Save could not be confirmed" in (await socket.receive_json())["error"]["message"]
    configured.client.edit_map.assert_awaited_once()


async def test_area_resolution_preserves_existing_destinations_if_geometry_read_fails(configured):
    configured.client.map_geometry.side_effect = ProtocolError("archive unavailable")
    with pytest.raises(HomeAssistantError) as error:
        await configured._resolve_areas("fixture-0", ["another-map:rid:room-a"])
    assert error.value.translation_key == "unsupported_areas"
    configured.client.map_geometry.assert_not_awaited()

    selection = await configured._resolve_areas("fixture-0", ["map-a:rid:room-a"])
    assert selection.regions == MAP.regions[:1]


async def test_dashboard_selection_rejects_stale_snapshot_before_publishing(
    hass, configured, hass_owner_user
):
    attrs = {
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": "old-version",
        "regions": ["map-a:rid:room-a"],
    }
    context = Context(user_id=hass_owner_user.id)
    with patch("custom_components.roomba_home.coordinator.execute_control", AsyncMock()) as control:
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN, "clean_map_selection", attrs, blocking=True, context=context
            )
        assert error.value.translation_key == "map_changed"
        control.assert_not_called()
        attrs["version"] = MAP.version_id
        attrs["inventory_id"] = "0" * 64
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN, "clean_map_selection", attrs, blocking=True, context=context
            )
        assert error.value.translation_key == "map_changed"
        control.assert_not_called()
        attrs["inventory_id"] = MAP.inventory_id
        await hass.services.async_call(
            DOMAIN, "clean_map_selection", attrs, blocking=True, context=context
        )
        control.assert_awaited_once()
        configured.show_maps = False
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN, "clean_map_selection", attrs, blocking=True, context=context
            )
        assert error.value.translation_key == "map_unavailable"
        assert control.await_count == 1


def test_map_live_geometry_expiration_and_exact_map_version():
    now = datetime.now(UTC)
    batch = PositionBatch(
        22,
        int(now.timestamp()),
        int(now.timestamp()) + 20,
        (
            Position(0, 4, 0, 0),
            Position(1, 4, 0, 5),
            Position(2, 4, 0, 4),
            Position(3, 4, 0, 6),
            Position(4, 4, 0, 128),
        ),
    )
    path = MissionPath((MAP.map_id, MAP.version_id), now, batch, ()).append(batch)
    fresh = live_geometry(path, MAP, now)
    assert fresh["position"]["x"] == 4
    assert fresh["trail"] == [
        (22, 0, 4, "traveling"),
        (23, 1, 4, "vacuuming"),
        (24, 2, 4, "mopping"),
        (25, 3, 4, "vacuum_mop"),
        (26, 4, 4, None),
    ]
    assert live_geometry(path, MAP, now + timedelta(seconds=21))["position"] is None
    assert live_geometry(path, replace(MAP, version_id="old"), now) == {
        "trail": [],
        "position": None,
    }


async def test_furniture_editor_reconciles_all_three_operations_with_active_revisions(
    hass_ws_client, configured, picea_archive, furniture_feature, hass_admin_user
):
    added, updated, restored = [replace(MAP, version_id=f"version.{n}") for n in (43, 44, 45)]
    detected = furniture_feature("1", "cabinet/tv", "robot", [(1, 1), (3, 1), (3, 2), (1, 2)])
    chair = furniture_feature("2", "chair/living", "user", [(4, 3), (6, 3), (6, 5), (4, 5)])
    moved = furniture_feature("2", "chair/living", "user", [(5, 3), (7, 3), (7, 5), (5, 5)])
    archives = {
        floor.version_id: picea_archive(version=floor.version_id, furniture=items)
        for floor, items in (
            (MAP, [detected]),
            (added, [detected, chair]),
            (updated, [detected, moved]),
            (restored, [detected]),
        )
    }
    configured.client.map_geometry.side_effect = lambda _, version: archives[version]
    configured.client.edit_map = AsyncMock(
        side_effect=[archives[floor.version_id] for floor in (added, updated, restored)]
    )
    configured.client.maps.side_effect = [
        (MAP,),
        (added,),
        (added,),
        (updated,),
        (updated,),
        (restored,),
    ]
    socket = await hass_ws_client()
    request = {
        "id": 1,
        "type": "roomba_home/edit_furniture",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "inventory_id": MAP.inventory_id,
        "operation": "create",
        "kind": "chair/living",
        "pose": [5, 4, 2, 2, 0],
    }
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(request)
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(request | {"id": 2})
    assert (await socket.receive_json())["result"] == {"version": added.version_id}
    _, edit = configured.client.edit_map.await_args.args
    rows = edit.request_body()["edit_cmd"]["params"]["furniture_list"]
    assert [row[:3] for row in rows] == [["1", 1520, 0], ["2", 1528, 1]]

    editing = {key: value for key, value in request.items() if key not in ("kind", "pose")}
    editing.update(id=3, operation="update", object_id="2", version=added.version_id)
    await socket.send_json(editing | {"pose": [6, 4, 2, 2, 0]})
    assert (await socket.receive_json())["result"] == {"version": updated.version_id}
    await socket.send_json({"id": 4, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    furniture = (await socket.receive_json())["result"]["geometry"]["furniture"]
    assert furniture["editable"] and furniture["types"]["chair/living"] == "Chair"
    assert [(item["source"], item["pose"]) for item in furniture["items"]] == [
        ("robot", [2, 1.5, 2, 1, 0]),
        ("user", [6, 4, 2, 2, 0]),
    ]
    delete = editing | {"id": 5, "operation": "delete", "version": updated.version_id}
    await socket.send_json(delete)
    assert (await socket.receive_json())["result"] == {"version": restored.version_id}
    _, edit = configured.client.edit_map.await_args.args
    rows = edit.request_body()["edit_cmd"]["params"]["furniture_list"]
    assert [row[:3] for row in rows] == [["1", 1520, 0], ["0", 1528, 1]]
    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (restored,)
    await socket.send_json(delete | {"id": 6})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    assert configured.client.edit_map.await_count == 3


async def test_estimate_accepts_card_geometry_review_with_a_furniture_destination(
    hass, hass_ws_client, configured, picea_archive, furniture_feature, hass_owner_user
):
    sofa = furniture_feature("1", "sofa", "robot", [(1, 1), (3, 1), (3, 2), (1, 2)])
    configured.client.map_geometry.return_value = picea_archive(furniture=[sofa])
    unsorted = replace(MAP, regions=tuple(reversed(MAP.regions)))
    configured._maps["fixture-0"] = (unsorted,)
    configured.client.maps.return_value = (unsorted,)
    socket = await hass_ws_client()
    await socket.send_json({"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    view = (await socket.receive_json())["result"]
    review = view["geometry"]["selection_id"]
    assert review != view["inventory_id"]
    furniture = view["geometry"]["furniture"]["destinations"][0]["id"]
    room = "map-a:rid:room-a"
    configured.client.cleaning_time_estimates = AsyncMock(
        return_value={
            "regions": [
                {
                    "id": room,
                    "estimates": [
                        {
                            "mode": "vacuum",
                            "duration_seconds": 240,
                            "suction_level": 1,
                            "two_pass": True,
                        }
                    ],
                }
            ]
        }
    )
    result = await hass.services.async_call(
        DOMAIN,
        "estimate_cleaning_routine",
        {
            "entity_id": ENTITY,
            "regions": [{"id": furniture}, {"id": room, "suction_level": 1, "two_pass": True}],
            "floor": {"map_id": MAP.map_id, "version": MAP.version_id, "inventory_id": review},
        },
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_owner_user.id),
    )
    assert result[ENTITY]["partial_duration_seconds"] == 240
    assert result[ENTITY]["duration_seconds"] is None
    assert [area["id"] for area in result[ENTITY]["areas"]] == [furniture, room]


async def test_quick_list_reads_the_active_floor_and_reviewed_draft_dispatches_without_saving(
    hass, configured, picea_archive, furniture_feature, hass_owner_user
):
    sofa = furniture_feature("1", "sofa", "robot", [(1, 1), (3, 1), (3, 2), (1, 2)])
    configured.client.map_geometry.return_value = picea_archive(furniture=[sofa])
    regions = [
        {"id": "map-a:furniture:1", "mode": "vacuum", "suction_level": 2, "two_pass": None},
        {"id": "map-a:rid:room-a", "mode": "mop", "wetness_level": 1, "two_pass": False},
    ]
    response = {
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "routines": [{"kind": "recent", "region_settings": regions}],
    }
    configured.client.map_quick_routines = AsyncMock(return_value=response)
    configured.client.create_cleaning_routine = AsyncMock()
    owner = Context(user_id=hass_owner_user.id)
    floor = {"map_id": MAP.map_id, "version": MAP.version_id}
    read = await hass.services.async_call(
        DOMAIN,
        "list_map_routines",
        {"entity_id": ENTITY, **floor},
        blocking=True,
        return_response=True,
        context=owner,
    )
    assert read == {ENTITY: response}
    robot, selected, _ = configured.client.map_quick_routines.await_args.args
    assert robot == "fixture-0" and selected.version_id == MAP.version_id
    assert selected.regions[-1].segment_id(MAP.map_id) == regions[0]["id"]
    with patch("custom_components.roomba_home.coordinator.execute_control", AsyncMock()) as control:
        data = {"entity_id": ENTITY, "regions": regions, "floor": floor}
        await hass.services.async_call(
            DOMAIN, "run_cleaning_draft", data, blocking=True, context=owner
        )
        adapter, command, profile = control.await_args.args
        assert command is Command.VACUUM and profile == CleaningProfile(suction_level=2)
        assert [area.segment_id(MAP.map_id) for area in adapter.target.regions] == [
            r["id"] for r in regions
        ]
        assert adapter.target.profiles == (
            CleaningProfile(suction_level=2),
            CleaningProfile(CleaningMode.MOP, wetness_level=1, two_pass=False),
        )
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN,
                "run_cleaning_draft",
                data | {"floor": floor | {"version": "obsolete"}},
                blocking=True,
                context=owner,
            )
        assert error.value.translation_key == "map_changed"
        control.assert_awaited_once()
    configured.client.create_cleaning_routine.assert_not_awaited()


async def test_quick_list_with_a_changed_floor_or_expired_session_returns_no_drafts(
    hass, configured
):
    endpoint = configured.client.map_quick_routines = AsyncMock(return_value={"routines": []})
    data = {"entity_id": ENTITY}
    configured.client.maps.return_value = (replace(MAP, version_id="new-version"),)
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN, "list_map_routines", data, blocking=True, return_response=True
        )
    assert error.value.translation_key == "map_changed"
    configured._maps["fixture-0"] = (MAP,)
    configured.client.maps.return_value = (MAP,)
    endpoint.side_effect = AuthenticationError()
    with pytest.raises(ConfigEntryAuthFailed):
        await hass.services.async_call(
            DOMAIN, "list_map_routines", data, blocking=True, return_response=True
        )
    assert endpoint.await_count == 2
    configured.data.pop("fixture-0")
    with pytest.raises(HomeAssistantError) as error:
        await configured.async_list_map_routines("fixture-0")
    assert error.value.translation_key == "map_unavailable"


async def test_routine_actions_resolve_furniture_and_run_in_saved_order(
    hass, hass_ws_client, configured, picea_archive, furniture_feature, hass_owner_user
):
    sofa = furniture_feature("1", "sofa", "robot", [(1, 1), (3, 1), (3, 2), (1, 2)])
    chair = furniture_feature("2", "chair/living", "user", [(4, 3), (6, 3), (6, 5), (4, 5)])
    configured.client.map_geometry.return_value = picea_archive(furniture=[sofa, chair])
    socket = await hass_ws_client()
    await socket.send_json({"id": 1, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    data = (await socket.receive_json())["result"]["geometry"]
    assert data["furniture"]["destinations"] == [
        {"id": "map-a:furniture:1", "name": "Sofa"},
        {"id": "map-a:furniture:2", "name": "Chair"},
    ]
    selections = [
        {"id": "map-a:furniture:2", "mode": "vacuum", "suction_level": 3},
        {"id": "map-a:rid:room-a", "mode": "vacuum", "suction_level": 1},
        {"id": "map-a:furniture:1", "mode": "vacuum", "suction_level": 2},
    ]
    identity = "1" * 32
    routine = {
        "id": identity,
        "name": "Example routine",
        "regions": [r["id"] for r in selections],
        "region_settings": selections,
        "editable": True,
    }
    configured.client.create_cleaning_routine = AsyncMock(return_value=routine)
    context = Context(user_id=hass_owner_user.id)
    await hass.services.async_call(
        DOMAIN,
        "create_cleaning_routine",
        {"entity_id": ENTITY, "name": routine["name"], "regions": selections},
        blocking=True,
        context=context,
    )
    args = configured.client.create_cleaning_routine.await_args.args
    assert args[:2] == ("fixture-0", routine["name"])
    assert [r.segment_id(MAP.map_id) for r in args[2].regions] == routine["regions"]
    assert [p.suction_level for p in args[2].profiles] == [3, 1, 2]
    with pytest.raises(ValueError, match="explicit order"):
        command_body(Command.VACUUM, 1, target=replace(args[2], ordered=False))

    configured.client.list_cleaning_routines = AsyncMock(
        return_value=[routine | {"id": "2" * 32, "region_settings": None}, routine]
    )
    with patch("custom_components.roomba_home.coordinator.execute_control", AsyncMock()) as control:
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN,
                "run_cleaning_draft",
                {
                    "entity_id": ENTITY,
                    "regions": selections,
                    "ordered": False,
                    "floor": {"map_id": MAP.map_id, "version": MAP.version_id},
                },
                blocking=True,
                context=context,
            )
        assert error.value.translation_key == "unsupported_areas"
        for invalid in ("2" * 32, "3" * 32):
            with pytest.raises(HomeAssistantError) as error:
                await hass.services.async_call(
                    DOMAIN,
                    "run_cleaning_routine",
                    {"entity_id": ENTITY, "routine_id": invalid},
                    blocking=True,
                    context=context,
                )
            assert error.value.translation_key == "routine_not_editable"
        control.assert_not_awaited()
        trigger = {"entity_id": ENTITY, "routine_id": identity}
        await hass.services.async_call(
            DOMAIN, "run_cleaning_routine", trigger, blocking=True, context=context
        )
        adapter, *_ = control.await_args.args
        assert adapter.robot_id == "fixture-0"
        assert adapter.target == args[2]
        assert control.await_args.kwargs["area_profiles"] == tuple(
            CleaningProfile(CleaningMode.VACUUM, suction_level=level) for level in [3, 1, 2]
        )
        new_floor = replace(MAP, version_id="version.450")
        configured.client.maps.return_value = (new_floor,)
        configured.client.map_geometry.return_value = picea_archive(
            version=new_floor.version_id, furniture=[sofa]
        )
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(
                DOMAIN, "run_cleaning_routine", trigger, blocking=True, context=context
            )
        assert error.value.translation_key == "unsupported_areas"
        control.assert_awaited_once()


async def test_native_routine_automatic_order_is_preserved_in_home_assistant(
    hass, configured, hass_owner_user
):
    identity = "1" * 32
    selections = [
        {"id": "map-a:rid:room-a", "mode": "vacuum", "suction_level": 3},
        {"id": "map-a:zid:zone-a", "mode": "mop", "wetness_level": 1},
    ]
    routine = {"id": identity, "region_settings": selections, "ordered": False}
    configured.client.create_cleaning_routine = AsyncMock(return_value=routine)
    configured.client.update_cleaning_routine = AsyncMock(return_value=routine)
    configured.client.list_cleaning_routines = AsyncMock(return_value=[routine])
    context = Context(user_id=hass_owner_user.id)
    target = {"entity_id": ENTITY}
    await hass.services.async_call(
        DOMAIN,
        "create_cleaning_routine",
        target | {"name": "Different modes", "regions": selections, "ordered": False},
        blocking=True,
        context=context,
    )
    assert not configured.client.create_cleaning_routine.await_args.args[-1].ordered
    await hass.services.async_call(
        DOMAIN,
        "update_cleaning_routine",
        target | {"routine_id": identity, "regions": selections, "ordered": False},
        blocking=True,
        context=context,
    )
    assert not configured.client.update_cleaning_routine.await_args.args[-1].ordered
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            DOMAIN,
            "update_cleaning_routine",
            target | {"routine_id": identity, "name": "New name", "ordered": False},
            blocking=True,
            context=context,
        )
    assert error.value.translation_key == "routine_not_editable"

    with patch("custom_components.roomba_home.coordinator.execute_control", AsyncMock()) as control:
        await hass.services.async_call(
            DOMAIN,
            "run_cleaning_routine",
            target | {"routine_id": identity},
            blocking=True,
            context=context,
        )
    adapter, command, profile = control.await_args.args
    assert adapter.target.version_id == MAP.version_id
    assert not adapter.target.ordered
    payload = json.loads(command_body(command, 1, profile, adapter.target))
    assert "ordered" not in payload
    assert [(area["type"], area["params"]) for area in payload["regions"]] == [
        ("rid", {"operatingMode": 2, "suctionLevel": 3}),
        ("zid", {"operatingMode": 4, "padWetness": {"padPlate": 1}}),
    ]


async def test_map_backup_remains_available_after_config_entry_unload_and_checks_permissions(
    hass,
    entry,
    configured,
    hass_ws_client,
    hass_admin_user,
):
    socket = await hass_ws_client()
    await socket.send_json(CAPTURE_BACKUP | {"id": 1})
    saved = await socket.receive_json()
    assert saved["success"], saved
    backup = saved["result"]
    assert backup["name"] == MAP.name and backup["version"] == MAP.version_id
    assert "archive" not in backup
    await socket.send_json(CAPTURE_BACKUP | {"id": 2, "settings_id": "0" * 64})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    read = {"type": "roomba_home/read_map_backup", "entity_id": ENTITY, "backup_id": backup["id"]}
    list_backups = {"type": "roomba_home/map_backups", "entity_id": ENTITY}
    assert await hass.config_entries.async_unload(entry.entry_id)
    bundle = configured.client.map_geometry.return_value
    configured.client.map_geometry.reset_mock()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, policy: policy == POLICY_READ,
    ):
        await socket.send_json(list_backups | {"id": 3})
        available = (await socket.receive_json())["result"]
        assert available["snapshots"] == [backup] and available["can_manage"] is False
        await socket.send_json(read | {"id": 4})
        detail = (await socket.receive_json())["result"]
        assert [area["name"] for area in detail["geometry"]["regions"][:2]] == [
            "Office",
            "Dining zone",
        ]
        assert detail["geometry"]["keep_out"] and detail["geometry"]["virtual_walls"]
        await socket.send_json(read | {"id": 5, "download": True})
        exported = (await socket.receive_json())["result"]
        assert exported["format_version"] == 1 and base64.b64decode(exported["archive"]) == bundle
        assert set(exported) == {
            "archive",
            "floor",
            "captured_at",
            "id",
            "pinned",
            "format_version",
            "format",
        }
        await socket.send_json(CAPTURE_BACKUP | {"id": 6})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    with patch.object(type(hass_admin_user.permissions), "check_entity", return_value=False):
        await socket.send_json(read | {"id": 7, "download": True})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(CAPTURE_BACKUP | {"id": 8})
    assert "Load this Roomba" in (await socket.receive_json())["error"]["message"]
    configured.client.map_geometry.assert_not_awaited()
    await hass.config_entries.async_remove(entry.entry_id)
    assert (await map_history(hass, entry.entry_id).async_list("fixture-0"))["snapshots"] == []


async def test_map_backup_websocket_configure_pin_and_delete(
    hass,
    entry,
    configured,
    hass_ws_client,
):
    socket = await hass_ws_client()
    options = {
        "type": "roomba_home/configure_map_backups",
        "entity_id": ENTITY,
        "retention": 1,
        "automatic": True,
    }
    await socket.send_json(options | {"id": 1})
    assert (await socket.receive_json())["success"]
    await socket.send_json(CAPTURE_BACKUP | {"id": 2})
    item = (await socket.receive_json())["result"]
    operation = {
        "type": "roomba_home/modify_map_backup",
        "entity_id": ENTITY,
        "backup_id": item["id"],
    }
    await socket.send_json(operation | {"id": 3, "operation": "pin"})
    assert (await socket.receive_json())["success"]
    history = map_history(hass, entry.entry_id)
    assert (await history.async_list("fixture-0"))["snapshots"] == [item | {"pinned": True}]
    await socket.send_json(operation | {"id": 4, "operation": "delete"})
    assert (await socket.receive_json())["success"]
    await socket.send_json(operation | {"id": 5, "operation": "pin"})
    assert (await socket.receive_json())["error"]["code"] == "map_backup_failed"
    await socket.send_json(options | {"id": 6, "entity_id": "vacuum.missing"})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    with patch.object(hass.config_entries, "async_get_entry", return_value=None):
        await socket.send_json(options | {"id": 7})
        assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    unrelated = entity_registry.async_get(hass).async_get_or_create(
        "vacuum",
        DOMAIN,
        "unrelated_registered_id",
        config_entry=entry,
        suggested_object_id="unrelated_robot",
    )
    await socket.send_json(options | {"id": 8, "entity_id": unrelated.entity_id})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    configured.show_maps = False
    await socket.send_json(CAPTURE_BACKUP | {"id": 9})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"
    configured.show_maps = True
    configured.client.maps.side_effect = AuthenticationError()
    await socket.send_json(CAPTURE_BACKUP | {"id": 10})
    assert "authentication" in (await socket.receive_json())["error"]["message"]
    with patch.object(history, "async_configure", AsyncMock(side_effect=OSError())):
        await socket.send_json(options | {"id": 11})
        assert "storage is unavailable" in (await socket.receive_json())["error"]["message"]


@pytest.mark.parametrize("failure", [None, ProtocolError("could not save"), AuthenticationError()])
async def test_opt_in_backup_precedes_provider_floor_edit(
    hass, entry, configured, picea_archive, failure
):
    robot = "fixture-0"
    history = map_history(hass, entry.entry_id)
    await history.async_configure(robot, 5, True)
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.maps.side_effect = [(MAP,), (replace(MAP, name="Renamed"),)]

    async def save_settings(*_):
        [saved] = (await history.async_list(robot))["snapshots"]
        assert saved["name"] == MAP.name
        assert saved["version"] == MAP.version_id

    configured.client.update_floor_settings = AsyncMock(side_effect=save_settings)
    args = (
        robot,
        MAP.map_id,
        MAP.version_id,
        MAP.inventory_id,
        "rename",
        MAP.settings_id,
        "Renamed",
        None,
    )
    if isinstance(failure, AuthenticationError):
        configured.client.map_geometry.side_effect = [picea_archive(), failure]
        with pytest.raises(AuthenticationError):
            await configured.async_edit_floor_settings(*args)
        configured.client.update_floor_settings.assert_not_awaited()
    elif failure:
        with (
            patch.object(history, "async_capture", AsyncMock(side_effect=failure)),
            pytest.raises(HomeAssistantError, match="automatic map backup failed"),
        ):
            await configured.async_edit_floor_settings(*args)
        configured.client.update_floor_settings.assert_not_awaited()
    else:
        await configured.async_edit_floor_settings(*args)
        configured.client.update_floor_settings.assert_awaited_once()


@pytest.fixture
async def settings_recovery(hass, entry, configured, picea_archive):
    saved = replace(MAP, version_id="archive.21", name="Ático", orientation=-pi / 2)
    archive = picea_archive(version=saved.version_id)
    record, _ = capture_snapshot(saved, archive, datetime.now(UTC))
    history = map_history(hass, entry.entry_id)
    await history.async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.update_floor_settings = AsyncMock()
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_settings",
        "backup_id": record["id"],
    }
    restored = replace(MAP, name=saved.name, orientation=saved.orientation)
    return history, request, restored


async def test_floor_backup_restore_previews_and_applies_both_fields_in_one_write(
    configured,
    hass_ws_client,
    hass_admin_user,
    settings_recovery,
):
    _, request, restored = settings_recovery
    socket = await hass_ws_client()
    await socket.send_json(request | {"id": 1})
    review = (await socket.receive_json())["result"]
    assert review == {
        "changes": {
            "name": {"from": MAP.name, "to": "Ático"},
            "orientation": {"from": MAP.orientation, "to": -pi / 2},
        },
        "applied": False,
    }
    configured.client.update_floor_settings.assert_not_awaited()
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity, permission: permission == POLICY_READ,
    ):
        await socket.send_json(request | {"id": 2, "confirmed": True})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"

    configured.client.maps.side_effect = [(MAP,), (MAP,), (restored,)]
    await socket.send_json(request | {"id": 3, "confirmed": True})
    applied = (await socket.receive_json())["result"]
    assert applied == review | {"applied": True}
    configured.client.update_floor_settings.assert_awaited_once()
    owner, scope, edit = configured.client.update_floor_settings.await_args.args
    assert owner == "fixture-0" and scope == MAP
    assert edit.request_body() == {"name": "Ático", "user_orientation_rad": -pi / 2}
    assert configured.maps_for_robot(owner) == (restored,)
    configured.client.maps.side_effect = None
    configured.client.maps.return_value = (restored,)
    await socket.send_json(
        request | {"id": 4, "settings_id": restored.settings_id, "confirmed": True}
    )
    assert (await socket.receive_json())["result"] == {"applied": False, "changes": {}}
    configured.client.update_floor_settings.assert_awaited_once()


async def test_floor_backup_restore_rechecks_current_settings_after_automatic_capture(
    configured,
    hass_ws_client,
    settings_recovery,
):
    history, request, _ = settings_recovery
    await history.async_configure("fixture-0", 5, True)
    configured.client.maps.side_effect = [(MAP,), (replace(MAP, name="External rename"),)]
    socket = await hass_ws_client()
    await socket.send_json(request | {"id": 1, "confirmed": True})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.update_floor_settings.assert_not_awaited()
    assert (await history.async_list("fixture-0"))["snapshots"][0]["name"] == MAP.name


@pytest.mark.parametrize("variant", ["other-floor", "other-format"])
async def test_floor_backup_restore_rejects_backups_with_a_wrong_scope_or_format(
    hass,
    entry,
    configured,
    hass_ws_client,
    picea_archive,
    variant,
):
    if variant == "other-floor":
        saved = replace(MAP, map_id="another-floor", name="Previous name")
        archive = picea_archive(map_id=saved.map_id)
    else:
        saved = replace(MAP, name="Previous name")
        archive = configured.client.map_geometry.return_value
    record, _ = capture_snapshot(saved, archive, datetime.now(UTC))
    history = map_history(hass, entry.entry_id)
    await history.async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.update_floor_settings = AsyncMock()
    socket = await hass_ws_client()
    await socket.send_json(
        CAPTURE_BACKUP
        | {
            "id": 1,
            "type": "roomba_home/restore_map_backup_settings",
            "backup_id": record["id"],
            "confirmed": True,
        }
    )
    error = (await socket.receive_json())["error"]
    assert error["code"] == "map_backup_failed"
    assert ("active floor" if variant == "other-floor" else "backup format") in error["message"]
    configured.client.update_floor_settings.assert_not_awaited()


@pytest.fixture
async def zone_recovery(hass, entry, configured, picea_archive):
    west = ((9, 1), (9, 2), (8.2, 2), (8.2, 1), (9, 1))
    east = ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))
    moved = ((9, 4), (9, 5), (7, 5), (7, 4), (9, 4))
    newer = ("102", "Newer zone", ((4, 6), (5, 6), (5, 7), (4, 7), (4, 6)))
    original = [("100", "Lectúra", east), ("101", "Entry", west)]
    saved = replace(MAP, version_id="archive.21")
    archive = picea_archive(version=saved.version_id, zones=original)
    history = map_history(hass, entry.entry_id)
    record, _ = capture_snapshot(saved, archive, datetime.now(UTC))
    await history.async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive(
        zones=[("100", "Moved", moved), newer]
    )
    configured.client.edit_map = AsyncMock(
        return_value=picea_archive(
            version="version.43",
            zones=[*original, newer],
        )
    )
    configured.client.list_cleaning_routines = AsyncMock(
        return_value=[
            {"name": "Morning", "regions": ["map-a:zid:100", "map-a:rid:room-a"]},
            {"name": "Other", "regions": ["map-a:zid:102"]},
            {"name": "Unavailable targets", "regions": None},
        ]
    )
    configured.client.list_cleaning_schedules = AsyncMock(
        return_value=[
            {"name": "Weekly", "regions": ["map-a:zid:100"]},
        ]
    )
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_zones",
        "backup_id": record["id"],
    }
    return history, request


async def test_zone_restore_previews_dependencies_and_writes_one_verified_revision(
    configured,
    hass_ws_client,
    hass_admin_user,
    zone_recovery,
):
    history, request = zone_recovery
    socket = await hass_ws_client()
    await socket.send_json(request | {"id": 1})
    response = await socket.receive_json()
    assert response["success"], response
    review = response["result"]
    assert len(review["review_id"]) == 64 and review["applied"] is False
    assert review["dependencies"] == [
        {"name": "Morning", "kind": "routine", "zones": ["100"]},
        {"name": "Weekly", "kind": "schedule", "zones": ["100"]},
    ]
    assert review["unchecked"] == ["routine"]
    assert [change["missing"] for change in review["changes"]] == [False, True]
    configured.client.edit_map.assert_not_awaited()
    confirmed = request | {"confirmed": True, "review_id": review["review_id"]}
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity_id, policy: policy == POLICY_READ,
    ):
        await socket.send_json(confirmed | {"id": 2})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(request | {"id": 3, "confirmed": True})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.edit_map.assert_not_awaited()
    await history.async_configure("fixture-0", 5, True)
    configured.client.maps.side_effect = [(MAP,), (MAP,), (replace(MAP, version_id="version.43"),)]
    await socket.send_json(confirmed | {"id": 4})
    assert (await socket.receive_json())["result"] == review | {"applied": True}
    configured.client.edit_map.assert_awaited_once()
    _, edit = configured.client.edit_map.await_args.args
    assert [zone.zone_id for zone in edit.zones] == ["100", "101"]
    assert len((await history.async_list("fixture-0"))["snapshots"]) == 2


async def test_zone_restore_requires_a_fresh_review_if_dependencies_change(
    configured,
    hass_ws_client,
    zone_recovery,
):
    _, request = zone_recovery
    socket = await hass_ws_client()
    await socket.send_json(request | {"id": 1})
    response = await socket.receive_json()
    assert response["success"], response
    review = response["result"]
    configured.client.list_cleaning_schedules.side_effect = ProtocolError()
    await socket.send_json(request | {"id": 2, "review_id": review["review_id"], "confirmed": True})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.edit_map.assert_not_awaited()
    await socket.send_json(request | {"id": 3})
    unchecked = (await socket.receive_json())["result"]
    assert unchecked["unchecked"] == ["routine", "schedule"]
    configured.client.list_cleaning_routines.side_effect = AuthenticationError()
    await socket.send_json(request | {"id": 4})
    assert (await socket.receive_json())["error"]["code"] == "map_unavailable"


@pytest.mark.parametrize("variant", ["no-change", "scope", "invalid-boundary"])
async def test_zone_restore_omits_writes_for_empty_or_unsafe_reviews(
    hass,
    entry,
    configured,
    hass_ws_client,
    picea_archive,
    variant,
):
    saved = replace(MAP, map_id="other-floor") if variant == "scope" else MAP
    record, _ = capture_snapshot(saved, picea_archive(map_id=saved.map_id), datetime.now(UTC))
    await map_history(hass, entry.entry_id).async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive()
    configured.client.edit_map = AsyncMock()
    if variant == "invalid-boundary":
        plan = await configured._floor_plan("fixture-0", MAP)
        configured._floor_plans["fixture-0", MAP.geometry_key] = replace(
            plan, border_digest="other"
        )
    socket = await hass_ws_client()
    await socket.send_json(
        CAPTURE_BACKUP
        | {
            "id": 1,
            "type": "roomba_home/restore_map_backup_zones",
            "backup_id": record["id"],
            "confirmed": True,
        }
    )
    response = await socket.receive_json()
    if variant == "no-change":
        assert response["result"]["changes"] == [] and response["result"]["applied"] is False
    else:
        assert response["error"]["code"] == "map_backup_failed"
    configured.client.edit_map.assert_not_awaited()


@pytest.fixture
async def program_recovery(configured, hass_ws_client, picea_archive):
    robot = configured.data["fixture-0"]
    configured.data[robot.robot_id] = replace(
        robot,
        capabilities=replace(
            robot.capabilities,
            cleaning=CleaningCapabilities(
                modes=frozenset({CleaningMode.VACUUM, CleaningMode.MOP}),
                suction_levels=4,
                wetness_levels=3,
                two_pass=True,
            ),
        ),
    )
    zones = [
        ("100", "Reading area", ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))),
        ("101", "Entráda", ((9, 1), (9, 2), (8.2, 2), (8.2, 1), (9, 1))),
    ]
    profiles = [
        {"id": "map-a:zid:100", "mode": "vacuum", "suction_level": 1},
        {"id": "map-a:zid:101", "mode": "mop", "wetness_level": 2, "two_pass": True},
    ]
    routine = {"id": "a" * 32, "name": "Morning", "editable": True}
    schedule = {"id": "schedule:item", "name": "Weekly", "enabled": False, "time": "15:30"}

    def program(row, settings):
        return row | {"regions": [item["id"] for item in settings], "region_settings": settings}

    configured.client.list_cleaning_routines = AsyncMock(
        return_value=[
            program(routine, profiles),
            program(
                {"id": "b" * 32, "name": "Unrelated"}, [{**profiles[0], "id": "map-b:zid:100"}]
            ),
            program({"id": "c" * 32, "name": "Read-only", "editable": False}, profiles),
        ]
    )
    configured.client.list_cleaning_schedules = AsyncMock(
        return_value=[program(schedule, profiles)]
    )
    configured.client.update_cleaning_routine = AsyncMock()
    configured.client.update_cleaning_schedule = AsyncMock()
    configured.client.map_geometry.return_value = picea_archive(zones=zones)
    socket = await hass_ws_client()
    await socket.send_json(CAPTURE_BACKUP | {"id": 1})
    captured = await socket.receive_json()
    assert captured["success"], captured
    backup = captured["result"]
    assert backup["program_count"] == 2 and backup["programs_unchecked"] == ["routine"]
    await socket.send_json(
        {
            "id": 2,
            "type": "roomba_home/read_map_backup",
            "entity_id": ENTITY,
            "backup_id": backup["id"],
            "download": True,
        }
    )
    exported = (await socket.receive_json())["result"]["programs"]
    assert [item["id"] for item in exported["items"]] == [routine["id"], schedule["id"]]
    assert all(item["region_settings"] == profiles for item in exported["items"])
    assert all("time" not in item and "enabled" not in item for item in exported["items"])
    configured.client.list_cleaning_routines.return_value = [
        program(routine | {"name": "Renamed since capture"}, profiles[:1]),
    ]
    configured.client.list_cleaning_schedules.return_value = [
        program(schedule | {"time": "16:30"}, profiles[:1]),
    ]
    review = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_programs",
        "backup_id": backup["id"],
    }
    return socket, review, profiles


async def test_recover_selects_one_program_and_preserves_original_area_profiles(
    configured, program_recovery, hass_admin_user
):
    socket, request, profiles = program_recovery
    await socket.send_json(request | {"id": 3})
    response = await socket.receive_json()
    assert response["success"], response
    review = response["result"]
    assert review["unchecked"] == ["routine"] and review["applied"] is False
    routine, schedule = review["programs"]
    assert [routine["name"], schedule["name"]] == ["Renamed since capture", "Weekly"]
    assert all(row["status"] == "ready" for row in review["programs"])
    for row in review["programs"]:
        assert row["destinations"] == [
            profiles[0] | {"name": "Reading area", "restore": False},
            profiles[1] | {"name": "Entráda", "restore": True},
        ]
    writes = (configured.client.update_cleaning_routine, configured.client.update_cleaning_schedule)
    for write in writes:
        write.assert_not_awaited()
    confirmed = request | {"confirmed": True, "kind": "schedule", "program_id": schedule["id"]}
    with patch.object(
        type(hass_admin_user.permissions), "check_entity", side_effect=lambda _, p: p == POLICY_READ
    ):
        await socket.send_json(confirmed | {"id": 4, "review_id": schedule["review_id"]})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(confirmed | {"id": 5, "review_id": routine["review_id"]})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    for write in writes:
        write.assert_not_awaited()
    await socket.send_json(confirmed | {"id": 6, "review_id": schedule["review_id"]})
    assert (await socket.receive_json())["result"] == {"applied": True}
    writes[0].assert_not_awaited()
    writes[1].assert_awaited_once()
    selection = writes[1].await_args.kwargs
    assert selection["expected_selection"] == (profiles[:1], True)
    assert {"expected_selection", "target"} == selection.keys()
    assert selection["target"].profiles == (
        CleaningProfile(CleaningMode.VACUUM, suction_level=1),
        CleaningProfile(CleaningMode.MOP, wetness_level=2, two_pass=True),
    )
    await socket.send_json(
        confirmed
        | {
            "id": 7,
            "kind": "routine",
            "program_id": routine["id"],
            "review_id": routine["review_id"],
        }
    )
    assert (await socket.receive_json())["result"] == {"applied": True}
    writes[0].assert_awaited_once_with(
        "fixture-0",
        routine["id"],
        None,
        selection["target"],
        expected_selection=(profiles[:1], True),
    )


@pytest.mark.parametrize(
    "source_failure", [ProtocolError(), RateLimited(30), AuthenticationError()]
)
async def test_program_backup_keeps_geometry_when_a_program_source_fails(
    configured, picea_archive, hass_ws_client, source_failure
):
    zones = [("100", "Entry", ((9, 1), (9, 2), (8.2, 2), (8.2, 1), (9, 1)))]
    configured.client.map_geometry.return_value = picea_archive(zones=zones)
    configured.client.list_cleaning_routines = AsyncMock(side_effect=source_failure)
    configured.client.list_cleaning_schedules = AsyncMock(return_value=[])
    socket = await hass_ws_client()
    await socket.send_json(CAPTURE_BACKUP | {"id": 1})
    response = await socket.receive_json()
    if isinstance(source_failure, AuthenticationError):
        assert response["error"]["code"] == "map_unavailable"
        configured.client.list_cleaning_schedules.assert_not_awaited()
        return
    backup = response["result"]
    assert backup["program_count"] == 0 and backup["programs_unchecked"] == ["routine"]
    await socket.send_json(CAPTURE_BACKUP | {"id": 2})
    assert (await socket.receive_json())["result"] == backup
    expected_reads = 1 if isinstance(source_failure, RateLimited) else 2
    assert configured.client.list_cleaning_routines.await_count == expected_reads


@pytest.mark.parametrize(
    ("kind", "failure", "code"),
    [
        ("routine", RateLimited(30), "map_backup_failed"),
        ("schedule", RateLimited(30), "map_backup_failed"),
        ("schedule", ProgramSelectionChanged(), "map_changed"),
        ("schedule", AuthenticationError(), "map_unavailable"),
        ("routine", ProtocolError(), "map_backup_failed"),
    ],
)
async def test_recovery_reports_write_errors_and_never_retries(
    configured, program_recovery, kind, failure, code
):
    socket, request, _ = program_recovery
    await socket.send_json(request | {"id": 3})
    responses = (await socket.receive_json())["result"]["programs"]
    row = next(item for item in responses if item["kind"] == kind)
    other = "schedule" if kind == "routine" else "routine"
    write = getattr(configured.client, f"update_cleaning_{kind}")
    write.side_effect = failure
    await socket.send_json(
        request
        | {
            "id": 4,
            "confirmed": True,
            "kind": kind,
            "program_id": row["id"],
            "review_id": row["review_id"],
        }
    )
    assert (await socket.receive_json())["error"]["code"] == code
    write.assert_awaited_once()
    getattr(configured.client, f"update_cleaning_{other}").assert_not_awaited()


async def test_program_review_reports_unavailable_sources(configured, program_recovery):
    socket, request, _ = program_recovery
    configured.client.list_cleaning_schedules.side_effect = OSError()
    await socket.send_json(request | {"id": 3})
    routine, schedule = (await socket.receive_json())["result"]["programs"]
    assert routine["status"] == "ready"
    assert schedule["status"] == "source_unavailable" and "review_id" not in schedule
    configured.client.update_cleaning_schedule.assert_not_awaited()


async def test_program_recovery_accepts_old_copies_and_checks_floor_identity(
    hass, entry, configured, hass_ws_client, picea_archive
):
    history = map_history(hass, entry.entry_id)
    socket = await hass_ws_client()
    configured.client.map_geometry.return_value = picea_archive()
    for index, saved in enumerate((MAP, replace(MAP, map_id="other-map")), start=1):
        record, _ = capture_snapshot(saved, picea_archive(map_id=saved.map_id), datetime.now(UTC))
        await history.async_capture("fixture-0", record)
        await socket.send_json(
            CAPTURE_BACKUP
            | {
                "id": index,
                "type": "roomba_home/restore_map_backup_programs",
                "backup_id": record["id"],
            }
        )
        response = await socket.receive_json()
        if saved == MAP:
            assert response["result"] == {"programs": [], "unchecked": [], "applied": False}
        else:
            assert "Select the active floor" in response["error"]["message"]


async def test_backup_restrictions_requires_control_and_matching_review(
    hass, entry, configured, hass_ws_client, hass_admin_user, picea_archive, policy_feature
):
    rectangle = ((8, 1), (8, 3), (6, 3), (6, 1), (8, 1))
    moved_shape = ((8, 4), (8, 5), (6, 5), (6, 4), (8, 4))
    keep = policy_feature("100", "KeepOutZone", [rectangle])
    moved = policy_feature("100", "KeepOutZone", [moved_shape])
    wall = policy_feature("101", "KeepOutZone", [[2, 2], [3, 2]], geometry_type="LineString")
    newer = policy_feature("102", "NoMopZone", [rectangle])
    history = map_history(hass, entry.entry_id)
    saved = replace(MAP, version_id="original")
    record, _ = capture_snapshot(
        saved, picea_archive(version="original", restrictions=[keep, wall]), datetime.now(UTC)
    )
    await history.async_capture("fixture-0", record)
    await history.async_configure("fixture-0", 5, True)
    configured.client.map_geometry.return_value = picea_archive(restrictions=[moved, newer])
    configured.client.edit_map = AsyncMock(
        return_value=picea_archive(version="version.43", restrictions=[keep, newer, wall])
    )
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_restrictions",
        "backup_id": record["id"],
    }
    socket = await hass_ws_client()
    await socket.send_json(request | {"id": 1})
    review = (await socket.receive_json())["result"]
    assert review["changes"] == [
        {"id": "100", "kind": "keep_out", "missing": False},
        {"id": "101", "kind": "wall", "missing": True},
    ]
    assert review["applied"] is False and len(review["review_id"]) == 64
    configured.client.edit_map.assert_not_awaited()
    confirm = request | {"confirmed": True, "review_id": review["review_id"]}
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _entity, permission: permission == POLICY_READ,
    ):
        await socket.send_json(confirm | {"id": 2})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(confirm | {"id": 3, "review_id": "b" * 64})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.edit_map.assert_not_awaited()
    configured.client.maps.side_effect = [(MAP,), (MAP,), (replace(MAP, version_id="version.43"),)]
    await socket.send_json(confirm | {"id": 4})
    assert (await socket.receive_json())["result"] == review | {"applied": True}
    configured.client.edit_map.assert_awaited_once()
    _, edit = configured.client.edit_map.await_args.args
    assert [item.identifier for item in edit.restrictions] == ["100", "102", "101"]
    assert len((await history.async_list("fixture-0"))["snapshots"]) == 2


async def test_backup_furniture_reviews_known_routines_and_confirms_after_time_passes(
    hass, entry, configured, hass_ws_client, picea_archive, furniture_feature
):
    position = ((1, 1), (3, 1), (3, 2), (1, 2))
    shifted = ((7, 1), (9, 1), (9, 2), (7, 2))
    chair = furniture_feature("1", "chair/living", "user", position)
    moved = furniture_feature("1", "chair/living", "user", shifted)
    detected = furniture_feature("2", "table/coffee", "robot", shifted)
    new = furniture_feature("3", "cabinet", "user", position)
    saved = replace(MAP, version_id="original")
    record, _ = capture_snapshot(
        saved, picea_archive(version="original", furniture=[chair, detected]), datetime.now(UTC)
    )
    history = map_history(hass, entry.entry_id)
    await history.async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive(furniture=[moved, new])
    configured.client.edit_map = AsyncMock(
        return_value=picea_archive(version="version.43", furniture=[chair, new, detected])
    )
    configured.client.list_cleaning_routines = AsyncMock(
        return_value=[
            {
                "name": "Morning",
                "regions": ["map-a:rid:room-a", "map-a:furniture:2", "map-a:furniture:1"],
            },
            {"name": "Other", "regions": ["map-a:furniture:3"]},
            {"name": "Unrecognized", "regions": None},
        ]
    )
    configured.client.list_cleaning_schedules = AsyncMock()
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_furniture",
        "backup_id": record["id"],
    }
    socket = await hass_ws_client()
    clock = "custom_components.roomba_home.core.furniture_edits.time"
    with patch(clock, return_value=1720000000):
        await socket.send_json(request | {"id": 1})
        review = (await socket.receive_json())["result"]
    assert len(review["review_id"]) == 64 and review["applied"] is False
    assert [change["missing"] for change in review["changes"]] == [False, True]
    assert review["dependencies"] == [{"kind": "routine", "name": "Morning", "objects": ["1", "2"]}]
    assert review["unchecked"] == ["routine"]
    configured.client.list_cleaning_schedules.assert_not_awaited()
    configured.client.edit_map.assert_not_awaited()
    confirmed = request | {"confirmed": True, "review_id": review["review_id"]}
    original_routine = configured.client.list_cleaning_routines.return_value[0]
    configured.client.list_cleaning_routines.return_value[0] = original_routine | {
        "name": "Changed"
    }
    await socket.send_json(confirmed | {"id": 2})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.edit_map.assert_not_awaited()
    configured.client.list_cleaning_routines.return_value[0] = original_routine
    configured.client.maps.side_effect = [(MAP,), (MAP,), (replace(MAP, version_id="version.43"),)]
    with patch(clock, return_value=1720000600):
        await socket.send_json(confirmed | {"id": 3})
        assert (await socket.receive_json())["result"] == review | {"applied": True}
    configured.client.edit_map.assert_awaited_once()


async def test_backup_relinks_a_missing_furniture_target_with_its_original_settings(
    configured, hass_ws_client, picea_archive, furniture_feature
):
    rectangle = ((2, 1), (3, 1), (3, 2), (2, 2))
    chair = furniture_feature("1", "chair/living", "robot", rectangle)
    profiles = [
        {"id": "map-a:rid:room-a", "mode": "vacuum", "suction_level": 1},
        {"id": "map-a:furniture:1", "mode": "mop", "wetness_level": 2},
    ]
    program = {
        "id": "a" * 32,
        "name": "Routine",
        "regions": [row["id"] for row in profiles],
        "region_settings": profiles,
        "editable": True,
    }
    configured.client.map_geometry.return_value = picea_archive(furniture=[chair])
    configured.client.list_cleaning_routines = AsyncMock(return_value=[program])
    configured.client.list_cleaning_schedules = AsyncMock()
    configured.client.update_cleaning_routine = AsyncMock()
    socket = await hass_ws_client()
    await socket.send_json(CAPTURE_BACKUP | {"id": 1})
    backup = (await socket.receive_json())["result"]
    assert backup["program_count"] == 1
    configured.client.list_cleaning_schedules.assert_not_awaited()
    configured.client.list_cleaning_routines.return_value = [
        program | {"regions": [profiles[0]["id"]], "region_settings": profiles[:1]}
    ]
    configured.client.map_geometry.return_value = picea_archive(furniture=[])
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_programs",
        "backup_id": backup["id"],
    }
    await socket.send_json(request | {"id": 2})
    [review] = (await socket.receive_json())["result"]["programs"]
    assert review["status"] == "restore_areas_first"
    assert "review_id" not in review
    configured.client.map_geometry.return_value = picea_archive(furniture=[chair])
    configured._floor_plans.clear()
    await socket.send_json(request | {"id": 3})
    [review] = (await socket.receive_json())["result"]["programs"]
    assert review["status"] == "ready"
    assert review["destinations"] == [
        profiles[0] | {"name": "Office", "restore": False},
        profiles[1] | {"name": "Chair", "restore": True},
    ]
    await socket.send_json(
        request
        | {
            "id": 4,
            "confirmed": True,
            "kind": "routine",
            "program_id": program["id"],
            "review_id": review["review_id"],
        }
    )
    assert (await socket.receive_json())["result"] == {"applied": True}
    configured.client.update_cleaning_routine.assert_awaited_once()
    _, _, _, target = configured.client.update_cleaning_routine.await_args.args
    assert target.regions[-1].kind is RegionKind.FURNITURE
    assert target.profiles[-1] == CleaningProfile(CleaningMode.MOP, wetness_level=2)


@pytest.fixture
async def room_recovery(hass, entry, configured, hass_ws_client, picea_archive):
    def details(name, kind):
        def modify(files):
            files["rooms.geojson"]["features"][0]["properties"].update(
                name=name, type={"value": kind}
            )

        return modify

    archived = replace(MAP, version_id="archive.31")
    original = details("Cocína", "kitchen")
    current = details("Oficina", "other")
    backup, _ = capture_snapshot(
        archived, picea_archive(version=archived.version_id, mutate=original), datetime.now(UTC)
    )
    history = map_history(hass, entry.entry_id)
    await history.async_capture("fixture-0", backup)
    await history.async_configure("fixture-0", 5, True)

    def bundle(_map_id, version):
        return picea_archive(
            version=version, mutate=current if version == MAP.version_id else original
        )

    configured.client.map_geometry = AsyncMock(side_effect=bundle)
    configured.client.edit_map = AsyncMock(return_value=MapEditAcknowledgement("version.43"))
    socket = await hass_ws_client()
    request = CAPTURE_BACKUP | {
        "type": "roomba_home/restore_map_backup_room_details",
        "backup_id": backup["id"],
    }
    return history, socket, request, original


@pytest.mark.parametrize("corrupted_response", [False, True])
async def test_room_details_recovery_verifies_a_revision_acknowledgement(
    configured, hass_admin_user, room_recovery, picea_archive, corrupted_response
):
    history, socket, request, original = room_recovery
    await socket.send_json(request | {"id": 1})
    result = await socket.receive_json()
    assert result["success"], result
    [row] = result["result"]["rooms"]
    assert row["status"] == "ready"
    assert row["name"] == {"from": "Oficina", "to": "Cocína"}
    assert row["room_type"] == {"from": "other", "to": "kitchen"}
    configured.client.edit_map.assert_not_awaited()
    confirm = request | {"confirmed": True, "room_id": "room-a", "review_id": row["review_id"]}
    with patch.object(
        type(hass_admin_user.permissions),
        "check_entity",
        side_effect=lambda _, permission: permission == POLICY_READ,
    ):
        await socket.send_json(confirm | {"id": 2})
        assert (await socket.receive_json())["error"]["code"] == "unauthorized"
    await socket.send_json(confirm | {"id": 3, "room_id": "unrelated"})
    assert (await socket.receive_json())["error"]["code"] == "map_changed"
    configured.client.edit_map.assert_not_awaited()
    configured.client.maps.side_effect = [(MAP,), (MAP,), (replace(MAP, version_id="version.43"),)]
    if corrupted_response:
        read = configured.client.map_geometry.side_effect
        configured.client.map_geometry.side_effect = lambda map_id, version: (
            picea_archive(version="version.44", mutate=original)
            if version == "version.43"
            else read(map_id, version)
        )
    await socket.send_json(confirm | {"id": 4})
    confirmed = await socket.receive_json()
    if corrupted_response:
        assert confirmed["error"]["code"] == "map_backup_failed"
        assert "could not be confirmed" in confirmed["error"]["message"]
    else:
        assert confirmed["result"] == {"applied": True}
    configured.client.edit_map.assert_awaited_once()
    configured.client.map_geometry.assert_awaited_with(MAP.map_id, "version.43")
    _, edit = configured.client.edit_map.await_args.args
    assert edit.room_ids == ("room-a",)
    assert edit.name == "Cocína" and edit.room_type == "kitchen"
    assert len((await history.async_list("fixture-0"))["snapshots"]) == 2


@pytest.mark.parametrize("variant", ["wrong_floor", "old_format"])
async def test_room_details_refuses_incompatible_backups(
    hass, entry, configured, hass_ws_client, picea_archive, variant
):
    history = map_history(hass, entry.entry_id)
    saved = replace(MAP, map_id="wrong-floor") if variant == "wrong_floor" else MAP
    raw = (
        picea_archive(map_id=saved.map_id)
        if variant == "wrong_floor"
        else configured.client.map_geometry.return_value
    )
    record, _ = capture_snapshot(saved, raw, datetime.now(UTC))
    await history.async_capture("fixture-0", record)
    configured.client.map_geometry.return_value = picea_archive()
    socket = await hass_ws_client()
    await socket.send_json(
        CAPTURE_BACKUP
        | {
            "id": 1,
            "type": "roomba_home/restore_map_backup_room_details",
            "backup_id": record["id"],
        }
    )
    failure = (await socket.receive_json())["error"]
    assert (
        "Select the active floor" if variant == "wrong_floor" else "unavailable for this map format"
    ) in failure["message"]


async def test_room_details_review_lists_boundary_changes_without_a_write(
    configured, room_recovery, picea_archive
):
    _, socket, request, _ = room_recovery
    configured.client.map_geometry = AsyncMock(return_value=picea_archive(split=True))
    await socket.send_json(request | {"id": 1})
    result = (await socket.receive_json())["result"]
    [room] = result["rooms"]
    assert room["status"] == "changed_boundary" and "review_id" not in room
    assert result["applied"] is False
    configured.client.edit_map.assert_not_awaited()


async def test_virtual_wall_editor_creates_moves_and_removes_a_line(
    hass_ws_client, configured, picea_archive, policy_feature
):
    added = replace(MAP, version_id="version.43")
    moved = replace(MAP, version_id="version.44")
    cleared = replace(MAP, version_id="version.45")
    keep = policy_feature("100", "KeepOutZone", [[[4, 6], [4, 7], [3, 7], [3, 6], [4, 6]]])
    first = [[2, 1], [4, 1]]
    second = [[3, 3], [3, 1]]

    def wall(points):
        return policy_feature("101", "KeepOutZone", points, geometry_type="LineString")

    archives = {
        scope.version_id: picea_archive(version=scope.version_id, restrictions=restrictions)
        for scope, restrictions in (
            (MAP, [keep]),
            (added, [keep, wall(first)]),
            (moved, [keep, wall(second)]),
            (cleared, [keep]),
        )
    }
    configured.client.map_geometry.side_effect = lambda _, version: archives[version]
    configured.client.edit_map = AsyncMock(
        side_effect=[archives[scope.version_id] for scope in (added, moved, cleared)]
    )
    configured.client.maps.side_effect = [
        (MAP,),
        (added,),
        (added,),
        (moved,),
        (moved,),
        (cleared,),
    ]
    socket = await hass_ws_client()
    request = {
        "type": "roomba_home/edit_restrictions",
        "entity_id": ENTITY,
        "map_id": MAP.map_id,
        "version": MAP.version_id,
        "inventory_id": MAP.inventory_id,
    }
    await socket.send_json(
        request | {"id": 1, "operation": "create", "kind": "wall", "bounds": [2, 1, 4, 1]}
    )
    assert (await socket.receive_json())["result"]["version"] == added.version_id
    await socket.send_json(
        request
        | {
            "id": 2,
            "operation": "update",
            "zone_id": "101",
            "bounds": [3, 3, 3, 1],
            "version": added.version_id,
        }
    )
    assert (await socket.receive_json())["result"]["version"] == moved.version_id
    await socket.send_json({"id": 3, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert geometry["virtual_walls"] == [second]
    assert geometry["editable_restrictions"][-1] == {"id": "101", "kind": "wall", "points": second}
    await socket.send_json(
        request
        | {
            "id": 4,
            "operation": "delete",
            "zone_id": "101",
            "version": moved.version_id,
        }
    )
    assert (await socket.receive_json())["result"]["version"] == cleared.version_id
    await socket.send_json({"id": 5, "type": "roomba_home/floor_plan", "entity_id": ENTITY})
    geometry = (await socket.receive_json())["result"]["geometry"]
    assert geometry["virtual_walls"] == []
    assert [shape["id"] for shape in geometry["editable_restrictions"]] == ["100"]
    writes = [
        call.args[1].request_body()["edit_cmd"]["params"]["virwall"]
        for call in configured.client.edit_map.await_args_list
    ]
    assert [row[0] for row in writes] == [2, 2, 1]
    assert writes[1][2] == ["101", 2, 3, 3, 3, 3, 3, 1, 3, 1]
