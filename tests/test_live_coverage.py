"""Verify mode footprints, monitored gaps and incremental coverage rows."""

from math import floor

from custom_components.roomba_home.core.live_coverage import CELL_SIZE, LiveCoverage
from custom_components.roomba_home.core.live_maps import Position, RoutePoint


def mask_at(grid, x, y):
    column, row = floor(x / CELL_SIZE), floor(y / CELL_SIZE)
    return next(
        (mask for left, right, mask in grid.rows().get(row, ()) if left <= column < right),
        0,
    )


def test_live_coverage_combines_modes_and_only_restores_observed_gaps():
    grid = LiveCoverage()
    grid.observe([(1, RoutePoint(0, 0, 5)), (3, RoutePoint(0.8, 0, 5))])
    assert mask_at(grid, 0.4, 0) == 0
    grid.observe([(2, RoutePoint(0.4, 0, 5))])
    assert mask_at(grid, 0.2, 0) == mask_at(grid, 0.6, 0) == 1
    assert mask_at(grid, 0.2, 0.2) == 0
    grid.observe([(4, RoutePoint(0.3, 0, 4)), (5, RoutePoint(0.3, 0.4, 4))])
    assert mask_at(grid, 0.3, 0) == 3
    assert mask_at(grid, 0.3, 0.3) == 2
    assert mask_at(grid, 0.6, 0) == 1
    grid.observe([(6, RoutePoint(-0.3, -0.3, 6))])
    assert mask_at(grid, -0.3, -0.3) == 3


def test_coverage_ignores_travel_unknown_modes_and_unverified_jumps():
    grid = LiveCoverage()
    grid.observe([(0, RoutePoint(0, 0, 0)), (1, RoutePoint(2, 0, 17))])
    assert not grid.rows()
    grid.observe([(2, RoutePoint(0, 0, 5)), (3, RoutePoint(2, 0, 5))])
    assert mask_at(grid, 0, 0) == mask_at(grid, 2, 0) == 1
    assert mask_at(grid, 1, 0) == 0
    grid.observe([(4, RoutePoint(2.5, 0, 4))])
    assert mask_at(grid, 2.2, 0) == 0


def test_row_updates_are_stable_and_do_not_repaint_heading_changes():
    grid = LiveCoverage()
    grid.observe([(10, Position(0, 0, 0, 5))])
    original_row = grid.rows()[0]
    grid.observe([(10, Position(0, 0, 1.2, 5))])
    assert grid.rows()[0] is original_row
    grid.observe([(11, RoutePoint(1, 2, 4))])
    assert grid.rows()[0] is original_row
    assert mask_at(grid, 1, 2) == 2
    grid.observe([(12, RoutePoint(0, 0, 4))])
    assert grid.rows()[0] is not original_row
    assert mask_at(grid, 0, 0) == 3


def test_bounded_cells_still_merge_modes_and_sample_eviction_preserves_coverage(monkeypatch):
    monkeypatch.setattr("custom_components.roomba_home.core.live_coverage.MAX_SAMPLES", 2)
    grid = LiveCoverage()
    grid.observe([(1, RoutePoint(0, 0, 5)), (2, RoutePoint(1, 1, 4))])
    grid.observe([(3, RoutePoint(3, 3, 4))])
    assert [mask_at(grid, n, n) for n in (0, 1, 3)] == [1, 2, 2]

    monkeypatch.setattr("custom_components.roomba_home.core.live_coverage.MAX_CELLS", 1)
    grid = LiveCoverage()
    grid.observe([(1, RoutePoint(0, 0, 5)), (2, RoutePoint(0, 0, 4))])
    assert [
        (end - start, mask) for _, spans in grid.rows().items() for start, end, mask in spans
    ] == [(1, 3)]
