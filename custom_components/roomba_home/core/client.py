"""Native authentication and cloud operations, independent of Home Assistant."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import aiohttp
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from .cleaning import CleaningCapabilities
from .errors import (
    ApiError,
    AuthenticationError,
    ProtocolError,
    RateLimited,
    RoutineNotEditable,
    RoutineUpdateUnconfirmed,
    ScheduleNotEditable,
    ScheduleUpdateUnconfirmed,
)
from .history import history_metrics
from .maps import AreaTarget, PersistentMap, map_identifier, parse_maps
from .models import AppProfile, CloudSession, LoginDetails, relative_api_path, trusted_url
from .routines import (
    APP_EDITION,
    FAVORITES_PATH,
    ROUTINE_ITEM_PATH,
    cleaning_routines,
    new_routine,
    routine_command,
    routine_matches,
    routine_name,
)
from .schedules import (
    SCHEDULE_ITEM_PATH,
    associated_households,
    editable_schedules,
    new_weekly_schedule,
    schedule_metrics,
    schedule_removed,
    weekly_start,
)
from .time_estimates import parse_time_estimates
from .transport import GZIP_JSON_ACCEPT, HttpResponse, HttpTransport

DISCOVERY_URL = "https://disc-prod.iot.irobotapi.com/v1/discover/endpoints"


def check_status(response: HttpResponse) -> None:
    if response.status == 429:
        try:
            delay = int(
                {k.lower(): v for k, v in response.headers.items()}.get("retry-after", "60")
            )
        except TypeError, ValueError:
            delay = 60
        raise RateLimited(delay)
    if response.status >= 300:
        raise ApiError(response.status)


def signed_headers(
    method: str, url: str, body: bytes | None, session: CloudSession, *, accept="application/json"
):
    c = session.raw["credentials"]
    credentials = Credentials(c["AccessKeyId"], c["SecretKey"], c["SessionToken"])
    request = AWSRequest(
        method=method,
        url=url,
        data=body,
        headers={"Accept": accept, "Content-Type": "application/json"},
    )
    SigV4Auth(credentials, "execute-api", session.deployment["awsRegion"]).add_auth(request)
    return dict(request.headers)


class RoombaClient:
    """One private client identity, one session, and one single-flight login lock."""

    def __init__(
        self,
        http: HttpTransport,
        login: LoginDetails,
        profile: AppProfile,
        country: str = "ES",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            raise ValueError("Use a two-letter country code.")
        self.http = http
        self.login_details = login
        self.profile = profile
        self.country = country.upper()
        self.clock = clock or (lambda: datetime.now(UTC))
        self._session: CloudSession | None = None
        self._login_lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "RoombaClient(<private account>)"

    def invalidate_session(self) -> None:
        self._session = None

    async def ensure_session(self) -> CloudSession:
        if self._session is not None and not self._session.expiring(self.clock()):
            return self._session
        async with self._login_lock:
            if self._session is not None and not self._session.expiring(self.clock()):
                return self._session
            self._session = await self._authenticate()
            return self._session

    async def _authenticate(self) -> CloudSession:
        response = await self.http.request(
            "GET", DISCOVERY_URL + "?" + urlencode({"country_code": self.country})
        )
        check_status(response)
        discovery = response.data
        try:
            deployment = discovery["deployments"][discovery["current_deployment"]]
            base = trusted_url(deployment["httpBase"])
            trusted_url(deployment["httpBaseAuth"])
            domain = discovery["gigya"]["datacenter_domain"]
            if not isinstance(domain, str) or "/" in domain:
                raise ValueError
            host = domain if domain.startswith("accounts.") else "accounts." + domain
            gigya_base = trusted_url("https://" + host, "gigya.com")
            api_key = discovery["gigya"]["api_key"]
            if not isinstance(api_key, str) or not api_key:
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("Incomplete discovery response.") from exc
        form = urlencode(
            {
                "apiKey": api_key,
                "loginID": self.login_details.username,
                "password": self.login_details.password,
                "targetEnv": "mobile",
                "sessionExpiration": "-2",
                "format": "json",
            }
        ).encode()
        response = await self.http.request(
            "POST",
            gigya_base + "/accounts.login",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=form,
        )
        check_status(response)
        gigya = response.data
        if not isinstance(gigya, dict):
            raise ProtocolError("Expected a Gigya JSON response.")
        code = gigya.get("errorCode")
        if not isinstance(code, int) or isinstance(code, bool):
            raise ProtocolError("Missing Gigya application status.")
        if code:
            raise AuthenticationError(code)
        try:
            assertion = {
                "uid": gigya["UID"],
                "signature": gigya["UIDSignature"],
                "timestamp": gigya["signatureTimestamp"],
            }
            if not all(isinstance(v, (str, int)) and str(v) for v in assertion.values()):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("Missing Gigya identity assertion.") from exc
        payload = json.dumps(self.profile.login_payload(assertion), separators=(",", ":")).encode()
        response = await self.http.request(
            "POST",
            base + "/v2/login",
            headers={"Content-Type": "application/json"},
            body=payload,
        )
        check_status(response)
        if not isinstance(response.data, dict):
            raise ProtocolError("Expected an iRobot JSON session.")
        session = CloudSession.parse(response.data, discovery)
        if session.expiring(self.clock()):
            raise ProtocolError("Provider returned credentials that are already expiring.")
        return session

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        accept: str = "application/json",
    ) -> Any:
        """Issue a signed request; caller owns the operation's product semantics."""
        method = method.upper()
        path = relative_api_path(path)
        if method not in {"GET", "POST"} and not (
            method in {"PUT", "DELETE"}
            and (SCHEDULE_ITEM_PATH.fullmatch(path) or ROUTINE_ITEM_PATH.fullmatch(path))
        ):
            raise ValueError("This method is not supported for the requested API path.")
        session = await self.ensure_session()
        base = trusted_url(session.deployment["httpBaseAuth"])
        url = base + path
        if params:
            url += "?" + urlencode(params, doseq=True)
        body = json.dumps(data, separators=(",", ":")).encode() if data is not None else None
        response = await self.http.request(
            method,
            url,
            headers=signed_headers(method, url, body, session, accept=accept),
            body=body,
        )
        check_status(response)
        if response.data is None and method != "DELETE":
            raise ProtocolError("Expected an API JSON response.")
        return response.data

    async def robots(self) -> dict[str, Any]:
        robots = await self.request("GET", "/v1/user/associations/robots")
        if not isinstance(robots, dict) or not all(isinstance(v, dict) for v in robots.values()):
            raise ProtocolError("Expected a robot association object.")
        return robots

    async def maps(self, robot_id: str) -> tuple[PersistentMap, ...]:
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise ProtocolError("Maps require an associated robot")
        response = await self.request(
            "GET", "/v1/p2maps", params={"robotId": robot_id, "visible": "true"}
        )
        return parse_maps(response, robot_id)

    async def map_geometry(self, map_id: str, version: str) -> bytes:
        """Read a selected active map version as used by the Android app."""
        if not map_identifier(map_id) or not map_identifier(version):
            raise ProtocolError("A valid map identifier and version are required.")
        response = await self.request(
            "GET",
            f"/v1/p2maps/{map_id}/versions/{version}/geojson",
            params={"response_type": "binary"},
            accept=GZIP_JSON_ACCEPT,
        )
        if not isinstance(response, bytes) or not response:
            raise ProtocolError("Expected a binary persistent map bundle.")
        return response

    async def live_map_topic(self, robot_id: str) -> str | None:
        """Request the native live-map channel for an associated robot."""
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise ProtocolError("Live maps require an associated robot")
        response = await self.request(
            "GET", "/v1/p2maps/livemap", params={"robotId": robot_id, "rawOnly": "true"}
        )
        topic = response.get("mqtt_topic") if isinstance(response, dict) else None
        return topic if isinstance(topic, str) else None

    async def mission_history(self, robot_id: str) -> dict:
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise ProtocolError("Mission history requires an associated robot")
        response = await self.request(
            "GET",
            f"/v1/{robot_id}/missionhistory",
            params={
                "app_id": self.profile.app_id,
                "maxAge": 10,
                "filterType": "omit_quickly_canceled_not_scheduled",
                "supportedDoneCodes": "dndEnd,returnHomeEnd",
            },
        )
        return history_metrics(response, robot_id)

    async def cleaning_time_estimates(
        self, robot_id: str, target: AreaTarget, capabilities: CleaningCapabilities
    ) -> dict:
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise ProtocolError("Time estimates require an associated robot")
        response = await self.request(
            "POST",
            "/v1/time-estimates",
            data={
                "robot_id": robot_id,
                "smart_map_id": target.map_id,
                "region_id": "",
                "zone_id": "",
            },
        )
        return parse_time_estimates(response, robot_id, target, capabilities)

    async def cloud_schedules(self, robots: frozenset[str]) -> dict[str, dict]:
        session = await self.ensure_session()
        associated = robots.intersection(session.raw["robots"])
        households = associated_households(
            await self.request("GET", "/v1/user/households"), associated
        )
        result = {}
        for household_id, members in households.items():
            document = await self.request("GET", f"/v1/households/{household_id}/settings/schedule")
            result.update(schedule_metrics(document, members))
        return result

    async def _favorite_documents(self):
        return await self.request("GET", FAVORITES_PATH, params=APP_EDITION)

    async def _associated_routines(self, robot_id):
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise RoutineNotEditable("The selected robot is not associated.")
        return cleaning_routines(await self._favorite_documents(), robot_id)

    async def list_cleaning_routines(self, robot_id: str) -> list[dict]:
        rows = await self._associated_routines(robot_id)
        return [row.action_response() for row in rows.values()]

    async def create_cleaning_routine(self, robot_id: str, name: str, target: AreaTarget) -> dict:
        command = routine_command(robot_id, target)
        name = routine_name(name)

        def match(rows):
            candidates = [row for row in rows.values() if routine_matches(row, name, command)]
            if len(candidates) > 1:
                raise RoutineNotEditable("Several saved routines match this request.")
            return candidates[0] if candidates else None

        existing = match(await self._associated_routines(robot_id))
        if existing is not None:
            return existing.action_response()
        await self._mutate_cloud_object(
            "POST",
            FAVORITES_PATH,
            params=APP_EDITION,
            data=new_routine(name, command, int(self.clock().timestamp())),
        )
        created = await self._confirm_routine(robot_id, match)
        return created.action_response()

    async def _editable_routine(self, robot_id, routine_id):
        rows = await self._associated_routines(robot_id)
        if (row := rows.get(routine_id)) is None or row.payload.get("default"):
            raise RoutineNotEditable("The saved routine is unavailable or read-only.")
        return row

    async def update_cleaning_routine(self, robot_id, routine_id, name, target=None) -> dict:
        row = await self._editable_routine(robot_id, routine_id)
        name = routine_name(name) if name is not None else row.name
        command = row.command if target is None else routine_command(robot_id, target)
        if routine_matches(row, name, command):
            return row.action_response()
        payload = dict(row.payload)
        payload.pop("app_edition", None)
        stamp = int(self.clock().timestamp())
        payload.update(
            name=name, commanddefs=[command], last_modified=stamp, last_user_modified=stamp
        )
        if target is not None:
            payload.pop("time_estimates", None)
        await self._mutate_cloud_object(
            "PUT", f"{FAVORITES_PATH}/{row.identity}", params=APP_EDITION, data=payload
        )

        def match(rows):
            updated = rows.get(row.identity)
            return updated if updated and routine_matches(updated, name, command) else None

        updated = await self._confirm_routine(robot_id, match)
        return updated.action_response()

    async def remove_cleaning_routine(self, robot_id, routine_id) -> dict:
        row = await self._editable_routine(robot_id, routine_id)
        await self._mutate_cloud_object(
            "DELETE", f"{FAVORITES_PATH}/{row.identity}", params=APP_EDITION
        )

        def removed(document):
            if not isinstance(document, list):
                raise ProtocolError("Expected an account routine list.")
            return all(
                not isinstance(item, dict)
                or item.get("favorite_id") != row.identity
                or item.get("deleted") is True
                for item in document
            )

        await self._confirm_write(self._favorite_documents, removed, RoutineUpdateUnconfirmed)
        return {"id": routine_id, "removed": True}

    async def _confirm_routine(self, robot_id, match):
        async def read():
            return cleaning_routines(await self._favorite_documents(), robot_id)

        return await self._confirm_write(read, match, RoutineUpdateUnconfirmed)

    async def _schedule_path(self, robot_id: str) -> str:
        session = await self.ensure_session()
        if robot_id not in session.raw["robots"]:
            raise ScheduleNotEditable("The selected robot is not associated")
        households = associated_households(
            await self.request("GET", "/v1/user/households"), frozenset({robot_id})
        )
        if len(households) != 1:
            raise ScheduleNotEditable("The selected robot has no unique household")
        return f"/v1/households/{next(iter(households))}/settings/schedule"

    async def list_weekly_schedules(self, robot_id: str) -> list[dict]:
        path = await self._schedule_path(robot_id)
        rows = editable_schedules(await self.request("GET", path), robot_id)
        return [row.action_response() for row in rows.values()]

    async def update_weekly_schedule(
        self, robot_id: str, schedule_id: str, weekdays: list[int], local_time: str
    ) -> dict:
        start = weekly_start(weekdays, local_time)
        return await self._change_weekly_schedule(robot_id, schedule_id, start=start)

    async def set_weekly_schedule_enabled(
        self, robot_id: str, schedule_id: str, enabled: bool
    ) -> dict:
        if type(enabled) is not bool:
            raise ValueError("Use an explicit enabled state for the weekly schedule")
        return await self._change_weekly_schedule(robot_id, schedule_id, enabled=enabled)

    async def create_weekly_schedule(
        self, robot_id: str, name: str, weekdays: list[int], local_time: str, target: AreaTarget
    ) -> dict:
        options = new_weekly_schedule(robot_id, name, weekly_start(weekdays, local_time), target)
        path = await self._schedule_path(robot_id)

        def find_creation(document):
            matches = [
                schedule
                for schedule in editable_schedules(document, robot_id).values()
                if all(schedule.options.get(key) == value for key, value in options.items())
            ]
            if len(matches) > 1:
                raise ScheduleNotEditable("The scheduled routine matches more than one entry")
            return matches[0] if matches else None

        existing = find_creation(await self.request("GET", path))
        if existing is not None:
            return existing.action_response()
        await self._mutate_cloud_object("POST", path, data={"schedules": [{"options": options}]})
        created = await self._confirm_schedule(path, find_creation)
        return created.action_response()

    async def remove_weekly_schedule(self, robot_id: str, schedule_id: str) -> dict:
        path = await self._schedule_path(robot_id)
        rows = editable_schedules(await self.request("GET", path), robot_id)
        if (schedule := rows.get(schedule_id)) is None:
            raise ScheduleNotEditable("The weekly schedule is not available for the selected robot")
        await self._mutate_cloud_object("DELETE", f"{path}/{schedule.group_id}", data=None)
        await self._confirm_schedule(
            path, lambda document: schedule_removed(document, schedule.group_id)
        )
        return {"id": schedule_id, "removed": True}

    async def _change_weekly_schedule(
        self,
        robot_id: str,
        schedule_id: str,
        *,
        start: dict | None = None,
        enabled: bool | None = None,
    ) -> dict:
        path = await self._schedule_path(robot_id)
        rows = editable_schedules(await self.request("GET", path), robot_id)
        if (schedule := rows.get(schedule_id)) is None:
            raise ScheduleNotEditable("The weekly schedule is not available for the selected robot")
        options = dict(schedule.options)
        expected_start = schedule.start
        if start is not None:
            expected_start = {
                "weekdays": tuple(start["day"]),
                "time": f"{start['hour']:02d}:{start['min']:02d}",
            }
            options["start"] = {**schedule.options["start"], **start}
        if enabled is not None:
            options["enabled"] = enabled
        if schedule.start == expected_start and schedule.options["enabled"] == options["enabled"]:
            return schedule.action_response()

        await self._mutate_cloud_object(
            "PUT",
            f"{path}/{schedule.group_id}",
            data={"schedules": [{"schedule_id": schedule.item_id, "options": options}]},
        )

        def find_update(document):
            rows = editable_schedules(document, robot_id)
            updated = rows.get(schedule_id)
            if (
                updated is not None
                and updated.start == expected_start
                and updated.options["enabled"] is options["enabled"]
                and updated.options["commands"] == schedule.options["commands"]
            ):
                return updated
            return None

        updated = await self._confirm_schedule(path, find_update)
        return updated.action_response()

    async def _mutate_cloud_object(self, method, path, **kwargs):
        try:
            await self.request(method, path, **kwargs)
        except ApiError as error:
            if error.status < 500:
                raise
        except aiohttp.ClientError, OSError, ProtocolError:
            # Verify through a read when the provider may already have applied the change.
            pass

    async def _confirm_schedule(self, path, match):
        async def read():
            return await self.request("GET", path)

        return await self._confirm_write(read, match, ScheduleUpdateUnconfirmed)

    async def _confirm_write(self, read, match, error_type):
        for delay in (0, 0.75, 1.5):
            if delay:
                await asyncio.sleep(delay)
            try:
                result = match(await read())
            except RateLimited:
                raise
            except ApiError, aiohttp.ClientError, OSError, ProtocolError:
                continue
            if result:
                return result
        raise error_type("Roomba Home did not confirm the change.")
