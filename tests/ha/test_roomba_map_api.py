from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.roomba_home.const import CONF_SHOW_MAPS, DOMAIN
from custom_components.roomba_home.coordinator import RoombaCoordinator
from custom_components.roomba_home.core.live_maps import MissionPath, Position, PositionBatch
from custom_components.roomba_home.core.maps import CleaningRegion, PersistentMap, RegionKind
from custom_components.roomba_home.map_api import live_geometry

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


@pytest.fixture
async def configured(hass, entry, robot_states, make_point_bundle):
    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_MAPS: True})
    robot = replace(
        robot_states["fixture-0"],
        telemetry={"maps_available": True},
        capabilities=replace(robot_states["fixture-0"].capabilities, persistent_maps=True),
    )

    def with_zone(documents):
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
    assert result["maps"] == [{"id": MAP.map_id, "name": MAP.name}]
    assert result["geometry"]["keep_out"]
    assert result["geometry"]["virtual_walls"] == [[[1, 1], [2, 2]]]
    assert [(r["name"], r["kind"], bool(r["polygons"])) for r in result["geometry"]["regions"]] == [
        ("Office", "room", True),
        ("Dining zone", "zone", True),
    ]
    assert result["live"] == {"trail": [], "position": None}
    await socket.send_json(
        initial | {"id": 2, "map_id": MAP.map_id, "known_version": MAP.version_id}
    )
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
        22, int(now.timestamp()), int(now.timestamp()) + 20, (Position(2, 4, 0, 2),)
    )
    path = MissionPath((MAP.map_id, MAP.version_id), now, batch, ()).append(batch)
    fresh = live_geometry(path, MAP, now)
    assert fresh["position"]["x"] == 2
    assert fresh["trail"] == [(22, 2, 4)]
    assert live_geometry(path, MAP, now + timedelta(seconds=21))["position"] is None
    assert live_geometry(path, replace(MAP, version_id="old"), now) == {
        "trail": [],
        "position": None,
    }
