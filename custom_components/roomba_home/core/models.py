"""Runtime secrets and provider values with deliberately private representations."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .errors import ProtocolError


def trusted_url(value: str, suffix: str = "irobotapi.com") -> str:
    """Reject credential forwarding to non-provider URLs, redirects and local hosts."""
    if not isinstance(value, str):
        raise ProtocolError("Expected an HTTPS provider URL.")
    try:
        u = urlsplit(value)
        valid_port = u.port in (None, 443)
    except ValueError as exc:
        raise ProtocolError("Invalid provider port.") from exc
    host = (u.hostname or "").lower()
    if (
        u.scheme != "https"
        or not valid_port
        or u.username is not None
        or u.password is not None
        or not host.endswith("." + suffix)
        or u.query
        or u.fragment
    ):
        raise ProtocolError("Untrusted provider URL.")
    return value.rstrip("/")


def relative_api_path(path: str) -> str:
    if not isinstance(path, str):
        raise ProtocolError("Expected a relative API path.")
    decoded = unquote(path)
    if (
        not path.startswith("/")
        or decoded.startswith("//")
        or any(p in (".", "..") for p in decoded.split("/"))
        or any(c in decoded for c in ("?", "#", "\\", "\r", "\n", "%"))
    ):
        raise ProtocolError("Expected a relative API path.")
    return path


@dataclass(frozen=True, repr=False)
class LoginDetails:
    username: str
    password: str

    def __repr__(self) -> str:
        return "LoginDetails(<redacted>)"


@dataclass(frozen=True, repr=False)
class RobotAsset:
    """Private asset metadata for a verified robot association."""

    serial_number: str
    activation_date: date | None


@dataclass(frozen=True, repr=False)
class AppProfile:
    """Client application configuration; no account assertion belongs here."""

    app_id: str
    app_info: dict[str, Any]
    authorizer_params: dict[str, Any] = field(default_factory=dict)
    multiple_authorizer_token_support: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.app_id, str) or not self.app_id.strip():
            raise ProtocolError("A client application profile is required.")
        if not isinstance(self.app_info, dict) or not self.app_info.get("device_id"):
            raise ProtocolError("A stable, private client device identifier is required.")

    def __repr__(self) -> str:
        return "AppProfile(<redacted>)"

    @classmethod
    def native(cls) -> AppProfile:
        """Create a separate client using observed, non-secret app configuration.

        Persist this profile privately: app_id determines MQTT client identity.
        Creating a new profile for every refresh would create needless clients.
        """
        return cls(
            "ANDROID-PRIME-" + str(uuid4()),
            {
                "device_id": "ANDROID-DEVICE-" + str(uuid4()),
                "device_name": "Home Assistant API client",
                "language": "es-es",
                "version": "3.4.1",
                "package_name": "com.irobot.home.prime",
            },
            {"devices_per_token": 2},
            True,
        )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> AppProfile:
        return cls(
            app_id=value["app_id"],
            app_info=deepcopy(value["app_info"]),
            authorizer_params=deepcopy(value.get("authorizer_params", {})),
            multiple_authorizer_token_support=value.get("multiple_authorizer_token_support", True),
        )

    def login_payload(self, assertion: dict[str, Any]) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "app_info": deepcopy(self.app_info),
            "gigya": dict(assertion),
            "authorizer_params": deepcopy(self.authorizer_params),
            "multiple_authorizer_token_support": self.multiple_authorizer_token_support,
        }


@dataclass(frozen=True, repr=False)
class CloudSession:
    raw: dict[str, Any]
    discovery: dict[str, Any]
    expires_at: datetime

    def __repr__(self) -> str:
        return "CloudSession(<redacted>)"

    @classmethod
    def parse(cls, raw: dict[str, Any], discovery: dict[str, Any]) -> CloudSession:
        try:
            c = raw["credentials"]
            if not all(
                isinstance(c[k], str) and c[k] for k in ("AccessKeyId", "SecretKey", "SessionToken")
            ):
                raise ValueError
            expiration = datetime.fromisoformat(c["Expiration"])
            if expiration.tzinfo is None:
                raise ValueError
            if not isinstance(raw["robots"], dict) or not isinstance(
                raw["connection_tokens"], list
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("Incomplete iRobot session response.") from exc
        return cls(raw, discovery, expiration.astimezone(UTC))

    def expiring(self, now: datetime, skew: int = 300) -> bool:
        return now + timedelta(seconds=skew) >= self.expires_at

    @property
    def deployment(self) -> dict[str, Any]:
        try:
            return self.discovery["deployments"][self.discovery["current_deployment"]]
        except (KeyError, TypeError) as exc:
            raise ProtocolError("Incomplete deployment discovery.") from exc
