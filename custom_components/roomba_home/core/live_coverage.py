"""Accumulate a mode-specific footprint from the observed cleaning path."""

from itertools import groupby
from math import ceil, floor

from .live_maps import RoutePoint

CELL_SIZE = 0.025
MAX_CELLS = 600_000
MAX_SAMPLES = 32_768
MAX_JOIN_DISTANCE = 1.0

# Radii fitted to the Roomba-issued coverage polygons for Max 700 Combo.
# Flag 3 is the union of observed vacuuming and mopping.
FOOTPRINTS = {5: (1, 0.09), 4: (2, 0.11), 6: (3, 0.10)}


class LiveCoverage:
    """Sparse mission-scoped grid with independently replaceable rows."""

    def __init__(self):
        self._points = {}
        self._cells = {}
        self._count = 0
        self._rows = {}
        self._dirty = set()

    def observe(self, samples):
        for index, point in samples:
            point = RoutePoint(point.x, point.y, point.modes)
            if self._points.get(index) == point:
                continue
            self._points[index] = point
            if len(self._points) > MAX_SAMPLES:
                del self._points[next(iter(self._points))]
            if (footprint := FOOTPRINTS.get(point.modes)) is None:
                continue
            self._paint(point, point, *footprint)
            for neighbor in (self._points.get(index - 1), self._points.get(index + 1)):
                if neighbor is not None and neighbor.modes == point.modes:
                    self._paint(point, neighbor, *footprint)

    def _paint(self, first, last, mask, radius):
        dx, dy = last.x - first.x, last.y - first.y
        length = dx * dx + dy * dy
        if length > MAX_JOIN_DISTANCE**2:
            return
        x_start = floor((min(first.x, last.x) - radius) / CELL_SIZE)
        x_end = ceil((max(first.x, last.x) + radius) / CELL_SIZE)
        y_start = floor((min(first.y, last.y) - radius) / CELL_SIZE)
        y_end = ceil((max(first.y, last.y) + radius) / CELL_SIZE)
        for row in range(y_start, y_end):
            y = (row + 0.5) * CELL_SIZE - first.y
            for column in range(x_start, x_end):
                x = (column + 0.5) * CELL_SIZE - first.x
                progress = min(1.0, max(0.0, (x * dx + y * dy) / length)) if length else 0.0
                if (x - progress * dx) ** 2 + (y - progress * dy) ** 2 <= radius**2:
                    self._cover_cell(row, column, mask)

    def _cover_cell(self, row, column, mask):
        columns = self._cells.get(row, {})
        previous = columns.get(column, 0)
        updated = previous | mask
        if updated == previous or (previous == 0 and self._count >= MAX_CELLS):
            return
        self._count += previous == 0
        columns[column] = updated
        self._cells[row] = columns
        self._dirty.add(row)

    def rows(self):
        """Return stable run tuples for rows that have not changed."""
        for row in self._dirty:
            cells = sorted(self._cells[row].items())
            runs = []
            for _, group in groupby(
                enumerate(cells), key=lambda item: (item[1][0] - item[0], item[1][1])
            ):
                points = list(group)
                first, mask = points[0][1]
                last = points[-1][1][0]
                runs.append((first, last + 1, mask))
            self._rows[row] = tuple(runs)
        self._dirty.clear()
        return self._rows

    def samples(self):
        """Return the bounded native indices used by the footprint estimator."""
        return self._points
