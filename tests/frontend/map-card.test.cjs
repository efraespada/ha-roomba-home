const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

class Path {
  constructor() { this.points = []; }
  moveTo(...point) { this.points.push(point); }
  lineTo(...point) { this.points.push(point); }
  closePath() {}
  addPath(path) { this.points.push(...path.points); }
}

const sandbox = {
  document: { createElement: (tag) => mockElement(tag) },
  customElements: { define() {} },
  Option: class { constructor(text, value) { this.text = text; this.value = value; } },
  window: {},
  HTMLElement: class {},
  Path2D: Path,
};
const source = readFileSync(resolve(__dirname,
  "../../custom_components/roomba_home/frontend/roomba-home-map-card.js"), "utf8");
runInNewContext(`${source}\nglobalThis.card = RoombaHomeMapCard.prototype;\nglobalThis.drawMissionMap = drawMissionMap;`, sandbox);

const boundary = [[0, 0], [10, 0], [10, 4], [0, 4], [0, 0]];
const region = { id: "example:rid:room-a", kind: "room", polygons: [[boundary]] };

function mockElement(tag) {
  return {
    tag,
    children: [],
    dataset: {},
    style: { setProperty() {} },
    setAttribute(key, value) { this[key] = String(value); },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    focus() { this.focused = true; },
    querySelectorAll(selector) {
      const key = { "[data-setting]": "setting", "[data-routine-preset]": "routinePreset" }[selector];
      return this.children.flatMap((child) => [
        ...(child.tag === selector || (key && Object.hasOwn(child.dataset ?? {}, key)) ? [child] : []),
        ...(child.querySelectorAll?.(selector) ?? []),
      ]);
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0]; },
  };
}

function mockCard(orientation) {
  const lines = [];
  const fills = [];
  const elements = new Map();
  let lastPoint;
  const card = Object.assign(Object.create(sandbox.card), {
    ctx: {
      clearRect() {},
      fillRect(...bounds) { fills.push([this.fillStyle, bounds]); },
      fill(path) { fills.push([this.fillStyle, path?.points]); },
      stroke() {}, setLineDash() {}, beginPath() {}, arc() {},
      moveTo(...point) { lastPoint = point; },
      lineTo(...point) {
        lines.push([lastPoint, point]);
        lastPoint = point;
      },
    },
    $(id) {
      if (!elements.has(id)) elements.set(id, mockElement());
      return elements.get(id);
    },
    drawLabel() {},
    geometry: { regions: [region], keep_out: [], virtual_walls: [] },
    snapshot: {
      floor_settings: { orientation },
      live: {
        trail: [[1, 2, 1], [2, 4, 1]],
        position: { x: 4, y: 1, orientation: 0, expires_at: Date.now() / 1000 + 40 },
      },
    },
    selected: new Set(),
    zoom: 1.4,
    pan: [45, -23],
    orbit: 0,
  });
  card.markerCtx = card.ctx;
  return { card, lines, fills };
}

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} ≠ ${b}`);

test("saved routines display the estimate from the selected provider record", () => {
  const { card } = mockCard(0);
  const saved = { id: "saved", name: "Test routine", estimate: {
    duration_minutes: 57.483333333333334, confidence: "good",
  } };
  card.routineAreas = new Map();
  card.routines = [saved];
  card.routineDraft = { saved, name: saved.name, regions: [] };
  const estimate = card.$("routine-estimate");
  card.renderRoutine();
  assert.equal(estimate.hidden, false);
  assert.equal(estimate.textContent, "Saved estimate: 58 min · Good confidence");
  saved.estimate = { duration_minutes: 0, confidence: null };
  card.renderRoutine();
  assert.equal(estimate.textContent, "Saved estimate: 0 min");
  card.routineDraft = { name: "New routine", regions: [] };
  card.renderRoutine();
  assert.equal(estimate.hidden, true);
});

test("routine presets preserve order and apply only to the intended areas and modes", () => {
  const { card } = mockCard(0);
  const vacuumLight = { mode: "vacuum", suction_level: 1, two_pass: false, wetness_level: null };
  const mopLight = { mode: "mop", suction_level: null, wetness_level: 1, two_pass: false };
  const vacuumDeep = { mode: "vacuum", suction_level: 4, two_pass: true, wetness_level: null };
  card.snapshot.cleaning = {
    default_mode: "vacuum", modes: ["vacuum", "mop"],
    suction_level: 4, wetness_level: 3, two_pass: true,
    presets: { vacuum: { light: vacuumLight, deep: vacuumDeep }, mop: { light: mopLight } },
  };
  card.routines = [];
  card.routineAreas = new Map([["zone", "Zone"], ["room", "Room"]]);
  const regions = [{ id: "zone", mode: "mop" }, { id: "room", wetness_level: 3 }];
  card.routineDraft = { name: "Mixed routine", regions };
  card.renderRoutine();
  const all = card.$("routine-preset-all");
  assert.deepEqual(Array.from(all.children, (option) => option.value), ["", "light"]);
  assert.equal(card.$("routine-preset-all-label").hidden, false);
  all.value = "light";
  all.onchange();
  assert.deepEqual(regions, [{ id: "zone", ...mopLight }, { id: "room", ...vacuumLight }]);
  assert.equal(all.focused, true);

  const row = card.$("routine-regions").children[1];
  const preset = row.querySelector("[data-routine-preset]");
  preset.value = "deep";
  preset.onchange();
  assert.deepEqual(regions, [{ id: "zone", ...mopLight }, { id: "room", ...vacuumDeep }]);
  assert.equal(card.$("routine-regions").children[1].querySelector("[data-routine-preset]").focused, true);

  const mode = card.$("routine-regions").children[1].querySelector("select");
  mode.value = "mop";
  mode.onchange();
  assert.equal(regions[1].mode, "mop");
  assert.deepEqual(Array.from(card.$("routine-regions").children[1].querySelector("[data-routine-preset]")
    .children, (option) => option.value), ["", "light"]);
  delete card.snapshot.cleaning.presets.mop;
  card.renderRoutine();
  assert.equal(card.$("routine-preset-all-label").hidden, true);
  assert.equal(card.$("routine-regions").children[1].querySelector("[data-routine-preset]").disabled, true);
});

function draftEstimateCard() {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example_robot" };
  card.snapshot.map = { id: "fixture-map", version: "v1" };
  card.geometry.selection_id = "inventory";
  card.routineMap = { ...card.snapshot.map, selectionId: "inventory" };
  card.routineAreas = new Map([["room-a", "Kitchen"], ["furniture-b", "Table"]]);
  card.routines = [];
  card.routineDraft = { name: "Draft", regions: [
    { id: "room-a", mode: "mop", two_pass: false }, { id: "furniture-b", mode: "vacuum" },
  ] };
  card.routineDialog.open = true;
  card.renderRoutine();
  return card;
}

test("native automatic order survives editing, copying, and confirming a draft", async () => {
  const card = draftEstimateCard();
  const saved = {
    id: "favorite", name: "Mixed cleaning", ordered: false, editable: true,
    region_settings: [{ id: "room-a", mode: "mop" }, { id: "room-b", mode: "vacuum" }],
  };
  card.routines = [saved];
  card.routineAreas.set("room-b", "Hall");
  card.editRoutine(saved.id);
  assert.equal(card.$("routine-order").value, "automatic");
  const saves = [];
  card.mutateRoutine = async (...args) => { saves.push(args); };
  card.routineDraft.name = "Renamed";
  await card.saveRoutine();
  assert.equal(saves[0][1].ordered, undefined);
  assert.equal(saves[0][1].regions, undefined);
  card.routineDraft.regions[0].wetness_level = 1;
  await card.saveRoutine();
  assert.equal(saves[1][1].ordered, false);
  assert.equal(saves[1][1].regions[0].wetness_level, 1);

  card.copyRoutine();
  const runs = [];
  card._hass = { callService: async (...args) => { runs.push(args); } };
  await card.runRoutine();
  assert.match(card.$("routine-status").textContent, /Roomba will choose the order/);
  await card.runRoutine();
  assert.equal(runs[0][2].ordered, false);
});

test("a schedule can be created from the reviewed floor, enabled and removed", async () => {
  const card = draftEstimateCard();
  card.geometry.regions = [{ id: "room-a", name: "Kitchen" }, { id: "room-b", name: "Hall" }];
  card.geometry.furniture = { destinations: [{ id: "furniture-b", name: "Table" }] };
  card.selected.add("room-a");
  card.routineDialog.open = false;
  card.routineDialog.showModal = function () { this.open = true; };
  const calls = [];
  let saved;
  card.callAction = async (action, data, entity) => {
    calls.push([action, JSON.parse(JSON.stringify(data)), entity]);
    if (action === "list_cleaning_schedules") return { schedules: [] };
    if (action === "create_cleaning_schedule") {
      saved = { id: "group:item", name: data.name, time: data.time,
        weekdays: data.weekdays, region_settings: data.regions, enabled: false };
    }
    if (action === "set_cleaning_schedule_enabled") saved = { ...saved, enabled: data.enabled };
    return saved;
  };
  await card.openRoutines(true);
  assert.equal(card.$("routine-title").textContent, "Cleaning schedules");
  assert.equal(card.routineAreas.has("furniture-b"), false);
  assert.equal(card.$("run-routine").hidden, true);
  card.routineDraft.name = "Office cleaning";
  card.routineDraft.time = "10:15";
  const days = card.$("schedule-day-options").children;
  for (const day of [5, 2]) {
    const check = days[day - 1].children[0];
    check.checked = true;
    check.onchange();
  }
  card.routineDraft.regions[0].mode = "vacuum";
  await card.saveSchedule();
  assert.deepEqual(calls[1], ["create_cleaning_schedule", {
    name: "Office cleaning", frequency: "weekly", time: "10:15", weekdays: [2, 5],
    regions: [{ id: "room-a", mode: "vacuum" }],
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
  }, card.config.entity]);
  assert.equal(card.$("toggle-schedule").textContent, "Enable schedule");
  await card.toggleSchedule();
  assert.deepEqual(calls[2][1], { schedule_id: "group:item", enabled: true });
  assert.equal(card.$("toggle-schedule").textContent, "Disable schedule");
  await card.removeRoutine();
  assert.equal(calls.length, 3);
  await card.removeRoutine();
  assert.deepEqual(calls[3], ["remove_cleaning_schedule", { schedule_id: "group:item" }, card.config.entity]);
  assert.equal(card.routines.length, 0);
});

test("editing a one-time schedule keeps timing unless changed and rechecks the floor for preferences", async () => {
  const card = draftEstimateCard();
  card.scheduleEditor = true;
  card.routines = [{ id: "group:item", name: "Once", frequency: "once", weekday: 3, time: "08:30",
    enabled: true, region_settings: [{ id: "room-a", mode: "mop", wetness_level: 1 }] }];
  const writes = [];
  card.mutateRoutine = async (...args) => writes.push(JSON.parse(JSON.stringify(args)));
  card.editRoutine("group:item");
  assert.equal(card.$("schedule-days").hidden, true);
  await card.saveSchedule();
  assert.equal(writes.length, 0);
  card.routineDraft.regions[0].wetness_level = 2;
  card.snapshot.map.version = "v2";
  await card.saveSchedule();
  assert.match(card.$("routine-status").textContent, /current floor/);
  assert.equal(writes.length, 0);
  card.snapshot.map.version = "v1";
  await card.saveSchedule();
  assert.deepEqual(writes[0], ["update_cleaning_schedule", {
    schedule_id: "group:item", regions: [{ id: "room-a", mode: "mop", wetness_level: 2 }],
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
  }]);
});

test("local backups can be opened offline by a reader without showing write controls", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = null;
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "a".repeat(64), map_id: "fixture", version: "one", name: "Ático",
    captured_at: "2026-11-25T21:00:00+00:00", pinned: true };
  const calls = [];
  card._hass = { callWS: async (request) => {
    calls.push(request);
    return request.type === "roomba_home/map_backups"
      ? { snapshots: [saved], can_manage: false, retention: 5, automatic: true }
      : { backup: saved, geometry: { regions: [region] } };
  } };
  card.drawMapBackup = (canvas, backup, geometry) => {
    assert.equal(canvas, card.$("map-backup-preview"));
    assert.equal(backup.name, "Ático");
    assert.equal(geometry.regions.length, 1);
  };
  await card.openMapBackups();
  assert.match(card.$("map-backup-choice").children[0].text, /Ático.+Pinned/);
  assert.equal(card.$("map-backup-preview").hidden, false);
  assert.equal(card.$("map-backup-comparison").hidden, true);
  assert.equal(card.$("map-backup-controls").hidden, true);
  assert.equal(card.$("review-map-backup-restore").hidden, true);
  assert.equal(card.$("export-map-backup").disabled, false);
  assert.equal(calls.map(({ type }) => type).join(","), "roomba_home/map_backups,roomba_home/read_map_backup");
  assert.ok(calls.every(({ entity_id }) => entity_id === "vacuum.example"));
});

test("a backup capture sends the reviewed map, then restores selection and confirms deletion", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "two" }, inventory_id: "inventory",
    floor_settings: { id: "settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "b".repeat(64), map_id: "floor", version: "one", name: "Ático",
    orientation: 0, captured_at: "2026-11-25T21:00:00+00:00", pinned: false };
  let records = [];
  const calls = [];
  card._hass = { callWS: async (request) => {
    calls.push(JSON.parse(JSON.stringify(request)));
    switch (request.type) {
      case "roomba_home/map_backups": return { snapshots: records, can_manage: true, retention: 5 };
      case "roomba_home/capture_map_backup": records = [saved]; return saved;
      case "roomba_home/read_map_backup": return { backup: saved, geometry: { regions: [region] } };
      case "roomba_home/modify_map_backup": records = []; break;
    }
  } };
  card.drawMapBackup = () => {};
  await card.openMapBackups();
  assert.equal(card.$("map-backup-detail").hidden, true);
  await card.captureMapBackup();
  assert.deepEqual(calls[1], { type: "roomba_home/capture_map_backup", entity_id: "vacuum.example",
    map_id: "floor", version: "two", inventory_id: "inventory", settings_id: "settings" });
  assert.equal(card.$("map-backup-choice").value, saved.id);
  assert.match(card.$("map-backup-comparison").textContent, /Map revision/);
  await card.modifyMapBackup("delete");
  assert.equal(calls.length, 4);
  assert.equal(card.$("delete-map-backup").textContent, "Confirm delete");
  await card.modifyMapBackup("delete");
  assert.equal(calls[4].operation, "delete");
  assert.equal(calls[4].backup_id, saved.id);
  assert.equal(card.$("map-backup-detail").hidden, true);
});

test("restore shows both settings and requires reviewing a changed floor again", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "settings-one", name: "Rooms", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "c".repeat(64), map_id: "floor", version: "earlier", name: "Ático", orientation: -Math.PI / 2,
    captured_at: "2026-11-25T21:00:00+00:00", pinned: false };
  const requests = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved, geometry: { regions: [region] } };
    requests.push(JSON.parse(JSON.stringify(request)));
    return { applied: request.confirmed === true,
      changes: { name: { from: "Rooms", to: "Ático" }, orientation: { from: 0, to: -Math.PI / 2 } } };
  } };
  card.drawMapBackup = () => {};
  const refresh = [];
  card.refresh = async (force) => { refresh.push(force); };
  await card.openMapBackups();
  assert.equal(card.$("review-map-backup-restore").hidden, false);
  await card.reviewMapBackupRestore();
  assert.equal(requests[0].confirmed, undefined);
  assert.equal(card.$("map-backup-restore").hidden, false);
  const fields = card.$("map-backup-restore-changes").children;
  assert.equal(fields[0].children[1].textContent, "Rooms → Ático");
  assert.equal(fields[1].children[1].textContent, "0° → -90°");

  card.snapshot.floor_settings.id = "settings-two";
  await card.confirmMapBackupRestore();
  assert.equal(requests.length, 1);
  assert.match(card.$("map-backups-status").textContent, /current floor changed/i);
  await card.reviewMapBackupRestore();
  await card.confirmMapBackupRestore();
  assert.deepEqual(requests[2], { ...requests[1], settings_id: "settings-two", confirmed: true });
  assert.deepEqual(refresh, [true]);
  assert.equal(card.$("map-backup-restore").hidden, true);
});

test("zone recovery previews active dependencies and binds confirmation to the reviewed result", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "floor-settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "d".repeat(64), map_id: "floor", version: "earlier", name: "Ático",
    captured_at: "2026-11-25T21:00:00+00:00", orientation: 0 };
  const reviewId = "a".repeat(64);
  const view = { review_id: reviewId, changes: [
    { id: "100", name: "Lectúra", current_name: "Moved", outline_changed: true },
    { id: "101", name: "Entry", current_name: null, missing: true, outline_changed: true },
  ], dependencies: [{ kind: "schedule", name: "Weekly", zones: ["100"] }], unchecked: ["routine"] };
  const writes = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved, geometry: { regions: [region, { kind: "zone" }] } };
    writes.push(JSON.parse(JSON.stringify(request)));
    return { ...view, applied: Boolean(request.confirmed) };
  } };
  card.drawMapBackup = () => {};
  card.refresh = async () => {};
  await card.openMapBackups();
  assert.equal(card.$("review-map-backup-zones").hidden, false);
  await card.reviewMapBackupRestore("zones");
  assert.equal(card.$("map-backup-restore-zone-detail").hidden, false);
  const zoneItems = card.$("map-backup-restore-zone-list").children;
  assert.deepEqual(Array.from(zoneItems[0].children, ({ textContent }) => textContent), [
    "Restore Lectúra", "Current name: Moved", "Restore saved outline", "Schedule · Weekly",
  ]);
  assert.equal(zoneItems[1].children[0].textContent, "Recreate Entry");
  const note = card.$("map-backup-restore-dependency-status").textContent;
  assert.match(note, /destinations may need to be added again/);
  assert.match(note, /routines could not be checked/);
  await card.confirmMapBackupRestore();
  assert.equal(writes[0].type, "roomba_home/restore_map_backup_zones");
  assert.deepEqual(writes[1], { ...writes[0], review_id: reviewId, confirmed: true });
  assert.equal(card.$("map-backups-status").textContent, "Cleaning zones restored.");
});

test("program recovery previews settings and confirms only the selected program", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "f".repeat(64), map_id: "floor", version: "older", program_count: 3 };
  const entry = { name: "Entráda", mode: "mop", wetness_level: 2, two_pass: true, restore: true };
  const programs = [
    { kind: "routine", id: "routine", name: "Morning", status: "ready", review_id: "routine-review",
      ordered: true, destinations: [entry] },
    { kind: "schedule", id: "schedule", name: "Evening", status: "ready", review_id: "schedule-review",
      ordered: true, destinations: [{ name: "Oficina", mode: "vacuum", suction_level: 1 }, entry] },
    { kind: "routine", id: "stale", name: "Changed", status: "changed_selection", destinations: [] },
  ];
  const requests = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved, geometry: { regions: [region] } };
    requests.push(JSON.parse(JSON.stringify(request)));
    return request.confirmed ? { applied: true } : { programs, unchecked: ["schedule"] };
  } };
  card.drawMapBackup = () => {};
  card.refresh = async () => {};
  const select = card.$("map-backup-restore-program-choice");
  select.parentElement = {};
  select.value = "0";
  await card.openMapBackups();
  await card.reviewMapBackupRestore("programs");
  assert.equal(card.$("map-backup-restore-program-order").textContent, "Listed order");
  assert.match(card.$("map-backup-restore-program-status").children[0].textContent, /Destinations or settings have changed/);
  assert.match(card.$("map-backup-restore-program-unchecked").textContent, /incomplete for schedules/);
  select.value = "1";
  card.showMapBackupProgram();
  const areas = card.$("map-backup-restore-program-areas").children;
  assert.deepEqual(Array.from(areas, (row) => row.children[0].textContent), ["Oficina", "Entráda · Restore"]);
  assert.equal(areas[1].children[1].textContent, "Mop · Mop wetness 2 · Two passes on");
  await card.confirmMapBackupRestore();
  assert.deepEqual(requests[1], {
    ...requests[0], confirmed: true, kind: "schedule", program_id: "schedule", review_id: "schedule-review",
  });
  assert.equal(card.$("map-backups-status").textContent, "Cleaning destinations restored.");
});

test("Smart recommendations update supported rooms independently in the existing order", async () => {
  const card = draftEstimateCard();
  const kitchen = "fixture-map:rid:room-a";
  const hall = "fixture-map:rid:room-b";
  const zones = [kitchen, "fixture-map:tid:furniture-b", hall];
  const first = { id: kitchen, mode: "mop", wetness_level: 1 };
  const furniture = { id: zones[1], mode: "vacuum", suction_level: 2 };
  const last = { id: hall, suction_level: 3 };
  card.routineAreas = new Map([[kitchen, "Kitchen"], [hall, "Hall"], [zones[1], "Table"]]);
  card.routineDraft.regions = [first, furniture, last];
  card.snapshot.cleaning = {
    supports_smart_presets: true, default_mode: "vacuum",
    modes: ["vacuum", "mop"], suction_level: 4, wetness_level: 3,
  };
  const calls = [];
  card._hass = { callWS: async (query) => {
    calls.push(query);
    return {
      map: card.snapshot.map,
      smart_presets: {
        [kitchen]: { mop: { wetness_level: 3, smart_scrub: true } },
        [hall]: { vacuum: { suction_level: 1, two_pass: false } },
      },
    };
  }};
  card.renderRoutine();
  const all = card.$("routine-preset-all");
  assert.equal(all.children.at(-1).text, "Smart recommendations");
  all.value = "smart";
  await all.onchange();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].type, "roomba_home/cleaning_scores");
  assert.equal(calls[0].version, "v1");
  assert.deepEqual(card.routineDraft.regions.map(({ id }) => id), zones);
  assert.deepEqual(first, { id: kitchen, mode: "mop", wetness_level: 3, smart_scrub: true });
  assert.deepEqual(furniture, { id: zones[1], mode: "vacuum", suction_level: 2 });
  assert.deepEqual(last, { id: hall, mode: "vacuum", suction_level: 1, two_pass: false });
  assert.match(card.$("routine-status").textContent, /2 of 3 areas/);

  last.suction_level = 4;
  const preset = card.$("routine-regions").children[0].querySelector("[data-routine-preset]");
  preset.value = "smart";
  await preset.onchange();
  assert.equal(last.suction_level, 4);
  assert.match(card.$("routine-status").textContent, /this area/);
});

test("Smart recommendations leave edited drafts and mismatched floors alone", async () => {
  const card = draftEstimateCard();
  card.snapshot.cleaning = { supports_smart_presets: true, default_mode: "mop" };
  const room = card.routineDraft.regions[0];
  room.id = "fixture-map:rid:room-a";
  let deliver;
  card._hass = { callWS: async () => new Promise((resolve) => { deliver = resolve; }) };
  const delayed = card.applySmartPresets([room]);
  room.wetness_level = 1;
  deliver({ map: card.snapshot.map, smart_presets: { [room.id]: { mop: { wetness_level: 3 } } } });
  await delayed;
  assert.equal(room.wetness_level, 1);
  assert.equal(card.$("routine-status").textContent, "");

  card._hass.callWS = async () => ({ map: { ...card.snapshot.map, version: "outdated" } });
  await card.applySmartPresets([room]);
  assert.match(card.$("routine-status").textContent, /floor changed/i);
  assert.equal(room.wetness_level, 1);
  card._hass.callWS = async () => ({ map: card.snapshot.map });
  await card.applySmartPresets([room]);
  assert.match(card.$("routine-status").textContent, /no compatible recommendations/i);
});

test("quick routines load reviewed settings as a new draft without creating a favorite", async () => {
  const card = draftEstimateCard();
  const regions = [{ id: "furniture-b", mode: "vacuum", suction_level: 2 }, { id: "room-a", mode: "mop" }];
  card.callAction = async (service, data, entity) => {
    assert.equal(service, "list_map_routines");
    assert.equal(entity, card.config.entity);
    assert.deepEqual(JSON.parse(JSON.stringify(data)), { map_id: "fixture-map", version: "v1" });
    return { map_id: "fixture-map", version: "v1", routines: [
      { kind: "recent", name: "Recent cleaning", duration_seconds: 0, region_settings: regions },
      { kind: "recent", name: "Previous room", region_settings: [{ id: "missing" }] },
    ] };
  };
  await card.loadQuickRoutines();
  const [recent, unavailable] = card.$("quick-routines").children;
  assert.equal(recent.children[0].textContent, "Recent cleaning · 0 min");
  assert.equal(unavailable.children[1].textContent, "Unavailable on this floor plan");
  recent.children[1].onclick();
  assert.equal(card.routineDraft.saved, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(card.routineDraft.regions)), regions);
  card.routineDraft.regions[0].suction_level = 4;
  assert.equal(regions[0].suction_level, 2);
  assert.equal(card.$("run-routine").textContent, "Run draft");

  const calls = [];
  card._hass = { callService: async (...args) => { calls.push(JSON.parse(JSON.stringify(args))); } };
  await card.runRoutine();
  assert.match(card.$("routine-status").textContent, /Table → Kitchen/);
  card.routineDraft.regions[1].wetness_level = 1;
  await card.runRoutine();
  assert.equal(calls.length, 0);
  await card.runRoutine();
  assert.deepEqual(calls, [["roomba_home", "run_cleaning_draft", {
    regions: JSON.parse(JSON.stringify(card.routineDraft.regions)),
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
  }, { entity_id: card.config.entity }]]);
});

test("spot suggestion opens the existing point picker and a stale quick list is discarded", async () => {
  const card = draftEstimateCard();
  Object.defineProperty(card, "pointAvailable", { value: true });
  card.routineDialog.close = function () { this.open = false; };
  card.togglePointMode = () => { card.pointMode = true; };
  card.callAction = async () => ({ map_id: "fixture-map", version: "v1", routines: [
    { kind: "spot_clean", name: "Clean a point", choose_point: true },
  ] });
  await card.loadQuickRoutines();
  card.$("quick-routines").children[0].children[1].onclick();
  assert.equal(card.pointMode, true);
  assert.equal(card.routineDialog.open, false);
  assert.equal(card.$("point-mode").focused, true);

  card.routineDialog.open = true;
  let resolve;
  card.callAction = () => new Promise((done) => { resolve = done; });
  const pending = card.loadQuickRoutines();
  card.snapshot.map.version = "v2";
  resolve({ map_id: "fixture-map", version: "v1", routines: [] });
  await pending;
  assert.equal(card.quickRoutines, null);
  assert.equal(card.$("quick-routines").hidden, true);
});

test("routine draft sends reviewed settings and labels incomplete times by area", async () => {
  const card = draftEstimateCard();
  card.callAction = async (service, data, entity) => {
    assert.equal(service, "estimate_cleaning_routine");
    assert.equal(entity, card.config.entity);
    assert.deepEqual(JSON.parse(JSON.stringify(data)), {
      regions: card.routineDraft.regions,
      floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
    });
    return { duration_seconds: null, partial_duration_seconds: 3449, areas: [
      { id: "room-a", duration_seconds: 3449 }, { id: "furniture-b", duration_seconds: null },
    ] };
  };
  await card.estimateRoutine();
  assert.equal(card.$("routine-draft-time").textContent, "Known time · 58 min for 1 of 2 areas");
  assert.deepEqual(Array.from(card.$("routine-area-times").children, (x) => x.textContent),
    ["Kitchen · 58 min", "Table · Unavailable"]);
  card.routineDraft.regions[0].two_pass = true;
  card.renderRoutineEstimate();
  assert.equal(card.$("routine-draft-time").hidden, true);
});

test("routine draft ignores late responses for a revised floor or changed profiles", async () => {
  for (const change of [
    (card) => { card.snapshot.map.version = "v2"; },
    (card) => { card.routineDraft.regions[0].mode = "vacuum"; },
  ]) {
    const card = draftEstimateCard();
    let resolve;
    card.callAction = () => new Promise((done) => { resolve = done; });
    const pending = card.estimateRoutine();
    assert.equal(card.$("estimate-routine").disabled, true);
    change(card);
    resolve({ duration_seconds: 120, areas: [] });
    await pending;
    assert.equal(card.$("routine-draft-time").hidden, true);
  }
});

test("routine draft displays zero, ambiguity and endpoint errors", async () => {
  const card = draftEstimateCard();
  card.callAction = async () => ({ duration_seconds: 0, areas: [
    { id: "room-a", duration_seconds: 0 }, { id: "furniture-b", duration_seconds: 0 },
  ] });
  await card.estimateRoutine();
  assert.equal(card.$("routine-draft-time").textContent, "Draft estimate · 0 min");
  card.callAction = async () => ({ areas: [{ id: "room-a", duration_seconds: null, ambiguous: true }] });
  await card.estimateRoutine();
  assert.equal(card.$("routine-draft-time").textContent, "Roomba has no estimate for this draft.");
  assert.equal(card.$("routine-area-times").children[0].textContent, "Kitchen · Choose more specific preferences");
  card.callAction = async () => { throw new Error("Roomba rate limited estimates"); };
  await card.estimateRoutine();
  assert.equal(card.$("routine-draft-time").textContent, "Roomba rate limited estimates");
  assert.equal(card.$("routine-area-times").hidden, true);
});

function historyGeometry() {
  return {
    rooms: [{ polygons: region.polygons }], borders: [], walls: [{ kind: "exterior", points: [[0, 0], [10, 0]] }],
    furniture: [], carpets: [], docks: [[0, 0]], hazards: [[3, 2]], temporary_zones: [],
    coverage: [{ modes: ["mopping"], polygons: region.polygons }],
    trajectories: [
      { modes: ["traveling"], points: [[1, 0], [2, 0]] },
      { modes: ["vacuuming", "mopping"], points: [[7, 2], [8, 2]] },
    ],
  };
}

test("room cleaning scores read the displayed map and retain zero and false measurements", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example_robot" };
  card.snapshot.map = { id: "floor", version: "current" };
  card.scoreSequence = 0;
  card.$("cleaning-scores-dialog").showModal = function () { this.open = true; };
  let requested;
  card._hass = { callWS: async (request) => {
    requested = request;
    return { ranges: [0.7], last_processed_mission_started_at: "2026-11-24T12:30:00Z",
      rooms: [{ name: "Estudio", score: 0, traffic: "normal",
        preferences: { mode: "vacuum_mop", suction_level: 1, two_pass: false } }] };
  } };
  await card.openCleaningScores();
  assert.deepEqual(JSON.parse(JSON.stringify(requested)), {
    type: "roomba_home/cleaning_scores", entity_id: "vacuum.example_robot", map_id: "floor", version: "current",
  });
  const [section] = card.$("scores-rooms").children;
  assert.equal(section.children[0].textContent, "Estudio");
  const measurements = Object.fromEntries(section.children[1].children.map(
    (field) => field.children.map((item) => item.textContent),
  ));
  assert.deepEqual(measurements, {
    "Roomba score": "0", Traffic: "Normal", "Suggested mode": "Vacuum and mop", Suction: "1", "Two passes": "Off",
  });
  assert.equal(card.$("scores-summary").hidden, false);
  assert.equal(card.$("scores-status").textContent, "");
});

test("room cleaning scores discard a late result after changing the floor revision", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example_robot" };
  card.snapshot.map = { id: "floor", version: "current" };
  card.scoreSequence = 0;
  card.$("cleaning-scores-dialog").showModal = function () { this.open = true; };
  let resolveScores;
  card._hass = { callWS: () => new Promise((resolve) => { resolveScores = resolve; }) };
  const read = card.openCleaningScores();
  card.snapshot.map = { id: "floor", version: "newer" };
  resolveScores({ ranges: [0.7], rooms: [{ name: "Previous room", score: 0.8 }] });
  await read;
  assert.equal(card.$("scores-rooms").children.length, 0);
  assert.equal(card.$("scores-summary").hidden, true);
  card._hass.callWS = async () => ({ ranges: [], rooms: [] });
  await card.openCleaningScores();
  assert.match(card.$("scores-status").textContent, /no cleaning scores/i);
  card._hass.callWS = async () => { throw new Error("Map rate limited"); };
  await card.openCleaningScores();
  assert.equal(card.$("scores-status").textContent, "Map rate limited");
});

test("live route distinguishes reported activities and preserves gaps", () => {
  const { card, lines } = mockCard(0);
  const colors = [];
  card.ctx.stroke = function () { colors.push(this.strokeStyle); };
  card.snapshot.live = {
    position: null,
    trail: [
      [1, 0, 0, "traveling"], [2, 1, 0, "traveling"], [3, 2, 0, "vacuuming"],
      [6, 4, 0, "vacuuming"], [7, 5, 0, "vacuuming"], [8, 6, 0, "mopping"],
      [9, 7, 0, "vacuum_mop"], [10, 8, 0, null],
    ],
  };
  card.drawLive((point) => point);
  assert.deepEqual(colors, ["#9eafbf", "#59adff", "#59adff", "#4ed9ad", "#c39bff", "#80e9ff"]);
  assert.deepEqual(JSON.parse(JSON.stringify(lines)), [
    [[0, 0], [1, 0]], [[1, 0], [2, 0]], [[4, 0], [5, 0]], [[5, 0], [6, 0]],
    [[6, 0], [7, 0]], [[7, 0], [8, 0]],
  ]);
  const legend = card.$("live-map-legend");
  assert.equal(legend.hidden, false);
  assert.deepEqual(legend.children.map((chip) => chip.textContent),
    ["Travel", "Vacuuming", "Mopping", "Vacuum and mop", "Route"]);
  card.$("live-travel-path").checked = false;
  colors.length = 0;
  card.drawLive((point) => point);
  assert.deepEqual(colors, ["#59adff", "#59adff", "#4ed9ad", "#c39bff"]);
  card.$("live-travel-path").checked = true;
  card.$("live-cleaning-path").checked = false;
  colors.length = 0;
  card.drawLive((point) => point);
  assert.deepEqual(colors, ["#9eafbf"]);
  card.snapshot.live = null;
  card.drawLive((point) => point);
  assert.equal(legend.hidden, true);
  assert.equal(legend.children.length, 0);
});

test("mission maps retain coverage and separate route segments in the rotated 3D view", () => {
  const geometry = historyGeometry();
  const drawn = [];
  const ctx = {
    fillRect() {}, fill() {},
    beginPath() { this.line = []; },
    moveTo(...point) { this.line.push(point); }, lineTo(...point) { this.line.push(point); },
    stroke(shape) { if (!shape) drawn.push([this.strokeStyle, this.line]); },
    arc() {},
  };
  const canvas = { getContext: () => ctx };
  const view = { zoom: 1, pan: [0, 0], angle: 0, elevated: false };
  sandbox.drawMissionMap(canvas, geometry, view);
  assert.deepEqual(drawn.map(([color]) => color), ["#9eafbf", "#c39bff"]);
  assert.equal(drawn[0][1].length, 2);
  assert.notDeepEqual(drawn[0][1].at(-1), drawn[1][1][0]);
  const initial = drawn.splice(0);
  sandbox.drawMissionMap(canvas, geometry, { ...view, elevated: true, angle: Math.PI / 2 });
  assert.deepEqual(drawn.map(([color]) => color), ["#9eafbf", "#c39bff"]);
  assert.notDeepEqual(drawn[1][1], initial[1][1]);
});

test("the history panel opens the latest report and shows measurements when geometry is missing", async () => {
  const { card } = mockCard(0);
  const mission = { id: "report-a", finished_at: "2026-11-25T10:00:00Z", map_count: 1, duration_minutes: 2,
    outcome: "completed", area_m2: 0.5 };
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.renderAreaResults = () => {};
  card.$("mission-history-dialog").showModal = function () { this.open = true; };
  const calls = [];
  card._hass = { callWS: async (request) => {
    calls.push(request);
    return request.report_id ? { mission, geometry: null, map_index: 0, timeline: [], modes: {}, rooms: [], zones: [] }
      : { missions: [mission] };
  } };
  await card.openMissionHistory();
  assert.equal(calls[0].entity_id, "vacuum.example");
  assert.equal(calls[1].report_id, "report-a");
  assert.equal(card.$("history-no-map").hidden, false);
  assert.equal(card.$("history-map-view").hidden, true);
  assert.equal(card.$("history-totals").textContent, "1 report · 2 min · 0.5 m²");
  assert.ok(card.$("history-measurements").children.length);
});

test("selecting a different mission discards an older archive response", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.$("mission-history-dialog").open = true;
  const render = [];
  const pending = {};
  card.renderMissionReport = (data) => render.push(data);
  card._hass = { callWS: ({ report_id }) => new Promise((resolve) => { pending[report_id] = resolve; }) };
  const earlier = card.loadMissionReport("earlier", 0);
  const later = card.loadMissionReport("later", 1);
  pending.later({ id: "later" });
  await later;
  pending.earlier({ id: "earlier" });
  await earlier;
  assert.deepEqual(render, [{ id: "later" }]);
});

test("mapping can be started without a saved floor after an explicit review", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: null, maps: [], mapping: { can_start: true, activity: null } };
  const calls = [];
  card._hass = { callService: (...args) => calls.push(args) };
  card.refresh = async () => {};
  card.$("mapping-dialog").showModal = function () { this.open = true; };
  card.$("mapping-dialog").close = function () { this.open = false; };
  card.updateMappingControl(card.snapshot.mapping);
  await card.startMapping();
  assert.equal(calls.length, 0);
  card.reviewMapping();
  assert.equal(card.$("mapping-dialog").open, true);
  await card.startMapping();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["roomba_home", "start_mapping", { confirmed: true }, { entity_id: "vacuum.example" }],
  ]);
  assert.equal(card.$("mapping-dialog").open, false);
  card.reviewMapping();
  card.snapshot.mapping.activity = "paused";
  card.updateMappingControl(card.snapshot.mapping);
  await card.startMapping();
  assert.equal(calls.length, 1);
  assert.equal(card.$("review-mapping").hidden, true);
});

test("floor removal rechecks the reviewed revision and sends only one confirmed submission", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  Object.assign(card.snapshot, {
    can_edit_rooms: true,
    map: { id: "floor-test", version: "revision-a" },
    inventory_id: "inventory-a",
    floor_settings: { id: "settings-a", name: "Test floor" },
  });
  const calls = [];
  card._hass = { callWS: (request) => calls.push(request) };
  card.refresh = async () => {};
  const dialog = card.$("remove-floor-dialog");
  dialog.showModal = function () { this.open = true; };
  dialog.close = function () { this.open = false; };
  card.reviewFloorRemoval();
  assert.match(card.$("remove-floor-description").textContent, /Test floor/);
  card.snapshot.map.version = "revision-b";
  card.updateFloorRemoval();
  assert.equal(dialog.open, false);
  await card.removeFloor();
  assert.equal(calls.length, 0);
  card.reviewFloorRemoval();
  await card.removeFloor();
  await card.removeFloor();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{
    type: "roomba_home/remove_floor", entity_id: "vacuum.example", map_id: "floor-test",
    version: "revision-b", inventory_id: "inventory-a", settings_id: "settings-a", confirmed: true,
  }]);
});

test("a clockwise quarter-turn aligns the room, trail, and live heading", () => {
  const { card, lines } = mockCard(-Math.PI / 2);
  card.draw();
  const [start, end] = card.targets[0].path.points;
  close(start[0], end[0]);
  assert.ok(end[1] > start[1]);
  assert.equal(card.targets[0].id, region.id);

  const [[trailStart, trailEnd], [marker, arrow]] = lines;
  close(trailStart[0], trailEnd[0]);
  assert.ok(trailEnd[1] > trailStart[1]);
  assert.deepEqual(trailEnd, marker);
  close(marker[0], arrow[0]);
  close(marker[1] - arrow[1], 18);
});

test("a click on rotated geometry recovers the original native coordinates", () => {
  const { card } = mockCard(-1.76);
  card.draw();
  for (const [index, point] of boundary.entries()) {
    const click = card.targets[0].path.points[index];
    const recovered = card.mapPoint(...click);
    close(recovered[0], point[0]);
    close(recovered[1], point[1]);
  }
});

test("a rotation preview leaves the saved angle and area selections intact", () => {
  const { card } = mockCard(0);
  card.selected.add(region.id);
  card.floorDraft = { operation: "rotate", quarterTurns: 1 };
  card.draw();
  const [start, end] = card.targets[0].path.points;
  assert.ok(end[1] > start[1]);
  assert.equal(card.snapshot.floor_settings.orientation, 0);
  assert.ok(card.selected.has(region.id));
  card.floorDraft = null;
  card.draw();
  const [savedStart, savedEnd] = card.targets[0].path.points;
  close(savedEnd[1], savedStart[1]);
  assert.ok(savedEnd[0] > savedStart[0]);
});

test("two clicks create a restriction in native coordinates on a rotated floor", () => {
  const { card } = mockCard(-Math.PI / 2);
  const status = {};
  card.geometry.editable_restrictions = [];
  card.restrictionDraft = { operation: "create", kind: "no_mop", placing: 0 };
  card.canvas = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) };
  const getElement = card.$.bind(card);
  card.$ = (id) => id === "restriction-edit-status" ? status : getElement(id);
  card.setRestrictionBounds = (bounds) => { card.restrictionDraft.bounds = bounds; };
  card.draw();
  const outline = card.targets[0].path.points;
  card.pick({ clientX: outline[0][0], clientY: outline[0][1] });
  assert.equal(card.restrictionDraft.placing, 1);
  assert.equal(status.textContent, "Select the opposite corner.");
  card.pick({ clientX: outline[2][0], clientY: outline[2][1] });
  assert.equal(card.restrictionDraft.placing, null);
  for (const [index, expected] of [0, 0, 10, 4].entries()) {
    close(card.restrictionDraft.bounds[index], expected);
  }
});

test("room publication keeps an open confirmation valid when the available targets are unchanged", async () => {
  const { card } = mockCard(0);
  const map = { id: "example", version: "version.43" };
  const geometry = { ...card.geometry, selection_id: "visible-rooms-and-zones" };
  let reply = { map, robot: "Robot", maps: [], geometry, inventory_id: "published" };
  const submissions = [];
  const dialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; } };
  const elements = new Map([["confirm-dialog", dialog]]);
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, mockElement());
    return elements.get(id);
  };
  Object.assign(card, {
    isConnected: true,
    config: { entity: "vacuum.example" },
    sequence: 0,
    floor: map.id,
    geometry,
    snapshot: { map, robot: "Robot", maps: [], inventory_id: "before" },
    $: element,
    renderAreas() {},
    renderMissionPlan() {},
    renderAreaResults() {},
    draw() {},
    _hass: {
      callWS: async () => reply,
      callService(...args) { submissions.push(args); },
    },
  });

  card.selected.add(region.id);
  card.review();
  await card.refresh();
  assert.ok(dialog.open);
  assert.ok(card.selected.has(region.id));
  await card.submit();
  assert.equal(submissions.length, 1);
  assert.equal(submissions[0][2].inventory_id, geometry.selection_id);
  assert.equal(submissions[0][2].regions[0], region.id);

  card.selected.add(region.id);
  card.review();
  const roomDraft = { id: map.id, version: map.version };
  const roomDialog = { open: true, close() { this.open = false; } };
  elements.set("room-edit-dialog", roomDialog);
  card.roomDraft = roomDraft;
  reply = {
    ...reply,
    inventory_id: "zone-removed",
    geometry: { ...geometry, selection_id: "updated-targets" },
  };
  await card.refresh();
  assert.ok(!dialog.open);
  assert.equal(card.selected.size, 0);
  assert.equal(card.roomDraft, roomDraft);
  assert.ok(roomDialog.open);

  reply = { ...reply, map: { ...map, version: "version.44" } };
  await card.refresh();
  assert.equal(card.roomDraft, null);
  assert.ok(!roomDialog.open);
});

test("the floor picker follows the live floor and holds an explicit choice or draft", async () => {
  const { card } = mockCard(0);
  const lower = { id: "lower", version: "one" };
  const upper = { id: "upper", version: "two" };
  const maps = [lower, upper];
  const geometry = card.geometry;
  const queries = [];
  const reply = (map) => ({
    robot: "Example",
    map,
    maps,
    inventory_id: "fixture",
    floor_settings: { name: map.id },
    geometry,
  });
  Object.assign(card, {
    isConnected: true,
    config: { entity: "vacuum.example" },
    sequence: 0,
    floor: lower.id,
    snapshot: reply(lower),
    draw() {},
    renderMissionPlan() {},
    renderAreaResults() {},
    _hass: { callWS: async (query) => {
      queries.push(query);
      return reply(maps.find((map) => map.id === query.map_id) ?? upper);
    }},
  });
  await card.refresh();
  assert.equal(queries[0].map_id, undefined);
  assert.equal(queries[0].known_map_id, lower.id);
  assert.equal(card.floor, upper.id);
  assert.equal(card.$("maps").children[0].text, "Follow active floor");
  assert.equal(card.$("floor-name").hidden, false);
  assert.equal(card.$("floor-name").textContent, upper.id);

  card.selectedFloor = lower.id;
  await card.refresh();
  assert.equal(queries[1].map_id, lower.id);
  assert.equal(queries[1].known_map_id, upper.id);
  assert.equal(card.floor, lower.id);

  card.selectedFloor = null;
  card.selected.add(region.id);
  await card.refresh();
  assert.equal(queries[2].map_id, lower.id);
  assert.ok(card.selected.has(region.id));
});

test("a marked point on the rotated 3D map requires confirmation and sends only the reviewed point", async () => {
  const { card } = mockCard(-0.23);
  const submitted = [];
  Object.assign(card, {
    config: { entity: "vacuum.example" },
    elevated: true,
    canvas: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) },
    _hass: { callService(...args) { submitted.push(args); } },
  });
  Object.assign(card.snapshot, {
    robot: "Robot", map: { id: "example", version: "revision" }, can_clean_point: true,
    point_modes: ["vacuum"],
  });
  card.geometry.selection_id = "current-room-inventory";
  card.geometry.presentation = { walls: [{ kind: "exterior", points: boundary }] };
  card.geometry.regions = [
    { ...region, name: "Studio" },
    { ...region, id: "example:zid:zone-a", kind: "zone", name: "Desk" },
  ];
  card.geometry.keep_out = [[[[1, 1], [2, 1], [2, 2], [1, 1]]]];
  let excluded = false;
  card.ctx.isPointInPath = (path) => !card.exclusions.includes(path) || excluded;
  Object.assign(card.dialog, {
    open: false, showModal() { this.open = true; }, close() { this.open = false; },
  });

  card.togglePointMode();
  assert.equal(card.$("regions").hidden, true);
  assert.equal(card.$("point-picker").hidden, false);
  const [clientX, clientY] = card.screenPoint([3, 1]);
  excluded = true;
  card.pick({ clientX, clientY });
  assert.equal(card.point, null);
  assert.equal(card.$("review").disabled, true);
  excluded = false;
  card.pick({ clientX, clientY });
  assert.equal(card.point.id, region.id);
  close(card.point.x, 0.3);
  close(card.point.y, 0.25);
  assert.equal(submitted.length, 0);

  card.review();
  assert.ok(card.dialog.open);
  assert.match(card.$("confirm-text").textContent, /vacuum around the marked point in Studio/);
  card.snapshot.map.version = "new-revision";
  await card.submit();
  assert.equal(submitted.length, 0);
  card.clearSelection();
  assert.equal(card.point, null);
  card.pick({ clientX, clientY });
  card.review();
  await card.submit();
  await card.submit();
  const [[domain, action, payload, target]] = submitted;
  assert.equal(submitted.length, 1);
  assert.equal(domain, "roomba_home");
  assert.equal(action, "clean_point");
  assert.equal(target.entity_id, "vacuum.example");
  assert.equal(payload.region_id, region.id);
  assert.equal(payload.mode, "vacuum");
  assert.equal(payload.review.version, "new-revision");
  assert.equal(payload.review.inventory_id, card.geometry.selection_id);
  close(payload.x, 0.3);
  close(payload.y, 0.25);
});

test("keyboard point placement validates fractions and disables point mode on floors with virtual walls", () => {
  const { card } = mockCard(Math.PI / 2);
  card.snapshot.can_clean_point = true;
  card.snapshot.point_modes = ["vacuum"];
  card.ctx.isPointInPath = () => true;
  card.togglePointMode();
  card.$("point-room").value = region.id;
  card.$("point-x").valueAsNumber = 25;
  card.$("point-y").valueAsNumber = 75;
  card.placePoint();
  close(card.point.native[0], 2.5);
  close(card.point.native[1], 3);
  card.$("point-y").valueAsNumber = 100;
  card.placePoint();
  assert.equal(card.point, null);
  card.geometry.virtual_walls.push([[3, 0], [3, 4]]);
  card.updateSelection();
  assert.equal(card.pointMode, false);
  assert.equal(card.$("point-mode").disabled, true);
});

test("point modes follow robot capabilities and a wet mission cannot target a no-mop zone", async () => {
  const { card } = mockCard(0);
  const submitted = [];
  Object.assign(card, {
    config: { entity: "vacuum.example" },
    canvas: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) },
    _hass: { callService(...args) { submitted.push(args); } },
  });
  Object.assign(card.snapshot, {
    robot: "Robot", map: { id: "example", version: "revision" }, can_clean_point: true,
    point_modes: ["vacuum", "mop"],
  });
  card.geometry.regions = [{ ...region, name: "Studio" }];
  card.geometry.no_mop = [[[boundary[0], [2, 0], [2, 4], [0, 4], boundary[0]]]];
  let inNoMopZone = true;
  card.ctx.isPointInPath = (path) => !card.noMopPaths.includes(path) || inNoMopZone;
  Object.assign(card.dialog, {
    open: false, showModal() { this.open = true; }, close() { this.open = false; },
  });

  card.togglePointMode();
  const selector = card.$("point-cleaning-mode");
  assert.equal(card.$("point-cleaning-settings").hidden, false);
  assert.deepEqual(selector.children.map(({ value }) => value), ["vacuum", "mop"]);
  const [clientX, clientY] = card.screenPoint([1, 1]);
  card.pick({ clientX, clientY });
  card.review();
  card.setPointCleaningMode("vacuum_mop");
  assert.ok(card.dialog.open);
  card.setPointCleaningMode("mop");
  assert.equal(card.dialog.open, false);
  assert.equal(card.point, null);
  await card.submit();
  assert.equal(submitted.length, 0);

  inNoMopZone = false;
  card.pick({ clientX, clientY });
  card.review();
  assert.match(card.$("confirm-text").textContent, /will mop around the marked point/);
  card.snapshot.point_modes = ["vacuum"];
  await card.submit();
  assert.equal(submitted.length, 0);
  card.updateSelection();
  assert.equal(card.dialog.open, false);
  assert.equal(card.pointCleaningMode, "vacuum");
  assert.equal(card.point, null);

  card.snapshot.point_modes = ["vacuum", "mop"];
  card.updateSelection();
  card.setPointCleaningMode("mop");
  card.pick({ clientX, clientY });
  card.review();
  await card.submit();
  assert.equal(submitted[0][2].mode, "mop");

  card.snapshot.point_modes = ["vacuum_mop", "vacuum_then_mop"];
  card.updateSelection();
  assert.deepEqual(selector.children.map(({ text }) => text), ["Vacuum and mop", "Vacuum then mop"]);
  for (const [mode, label] of [
    ["vacuum_mop", "vacuum and mop"],
    ["vacuum_then_mop", "vacuum then mop"],
  ]) {
    card.setPointCleaningMode(mode);
    card.pick({ clientX, clientY });
    card.review();
    assert.equal(card.$("confirm-text").textContent, `Robot will ${label} around the marked point in Studio.`);
    await card.submit();
    assert.equal(submitted.at(-1)[2].mode, mode);
  }
});

test("the live point marker follows the floor projection and expires", () => {
  const { card } = mockCard(-0.66);
  const point = [7, 2];
  card.snapshot.active_point = { center: point, mode: "mop", expires_at: Date.now() / 1000 + 30 };
  const markers = [];
  card.drawPointMarker = (screen) => markers.push(screen);
  card.draw();
  assert.equal(card.$("point-key").hidden, false);
  assert.equal(card.$("point-key").textContent, "Mop point");
  assert.deepEqual(markers, [card.screenPoint(point)]);
  card.snapshot.active_point.expires_at = Date.now() / 1000 - 1;
  card.draw();
  assert.equal(card.$("point-key").hidden, true);
  assert.equal(markers.length, 1);
});

test("merge selects two adjacent rooms on the map before reviewing or saving", async () => {
  const { card } = mockCard(0);
  const adjacent = { id: "example:rid:room-b", kind: "room", polygons: [[boundary.map(
    ([x, y]) => [x + 10, y],
  )]] };
  const distant = { id: "example:rid:room-c", kind: "room", polygons: [[boundary.map(
    ([x, y]) => [x + 30, y],
  )]] };
  card.geometry.regions.push(adjacent, distant);
  card.geometry.editable_rooms = [
    { id: "room-a", name: "Office", adjacent: ["room-b"] },
    { id: "room-b", name: "Kitchen", adjacent: ["room-a"] },
    { id: "room-c", name: "Hall", adjacent: [] },
  ];
  card.snapshot = { robot: "Robot", inventory_id: "published", floor_settings: { orientation: 0 } };
  const select = () => ({
    value: "", options: [],
    replaceChildren(...options) { this.options = options; this.value = options[0]?.value ?? ""; },
  });
  const dialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; } };
  const elements = new Map([
    ["edit-room-first", select()],
    ["edit-room-second", select()],
    ["room-operation", { value: "merge" }],
    ["room-edit-dialog", dialog],
  ]);
  const sent = [];
  Object.assign(card, {
    $(id) {
      if (!elements.has(id)) elements.set(id, mockElement());
      return elements.get(id);
    },
    roomDraft: { id: "example", version: "revision.1" },
    dividerFields: Array.from({ length: 4 }, () => ({ valueAsNumber: NaN })),
    canvas: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) },
    config: { entity: "vacuum.example" },
    _hass: { async callWS(request) { sent.push(request); } },
    async refresh() {},
  });
  card.ctx.isPointInPath = (path, x) =>
    Math.min(...path.points.map(([column]) => column)) < x &&
    Math.max(...path.points.map(([column]) => column)) > x;
  const click = (regionId) => {
    const points = card.targets.find(({ id }) => id === regionId).path.points;
    card.pick({ clientX: (points[0][0] + points[2][0]) / 2, clientY: points[0][1] });
  };

  card.renderRoomEditor();
  assert.equal(elements.get("review-room-edit").disabled, true);
  click(region.id);
  click(distant.id);
  assert.equal(elements.get("edit-room-first").value, "room-a");
  assert.equal(elements.get("review-room-edit").disabled, true);
  click(adjacent.id);
  assert.equal(elements.get("review-room-edit").disabled, false);
  card.reviewRoomEdit();
  assert.ok(dialog.open);
  assert.equal(elements.get("room-edit-description").textContent, "Merge Office and Kitchen on Robot's map?");
  assert.equal(sent.length, 0);
  await card.saveRoomEdit();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].type, "roomba_home/edit_rooms");
  assert.equal(sent[0].inventory_id, "published");
  assert.equal(sent[0].room_ids.join(","), "room-a,room-b");
  assert.equal(card.roomDraft, null);
});

test("furniture placement uses native coordinates and sends the reviewed pose", async () => {
  const { card, lines } = mockCard(-Math.PI / 2);
  const pending = { id: "example", version: "revision.3", inventoryId: "inventory",
    operation: "create", placing: true };
  const dialog = { open: false, showModal() { this.open = true; }, close() { this.open = false; } };
  const elements = new Map([
    ["furniture-edit-dialog", dialog],
    ["furniture-kind", { value: "chair/living" }],
  ]);
  const outgoing = [];
  Object.assign(card, {
    geometry: { ...card.geometry, furniture: { types: { "chair/living": "Chair" }, items: [] } },
    canvas: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) },
    furnitureDraft: pending,
    furnitureFields: ["", "", 2, 1, 90].map((value) => ({
      value,
      get valueAsNumber() { return this.value === "" ? NaN : Number(this.value); },
    })),
    config: { entity: "vacuum.example" },
    floor: "example",
    $(id) {
      if (!elements.has(id)) elements.set(id, mockElement());
      return elements.get(id);
    },
    drawLive() {},
    async refresh() {},
    _hass: { async callWS(request) { outgoing.push(request); } },
  });
  card.draw();
  const ring = card.targets[0].path.points;
  card.pick({ clientX: (ring[0][0] + ring[2][0]) / 2, clientY: (ring[0][1] + ring[2][1]) / 2 });
  assert.equal(pending.placing, false);
  for (const [index, expected] of [5, 2, 2, 1, 90].entries()) close(pending.pose[index], expected);
  const [start, stop] = lines.at(-1);
  close(start[1], stop[1]);
  assert.ok(stop[0] > start[0]);
  card.reviewFurnitureEdit();
  assert.ok(dialog.open);
  assert.equal(outgoing.length, 0);
  await card.saveFurnitureEdit();
  assert.equal(outgoing.length, 1);
  const [request] = outgoing;
  assert.equal(request.type, "roomba_home/edit_furniture");
  assert.equal(request.kind, "chair/living");
  assert.equal(request.version, "revision.3");
  close(request.pose[0], 5);
  assert.equal(card.furnitureDraft, null);
});

test("3D view aligns room hits, dock, furniture, carpet, and live track through the camera", () => {
  const { card, lines, fills } = mockCard(-0.22);
  card.geometry.presentation = {
    walls: [
      { kind: "exterior", points: boundary },
      { kind: "door", points: [[0, 0], [1, 0]] },
    ],
    carpets: [[[[4, 1], [5, 1], [5, 2], [4, 1]]]],
    docks: [[4, 1]],
  };
  card.geometry.furniture = { items: [{ kind: "sofa", points: [[2, 1], [3, 1], [3, 2], [2, 2]] }] };
  card.elevated = true;
  card.draw();
  assert.equal(card.$("show-3d")["aria-pressed"], "true");
  assert.equal(card.$("orbit-map").hidden, false);
  assert.equal(card.$("carpet-key").hidden, false);
  assert.equal(card.$("dock-key").hidden, false);
  assert.ok(fills.some(([fill]) => fill === "#7d9aaf"));
  const [room] = card.targets;
  const [firstCorner] = room.path.points;
  assert.equal(room.id, region.id);
  card.mapPoint(...firstCorner).forEach((value) => close(value, 0));
  const [[, trailEnd], [robot, heading]] = lines;
  const [, [dockX, dockY, width, height]] = fills.find(([fill]) => fill === "#7dd9e4");
  close(dockX + width / 2, robot[0]);
  close(dockY + height / 2, robot[1]);
  assert.deepEqual(robot, trailEnd);
  close(Math.hypot(heading[0] - robot[0], heading[1] - robot[1]), 18);

  card.orbit = 1;
  card.furnitureShown = false;
  fills.length = 0;
  card.draw();
  assert.notDeepEqual(card.targets[0].path.points[0], firstCorner);
  assert.ok(!fills.some(([fill]) => fill === "#7d9aaf"));
  assert.equal(card.$("show-furniture")["aria-pressed"], "false");
  assert.equal(card.snapshot.floor_settings.orientation, -0.22);
});

test("editing temporarily uses the flat map and unsupported geometry keeps the 3D toggle hidden", () => {
  const { card } = mockCard(0);
  card.geometry.presentation = { walls: [{ kind: "door", points: [[0, 0], [1, 0]] }] };
  card.elevated = true;
  card.draw();
  const flat = card.targets[0].path.points;
  assert.equal(card.$("show-3d").hidden, true);
  card.geometry.presentation.walls.push({ kind: "interior", points: [[2, 1], [2, 4]] });
  card.roomDraft = { id: "example", operation: "merge" };
  card.draw();
  assert.equal(card.$("show-3d").disabled, true);
  assert.equal(card.$("show-3d")["aria-pressed"], "false");
  assert.deepEqual(card.targets[0].path.points, flat);
  card.roomDraft = null;
  card.draw();
  assert.equal(card.$("show-3d").disabled, false);
  assert.equal(card.$("show-3d")["aria-pressed"], "true");
  assert.notDeepEqual(card.targets[0].path.points, flat);
});

test("a saved furniture routine shows its order and requires a fresh confirmation to run", async () => {
  const { card } = mockCard(0);
  const sofa = { id: "example:furniture:1", name: "Sofa" };
  const chair = { id: "example:furniture:2", name: "Chair" };
  const map = { id: "example", version: "revision.1" };
  const calls = [];
  const elements = new Map([
    ["run-routine", { textContent: "Run saved routine" }],
    ["routine-dialog", { open: false, showModal() { this.open = true; } }],
  ]);
  const saved = { id: "test-identity", name: "Around the furniture",
    region_settings: [{ id: chair.id }, { id: sofa.id }] };
  Object.assign(card, {
    geometry: { regions: [], selection_id: "stable", furniture: { destinations: [sofa, chair] } },
    snapshot: { map, inventory_id: "inventory" },
    config: { entity: "vacuum.example" },
    editRoutine() { this.routineDraft = { saved }; },
    renderRoutine() {},
    async callAction() { return { routines: [saved] }; },
    _hass: { async callService(...args) { calls.push(args); } },
    $(id) {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
  });
  await card.openRoutines();
  assert.equal(card.routineAreas.get(sofa.id), "Sofa");
  await card.runRoutine();
  assert.equal(elements.get("routine-status").textContent, "Start Around the furniture: Chair → Sofa?");
  assert.equal(calls.length, 0);
  card.snapshot.map = { ...map, version: "revision.2" };
  await card.runRoutine();
  assert.equal(calls.length, 0);
  card.snapshot.map = map;
  card.snapshot.inventory_id = "updated inventory";
  await card.runRoutine();
  assert.equal(calls.length, 0);
  assert.equal(elements.get("routine-status").textContent, "Start Around the furniture: Chair → Sofa?");
  await card.runRoutine();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], "run_cleaning_routine");
  assert.equal(calls[0][2].routine_id, saved.id);
});

test("skipping an area requires confirmation and discards a changed destination", async () => {
  const { card } = mockCard(0);
  const elements = new Map([
    ["skip-dialog", {
      open: false,
      showModal() { this.open = true; },
      close() { this.open = false; },
    }],
  ]);
  const calls = [];
  Object.assign(card, {
    snapshot: { robot: "Example robot", skip_review: "first" },
    config: { entity: "vacuum.example" },
    _hass: { async callService(...args) { calls.push(args); } },
    async refresh() {},
    $(id) {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
  });
  card.reviewSkip();
  assert.equal(elements.get("skip-dialog").open, true);
  assert.equal(calls.length, 0);
  card.snapshot.skip_review = "second";
  card.updateSkipControl("second");
  assert.equal(elements.get("skip-dialog").open, false);
  await card.skipArea();
  assert.equal(calls.length, 0);
  card.reviewSkip();
  await card.skipArea();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1], "skip_current_area");
  assert.equal(calls[0][2].review_id, "second");
  assert.equal(calls[0][3].entity_id, "vacuum.example");
  assert.equal(card.operationMessage, "Roomba confirmed the area was skipped.");
  assert.equal(elements.get("status").textContent, card.operationMessage);
});

test("last mission results name furniture and keep separately reported zone metrics", () => {
  const { card } = mockCard(0);
  const element = () => ({ children: [], append(...items) { this.children.push(...items); } });
  const rows = { ...element(), replaceChildren() { this.children = []; } };
  const details = { dataset: {}, querySelector: () => rows };
  card.$ = () => details;
  const createElement = sandbox.document.createElement;
  sandbox.document.createElement = element;
  try {
    card.renderAreaResults("history", [
      { kind: "furniture", name: "Sofa", status: "finished", area: 8, total_area: 10, pass_count: 0 },
      { kind: "temporary_zone", name: null, status: null, area: null, total_area: null, pass_count: null },
    ], "Unknown outcome");
    assert.equal(details.hidden, false);
    assert.deepEqual(rows.children.map((row) => row.children.map((child) => child.textContent)), [
      ["Sofa", "finished", "Passes 0 · Reported area 8 / 10"],
      ["Temporary zone 2", "Unknown outcome", ""],
    ]);
  } finally {
    sandbox.document.createElement = createElement;
  }
});

test("live plans show real destination counts, preserve order and disappear when unavailable", () => {
  const { card } = mockCard(0);
  const plan = {
    ordered: true, completed: 1, total: 3,
    destinations: [
      { kind: "furniture", name: "Sofá", status: "finished" },
      { kind: "room", name: "Cocina", status: "traveling", mode: "vacuum" },
      { kind: "temporary_zone", name: null, status: "skipped_will_return" },
    ],
  };
  const view = card.$("mission-plan");
  const summary = mockElement("summary");
  const results = mockElement("div");
  view.append(summary, results);
  card.renderMissionPlan(plan);
  assert.equal(view.hidden, false);
  assert.equal(summary.textContent, "Planned order · 1 of 3 completed");
  assert.equal(results.children[0].tag, "ol");
  assert.deepEqual(results.children[0].children.map((item) =>
    item.children[0].children.map((text) => text.textContent)), [
    ["Sofá", "Completed"], ["Cocina", "Vacuum · On the way"], ["Temporary zone", "Skipped, will return"],
  ]);
  const list = results.children[0];
  card.renderMissionPlan(plan);
  assert.equal(results.children[0], list);
  card.renderMissionPlan({ ...plan, ordered: false });
  assert.equal(summary.textContent, "Selected destinations · 1 of 3 completed");
  assert.equal(results.children[0].tag, "ul");
  card.renderMissionPlan({
    ...plan, estimated_remaining_seconds: 401,
    destinations: plan.destinations.map((destination) => destination.kind === "room" ?
      { ...destination, estimated_duration_seconds: 502 } : destination),
  });
  assert.equal(summary.textContent, "Planned order · 1 of 3 completed · About 7 min left");
  assert.equal(results.children[0].children[1].children[0].children[1].textContent,
    "Vacuum · On the way · 9 min planned");
  card.renderMissionPlan(null);
  assert.equal(view.hidden, true);
  assert.equal(results.children.length, 0);
});

test("live position updates use stream deltas and animate only adjacent samples", () => {
  const { card } = mockCard(0);
  let draws = 0;
  let frame;
  sandbox.performance = { now: () => 1000 };
  sandbox.window.requestAnimationFrame = (callback) => { frame = callback; return 4; };
  sandbox.window.cancelAnimationFrame = () => { frame = null; };
  card.draw = () => { draws++; };
  const stream = card.liveStream = {};
  const from = { index: 10, timestamp: 20, x: 0, y: 0, orientation: 3.1, expires_at: 35 };
  const to = { index: 11, timestamp: 21, x: 0.5, y: 0, orientation: -3.1, expires_at: 35 };
  card.receiveLivePositions(stream, { reset: true, trail: [[10, 0, 0, "vacuuming"]], position: from });
  card.receiveLivePositions(stream, { reset: false, trail: [[11, 0.5, 0, "mopping"]], position: to });
  assert.equal(draws, 2);
  assert.equal(card.liveMarker(to, 1500).x, 0.25);
  assert.ok(Math.abs(card.liveMarker(to, 1500).orientation - Math.PI) < 0.0001);
  assert.equal(stream.reading.trail.length, 2);
  card.receiveLivePositions(stream, {
    reset: false, trail: [], position: { ...to }, obstacles: [[2, 4]],
  });
  assert.equal(draws, 3);
  assert.equal(card.liveMarker(stream.reading.position, 1500).x, 0.25);
  frame(2010);
  assert.equal(card.liveMarker(to, 2010), to);

  const gap = { ...to, index: 14, timestamp: 25, x: 1 };
  card.receiveLivePositions(stream, { reset: false, trail: [[14, 1, 0, "mopping"]], position: gap });
  assert.equal(card.liveMarker(gap, 1400), gap);
  card.receiveLivePositions(stream, { reset: false, trail: [[12, 0.7, 0, "mopping"]], position: gap });
  assert.equal(stream.reading.trail.map(([index]) => index).join(","), "10,11,12,14");
  assert.equal(stream.reading.obstacles.length, 1);
  card.receiveLivePositions(stream, { reset: false, trail: [], position: gap, obstacles: [] });
  assert.equal(stream.reading.obstacles.length, 0);
  card.receiveLivePositions(stream, { reset: true, trail: [], position: null });
  assert.equal(stream.reading.trail.length, 0);
  assert.equal(stream.reading.obstacles, undefined);
  card.closeLiveSubscription();
  card.receiveLivePositions(stream, { reset: true, trail: [], position: from });
  assert.equal(card.liveStream, null);
});

test("temporary obstacles use the current map projection and an independent toggle", () => {
  const { card, lines } = mockCard(0);
  const colors = [];
  card.ctx.closePath = () => {};
  card.ctx.fill = function () { colors.push(this.fillStyle); };
  card.ctx.stroke = () => {};
  card.$("live-obstacles").checked = true;
  card.$("live-cleaning-path").checked = false;
  card.$("live-travel-path").checked = false;
  card.snapshot.live = { trail: [], obstacles: [[3, 5]], position: null };
  const project = ([x, y]) => [y * 2, -x * 2];
  card.drawLive(project);
  assert.equal(card.$("live-obstacle-controls").hidden, false);
  assert.deepEqual(colors, ["#ffad55"]);
  assert.deepEqual(JSON.parse(JSON.stringify(lines)), [
    [[10, -13], [17, -1]], [[17, -1], [3, -1]],
  ]);
  card.$("live-obstacles").checked = false;
  card.drawLive(project);
  assert.deepEqual(colors, ["#ffad55"]);
  assert.equal(card.$("live-obstacle-controls").hidden, false);
  card.snapshot.live.obstacles = [];
  card.drawLive(project);
  assert.equal(card.$("live-obstacle-controls").hidden, true);
});

test("live animation follows the consecutive positions inside a batch", () => {
  const { card } = mockCard(0);
  card.draw = () => {};
  sandbox.performance = { now: () => 1000 };
  sandbox.window.requestAnimationFrame = () => 4;
  const stream = card.liveStream = {};
  const from = { index: 10, timestamp: 20, x: 0, y: 0, orientation: 0, expires_at: 35 };
  const to = { ...from, index: 13, timestamp: 22, x: 0.8, y: 0.4 };
  card.receiveLivePositions(stream, { reset: true, trail: [], position: from });
  card.receiveLivePositions(stream, {
    reset: false, trail: [[11, 0.4, 0, "vacuuming"], [12, 0.4, 0.4, "vacuuming"]], position: to,
  });
  const marker = card.liveMarker(to, 1450);
  assert.ok(Math.abs(marker.x - 0.3) < 0.0001);
  assert.equal(marker.y, 0);
  assert.equal(card.positionTransition(from, to, new Map([[11, [11, 3, 0]]])), null);
  const stationary = { ...from, index: 11, timestamp: 21, orientation: 1 };
  card.liveTween = card.positionTransition(from, stationary, new Map());
  assert.equal(card.liveMarker(stationary, 1500).x, 0);
  assert.equal(card.liveMarker(stationary, 1500).orientation, 0.5);
});

test("live movement uses late consecutive samples and keeps unobserved gaps visible", () => {
  const { card } = mockCard(0);
  sandbox.performance = { now: () => 1000 };
  const observed = new Map([[11, [11, 0.4, 0, "vacuuming"]]]);
  const from = { index: 10, timestamp: 20, x: 0, y: 0, orientation: 0 };
  const to = { ...from, index: 12, timestamp: 26, x: 0.4, y: 0.4 };
  card.liveTween = card.positionTransition(from, to, observed);
  assert.equal(card.liveTween.duration, 1800);
  assert.equal(card.liveMarker(to, 1900).x, 0.4);
  assert.equal(card.liveMarker(to, 1900).y, 0);
  assert.equal(card.positionTransition(from, to, new Map()), null);
  assert.equal(card.positionTransition(from, { ...to, timestamp: 27 }, observed), null);
  assert.equal(card.positionTransition(from, { ...to, x: 8 }, observed), null);
});

test("a position arriving mid-animation continues from the visible marker through the reported turn", () => {
  const { card } = mockCard(0);
  card.draw = () => {};
  let now = 1000;
  sandbox.performance = { now: () => now };
  sandbox.window.requestAnimationFrame = () => 4;
  const stream = card.liveStream = {};
  const first = { index: 10, timestamp: 20, x: 0, y: 0, orientation: 0, expires_at: 35 };
  const second = { ...first, index: 11, timestamp: 21, x: 0.4, orientation: 1 };
  const third = { ...second, index: 12, timestamp: 22, y: 0.4, orientation: 2 };
  card.receiveLivePositions(stream, { reset: true, trail: [], position: first });
  card.receiveLivePositions(stream, { reset: false, trail: [], position: second });
  now = 1500;
  const visible = card.liveMarker(second, now);
  card.receiveLivePositions(stream, { reset: false, trail: [], position: third });
  const continued = card.liveMarker(third, now);
  assert.equal(continued.x, visible.x);
  assert.equal(continued.y, visible.y);
  assert.equal(continued.orientation, visible.orientation);
  assert.equal(card.liveMarker(third, 1750).y, 0);
  assert.equal(card.liveMarker(third, 2250).x, 0.4);
  assert.ok(Math.abs(card.liveMarker(third, 2250).y - 0.25) < 0.0001);
  assert.equal(card.liveMarker(third, 2500).y, 0.4);
});

test("switching floors releases the old live subscription", async () => {
  const { card } = mockCard(0);
  const received = [];
  const closed = [];
  card.config = { entity: "vacuum.example" };
  card._hass = { connection: { subscribeMessage: async (callback, request) => {
    received.push([callback, request]);
    return async () => { closed.push(request.version); };
  } } };
  card.updateLiveSubscription({ id: "floor", version: "a" });
  card.updateLiveSubscription({ id: "floor", version: "a" });
  card.updateLiveSubscription({ id: "floor", version: "b" });
  await Promise.resolve();
  assert.equal(received.length, 2);
  assert.equal(closed.join(","), "a");
  card.closeLiveSubscription();
  assert.equal(closed.join(","), "a,b");
});

test("live coverage keeps unmodified rows, separates modes and clears with the mission", () => {
  const { card } = mockCard(0);
  const drawn = [];
  card.draw = () => {};
  card.ctx = {
    save() {},
    restore() {},
    clip(path, rule) { drawn.push([rule, path.points.length]); },
    fill(path) { drawn.push([this.fillStyle, path.points]); },
  };
  card.$("coverage-vacuum").checked = true;
  card.$("coverage-mop").checked = true;
  const stream = card.liveStream = {};
  card.receiveLivePositions(stream, {
    reset: true, position: null, trail: [],
    coverage: { cell_size: 0.25, rows: [[1, [[1, 3, 1], [4, 5, 2]]]] },
  });
  card.receiveLivePositions(stream, {
    reset: false, position: null, trail: [],
    coverage: { cell_size: 0.25, rows: [[7, [[1, 3, 3]]]] },
  });
  card.drawLiveCoverage(([x, y]) => [x, y], [region]);
  assert.equal(card.$("live-coverage-controls").hidden, false);
  assert.deepEqual(drawn.shift(), ["evenodd", boundary.length]);
  assert.equal(drawn.length, 3);
  assert.ok(drawn.every(([, points]) => points.length === 4));
  assert.deepEqual(drawn[0][1][0], [0.25, 0.25]);
  assert.deepEqual(drawn[2][1][0], [0.25, 1.75]);
  card.$("coverage-vacuum").checked = false;
  drawn.length = 0;
  card.drawLiveCoverage(([x, y]) => [x, y], [region]);
  assert.equal(drawn[1][1].length, 0);
  assert.equal(drawn[2][1].length, 8);
  assert.equal(drawn[3][1].length, 0);

  card.receiveLivePositions(stream, {
    reset: false, position: null, trail: [],
    coverage: { cell_size: 0.25, rows: [[1, [[1, 5, 3]]]] },
  });
  assert.equal(stream.reading.coverage.rows.length, 2);
  assert.equal(stream.reading.coverage.rows[0][1].length, 1);
  card.receiveLivePositions(stream, { reset: true, position: null, trail: [] });
  assert.equal(stream.reading.coverage, undefined);
});
