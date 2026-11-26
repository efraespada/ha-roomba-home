import asyncio
import json
from collections import deque
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import pytest
from aiohttp import ClientError

from custom_components.roomba_home.core import AppProfile, LoginDetails, RoombaClient
from custom_components.roomba_home.core.cleaning import (
    CleaningCapabilities,
    CleaningMode,
    CleaningProfile,
)
from custom_components.roomba_home.core.client import (
    MapEditAcknowledgement,
    check_status,
    signed_headers,
)
from custom_components.roomba_home.core.errors import (
    ApiError,
    AuthenticationError,
    ProgramSelectionChanged,
    ProtocolError,
    RateLimited,
    RoutineNotEditable,
    RoutineUpdateUnconfirmed,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from custom_components.roomba_home.core.floor_settings import prepare_floor_settings
from custom_components.roomba_home.core.live_route import raw_route_reference
from custom_components.roomba_home.core.maps import (
    AreaTarget,
    CleaningRegion,
    PersistentMap,
    RegionKind,
)
from custom_components.roomba_home.core.models import CloudSession, relative_api_path, trusted_url
from custom_components.roomba_home.core.room_edits import RoomEdit
from custom_components.roomba_home.core.routines import (
    cleaning_routines,
    routine_appearance,
    routine_command,
    routine_matches,
)
from custom_components.roomba_home.core.schedules import new_cleaning_schedule
from custom_components.roomba_home.core.transport import (
    GZIP_JSON_ACCEPT,
    RAW_MAP_ACCEPT,
    HttpResponse,
)

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)


def discovery():
    return {
        "current_deployment": "fixture",
        "deployments": {
            "fixture": {
                "httpBase": "https://unauth.fixture.irobotapi.com",
                "httpBaseAuth": "https://auth.fixture.irobotapi.com",
                "awsRegion": "us-east-1",
            }
        },
        "gigya": {"api_key": "fixture-public-app-key", "datacenter_domain": "us1.gigya.com"},
    }


def session():
    return {
        "credentials": {
            "AccessKeyId": "fixture-access",
            "SecretKey": "fixture-secret",
            "SessionToken": "fixture-token",
            "Expiration": (NOW + timedelta(hours=1)).isoformat(),
        },
        "robots": {"robot-fixture": {"sku": "TESTMODEL"}},
        "connection_tokens": [],
    }


def login_responses():
    return [
        HttpResponse(200, discovery()),
        HttpResponse(
            200,
            {
                "errorCode": 0,
                "UID": "fixture-uid",
                "UIDSignature": "fixture-signature",
                "signatureTimestamp": "fixture-timestamp",
            },
        ),
        HttpResponse(200, session()),
    ]


async def test_robot_serial_number_uses_signed_associated_asset_lookup():
    payload = {"RobotID": "robot-fixture", "SerialNumber": "FIXTURE123"}
    http = FakeHttp(login_responses() + [HttpResponse(200, payload)])
    api = client(http)
    assert await api.robot_serial_number("robot-fixture") == "FIXTURE123"
    method, url, headers, body = http.calls[-1]
    assert method == "GET" and body is None
    assert url.endswith("/v1/robots?robot_id=robot-fixture")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    with pytest.raises(ProtocolError, match="associated robot"):
        await api.robot_serial_number("unknown-fixture")
    assert len(http.calls) == 4


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"RobotID": "different-robot", "SerialNumber": "FIXTURE123"},
        {"RobotID": "robot-fixture", "SerialNumber": 123},
        {"RobotID": "robot-fixture", "SerialNumber": "  "},
    ],
)
async def test_robot_serial_number_rejects_unmatched_or_invalid_metadata(payload):
    http = FakeHttp(login_responses() + [HttpResponse(200, payload)])
    with pytest.raises(ProtocolError, match="serial number for the selected robot"):
        await client(http).robot_serial_number("robot-fixture")


@pytest.mark.parametrize("scope", ["current", "foreign robot", "invalid map"])
async def test_cleaning_score_request_uses_only_the_scoped_map(scope):
    floor = PersistentMap("floor-fixture", "version.2", "Office floor", ())
    robot = "robot-fixture"
    payload = {"clean_scores": [], "clean_score_ranges": [0.7]}
    if scope == "foreign robot":
        robot = "different-robot"
    elif scope == "invalid map":
        floor = replace(floor, map_id="..")
    http = FakeHttp(login_responses() + [HttpResponse(200, payload)])
    if scope == "current":
        scores = await client(http).map_cleaning_scores(robot, floor)
        assert scores["rooms"] == [] and scores["map"]["version"] == floor.version_id
        method, url, headers, body = http.calls[-1]
        assert method == "GET" and body is None
        assert url.endswith("/v1/p2maps/clean-score?p2map_id=floor-fixture")
        assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")
    else:
        with pytest.raises(ProtocolError, match="associated map"):
            await client(http).map_cleaning_scores(robot, floor)
        assert len(http.calls) == 3


@pytest.mark.parametrize(
    "status, data", [(200, b"object"), (403, b"error"), (200, None), (200, b"")]
)
async def test_live_route_download_preserves_the_signed_query(
    make_raw_route_document, status, data
):
    stamp = int(NOW.timestamp())
    reference = raw_route_reference(make_raw_route_document(stamp), "fixture-robot", stamp)
    http = FakeHttp([HttpResponse(status, data)])
    api = client(http)
    if status == 200 and data:
        assert await api.raw_live_route(reference) == data
    else:
        with pytest.raises(ProtocolError, match="object is unavailable"):
            await api.raw_live_route(reference)
    assert http.calls == [("GET", http.calls[0][1], {"Accept": RAW_MAP_ACCEPT}, None)]
    assert str(http.calls[0][1]) == reference.url
    assert http.calls[0][1].raw_query_string.find("fixture%2Fread-only") > 0


async def test_live_route_download_hides_transport_error_details(make_raw_route_document):
    stamp = int(NOW.timestamp())
    reference = raw_route_reference(make_raw_route_document(stamp), "fixture-robot", stamp)
    request = AsyncMock(side_effect=ClientError("Private object URL"))
    api = client(FakeHttp([]))
    api.http.request = request
    with pytest.raises(ProtocolError, match="object is unavailable") as failure:
        await api.raw_live_route(reference)
    assert "Private object URL" not in str(failure.value)


class FakeHttp:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    async def request(self, method, url, *, headers=None, body=None):
        self.calls.append((method, url, headers, body))
        await asyncio.sleep(0)
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


async def test_part_reset_posts_one_zero_counter_to_associated_robot():
    payload = {"parts": [{"part_id": "202", "counter": 0}]}
    http = FakeHttp(
        [*login_responses(), HttpResponse(200, {"robot_id": "robot-fixture", **payload})]
    )
    await client(http).reset_part("robot-fixture", "202")
    method, url, headers, body = http.calls[-1]
    assert method == "POST"
    assert url == "https://auth.fixture.irobotapi.com/v1/robots/robot-fixture/parts"
    assert "Authorization" in headers
    assert json.loads(body) == payload


@pytest.mark.parametrize(("robot", "part"), [("unassociated", "202"), ("robot-fixture", "147")])
async def test_part_reset_rejects_unassociated_robot_or_non_resettable_part(robot, part):
    http = FakeHttp(login_responses())
    with pytest.raises(ProtocolError, match="associated robot"):
        await client(http).reset_part(robot, part)
    assert len(http.calls) == 3


@pytest.mark.parametrize("ack", [[], {}, {"robot_id": "robot-fixture", "parts": []}])
async def test_part_reset_rejects_invalid_acknowledgement(ack):
    http = FakeHttp([*login_responses(), HttpResponse(200, ack)])
    with pytest.raises(ProtocolError, match="acknowledge"):
        await client(http).reset_part("robot-fixture", "202")


def client(http, **kwargs):
    return RoombaClient(
        http,
        LoginDetails("fixture-login", "fixture-password"),
        AppProfile("fixture-app", {"device_id": "fixture-device"}),
        clock=lambda: NOW,
        **kwargs,
    )


async def test_fresh_native_login_and_signed_read():
    http = FakeHttp(
        login_responses() + [HttpResponse(200, {"robot-fixture": {"sku": "TESTMODEL"}})]
    )
    c = client(http)
    assert len(await c.robots()) == 1
    form = parse_qs(http.calls[1][3].decode())
    assert form["loginID"] == ["fixture-login"]
    assert form["targetEnv"] == ["mobile"]
    payload = json.loads(http.calls[2][3])
    assert payload["gigya"]["uid"] == "fixture-uid"
    assert "password" not in payload
    headers = {k.lower(): v for k, v in http.calls[3][2].items()}
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
    assert headers["x-amz-security-token"] == "fixture-token"


async def test_mission_report_list_reuses_signed_history_resource():
    row = {"robot_id": "robot-fixture", "timestamp": 1700000500, "cmd": {"command": "start"}}
    http = FakeHttp([*login_responses(), HttpResponse(200, [row])])
    reports = await client(http).mission_reports("robot-fixture")
    assert len(reports) == 1 and reports[0].summary()["command"] == "start"
    method, url, headers, _body = http.calls[-1]
    assert method == "GET" and "Authorization" in headers
    assert url.startswith("https://auth.fixture.irobotapi.com/v1/robot-fixture/missionhistory?")
    assert parse_qs(url.partition("?")[2])["maxAge"] == ["10"]


async def test_floor_removal_uses_one_signed_visibility_write_with_empty_response():
    http = FakeHttp([*login_responses(), HttpResponse(204, None)])
    await client(http).remove_floor("fixture-map")
    method, target, headers, body = http.calls[-1]
    assert method == "POST"
    assert (
        target
        == "https://auth.fixture.irobotapi.com/v1/p2maps/fixture-map/settings?trigger_fast_updates=true"
    )
    assert "Authorization" in headers and json.loads(body) == {"visible": False}


async def test_floor_removal_rejects_an_invalid_identifier_before_signing():
    http = FakeHttp([])
    with pytest.raises(ProtocolError, match="valid map identifier"):
        await client(http).remove_floor("../wrong")
    assert http.calls == []


@pytest.mark.parametrize("dock_version", [None, "42"])
async def test_firmware_status_uses_a_public_model_query_and_returns_only_versions(dock_version):
    installed = "p25-705+9.3.6+I5.3.149"
    firmware = [
        {"sku": "x185240", "version": "9.3.7", "downloadUrl": "fixture-private-url"},
        {"sku": "X185240", "version": "9.3.7"},
        {"sku": "X185240", "version": installed},
    ]
    http = FakeHttp([HttpResponse(200, {"firmware": firmware})])
    assert await client(http).firmware_candidates("X185240", installed, dock_version) == ("9.3.7",)
    [(method, url, headers, body)] = http.calls
    host, query = url.split("?", 1)
    assert host == "https://content-prod.iot.irobotapi.com/v2/firmware"
    expected = {"sku": ["X185240"], "softwareVer": [installed]}
    if dock_version:
        expected["dockFwVer"] = [dock_version]
    assert parse_qs(query) == expected
    assert method == "GET" and headers is None and body is None


@pytest.mark.parametrize(
    "document",
    [
        None,
        {},
        {"firmware": [None]},
        {"firmware": [{"sku": "other", "version": "9.3.7"}]},
        {"firmware": [{"sku": "X185240", "version": "https://example.invalid"}]},
        {"firmware": [{"sku": 185240, "version": "9.3.7"}]},
    ],
)
async def test_malformed_firmware_catalog_is_not_reported_as_up_to_date(document):
    http = FakeHttp([HttpResponse(200, document)])
    with pytest.raises(ProtocolError, match="firmware catalog"):
        await client(http).firmware_candidates("X185240", "9.3.6", None)


@pytest.mark.parametrize(
    "sku,installed,dock",
    [
        (None, "9.3.6", "42"),
        ("invalid?model", "9.3.6", "42"),
        ("X185240", "bad version", "42"),
        ("X185240", "9.3.6", "bad dock"),
    ],
)
async def test_firmware_query_rejects_non_version_input(sku, installed, dock):
    http = FakeHttp([])
    with pytest.raises(ProtocolError, match="model and installed firmware"):
        await client(http).firmware_candidates(sku, installed, dock)
    assert not http.calls


async def test_public_voice_catalog_requires_no_credentials_and_scopes_results_to_the_model():
    http = FakeHttp(
        [
            HttpResponse(
                200,
                {
                    "languagePackItems": [
                        None,
                        {"sku": 1, "languages": ["tr-TR"]},
                        {"sku": "other", "languages": ["tr-TR"]},
                        {"sku": "x185240", "languages": "tr-TR"},
                        {"sku": "x185240", "languages": ["es-ES", "en-GB", "private data"]},
                        {"sku": "X185240", "languages": ["en-GB", "cs-CZ"]},
                    ]
                },
            )
        ]
    )
    assert await client(http).voice_catalog("X185240") == ("cs-cz", "en-gb", "es-es")
    assert http.calls == [
        ("GET", "https://content-prod.iot.irobotapi.com/v2/app/langpacks/X185240", None, None)
    ]


@pytest.mark.parametrize("sku", ["../robots", 0])
async def test_voice_catalog_rejects_bad_model_paths_before_using_the_network(sku):
    http = FakeHttp([])
    with pytest.raises(ProtocolError):
        await client(http).voice_catalog(sku)
    assert http.calls == []


@pytest.mark.parametrize("body", [[], {"languagePackItems": {}}])
async def test_voice_catalog_rejects_malformed_documents(body):
    with pytest.raises(ProtocolError):
        await client(FakeHttp([HttpResponse(200, body)])).voice_catalog("X185240")


async def test_voice_pack_uses_the_same_unsigned_catalog():
    http = FakeHttp(
        [
            HttpResponse(
                200,
                {
                    "languagePackItems": [
                        {
                            "sku": "x185240",
                            "languages": ["da-DK"],
                            "deploymentMpkg": "picea_lang_pack/da_DK_v10.zip",
                        }
                    ]
                },
            )
        ]
    )
    pack = await client(http).voice_pack("X185240", "da-dk")
    assert pack.language == "da-DK"
    assert pack.metapackage == "picea_lang_pack/da_DK_v10.zip"
    assert http.calls[0][2:] == (None, None)


async def test_signed_geojson_response_pins_the_selected_map_version():
    http = FakeHttp(login_responses() + [HttpResponse(200, b"fixture-bundle")])
    api = client(http)
    assert await api.map_geometry("map-a", "version.42") == b"fixture-bundle"
    method, url, headers, body = http.calls[-1]
    assert method == "GET" and body is None
    assert url == (
        "https://auth.fixture.irobotapi.com/v1/p2maps/map-a/versions/version.42/geojson"
        "?response_type=binary"
    )
    assert headers["Accept"] == GZIP_JSON_ACCEPT
    assert "SignedHeaders=accept;" in headers["Authorization"]


@pytest.mark.parametrize(
    ("edit", "name", "params"),
    [
        (
            RoomEdit(("room-a",), ((-1, 4), (11, 4))),
            "split_room",
            {"room_id": "room-a", "split_points": [-1, 4, 11, 4]},
        ),
        (
            RoomEdit(("room-a", "room-b")),
            "arrange_room",
            {"room_ids": ["room-a", "room-b"]},
        ),
    ],
)
async def test_signed_room_edit_writes_one_map_version(edit, name, params):
    http = FakeHttp(login_responses() + [HttpResponse(200, b"fixture-bundle")])
    assert await client(http).edit_map("map-a", edit) == b"fixture-bundle"
    method, url, headers, body = http.calls[-1]
    assert len(http.calls) == 4
    assert method == "POST"
    assert url == "https://auth.fixture.irobotapi.com/v1/p2maps/map-a/versions"
    assert headers["Accept"] == GZIP_JSON_ACCEPT
    assert json.loads(body) == {
        "edit_cmd": {"command": name, "params": params},
        "response_type": "binary",
    }


async def test_room_edit_rejects_an_invalid_path_or_nonbinary_acknowledgement():
    http = FakeHttp(login_responses() + [HttpResponse(200, {"version": "unconfirmed"})])
    api = client(http)
    edit = RoomEdit(("room-a", "room-b"))
    with pytest.raises(ProtocolError, match="identifier"):
        await api.edit_map("..", edit)
    assert not http.calls
    with pytest.raises(ProtocolError, match="binary"):
        await api.edit_map("map-a", edit)
    assert len(http.calls) == 4


@pytest.mark.parametrize(
    "change",
    [
        None,
        {"status": 0},
        {"p2map_metadata": None},
        {"p2map_metadata": {"p2map_id": "different-map"}},
        {"p2mapv_id": "../old"},
    ],
)
async def test_room_edit_only_accepts_a_revision_acknowledgement_for_the_same_floor(change):
    ack = {
        "status": "success",
        "p2map_metadata": {"p2map_id": "map-a"},
        "p2mapv_id": "version.43",
        "url": "https://example.invalid/bundle",
    }
    http = FakeHttp(login_responses() + [HttpResponse(200, ack | (change or {}))])
    api = client(http)
    edit = RoomEdit(("room-a",), name="Kitchen", room_type="kitchen")
    if change is None:
        assert await api.edit_map("map-a", edit) == MapEditAcknowledgement("version.43")
    else:
        with pytest.raises(ProtocolError, match="revision acknowledgement"):
            await api.edit_map("map-a", edit)
    assert len(http.calls) == 4 and http.calls[-1][0] == "POST"


@pytest.mark.parametrize("ack", ["expected", "other robot", "different revision"])
async def test_floor_settings_post_checks_associated_map_and_active_revision(ack):
    floor = PersistentMap("map-a", "version.42", "Example floor", (), 0.0)
    value = {
        "p2map_id": floor.map_id,
        "active_p2mapv_id": floor.version_id if ack != "different revision" else "version.43",
        "name": "Ático",
        "robot_id": "robot-fixture" if ack != "other robot" else "other-robot",
        "visible": True,
        "state": "active",
        "rooms_metadata": [],
        "user_orientation_rad": 0,
    }
    http = FakeHttp(login_responses() + [HttpResponse(200, value)])
    api = client(http)
    edit = prepare_floor_settings(floor, "rename", "Ático", None)
    with pytest.raises(ProtocolError, match="identifier"):
        await api.update_floor_settings("robot-fixture", replace(floor, map_id=".."), edit)
    assert not http.calls
    if ack == "expected":
        await api.update_floor_settings("robot-fixture", floor, edit)
    else:
        with pytest.raises(ProtocolError, match="floor settings"):
            await api.update_floor_settings("robot-fixture", floor, edit)
    method, url, headers, body = http.calls[-1]
    assert method == "POST"
    assert url.endswith("/v1/p2maps/map-a/settings?trigger_fast_updates=true")
    assert "Authorization" in headers
    assert json.loads(body) == {"name": "Ático"}


@pytest.mark.parametrize("ids", [("..", "v"), ("map-a", "../v")])
async def test_point_geometry_rejects_invalid_paths_before_login(ids):
    http = FakeHttp([])
    with pytest.raises(ProtocolError, match="identifier"):
        await client(http).map_geometry(*ids)
    assert not http.calls


@pytest.mark.parametrize("value", [b"", {"url": "https://fixture.example/other"}])
async def test_point_geometry_requires_archive_and_does_not_follow_json_links(value):
    http = FakeHttp(login_responses() + [HttpResponse(200, value)])
    with pytest.raises(ProtocolError, match="binary"):
        await client(http).map_geometry("map-a", "version.42")
    assert len(http.calls) == 4


async def test_valid_session_is_reused_without_discovery_or_relogin():
    h = FakeHttp(login_responses())
    c = client(h)
    assert await c.ensure_session() is await c.ensure_session()
    assert len(h.calls) == 3


async def test_concurrent_session_requests_share_one_login():
    h = FakeHttp(login_responses())
    c = client(h)
    results = await asyncio.gather(*(c.ensure_session() for _ in range(12)))
    assert all(s is results[0] for s in results)
    assert len(h.calls) == 3


async def test_expiring_credentials_are_replaced_before_a_read():
    renewed = login_responses()
    renewed[-1].data["credentials"]["Expiration"] = (NOW + timedelta(hours=2)).isoformat()
    h = FakeHttp(login_responses() + renewed)
    c = client(h)
    old = await c.ensure_session()
    c.clock = lambda: NOW + timedelta(minutes=56)
    assert await c.ensure_session() is not old
    assert len(h.calls) == 6


async def test_cancelled_login_releases_the_lock_and_does_not_publish_partial_state():
    class CancelledHttp(FakeHttp):
        async def request(self, *args, **kwargs):
            raise asyncio.CancelledError

    c = client(CancelledHttp([]))
    with pytest.raises(asyncio.CancelledError):
        await c.ensure_session()
    assert c._session is None
    c.http = FakeHttp(login_responses())
    assert await c.ensure_session()


async def test_invalid_login_does_not_publish_provider_details_or_retry():
    h = FakeHttp(
        [
            HttpResponse(200, discovery()),
            HttpResponse(
                200,
                {
                    "errorCode": 403042,
                    "errorDetails": "private provider details",
                },
            ),
        ]
    )
    c = client(h)
    with pytest.raises(AuthenticationError) as e:
        await c.ensure_session()
    assert e.value.code == 403042
    assert "private" not in str(e.value)
    assert len(h.calls) == 2
    assert c._session is None


async def test_valid_identity_with_forbidden_session_exchange_is_not_a_password_error():
    http = FakeHttp(
        login_responses()[:2] + [HttpResponse(403, {"message": "private provider details"})]
    )
    api = client(http)

    with pytest.raises(ApiError) as error:
        await api.ensure_session()

    assert error.value.status == 403
    assert "private provider details" not in str(error.value)
    assert http.calls[-1][1] == "https://unauth.fixture.irobotapi.com/v2/login"
    assert len(http.calls) == 3
    assert api._session is None


@pytest.mark.parametrize("data", [None, {"statusCode": 200}, {"errorCode": False}])
async def test_http_200_without_a_valid_gigya_success_is_not_authenticated(data):
    c = client(FakeHttp([HttpResponse(200, discovery()), HttpResponse(200, data)]))
    with pytest.raises(ProtocolError):
        await c.ensure_session()


async def test_missing_identity_assertion_is_a_protocol_error():
    h = FakeHttp([HttpResponse(200, discovery()), HttpResponse(200, {"errorCode": 0})])
    with pytest.raises(ProtocolError):
        await client(h).ensure_session()


@pytest.mark.parametrize("field", ["httpBase", "httpBaseAuth"])
async def test_discovery_cannot_forward_login_credentials_to_another_host(field):
    d = discovery()
    d["deployments"]["fixture"][field] = "https://untrusted.invalid"
    h = FakeHttp([HttpResponse(200, d)])
    with pytest.raises(ProtocolError):
        await client(h).ensure_session()
    assert len(h.calls) == 1


async def test_gigya_discovery_host_is_validated_before_sending_a_password():
    d = discovery()
    d["gigya"]["datacenter_domain"] = "untrusted.invalid"
    h = FakeHttp([HttpResponse(200, d)])
    with pytest.raises(ProtocolError):
        await client(h).ensure_session()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.clear(),
        lambda d: d.update(gigya=None),
        lambda d: d["gigya"].update(datacenter_domain="bad/path"),
        lambda d: d["gigya"].update(api_key=""),
    ],
)
async def test_incomplete_discovery_never_sends_credentials(change):
    d = discovery()
    change(d)
    h = FakeHttp([HttpResponse(200, d)])
    with pytest.raises(ProtocolError):
        await client(h).ensure_session()
    assert len(h.calls) == 1


@pytest.mark.parametrize(
    "data", [None, {}, {"credentials": {}, "robots": {}, "connection_tokens": []}]
)
async def test_incomplete_native_session_is_not_cached(data):
    responses = login_responses()
    responses[-1] = HttpResponse(200, data)
    c = client(FakeHttp(responses))
    with pytest.raises(ProtocolError):
        await c.ensure_session()
    assert c._session is None


async def test_already_expired_credentials_are_not_accepted():
    responses = login_responses()
    responses[-1].data["credentials"]["Expiration"] = NOW.isoformat()
    with pytest.raises(ProtocolError):
        await client(FakeHttp(responses)).ensure_session()


async def test_post_body_signed_is_exactly_the_body_sent():
    h = FakeHttp(login_responses() + [HttpResponse(200, {"result": "ok"})])
    c = client(h)
    await c.request("POST", "/v1/time-estimates", data={"fixture": [1, 2]})
    assert h.calls[-1][3] == b'{"fixture":[1,2]}'
    assert "Authorization" in h.calls[-1][2]


async def test_query_parameters_and_repeated_values_are_preserved():
    h = FakeHttp(login_responses() + [HttpResponse(200, [])])
    await client(h).request("GET", "/v1/p2maps", params={"robotId": "fixture id", "tags": [1, 2]})
    assert h.calls[-1][1].endswith("?robotId=fixture+id&tags=1&tags=2")


async def test_forbidden_method_never_authenticates_or_sends_a_request():
    h = FakeHttp([])
    with pytest.raises(ValueError):
        await client(h).request("DELETE", "/v1/user")
    assert h.calls == []


async def test_invalid_catalog_is_not_a_successful_empty_inventory():
    h = FakeHttp(login_responses() + [HttpResponse(200, [])])
    with pytest.raises(ProtocolError):
        await client(h).robots()


async def test_unauthorized_reads_are_not_blindly_retried():
    h = FakeHttp(login_responses() + [HttpResponse(403, {"detail": "private"})])
    with pytest.raises(ApiError) as e:
        await client(h).robots()
    assert e.value.status == 403 and "private" not in str(e.value)
    assert len(h.calls) == 4


@pytest.mark.parametrize("delay,expected", [("0", 1), ("120", 120), ("9999", 900), ("invalid", 60)])
def test_retry_delay_is_bounded_and_case_insensitive(delay, expected):
    with pytest.raises(RateLimited) as e:
        check_status(HttpResponse(429, {}, {"retry-after": delay}))
    assert e.value.retry_after == expected


def test_redirects_are_failures_not_new_credential_destinations():
    with pytest.raises(ApiError):
        check_status(HttpResponse(302, None, {"Location": "https://untrusted.invalid"}))


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.fixture.irobotapi.com",
        "https://evil-irobotapi.com",
        "https://irobotapi.com.untrusted.invalid",
        "https://localhost",
        "https://127.0.0.1",
        "https://x:y" + "@auth.fixture.irobotapi.com",
        "https://auth.fixture.irobotapi.com:444",
        "https://auth.fixture.irobotapi.com?q=x",
        "https://auth.fixture.irobotapi.com/#x",
        "https://[bad",
        None,
    ],
)
def test_untrusted_provider_urls_are_rejected(url):
    with pytest.raises(ProtocolError):
        trusted_url(url)


@pytest.mark.parametrize(
    "path",
    [
        "//untrusted.invalid/a",
        "/a/../b",
        "/a/%2e%2e/b",
        "/a/%252e%252e/b",
        "/a?secret=x",
        "/a#x",
        "/a\\b",
        "https://untrusted.invalid",
        None,
    ],
)
def test_unsafe_api_paths_are_rejected(path):
    with pytest.raises(ProtocolError):
        relative_api_path(path)


def test_trusted_provider_paths_remain_relative_to_the_deployment():
    assert (
        trusted_url("https://auth.fixture.irobotapi.com/") == "https://auth.fixture.irobotapi.com"
    )
    assert relative_api_path("/v1/user/associations/robots") == "/v1/user/associations/robots"


@pytest.mark.parametrize("country", ["", "ESP", "1E", "éS"])
def test_invalid_country_is_rejected_before_network_io(country):
    with pytest.raises(ValueError):
        client(FakeHttp([]), country=country)


def test_private_models_do_not_disclose_credentials_in_representations():
    c = client(FakeHttp([]))
    objects = [c, c.login_details, c.profile, CloudSession.parse(session(), discovery())]
    for obj in objects:
        assert "fixture-password" not in repr(obj)
        assert "fixture-secret" not in repr(obj)
        assert "fixture-token" not in repr(obj)


def test_profile_payload_is_an_independent_snapshot():
    p = AppProfile.from_mapping({"app_id": "fixture", "app_info": {"device_id": "fixture"}})
    payload = p.login_payload({"uid": "fixture"})
    payload["app_info"]["device_id"] = "changed"
    assert p.app_info["device_id"] == "fixture"


@pytest.mark.parametrize(
    "profile",
    [
        {"app_id": "", "app_info": {"device_id": "fixture"}},
        {"app_id": "fixture", "app_info": {}},
    ],
)
def test_incomplete_client_profile_is_rejected(profile):
    with pytest.raises(ProtocolError):
        AppProfile.from_mapping(profile)


def test_credentials_without_explicit_timezone_are_rejected():
    s = session()
    s["credentials"]["Expiration"] = "2026-11-23T13:00:00"
    with pytest.raises(ProtocolError):
        CloudSession.parse(s, discovery())


def test_signing_uses_the_native_service_and_security_token():
    s = CloudSession.parse(session(), discovery())
    h = signed_headers("GET", "https://auth.fixture.irobotapi.com/v1/test", None, s)
    assert "/us-east-1/execute-api/aws4_request" in h["Authorization"]
    assert h["X-Amz-Security-Token"] == "fixture-token"


def test_invalidation_requires_a_fresh_native_login():
    c = client(FakeHttp([]))
    c._session = CloudSession.parse(session(), discovery())
    c.invalidate_session()
    assert c._session is None


def test_missing_deployment_is_an_explicit_protocol_failure():
    s = CloudSession.parse(session(), {"deployments": {}})
    with pytest.raises(ProtocolError):
        _ = s.deployment


async def test_empty_gigya_assertion_is_rejected_without_session_exchange():
    responses = login_responses()
    responses[1].data["UID"] = ""
    http = FakeHttp(responses)
    with pytest.raises(ProtocolError):
        await client(http).ensure_session()
    assert len(http.calls) == 2


async def test_success_status_without_api_document_is_a_protocol_failure():
    http = FakeHttp(login_responses() + [HttpResponse(200, None)])
    with pytest.raises(ProtocolError):
        await client(http).request("GET", "/v1/user/households")
    assert len(http.calls) == 4


async def test_persistent_maps_use_the_observed_signed_request():
    http = FakeHttp(login_responses() + [HttpResponse(200, [])])
    assert await client(http).maps("robot-fixture") == ()
    method, url, headers, body = http.calls[-1]
    assert (method, body) == ("GET", None)
    assert url.endswith("/v1/p2maps?robotId=robot-fixture&visible=true")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")


async def test_map_lookup_cannot_target_an_unassociated_robot():
    http = FakeHttp(login_responses())
    with pytest.raises(ProtocolError, match="associated robot"):
        await client(http).maps("other-robot")
    assert len(http.calls) == 3


async def test_mission_history_uses_observed_read_only_signed_contract():
    http = FakeHttp(login_responses() + [HttpResponse(200, [])])
    c = client(http)
    assert await c.mission_history("robot-fixture") == {"history_count": 0}
    method, url, headers, body = http.calls[-1]
    assert (method, body) == ("GET", None)
    assert "/v1/robot-fixture/missionhistory?" in url
    assert parse_qs(url.split("?")[1]) == {
        "app_id": [c.profile.app_id],
        "maxAge": ["10"],
        "filterType": ["omit_quickly_canceled_not_scheduled"],
        "supportedDoneCodes": ["dndEnd,returnHomeEnd"],
    }
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")


async def test_mission_history_cannot_target_an_unassociated_robot():
    http = FakeHttp(login_responses())
    with pytest.raises(ProtocolError, match="associated robot"):
        await client(http).mission_history("other-robot")
    assert len(http.calls) == 3


async def test_time_estimates_use_the_signed_map_query_with_empty_region_and_zone():
    http = FakeHttp(
        login_responses()
        + [HttpResponse(200, {"robot_id": "robot-fixture", "api_version": "v1", "smart_maps": []})]
    )
    c = client(http)
    target = AreaTarget("map-fixture", "version-fixture", ())
    assert await c.cleaning_time_estimates("robot-fixture", target, CleaningCapabilities()) == {
        "regions": []
    }
    method, url, headers, body = http.calls[-1]
    assert method == "POST" and url.endswith("/v1/time-estimates")
    assert json.loads(body) == {
        "robot_id": "robot-fixture",
        "smart_map_id": "map-fixture",
        "region_id": "",
        "zone_id": "",
    }
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")


async def test_time_estimates_cannot_target_an_unassociated_robot():
    http = FakeHttp(login_responses())
    with pytest.raises(ProtocolError, match="associated robot"):
        await client(http).cleaning_time_estimates(
            "other-robot", AreaTarget("map-fixture", "version-fixture", ()), CleaningCapabilities()
        )
    assert len(http.calls) == 3


async def test_quick_routines_use_read_only_signed_floor_route_and_native_limit():
    from custom_components.roomba_home.core.capabilities import DeviceCapabilities
    from custom_components.roomba_home.core.maps import PersistentMap

    http = FakeHttp(login_responses() + [HttpResponse(200, [])])
    result = await client(http).map_quick_routines(
        "robot-fixture", PersistentMap("floor-a", "current", None, ()), DeviceCapabilities()
    )
    assert result == {"map_id": "floor-a", "version": "current", "routines": []}
    method, url, headers, body = http.calls[-1]
    assert method == "GET" and url.endswith("/v1/p2maps/floor-a/routines?limit=5") and body is None
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256")


@pytest.mark.parametrize(("robot", "map_id"), [("foreign", "floor-a"), ("robot-fixture", "../")])
async def test_quick_routines_reject_an_unassociated_robot_or_invalid_floor(robot, map_id):
    from custom_components.roomba_home.core.capabilities import DeviceCapabilities
    from custom_components.roomba_home.core.maps import PersistentMap

    http = FakeHttp(login_responses())
    with pytest.raises(ProtocolError, match="associated map"):
        await client(http).map_quick_routines(
            robot, PersistentMap(map_id, "current", None, ()), DeviceCapabilities()
        )
    assert len(http.calls) == 3


async def test_cloud_schedule_requests_are_signed_and_share_household_lookup():
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(
                200,
                [
                    {
                        "household_id": "fixture.house",
                        "household_robots": [{"robot_id": "robot-fixture"}],
                    },
                    {
                        "household_id": "foreign",
                        "household_robots": [{"robot_id": "foreign-robot"}],
                    },
                ],
            ),
            HttpResponse(200, {"household_schedules": []}),
        ]
    )
    result = await client(http).cloud_schedules(frozenset({"robot-fixture", "foreign-robot"}))
    assert result["robot-fixture"]["cloud_schedule_count"] == 0
    assert "foreign-robot" not in result
    assert [item[1].split(".com")[-1] for item in http.calls[-2:]] == [
        "/v1/user/households",
        "/v1/households/fixture.house/settings/schedule",
    ]
    assert all(call[2]["Authorization"].startswith("AWS4-HMAC-SHA256") for call in http.calls[-2:])


def fixture_weekly_schedules(*, hour=8, enabled=False, robot="robot-fixture"):
    return {
        "household_schedules": [
            {
                "household_schedule_id": "fixture.group",
                "schedules": [
                    {
                        "schedule_id": "fixture.item",
                        "options": {
                            "name": "Example schedule",
                            "robot_id": robot,
                            "enabled": enabled,
                            "frequency": "WEEKLY",
                            "start": {"day": [1, 3], "hour": hour, "min": 15},
                            "commands": [{"command": {"command": "start", "robot_id": robot}}],
                            "future_option": {"shape": "preserved"},
                        },
                    }
                ],
            }
        ]
    }


def schedule_http(*responses, households=("fixture.house",), document=None):
    return FakeHttp(
        login_responses()
        + [
            HttpResponse(
                200,
                [
                    {"household_id": home, "household_robots": [{"robot_id": "robot-fixture"}]}
                    for home in households
                ],
            ),
            HttpResponse(200, fixture_weekly_schedules() if document is None else document),
            *responses,
        ]
    )


@pytest.fixture
def created_schedule_fixture():
    area = AreaTarget(
        "map-fixture",
        "version-fixture",
        (CleaningRegion("room-test", RegionKind.ROOM, None),),
        (CleaningProfile(suction_level=1, two_pass=False),),
    )
    options = new_cleaning_schedule(
        "robot-fixture", "New schedule", {"day": [1, 3], "hour": 8, "min": 15}, area
    )
    document = fixture_weekly_schedules()
    document["household_schedules"][0]["schedules"][0]["options"] = options | {
        "created_time": "provider timestamp"
    }
    return area, options, document


async def test_create_disabled_weekly_schedule_is_confirmed_with_provider_owned_identity(
    created_schedule_fixture,
):
    target, options, created = created_schedule_fixture
    http = schedule_http(HttpResponse(200, {}), HttpResponse(200, created))
    result = await client(http).create_cleaning_schedule(
        "robot-fixture", "New schedule", [3, 1], "08:15:00", target
    )
    assert result == {
        "id": "fixture.group:fixture.item",
        "enabled": False,
        "name": "New schedule",
        "regions": ["map-fixture:rid:room-test"],
        "region_settings": [
            {
                "id": "map-fixture:rid:room-test",
                "mode": "vacuum",
                "suction_level": 1,
                "wetness_level": None,
                "two_pass": False,
                "smart_scrub": None,
                "carpet_boost": None,
            }
        ],
        "weekdays": (1, 3),
        "time": "08:15",
    }
    post = http.calls[5]
    assert post[0] == "POST" and post[1].endswith("/settings/schedule")
    assert json.loads(post[3]) == {"schedules": [{"options": options}]}


async def test_resubmitting_the_same_disabled_schedule_only_reads(created_schedule_fixture):
    target, _, existing = created_schedule_fixture
    http = schedule_http(document=existing)
    result = await client(http).create_cleaning_schedule(
        "robot-fixture", "New schedule", [1, 3], "08:15", target
    )
    assert result["id"] == "fixture.group:fixture.item" and len(http.calls) == 5


async def test_multiple_exact_matches_do_not_create_another_schedule(created_schedule_fixture):
    target, _, existing = created_schedule_fixture
    existing["household_schedules"].append(
        existing["household_schedules"][0] | {"household_schedule_id": "other.group"}
    )
    http = schedule_http(document=existing)
    with pytest.raises(ScheduleNotEditable, match="more than one"):
        await client(http).create_cleaning_schedule(
            "robot-fixture", "New schedule", [1, 3], "08:15", target
        )
    assert len(http.calls) == 5


async def test_remove_only_the_selected_robot_schedule_and_confirm_absence():
    existing = fixture_weekly_schedules(enabled=True)
    http = schedule_http(
        HttpResponse(200, None), HttpResponse(200, {"household_schedules": []}), document=existing
    )
    response = await client(http).remove_cleaning_schedule(
        "robot-fixture", "fixture.group:fixture.item"
    )
    assert response == {"id": "fixture.group:fixture.item", "removed": True}
    deletion = http.calls[-2]
    assert (
        deletion[0] == "DELETE"
        and deletion[1].endswith("/settings/schedule/fixture.group")
        and deletion[3] is None
    )


async def test_remove_rejects_unknown_or_foreign_schedule_before_writing():
    http = schedule_http(document=fixture_weekly_schedules(robot="foreign-robot"))
    with pytest.raises(ScheduleNotEditable):
        await client(http).remove_cleaning_schedule("robot-fixture", "fixture.group:fixture.item")
    assert len(http.calls) == 5


async def test_uncertain_removal_does_not_repeat_the_delete():
    http = schedule_http(
        TimeoutError(), *(HttpResponse(200, fixture_weekly_schedules()) for _ in range(3))
    )
    with (
        patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ScheduleUpdateUnconfirmed),
    ):
        await client(http).remove_cleaning_schedule("robot-fixture", "fixture.group:fixture.item")
    assert [row[0] for row in http.calls].count("DELETE") == 1


async def test_list_editable_weekly_schedules_returns_only_local_selection_fields():
    http = schedule_http()
    [schedule] = await client(http).list_cleaning_schedules("robot-fixture")
    assert schedule == {
        "id": "fixture.group:fixture.item",
        "name": "Example schedule",
        "enabled": False,
        "regions": None,
        "weekdays": (1, 3),
        "time": "08:15",
    }


async def test_once_schedule_update_preserves_native_command_and_enabled_state():
    before = fixture_weekly_schedules(enabled=True)
    options = before["household_schedules"][0]["schedules"][0]["options"]
    options["commands"][0]["command"].pop("robot_id")
    after = fixture_weekly_schedules(enabled=True)
    updated = after["household_schedules"][0]["schedules"][0]["options"]
    updated.update(
        frequency="ONCE",
        start={"day": [3], "hour": 22, "min": 39},
        commands=options["commands"],
    )
    http = schedule_http(HttpResponse(200, {}), HttpResponse(200, after), document=before)
    result = await client(http).update_cleaning_schedule(
        "robot-fixture", "fixture.group:fixture.item", [3], "22:39", frequency="once"
    )
    assert result["frequency"] == "once" and result["weekday"] == 3
    assert result["enabled"] is True
    [put] = [row for row in http.calls if row[0] == "PUT"]
    assert json.loads(put[3]) == {"schedules": after["household_schedules"][0]["schedules"]}


@pytest.mark.parametrize(
    "overrides",
    [
        {"p2map_id": "floor", "regions": []},
        {"p2map_id": "floor", "regions": None},
        {"p2map_id": "floor", "regions": [{"type": "tid", "region_id": "area"}]},
        {
            "select_all": True,
            "p2map_id": "floor",
            "regions": [{"type": "rid", "region_id": "area"}],
        },
    ],
)
async def test_weekly_schedule_reports_unresolved_map_dependencies(overrides):
    document = fixture_weekly_schedules()
    options = document["household_schedules"][0]["schedules"][0]["options"]
    options["commands"][0]["command"].update(overrides)
    [schedule] = await client(schedule_http(document=document)).list_cleaning_schedules(
        "robot-fixture"
    )
    assert schedule["regions"] is None


@pytest.mark.parametrize("households", [(), ("first", "second")])
async def test_schedule_action_requires_one_associated_household(households):
    http = schedule_http(households=households)
    with pytest.raises(ScheduleNotEditable, match="unique household"):
        await client(http).list_cleaning_schedules("robot-fixture")
    assert len(http.calls) == 4


async def test_foreign_robot_cannot_access_schedule_actions():
    http = schedule_http()
    with pytest.raises(ScheduleNotEditable, match="not associated"):
        await client(http).list_cleaning_schedules("other-robot")
    assert len(http.calls) == 3


@pytest.mark.parametrize(
    "first_response", [HttpResponse(200, {}), HttpResponse(502, {}), TimeoutError()]
)
async def test_schedule_update_converges_without_republishing(first_response):
    http = schedule_http(
        first_response,
        HttpResponse(200, fixture_weekly_schedules()),
        HttpResponse(200, fixture_weekly_schedules(hour=9)),
    )
    with patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()):
        result = await client(http).update_cleaning_schedule(
            "robot-fixture", "fixture.group:fixture.item", [3, 1], "09:15:00"
        )
    assert result["time"] == "09:15" and result["enabled"] is False
    [put] = [row for row in http.calls if row[0] == "PUT"]
    assert put[1].endswith("/v1/households/fixture.house/settings/schedule/fixture.group")
    assert put[2]["Authorization"].startswith("AWS4-HMAC-SHA256")
    assert json.loads(put[3]) == {
        "schedules": fixture_weekly_schedules(hour=9)["household_schedules"][0]["schedules"]
    }


async def test_retrying_an_already_applied_schedule_is_read_only():
    http = schedule_http()
    result = await client(http).update_cleaning_schedule(
        "robot-fixture", "fixture.group:fixture.item", [3, 1], "08:15"
    )
    assert result["weekdays"] == (1, 3)
    assert len(http.calls) == 5


async def test_weekly_enable_preserves_start_and_native_command():
    http = schedule_http(
        HttpResponse(200, {}), HttpResponse(200, fixture_weekly_schedules(enabled=True))
    )
    result = await client(http).set_cleaning_schedule_enabled(
        "robot-fixture", "fixture.group:fixture.item", True
    )
    assert result["enabled"] is True and result["time"] == "08:15"
    [put] = [row for row in http.calls if row[0] == "PUT"]
    assert json.loads(put[3]) == {
        "schedules": fixture_weekly_schedules(enabled=True)["household_schedules"][0]["schedules"]
    }


@pytest.mark.parametrize("explicit_selection", [False, True])
async def test_schedule_settings_update_preserves_next_start_and_applies_region_order(
    created_schedule_fixture, explicit_selection
):
    target, _, before = created_schedule_fixture
    options = before["household_schedules"][0]["schedules"][0]["options"]
    options.update(enabled=True, frequency="ONCE", start={"day": [2], "hour": 14, "min": 30})
    if explicit_selection:
        options["commands"][0]["command"]["select_all"] = False
    selection = replace(
        target,
        version_id="current-revision",
        regions=(CleaningRegion("second", RegionKind.ZONE, None), target.regions[0]),
        profiles=(CleaningProfile(CleaningMode.MOP, wetness_level=2), target.profiles[0]),
    )
    after = deepcopy(before)
    new_options = after["household_schedules"][0]["schedules"][0]["options"]
    command = new_options["commands"][0]["command"]
    command["user_p2mapv_id"] = "current-revision"
    command["regions"].insert(
        0,
        {
            "region_id": "second",
            "type": "zid",
            "params": {"operatingMode": 4, "padWetness": {"padPlate": 2}},
        },
    )
    new_options["name"] = "Revised schedule"
    http = schedule_http(HttpResponse(200, None), HttpResponse(200, after), document=before)
    result = await client(http).update_cleaning_schedule(
        "robot-fixture", "fixture.group:fixture.item", name="Revised schedule", target=selection
    )
    assert result["frequency"] == "once" and result["weekday"] == 2 and result["enabled"] is True
    assert [area["mode"] for area in result["region_settings"]] == ["mop", "vacuum"]
    [put] = [request for request in http.calls if request[0] == "PUT"]
    assert json.loads(put[3]) == {"schedules": after["household_schedules"][0]["schedules"]}


async def test_schedule_recovery_rejects_selection_changed_after_preview(created_schedule_fixture):
    target, _, document = created_schedule_fixture
    http = schedule_http(document=document)
    with pytest.raises(ProgramSelectionChanged):
        await client(http).update_cleaning_schedule(
            "robot-fixture",
            "fixture.group:fixture.item",
            target=target,
            expected_selection=([{"id": "floor:zid:101", "mode": "mop"}], True),
        )
    assert all(row[0] != "PUT" for row in http.calls)


@pytest.mark.parametrize(
    "override",
    [
        {"unexpected": 1},
        {"ordered": True},
        {"ordered": 0},
        {"select_all": True},
        {"params": {"routine_modified": 1}},
        {"params": {"routine_modified": False}},
        {"user_p2mapv_id": []},
        {"regions": [{"region_id": "room", "type": "rid", "params": {"unknown": 1}}]},
        {"regions": [{"region_id": "room", "type": "rid", "params": {"operatingMode": 2}}] * 2},
        {
            "regions": [
                {"region_id": f"room-{i}", "type": "rid", "params": {"operatingMode": 2}}
                for i in range(33)
            ]
        },
        None,
    ],
)
async def test_schedule_keeps_recognized_timing_when_cleaning_parameters_are_unsupported(
    created_schedule_fixture, override
):
    target, _, document = created_schedule_fixture
    options = document["household_schedules"][0]["schedules"][0]["options"]
    if override is None:
        options["commands"][0]["unsupported_wrapper"] = True
    else:
        options["commands"][0]["command"].update(override)
    [result] = await client(schedule_http(document=document)).list_cleaning_schedules(
        "robot-fixture"
    )
    assert result["time"] == "08:15" and "region_settings" not in result
    http = schedule_http(document=document)
    with pytest.raises(ValueError, match="preferences are not supported"):
        await client(http).update_cleaning_schedule(
            "robot-fixture", "fixture.group:fixture.item", target=target
        )
    assert all(request[0] != "PUT" for request in http.calls)


@pytest.mark.parametrize(
    "override, editable",
    [
        ({}, True),
        ({"params": {"unknown": True}}, False),
        ({"initiator": "unknown"}, False),
        ({"time": True}, False),
        ({"time": 0}, False),
        ({"frequency": "WEEKLY"}, False),
        ({"regional": {"operatingMode": 2}}, True),
        ({"regional": {"operatingMode": 4}}, True),
    ],
)
async def test_native_timed_once_schedule_preserves_inactive_mop_preferences(
    created_schedule_fixture,
    override,
    editable,
):
    _, _, document = created_schedule_fixture
    options = document["household_schedules"][0]["schedules"][0]["options"]
    options.update(
        frequency=override.get("frequency", "ONCE"), start={"day": [2], "hour": 7, "min": 30}
    )
    command = options["commands"][0]["command"]
    command.pop("robot_id")
    command.update(
        initiator=override.get("initiator", "rmtApp"),
        time=override.get("time", 12),
        params=override.get("params", {}),
    )
    command["regions"][0]["params"] = override.get(
        "regional",
        {
            "operatingMode": 2,
            "suctionLevel": 2,
            "twoPass": False,
            "carpetBoost": False,
            "padWetness": {"padPlate": 1},
            "swScrub": 0,
        },
    )
    [result] = await client(schedule_http(document=document)).list_cleaning_schedules(
        "robot-fixture"
    )
    assert result["time"] == "07:30" and ("region_settings" in result) == editable
    if not override:
        [area] = result["region_settings"]
        assert (area["mode"], area["wetness_level"], area["smart_scrub"]) == ("vacuum", 1, False)


async def test_weekly_disable_is_idempotent():
    http = schedule_http()
    result = await client(http).set_cleaning_schedule_enabled(
        "robot-fixture", "fixture.group:fixture.item", False
    )
    assert result["enabled"] is False and len(http.calls) == 5


@pytest.mark.parametrize("value", [1, None, "true"])
async def test_weekly_activation_requires_an_explicit_boolean(value):
    http = FakeHttp([])
    with pytest.raises(ValueError, match="explicit enabled"):
        await client(http).set_cleaning_schedule_enabled(
            "robot-fixture", "fixture.group:fixture.item", value
        )
    assert not http.calls


async def test_schedule_id_must_resolve_in_fresh_household_read():
    http = schedule_http()
    with pytest.raises(ScheduleNotEditable):
        await client(http).update_cleaning_schedule("robot-fixture", "old:group", [3], "08:15")
    assert len(http.calls) == 5


@pytest.mark.parametrize("bad_status", [403, 429])
async def test_rejected_schedule_write_is_not_retried(bad_status):
    http = schedule_http(HttpResponse(bad_status, {}))
    with pytest.raises(ApiError) as error:
        await client(http).update_cleaning_schedule(
            "robot-fixture", "fixture.group:fixture.item", [1, 3], "09:15"
        )
    assert error.value.status == bad_status
    assert len(http.calls) == 6


async def test_unconfirmed_schedule_write_never_repeats_its_mutation():
    response = fixture_weekly_schedules(hour=9)
    response["household_schedules"][0]["schedules"][0]["options"]["commands"][0]["command"][
        "params"
    ] = {"changed": True}
    http = schedule_http(
        HttpResponse(200, {}),
        HttpResponse(500, {}),
        HttpResponse(200, fixture_weekly_schedules(hour=9, enabled=True)),
        HttpResponse(200, response),
    )
    with (
        patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ScheduleUpdateUnconfirmed),
    ):
        await client(http).update_cleaning_schedule(
            "robot-fixture", "fixture.group:fixture.item", [1, 3], "09:15"
        )
    assert [row[0] for row in http.calls].count("PUT") == 1


async def test_rate_limited_confirmation_notifies_caller_after_one_attempt():
    http = schedule_http(HttpResponse(200, {}), HttpResponse(429, {}, {"Retry-After": "35"}))
    with pytest.raises(RateLimited) as error:
        await client(http).update_cleaning_schedule(
            "robot-fixture", "fixture.group:fixture.item", [1, 3], "09:15"
        )
    assert error.value.retry_after == 35
    assert len(http.calls) == 7


async def test_put_stays_restricted_to_observed_schedule_path():
    http = FakeHttp([])
    with pytest.raises(ValueError, match="not supported"):
        await client(http).request("PUT", "/v1/user/favorites")
    assert not http.calls


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["credentials"].update(AccessKeyId=""),
        lambda value: value["credentials"].update(SecretKey=1),
        lambda value: value.update(robots=[]),
        lambda value: value.update(connection_tokens={}),
    ],
)
def test_invalid_native_session_types_and_empty_keys_are_rejected(change):
    value = session()
    change(value)
    with pytest.raises(ProtocolError):
        CloudSession.parse(value, discovery())


@pytest.mark.parametrize(
    ("body", "topic"),
    [
        (
            {"mqtt_topic": "fixture-irbt/things/robot-fixture/livemap/update"},
            "fixture-irbt/things/robot-fixture/livemap/update",
        ),
        ({"mqtt_topic": False}, None),
        ([], None),
    ],
)
async def test_live_map_channel_uses_signed_get_for_associated_robot(body, topic):
    from urllib.parse import parse_qs, urlsplit

    http = FakeHttp(login_responses() + [HttpResponse(200, body)])
    api = client(http)
    with pytest.raises(ProtocolError, match="associated robot"):
        await api.live_map_topic("foreign")
    assert await api.live_map_topic("robot-fixture") == topic
    method, url, headers, payload = http.calls[-1]
    assert method == "GET" and payload is None
    assert urlsplit(url).path == "/v1/p2maps/livemap"
    assert parse_qs(urlsplit(url).query) == {"robotId": ["robot-fixture"], "rawOnly": ["true"]}
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")


ROUTINE_ROBOT = "robot-fixture"
ROUTINE_ID = "1" * 32
ROUTINE_REGION = CleaningRegion("fixture-room", RegionKind.ROOM, "Example room")
ROUTINE_TARGET = AreaTarget("floor", "version", (ROUTINE_REGION,), (CleaningProfile(),))


def provider_routine(name="Example routine", target=ROUTINE_TARGET, **fields):
    return {
        "favorite_id": ROUTINE_ID,
        "name": name,
        "creation_timestamp": int(NOW.timestamp()),
        "commanddefs": [routine_command(ROUTINE_ROBOT, target)],
        "color": "#DAF6A1",
        "app_edition": 1,
        "time_estimates": [{"estimate": 60}],
    } | fields


def test_saved_routine_inventory_filters_foreign_and_malformed_records():
    primary = provider_routine()
    base = primary["commanddefs"][0]
    rows = [
        False,
        primary | {"hidden": True},
        primary | {"deleted": True},
        primary | {"favorite_id": ".."},
        primary | {"favorite_id": None},
        primary | {"commanddefs": None},
        primary | {"commanddefs": [False]},
        primary | {"commanddefs": []},
        primary | {"commanddefs": [base | {"robot_id": "foreign"}]},
        primary | {"commanddefs": [base | {"command": "other"}]},
        primary | {"name": 4},
        primary | {"name": "   "},
        primary | {"name": "New\nline"},
        primary,
    ]
    reader = cleaning_routines(rows, ROUTINE_ROBOT)
    assert list(reader) == [ROUTINE_ID]
    assert reader[ROUTINE_ID].action_response() == {
        "id": ROUTINE_ID,
        "name": "Example routine",
        "regions": ["floor:rid:fixture-room"],
        "region_settings": [
            {
                "id": "floor:rid:fixture-room",
                "mode": "vacuum",
                "suction_level": None,
                "wetness_level": None,
                "two_pass": None,
                "smart_scrub": None,
                "carpet_boost": None,
            }
        ],
        "editable": True,
        "color": "#DAF6A1",
    }
    with pytest.raises(ProtocolError, match="duplicate"):
        cleaning_routines([primary, primary], ROUTINE_ROBOT)
    with pytest.raises(ProtocolError, match="routine list"):
        cleaning_routines({}, ROUTINE_ROBOT)


@pytest.mark.parametrize("region", [False, {"type": "tid"}, {"type": "rid", "region_id": []}])
def test_only_supported_region_identifiers_appear_in_routine_list(region):
    original = provider_routine(default=True)
    original["commanddefs"][0]["regions"] = [region]
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["regions"] == []
    assert not row.action_response()["editable"]
    original["commanddefs"][0].pop("regions")
    assert row.action_response()["regions"] == []
    original["commanddefs"][0]["regions"] = [region]
    original["commanddefs"][0].pop("p2map_id")
    assert row.action_response()["regions"] == []


@pytest.mark.parametrize(
    "change",
    [
        lambda command: command["regions"].append(command["regions"][0]),
        lambda command: command.update(select_all=True),
        lambda command: command.update(ordered=0),
        lambda command: command.update(user_p2mapv_id=".."),
        lambda command: command.update(params={"preset": "auto"}),
        lambda command: command["regions"][0].update(metadata={}),
        lambda command: command["regions"][0].update(params=[]),
        lambda command: command["regions"][0]["params"].update(operatingMode=42),
        lambda command: command["regions"][0]["params"].update(preset=1),
        lambda command: command["regions"][0]["params"].update(suctionLevel=100),
    ],
)
def test_visual_routine_requires_a_lossless_region_projection(change):
    original = provider_routine()
    change(original["commanddefs"][0])
    response = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID].action_response()
    assert response["editable"] is True
    assert response["region_settings"] is None


@pytest.mark.parametrize("timed", [True, False])
def test_visual_routine_recovers_native_single_area_settings(timed):
    original = provider_routine()
    command = original["commanddefs"][0]
    if timed:
        del command["ordered"], command["select_all"]
        command.update(initiator="rmtApp", time=1)
    else:
        command["params"] = {"profile": "normal"}
    command["regions"][0]["params"] = {
        "operatingMode": 6,
        "suctionLevel": 4,
        "padWetness": {"padPlate": 3},
        "twoPass": True,
        "swScrub": 0,
    }
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["region_settings"] == [
        {
            "id": "floor:rid:fixture-room",
            "mode": "vacuum_mop",
            "suction_level": 4,
            "wetness_level": 3,
            "two_pass": True,
            "smart_scrub": False,
            "carpet_boost": None,
        }
    ]


@pytest.mark.parametrize(
    "flag", [{}, {"routine_modified": True}, {"routine_modified": False}, {"routine_modified": 1}]
)
def test_visual_routine_extracts_native_sequential_mode_without_edit_marker(flag):
    original = provider_routine()
    command = original["commanddefs"][0]
    del command["ordered"], command["select_all"]
    command.update(initiator="rmtApp", time=1)
    command["regions"][0]["params"] = {
        "operatingMode": 512,
        "suctionLevel": 4,
        "padWetness": {"padPlate": 3},
        "swScrub": 0,
        "twoPass": True,
        **flag,
    }
    response = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID].action_response()
    if flag.get("routine_modified", True) is not True:
        assert response["region_settings"] is None
    else:
        (settings,) = response["region_settings"]
        assert (settings["mode"], settings["suction_level"], settings["wetness_level"]) == (
            "vacuum_then_mop",
            4,
            3,
        )


@pytest.mark.parametrize(
    ("timed", "change"),
    [
        (True, {"time": True}),
        (True, {"time": 0}),
        (True, {"initiator": "cloud"}),
        (True, {"extra": None}),
        (True, {"params": []}),
        (
            True,
            {
                "regions": [
                    {"region_id": region, "type": "rid", "params": {"operatingMode": 2}}
                    for region in ("room-1", "room-2")
                ]
            },
        ),
        (False, {"ordered": True}),
        (False, {"select_all": True}),
        (False, {"params": {"profile": "normal", "extra": None}}),
        (False, {"params": {"profile": "smart"}}),
    ],
)
def test_visual_routine_does_not_assume_additional_native_command_semantics(timed, change):
    original = provider_routine()
    command = original["commanddefs"][0]
    if timed:
        del command["ordered"], command["select_all"]
        command.update(initiator="rmtApp", time=1)
    else:
        command["params"] = {"profile": "normal"}
    command.update(change)
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["region_settings"] is None


@pytest.mark.parametrize("shape", ["tagged", "replay", "edited replay", "timed", "versionless"])
def test_visual_routine_recovers_native_multi_area_favorites(shape):
    original = provider_routine()
    command = original["commanddefs"][0]
    command["regions"] = [
        {"region_id": "room-2", "type": "rid", "params": {"operatingMode": 2, "suctionLevel": 1}},
        {"region_id": "room-1", "type": "rid", "params": {"operatingMode": 2, "suctionLevel": 3}},
    ]
    if shape == "versionless":
        del command["user_p2mapv_id"], command["select_all"]
        command.update(initiator="rmtApp", time=1)
        command["regions"][0]["params"]["swScrub"] = 0
    elif shape == "timed":
        del command["ordered"], command["select_all"]
        command.update(initiator="rmtApp", time=1, params={"operatingMode": 2, "twoPass": False})
    else:
        command["params"] = {"profile": "normal"}
        if shape in ("replay", "edited replay"):
            command["params"].update(routine_type="REPLAY", replay_of="fixture-replay")
        if shape == "edited replay":
            command["params"]["routine_modified"] = True
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID].action_response()
    assert row.get("ordered", True) == (shape != "timed")
    assert row["regions"] == ["floor:rid:room-2", "floor:rid:room-1"]
    assert [profile["suction_level"] for profile in row["region_settings"]] == [1, 3]
    assert all(profile["smart_scrub"] is None for profile in row["region_settings"])
    if shape == "timed":
        assert all(profile["two_pass"] is False for profile in row["region_settings"])
    assert "replay_of" not in row and "fixture-replay" not in str(row)


@pytest.mark.parametrize(
    "changes",
    [
        {"profile": "smart"},
        {"replay_of": []},
        {"routine_modified": False},
        {"extra": 1},
    ],
)
def test_native_replay_rejects_an_unknown_scope_or_preference(changes):
    original = provider_routine()
    command = original["commanddefs"][0]
    command["params"] = {"routine_type": "REPLAY", "replay_of": "fixture-replay"} | changes
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID].action_response()
    assert row["region_settings"] is None


def test_unordered_saved_routine_persists_concrete_profiles_and_matches_across_timestamps():
    target = replace(ROUTINE_TARGET, ordered=False)
    with pytest.raises(ValueError, match="positive timestamp"):
        routine_command(ROUTINE_ROBOT, target)
    command = routine_command(ROUTINE_ROBOT, target, 12)
    assert "ordered" not in command and command["params"] == {}
    original = provider_routine() | {"commanddefs": [command]}
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["ordered"] is False
    assert routine_matches(row, row.name, command | {"time": 20}, regenerated=True)
    assert not routine_matches(row, row.name, command | {"ordered": 1}, regenerated=True)


@pytest.mark.parametrize(
    ("confidence", "expected"), [("GOOD_CONFIDENCE", "good"), ("OTHER", None), ([], None)]
)
def test_saved_routine_preserves_provider_estimate_and_known_confidence(confidence, expected):
    original = provider_routine(
        time_estimates=[{"unit": "minute", "estimate": 57.4833, "confidence": confidence}]
    )
    row = cleaning_routines([original], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["estimate"] == {
        "duration_minutes": 57.4833,
        "confidence": expected,
    }


@pytest.mark.parametrize(
    "estimates",
    [
        None,
        [],
        [None],
        [{"unit": "second", "estimate": 3}],
        [{"unit": "minute", "estimate": True}],
        [{"unit": "minute", "estimate": float("nan")}],
        [{"unit": "minute", "estimate": 1}, {"unit": "minute", "estimate": 2}],
    ],
)
def test_saved_routine_omits_unavailable_or_ambiguous_estimate(estimates):
    row = cleaning_routines([provider_routine(time_estimates=estimates)], ROUTINE_ROBOT)[ROUTINE_ID]
    assert "estimate" not in row.action_response()


def test_visual_routine_exposes_saved_combined_settings():
    target = replace(
        ROUTINE_TARGET,
        profiles=(
            CleaningProfile(
                CleaningMode.VACUUM_MOP,
                suction_level=3,
                wetness_level=2,
                two_pass=False,
                smart_scrub=True,
                carpet_boost=True,
            ),
        ),
    )
    row = cleaning_routines([provider_routine(target=target)], ROUTINE_ROBOT)[ROUTINE_ID]
    assert row.action_response()["region_settings"] == [
        {
            "id": "floor:rid:fixture-room",
            "mode": "vacuum_mop",
            "suction_level": 3,
            "wetness_level": 2,
            "two_pass": False,
            "smart_scrub": True,
            "carpet_boost": True,
        }
    ]


@pytest.mark.parametrize(
    "target", [None, replace(ROUTINE_TARGET, regions=()), replace(ROUTINE_TARGET, profiles=())]
)
def test_saved_routine_creation_requires_mapped_profiled_destinations(target):
    with pytest.raises(ValueError, match="Select areas"):
        routine_command(ROUTINE_ROBOT, target)


async def test_favorite_create_reads_server_identity_and_an_exact_retry_is_read_only():
    item = provider_routine()
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, []),
            HttpResponse(200, {"favorite_id": ROUTINE_ID}),
            HttpResponse(200, [item]),
            HttpResponse(200, [item]),
        ]
    )
    api = client(http)
    result = await api.create_cleaning_routine(ROUTINE_ROBOT, " Example routine ", ROUTINE_TARGET)
    assert result["id"] == ROUTINE_ID
    assert (
        await api.create_cleaning_routine(ROUTINE_ROBOT, "Example routine", ROUTINE_TARGET)
        == result
    )
    assert [call[0] for call in http.calls[3:]] == ["GET", "POST", "GET", "GET"]
    _, url, headers, raw = http.calls[4]
    assert url.endswith("/v1/user/favorites?app_edition=1")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
    sent = json.loads(raw)
    assert sent["favorite_id"] != ROUTINE_ID
    assert sent["creation_timestamp"] == int(NOW.timestamp())
    assert sent["commanddefs"] == item["commanddefs"]


@pytest.mark.parametrize(
    "appearance",
    [
        {"icon": 3},
        {"icon": " "},
        {"icon": "🦊" * 33},
        {"icon": "\u200d"},
        {"icon": "🦊\n"},
        {"color": 3},
        {"color": "#123"},
        {"color": "rgba(1,2,3,4)"},
    ],
)
def test_invalid_routine_appearance_cannot_be_written_or_override_existing_list(appearance):
    with pytest.raises(ValueError, match="routine (icon|color)"):
        routine_appearance(appearance)
    item = provider_routine(**appearance)
    received = cleaning_routines([item], ROUTINE_ROBOT)[ROUTINE_ID].action_response()
    assert received["id"] == ROUTINE_ID
    assert not set(received) & set(appearance)


def test_routine_appearance_accepts_multicodepoint_emoji_and_normalizes_hex():
    regional_flag = "🏴\U000e0067\U000e0062\U000e007f"
    for icon in ("🧑‍🔧", regional_flag):
        appearance = {"icon": f" {icon} ", "color": "#cbcBfb"}
        assert routine_appearance(appearance) == {"icon": icon, "color": "#CBCBFB"}


async def test_favorite_creation_confirms_the_requested_appearance_and_retries_read_only():
    old = provider_routine(icon="🤖")
    created = provider_routine(
        icon="😄",
        color="#CBCBFB",
        favorite_id="2" * 32,
    )
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [old]),
            HttpResponse(200, {}),
            HttpResponse(200, [old, created]),
            HttpResponse(200, [old, created]),
        ]
    )
    api = client(http)
    appearance = {"icon": "😄", "color": "#cbcbfb"}
    result = await api.create_cleaning_routine(
        ROUTINE_ROBOT, "Example routine", ROUTINE_TARGET, **appearance
    )
    assert (result["id"], result["icon"], result["color"]) == ("2" * 32, "😄", "#CBCBFB")
    assert (
        await api.create_cleaning_routine(
            ROUTINE_ROBOT, "Example routine", ROUTINE_TARGET, **appearance
        )
        == result
    )
    body = json.loads(http.calls[4][3])
    assert (body["icon"], body["color"]) == ("😄", "#CBCBFB")
    assert [call[0] for call in http.calls[3:]] == ["GET", "POST", "GET", "GET"]


async def test_favorite_appearance_update_preserves_command_order_and_estimates():
    old = provider_routine(icon="🤖", display_order=-20)
    updated = old | {"icon": "🧹", "color": "#FDF4A9"}
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [old]),
            HttpResponse(200, {}),
            HttpResponse(200, [old]),
            HttpResponse(200, [updated]),
            HttpResponse(200, [updated]),
        ]
    )
    api = client(http)
    with patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()):
        edited = await api.update_cleaning_routine(
            ROUTINE_ROBOT, ROUTINE_ID, None, icon="🧹", color="#fdf4a9"
        )
    retry = await api.update_cleaning_routine(ROUTINE_ROBOT, ROUTINE_ID, None, color="#fdf4a9")
    assert edited == retry
    assert edited["icon"] == "🧹" and edited["color"] == "#FDF4A9"
    body = json.loads(http.calls[4][3])
    assert {key: body[key] for key in ("commanddefs", "display_order", "time_estimates")} == {
        key: old[key] for key in ("commanddefs", "display_order", "time_estimates")
    }
    assert (body["icon"], body["color"]) == ("🧹", "#FDF4A9")
    assert [call[0] for call in http.calls[3:]].count("PUT") == 1


async def test_failed_or_ambiguous_favorite_creation_is_not_repeated():
    item = provider_routine()
    different_id = item | {"favorite_id": "2" * 32}
    http = FakeHttp(login_responses() + [HttpResponse(200, [item, different_id])])
    with pytest.raises(RoutineNotEditable, match="Several"):
        await client(http).create_cleaning_routine(ROUTINE_ROBOT, "Example routine", ROUTINE_TARGET)
    assert all(call[0] != "POST" for call in http.calls[3:])

    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [provider_routine("Other routine")]),
            HttpResponse(503, {}),
            HttpResponse(200, []),
            HttpResponse(200, []),
            HttpResponse(200, []),
        ]
    )
    with (
        patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(RoutineUpdateUnconfirmed),
    ):
        await client(http).create_cleaning_routine(ROUTINE_ROBOT, "Example routine", ROUTINE_TARGET)
    assert [call[0] for call in http.calls[3:]].count("POST") == 1


@pytest.mark.parametrize("change_targets", [False, True])
async def test_favorite_update_keeps_provider_metadata_and_verifies_changes(change_targets):
    old = provider_routine(version="fixture-metadata")
    target = replace(ROUTINE_TARGET, version_id="version-2") if change_targets else None
    updated = provider_routine(
        "Renamed" if not change_targets else "Example routine", target or ROUTINE_TARGET
    )
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [old]),
            HttpResponse(200, {"favorite_id": ROUTINE_ID}),
            HttpResponse(200, [{**old, "name": "Changed elsewhere"}]),
            HttpResponse(200, [updated]),
        ]
    )
    with patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()):
        result = await client(http).update_cleaning_routine(
            ROUTINE_ROBOT, ROUTINE_ID, None if change_targets else "Renamed", target
        )
    assert result["name"] == updated["name"]
    method, url, _, raw = http.calls[4]
    assert method == "PUT"
    assert url.endswith(f"/v1/user/favorites/{ROUTINE_ID}?app_edition=1")
    body = json.loads(raw)
    assert body["commanddefs"] == updated["commanddefs"]
    assert body["version"] == "fixture-metadata"
    assert "app_edition" not in body
    assert ("time_estimates" in body) is not change_targets


async def test_routine_recovery_rejects_selection_changed_after_preview():
    http = FakeHttp(login_responses() + [HttpResponse(200, [provider_routine()])])
    with pytest.raises(ProgramSelectionChanged):
        await client(http).update_cleaning_routine(
            ROUTINE_ROBOT,
            ROUTINE_ID,
            None,
            ROUTINE_TARGET,
            expected_selection=([{"id": "floor:zid:100", "mode": "mop"}], True),
        )
    assert all(row[0] != "PUT" for row in http.calls)


async def test_routine_reads_and_removals_reject_foreign_and_default_items():
    item = provider_routine(default=True)
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [item]),
            HttpResponse(200, [item]),
            HttpResponse(200, []),
        ]
    )
    api = client(http)
    with pytest.raises(RoutineNotEditable, match="associated"):
        await api.list_cleaning_routines("foreign")
    assert len(await api.list_cleaning_routines(ROUTINE_ROBOT)) == 1
    for _ in range(2):
        with pytest.raises(RoutineNotEditable, match="unavailable"):
            await api.remove_cleaning_routine(ROUTINE_ROBOT, ROUTINE_ID)
    assert all(call[0] != "DELETE" for call in http.calls)


async def test_idempotent_routine_update_and_remove_confirm_full_inventory():
    item = provider_routine()
    http = FakeHttp(
        login_responses()
        + [
            HttpResponse(200, [item]),
            HttpResponse(200, [item]),
            HttpResponse(200, None),
            HttpResponse(200, {}),
            HttpResponse(200, [item]),
            HttpResponse(200, [None, item | {"favorite_id": "2" * 32}, item | {"deleted": True}]),
        ]
    )
    api = client(http)
    updated = await api.update_cleaning_routine(ROUTINE_ROBOT, ROUTINE_ID, "Example routine")
    assert updated["id"] == ROUTINE_ID
    with patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()):
        assert await api.remove_cleaning_routine(ROUTINE_ROBOT, ROUTINE_ID) == {
            "id": ROUTINE_ID,
            "removed": True,
        }
    assert [call[0] for call in http.calls[3:]].count("DELETE") == 1
    assert all(call[0] != "PUT" for call in http.calls)
