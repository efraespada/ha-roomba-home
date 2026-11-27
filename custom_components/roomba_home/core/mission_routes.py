"""Project bounded Roomba position captures without filling gaps in observation."""

from dataclasses import dataclass
from datetime import datetime

from .live_coverage import CELL_SIZE, MAX_SAMPLES, LiveCoverage
from .live_maps import RoutePoint

MAX_LOCAL_ROUTES = 12
ROUTE_CHECKPOINT_SECONDS = 60
_MODES = {0: ("traveling",), 4: ("mopping",), 5: ("vacuuming",), 6: ("vacuuming", "mopping")}


@dataclass(frozen=True, repr=False)
class RouteCaptureKey:
    started: datetime
    number: int
    floor: tuple[str, str]

    def storage_key(self) -> list:
        return [self.started.isoformat(), self.number, *self.floor]


def merge_samples(previous, current):
    """Keep the newest bounded set of native point indices."""
    points = {point[0]: point for point in previous}
    for index, point in current.items():
        points[index] = [index, point.x, point.y, point.modes]
    return [points[index] for index in sorted(points)[-MAX_SAMPLES:]]


def captured_geometry(samples):
    coverage = LiveCoverage()
    coverage.observe((index, RoutePoint(x, y, mode)) for index, x, y, mode in samples)
    trajectories = []
    previous_index = None
    previous_point = None
    for index, x, y, mode in samples:
        modes = _MODES.get(mode, ())
        point = (x, y)
        consecutive = previous_index is not None and index == previous_index + 1
        if consecutive and trajectories[-1]["modes"] == modes:
            trajectories[-1]["points"].append(point)
        else:
            path = [previous_point, point] if consecutive else [point]
            trajectories.append({"index": index, "modes": modes, "points": path})
        previous_index, previous_point = index, point
    result = {"trajectories": trajectories}
    if rows := coverage.rows():
        result["estimated_coverage"] = {"cell_size": CELL_SIZE, "rows": sorted(rows.items())}
    return result
