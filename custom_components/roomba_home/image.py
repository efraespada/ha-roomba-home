"""Private saved floor plans with the current mission's observed trajectory."""

from bisect import bisect_right
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from itertools import pairwise
from math import cos, pi, sin
from pathlib import Path
from unicodedata import normalize

from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from PIL import Image, ImageDraw, ImageFont

from .core.live_maps import POSITION_ACTIVITIES, MissionPath
from .core.point_maps import FloorPlan
from .entity import RoombaEntity

CANVAS_SIZE = 768
MARGIN = 32
BACKGROUND = "#111827"
ROOM_COLORS = ("#253a54", "#2a4650", "#3a3855", "#314463")
ROUTE_COLORS = {
    "traveling": "#9eafbf",
    "vacuuming": "#59adff",
    "mopping": "#4ed9ad",
    "vacuum_mop": "#c39bff",
}
ROOM_LABEL_FONT = Path(__file__).with_name("fonts") / "NotoSans-Regular.ttf"
ROOM_LABEL_SIZE = 15
LABEL_STROKE = 2
LABEL_PADDING = 2
ROBOT_MARKER_CLEARANCE = 17


async def async_setup_entry(hass, entry, async_add_entities):
    account = entry.runtime_data
    if not account.show_maps:
        return
    known = set()

    @callback
    def discover():
        entities = []
        for robot_id in account.data:
            for floor in account.maps_for_robot(robot_id):
                key = (robot_id, floor.map_id)
                if key not in known:
                    known.add(key)
                    entities.append(RoombaFloorPlan(account, robot_id, floor))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(account.async_add_listener(discover))


class RoombaFloorPlan(RoombaEntity, ImageEntity):
    _attr_content_type = "image/png"
    _attr_translation_key = "floor_plan"

    def __init__(self, coordinator, robot_id, floor):
        super().__init__(
            coordinator, robot_id, "floor_plan_" + sha256(floor.map_id.encode()).hexdigest()
        )
        ImageEntity.__init__(self, coordinator.hass, verify_ssl=True)
        self._attr_translation_placeholders = {"map": floor.name or "Roomba"}
        self._map_id = floor.map_id
        self._render_key = None
        self._image_key = None
        self._image = None
        self._sync_image_state()

    @property
    def _floor(self):
        return next(
            (
                item
                for item in self.account.maps_for_robot(self.robot_id)
                if item.map_id == self._map_id
            ),
            None,
        )

    @property
    def available(self):
        return (
            self.coordinator.last_update_success
            and self.robot is not None
            and self.robot.telemetry.get("maps_available") is True
            and self._floor is not None
        )

    def _visible_path(self, floor):
        path = self.account.live_path(self.robot_id)
        if path and path.map_version == (floor.map_id, floor.version_id):
            marker = path.latest.expires > datetime.now(UTC).timestamp()
            return path, marker
        return None, False

    @callback
    def _sync_image_state(self):
        floor = self._floor
        path, marker = self._visible_path(floor) if floor else (None, False)
        key = (floor, path, marker)
        if key != self._render_key:
            self._render_key = key
            self._attr_image_last_updated = datetime.now(UTC) if floor is not None else None

    @callback
    def _handle_coordinator_update(self):
        self._sync_image_state()
        super()._handle_coordinator_update()

    async def async_image(self):
        floor = self._floor
        if not self.available or floor is None:
            return None
        path, marker = self._visible_path(floor)
        key = (floor, path, marker)
        if self._image_key == key:
            return self._image
        geometry = await self.account.async_floor_plan(self.robot_id, floor)
        if geometry is None:
            return None
        image = await self.hass.async_add_executor_job(
            render_floor_plan, geometry, path, marker, floor.orientation or 0.0
        )
        if (
            not self.available
            or floor != self._floor
            or (path, marker) != self._visible_path(floor)
        ):
            return None
        self._image_key, self._image = key, image
        return image


def _fit_name(name, font, width):
    if font.getlength(name) <= width:
        return name
    # Find the longest prefix that fits with the ellipsis.
    length = (
        bisect_right(
            range(len(name)), width, key=lambda count: font.getlength(name[:count].rstrip() + "…")
        )
        - 1
    )
    return name[:length].rstrip() + "…" if length > 0 else None


def _place_room_name(name, polygon, font, occupied):
    outer, *holes = polygon
    xs, ys = zip(*outer, strict=True)
    left, top = min(xs), min(ys)
    width, height = max(xs) - left + 1, max(ys) - top + 1

    interior = Image.new("1", (width, height))
    mask = ImageDraw.Draw(interior)
    mask.polygon([(x - left, y - top) for x, y in outer], fill=1)
    for hole in holes:
        mask.polygon([(x - left, y - top) for x, y in hole], fill=0)

    centers = [(width // 2, height // 2)]
    centers.extend(
        (width * column // 4, height * row // 4)
        for column in (1, 2, 3)
        for row in (1, 2, 3)
        if (column, row) != (2, 2)
    )
    usable_width = width - 2 * (LABEL_STROKE + LABEL_PADDING)
    for limit in (usable_width, usable_width * 2 // 3, usable_width // 2):
        if (text := _fit_name(name, font, limit)) is None:
            continue
        x0, y0, x1, y1 = font.getbbox(text, anchor="mm", stroke_width=LABEL_STROKE)
        for x, y in centers:
            box = (
                x + x0 - LABEL_PADDING,
                y + y0 - LABEL_PADDING,
                x + x1 + LABEL_PADDING,
                y + y1 + LABEL_PADDING,
            )
            # Cropping past the room bounds pads with zero. Holes also stay empty.
            if interior.crop(box).getextrema() != (1, 1):
                continue
            bounds = (left + box[0], top + box[1], left + box[2], top + box[3])
            if occupied.crop(bounds).getbbox() is None:
                return (left + x, top + y), text, bounds
    return None


def render_floor_plan(
    plan: FloorPlan, path: MissionPath | None, marker: bool, orientation: float = 0.0
) -> bytes:
    cosine, sine = cos(orientation), sin(orientation)

    def rotate(point):
        x, y = point
        return x * cosine - y * sine, x * sine + y * cosine

    points = [
        rotate(point) for room in plan.rooms for outer, *_ in room.polygons for point in outer
    ]
    xs, ys = zip(*points, strict=True)
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    usable = CANVAS_SIZE - 2 * MARGIN
    scale = usable / max(max_x - min_x, max_y - min_y, 1)
    width, height = round((max_x - min_x) * scale), round((max_y - min_y) * scale)

    def xy(point):
        x, y = rotate(point)
        return round((x - min_x) * scale) + MARGIN, round((max_y - y) * scale) + MARGIN

    def on_map(point):
        x, y = rotate((point.x, point.y))
        return min_x <= x <= max_x and min_y <= y <= max_y

    image = Image.new("RGB", (width + 2 * MARGIN, height + 2 * MARGIN), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(ROOM_LABEL_FONT, ROOM_LABEL_SIZE)
    occupied = Image.new("1", image.size)
    pose = path.latest.positions[-1] if path and marker else None
    marker_at = xy((pose.x, pose.y)) if pose is not None and on_map(pose) else None
    if marker_at is not None:
        x, y = marker_at
        gap = ROBOT_MARKER_CLEARANCE
        occupied.paste(1, (x - gap, y - gap, x + gap + 1, y + gap + 1))
    labels = []
    for index, room in enumerate(plan.rooms):
        color = ROOM_COLORS[index % len(ROOM_COLORS)]
        polygons = [tuple([xy(point) for point in ring] for ring in p) for p in room.polygons]
        for outer, *holes in polygons:
            draw.polygon(outer, fill=color, outline="#657994", width=2)
            for hole in holes:
                draw.polygon(hole, fill=BACKGROUND, outline="#657994")
        if room.name:
            name = normalize("NFC", room.name.strip())
            placements = (_place_room_name(name, polygon, font, occupied) for polygon in polygons)
            if label := max(filter(None, placements), key=lambda item: len(item[1]), default=None):
                at, text, bounds = label
                labels.append((at, text))
                occupied.paste(1, bounds)
    if path:
        for (first_index, first), (second_index, second) in pairwise(path.points):
            if second_index == first_index + 1 and on_map(first) and on_map(second):
                color = ROUTE_COLORS.get(POSITION_ACTIVITIES.get(second.modes), "#63d9eb")
                draw.line([xy((first.x, first.y)), xy((second.x, second.y))], fill=color, width=3)
    for at, label in labels:
        draw.text(
            at,
            label,
            fill="#ffffff",
            anchor="mm",
            font=font,
            stroke_width=LABEL_STROKE,
            stroke_fill=BACKGROUND,
        )
    if marker_at is not None:
        x, y = marker_at
        direction = pose.orientation + pi + orientation
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#63d9eb", outline="#ffffff")
        draw.line(
            (x, y, x + 15 * cos(direction), y - 15 * sin(direction)),
            fill="#ffffff",
            width=2,
        )
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
