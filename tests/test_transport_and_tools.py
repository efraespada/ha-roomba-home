"""Exercise transport limits and the boundary between private inputs and reports."""

import json
from types import SimpleNamespace

import pytest

from custom_components.roomba_home.core.errors import ProtocolError
from custom_components.roomba_home.core.models import AppProfile
from custom_components.roomba_home.core.transport import (
    GZIP_JSON_ACCEPT,
    RAW_MAP_ACCEPT,
    AiohttpTransport,
)
from tools.bootstrap_profile import profile_from_capture
from tools.validate_api import private_json, reference_reads, safe_route


class Response:
    status = 200
    headers = {"Content-Type": "application/json"}
    content_type = "application/json"

    def __init__(self, chunks):
        self.chunks = chunks
        self.content = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class Session:
    def __init__(self, response):
        self.response = response

    def request(self, method, url, **kwargs):
        self.call = SimpleNamespace(method=method, url=url, **kwargs)
        return self.response


async def test_transport_preserves_bytes_disables_redirects_and_bounds_time():
    response = Response([b'{"val', b'ue":42}'])
    http = Session(response)
    result = await AiohttpTransport(http).request("POST", "https://fixture.test", body=b"exact")
    assert result.data == {"value": 42}
    assert http.call.data == b"exact"
    assert http.call.allow_redirects is False
    assert http.call.timeout.total == 30
    assert response.closed


@pytest.mark.parametrize(
    ("accept", "mime", "chunks", "data"),
    [
        (GZIP_JSON_ACCEPT, "application/gzip", [b"opaque"], b"opaque"),
        (GZIP_JSON_ACCEPT, "application/json", [b'{"state":2}'], {"state": 2}),
        (RAW_MAP_ACCEPT, "binary/octet-stream", [b"opaque"], b"opaque"),
        ("application/json", "application/gzip", [b"opaque"], None),
    ],
)
async def test_binary_transport_is_explicit_and_preserves_the_response(accept, mime, chunks, data):
    response = Response(chunks)
    response.content_type = mime
    http = Session(response)
    result = await AiohttpTransport(http).request(
        "GET", "https://fixture.test", headers={"Accept": accept}
    )
    assert http.call.auto_decompress is (accept != RAW_MAP_ACCEPT)
    assert result.data == data and response.closed


async def test_oversized_body_closes_the_response_without_returning_partial_json():
    response = Response([b"1234", b"56"])
    with pytest.raises(ProtocolError, match="size limit"):
        await AiohttpTransport(Session(response), max_body_bytes=5).request("GET", "https://x")
    assert response.closed


@pytest.mark.parametrize("chunks", [[], [b"<html>private error</html>"], [b"\xff"]])
async def test_empty_or_non_json_payloads_are_not_returned(chunks):
    result = await AiohttpTransport(Session(Response(chunks))).request("GET", "https://x")
    assert result.data is None
    assert "private" not in repr(result)


def test_transport_requires_positive_body_limit():
    with pytest.raises(ValueError):
        AiohttpTransport(None, 0)


def test_private_input_rejects_world_readable_files_and_symlinks(tmp_path):
    source = tmp_path / "private.json"
    source.write_text('{"fixture":true}')
    source.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        private_json(source)
    source.chmod(0o600)
    assert private_json(source) == {"fixture": True}
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="regular"):
        private_json(link)


def test_report_routes_remove_household_robot_map_and_version_identifiers():
    route = "/v1/households/private-household/settings"
    assert safe_route(route) == "/v1/households/{household_id}/settings"
    route = "/v1/p2maps/0123456789ABCDEF01234567/versions/private-version/raw"
    assert safe_route(route) == "/v1/p2maps/{id}/versions/{version}/raw"


def test_reference_capture_cannot_replay_writes_foreign_hosts_or_failed_requests():
    def entry(
        method="GET", host="auth1.prod.iot.irobotapi.com", status=200, mime="application/json"
    ):
        return {
            "request": {"method": method, "url": f"https://{host}/v1/test?a=1"},
            "response": {"status": status, "content": {"mimeType": mime}},
        }

    capture = {
        "log": {
            "entries": [
                entry(),
                entry(),
                entry("POST"),
                entry(host="elsewhere.test"),
                entry(status=403),
                entry(mime="text/html"),
            ]
        }
    }
    assert list(reference_reads(capture)) == [("/v1/test", {"a": "1"})]
    assert "elsewhere" not in json.dumps(list(reference_reads(capture)))


def test_generated_profile_uses_an_independent_stable_app_identity():
    first, second = AppProfile.native(), AppProfile.native()
    assert first.app_id.startswith("ANDROID-PRIME-") and first.app_id != second.app_id
    assert first.app_info["device_id"] != second.app_info["device_id"]
    assert first.login_payload({})["app_id"] == first.login_payload({})["app_id"]
    assert first.authorizer_params == {"devices_per_token": 2}


def test_capture_bootstrap_does_not_copy_assertions_robot_data_or_the_apps_identity():
    original = AppProfile.native()
    raw = original.login_payload(
        {"uid": "fixture-private-uid", "signature": "fixture-private-proof"}
    )
    capture = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "POST",
                        "url": "https://unauth1.prod.iot.irobotapi.com/v2/login",
                        "postData": {"text": json.dumps(raw)},
                    }
                }
            ]
        }
    }
    generated = profile_from_capture(capture)
    assert generated["app_id"] != original.app_id
    assert generated["app_info"]["device_id"] != original.app_info["device_id"]
    assert "gigya" not in generated
    assert "fixture-private" not in json.dumps(generated)
