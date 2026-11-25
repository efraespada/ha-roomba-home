"""Errors expose classifications, never provider payloads or credentials."""


class RoombaError(Exception):
    """Base integration failure."""


class AuthenticationError(RoombaError):
    """Interactive authentication or corrected credentials are required."""

    def __init__(self, code: int | str = "authentication_failed") -> None:
        self.code = code
        super().__init__(f"Authentication failed ({code}).")


class ProtocolError(RoombaError):
    """A provider response violates the expected contract."""


class ScheduleNotEditable(RoombaError):
    """The requested weekly schedule is missing, ambiguous, or unsupported."""


class ScheduleUpdateUnconfirmed(RoombaError):
    """A schedule write was not confirmed by a subsequent read."""


class RoutineNotEditable(RoombaError):
    """The selected routine is missing, ambiguous, or unsupported."""


class RoutineUpdateUnconfirmed(RoombaError):
    """Roomba did not confirm the routine write in a subsequent read."""


class ProgramSelectionChanged(RoombaError):
    """A routine or schedule's selection changed before the requested write."""


class ApiError(RoombaError):
    """A remote operation failed without exposing its response body."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"API request failed (HTTP {status}).")


class RateLimited(ApiError):
    """The caller must respect a bounded retry delay."""

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = min(900, max(1, retry_after))
        super().__init__(429)
