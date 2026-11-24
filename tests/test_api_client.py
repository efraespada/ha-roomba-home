import asyncio
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import pytest

from custom_components.roomba_home.core import AppProfile, LoginDetails, RoombaClient
from custom_components.roomba_home.core.cleaning import CleaningCapabilities, CleaningProfile
from custom_components.roomba_home.core.client import check_status, signed_headers
from custom_components.roomba_home.core.errors import (
    ApiError,
    AuthenticationError,
    ProtocolError,
    RateLimited,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from custom_components.roomba_home.core.maps import AreaTarget, CleaningRegion, RegionKind
from custom_components.roomba_home.core.models import CloudSession, relative_api_path, trusted_url
from custom_components.roomba_home.core.schedules import new_weekly_schedule
from custom_components.roomba_home.core.transport import GZIP_JSON_ACCEPT, HttpResponse

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
    options = new_weekly_schedule(
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
    result = await client(http).create_weekly_schedule(
        "robot-fixture", "New schedule", [3, 1], "08:15:00", target
    )
    assert result == {
        "id": "fixture.group:fixture.item",
        "enabled": False,
        "name": "New schedule",
        "weekdays": (1, 3),
        "time": "08:15",
    }
    post = http.calls[5]
    assert post[0] == "POST" and post[1].endswith("/settings/schedule")
    assert json.loads(post[3]) == {"schedules": [{"options": options}]}


async def test_resubmitting_the_same_disabled_schedule_only_reads(created_schedule_fixture):
    target, _, existing = created_schedule_fixture
    http = schedule_http(document=existing)
    result = await client(http).create_weekly_schedule(
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
        await client(http).create_weekly_schedule(
            "robot-fixture", "New schedule", [1, 3], "08:15", target
        )
    assert len(http.calls) == 5


async def test_remove_only_the_selected_robot_schedule_and_confirm_absence():
    existing = fixture_weekly_schedules(enabled=True)
    http = schedule_http(
        HttpResponse(200, None), HttpResponse(200, {"household_schedules": []}), document=existing
    )
    response = await client(http).remove_weekly_schedule(
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
        await client(http).remove_weekly_schedule("robot-fixture", "fixture.group:fixture.item")
    assert len(http.calls) == 5


async def test_uncertain_removal_does_not_repeat_the_delete():
    http = schedule_http(
        TimeoutError(), *(HttpResponse(200, fixture_weekly_schedules()) for _ in range(3))
    )
    with (
        patch("custom_components.roomba_home.core.client.asyncio.sleep", new=AsyncMock()),
        pytest.raises(ScheduleUpdateUnconfirmed),
    ):
        await client(http).remove_weekly_schedule("robot-fixture", "fixture.group:fixture.item")
    assert [row[0] for row in http.calls].count("DELETE") == 1


async def test_list_editable_weekly_schedules_returns_only_local_selection_fields():
    http = schedule_http()
    [schedule] = await client(http).list_weekly_schedules("robot-fixture")
    assert schedule == {
        "id": "fixture.group:fixture.item",
        "name": "Example schedule",
        "enabled": False,
        "weekdays": (1, 3),
        "time": "08:15",
    }


@pytest.mark.parametrize("households", [(), ("first", "second")])
async def test_schedule_action_requires_one_associated_household(households):
    http = schedule_http(households=households)
    with pytest.raises(ScheduleNotEditable, match="unique household"):
        await client(http).list_weekly_schedules("robot-fixture")
    assert len(http.calls) == 4


async def test_foreign_robot_cannot_access_schedule_actions():
    http = schedule_http()
    with pytest.raises(ScheduleNotEditable, match="not associated"):
        await client(http).list_weekly_schedules("other-robot")
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
        result = await client(http).update_weekly_schedule(
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
    result = await client(http).update_weekly_schedule(
        "robot-fixture", "fixture.group:fixture.item", [3, 1], "08:15"
    )
    assert result["weekdays"] == (1, 3)
    assert len(http.calls) == 5


async def test_weekly_enable_preserves_start_and_native_command():
    http = schedule_http(
        HttpResponse(200, {}), HttpResponse(200, fixture_weekly_schedules(enabled=True))
    )
    result = await client(http).set_weekly_schedule_enabled(
        "robot-fixture", "fixture.group:fixture.item", True
    )
    assert result["enabled"] is True and result["time"] == "08:15"
    [put] = [row for row in http.calls if row[0] == "PUT"]
    assert json.loads(put[3]) == {
        "schedules": fixture_weekly_schedules(enabled=True)["household_schedules"][0]["schedules"]
    }


async def test_weekly_disable_is_idempotent():
    http = schedule_http()
    result = await client(http).set_weekly_schedule_enabled(
        "robot-fixture", "fixture.group:fixture.item", False
    )
    assert result["enabled"] is False and len(http.calls) == 5


@pytest.mark.parametrize("value", [1, None, "true"])
async def test_weekly_activation_requires_an_explicit_boolean(value):
    http = FakeHttp([])
    with pytest.raises(ValueError, match="explicit enabled"):
        await client(http).set_weekly_schedule_enabled(
            "robot-fixture", "fixture.group:fixture.item", value
        )
    assert not http.calls


async def test_schedule_id_must_resolve_in_fresh_household_read():
    http = schedule_http()
    with pytest.raises(ScheduleNotEditable):
        await client(http).update_weekly_schedule("robot-fixture", "old:group", [3], "08:15")
    assert len(http.calls) == 5


@pytest.mark.parametrize("bad_status", [403, 429])
async def test_rejected_schedule_write_is_not_retried(bad_status):
    http = schedule_http(HttpResponse(bad_status, {}))
    with pytest.raises(ApiError) as error:
        await client(http).update_weekly_schedule(
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
        await client(http).update_weekly_schedule(
            "robot-fixture", "fixture.group:fixture.item", [1, 3], "09:15"
        )
    assert [row[0] for row in http.calls].count("PUT") == 1


async def test_rate_limited_confirmation_notifies_caller_after_one_attempt():
    http = schedule_http(HttpResponse(200, {}), HttpResponse(429, {}, {"Retry-After": "35"}))
    with pytest.raises(RateLimited) as error:
        await client(http).update_weekly_schedule(
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
