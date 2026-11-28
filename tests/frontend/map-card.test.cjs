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
  window: { setInterval: () => 1 },
  HTMLElement: class {},
  Path2D: Path,
};
const source = readFileSync(resolve(__dirname,
  "../../custom_components/roomba_home/frontend/roomba-home-map-card.js"), "utf8");
runInNewContext(`${source}
globalThis.card = RoombaHomeMapCard.prototype;
globalThis.drawMissionMap = drawMissionMap;
globalThis.mapNavigation = { bindMapNavigation, WIDTH, HEIGHT };
`, sandbox);

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

function navigationFixture({ panAtFit = false, elevated = false, maxZoom = 4 } = {}) {
  const { bindMapNavigation, WIDTH, HEIGHT } = sandbox.mapNavigation;
  const view = { map: {}, zoom: 1, pan: [0, 0], elevated };
  const selections = [];
  const listeners = new Map();
  const canvas = {
    getBoundingClientRect: () => ({ left: 10, top: 20, width: WIDTH / 2, height: HEIGHT / 2 }),
    setPointerCapture() {},
    addEventListener(type, handler, options) { listeners.set(type, { handler, options }); },
  };
  bindMapNavigation(canvas, {
    viewport: () => view,
    update: (zoom, pan) => Object.assign(view, { zoom, pan: [...pan] }),
    select: (event) => selections.push(event.pointerId),
    maxZoom,
    panAtFit,
  });
  const pointer = (action, pointerId, x, y) =>
    canvas[`onpointer${action}`]({ pointerId, button: 0, clientX: x + 10, clientY: y + 20 });
  return { canvas, view, pointer, selections, listeners, WIDTH, HEIGHT };
}

test("a single touch can scroll the dashboard at fit without selecting a dragged floor area", () => {
  const { pointer, view, selections, listeners } = navigationFixture();
  pointer("down", 1, 30, 30);
  pointer("move", 1, 75, 100);
  pointer("up", 1, 75, 100);
  assert.deepEqual(view.pan, [0, 0]);
  assert.deepEqual(selections, []);

  const { handler, options } = listeners.get("touchstart");
  assert.equal(options.passive, false);
  let prevented = 0;
  const preventDefault = () => { prevented++; };
  handler({ targetTouches: [{}], cancelable: true, preventDefault });
  handler({ targetTouches: [{}, {}], cancelable: false, preventDefault });
  handler({ targetTouches: [{}, {}], cancelable: true, preventDefault });
  assert.equal(prevented, 1);

  pointer("down", 2, 30, 30);
  pointer("up", 2, 65, 30);
  assert.deepEqual(selections, []);
  pointer("down", 3, 31, 30);
  pointer("up", 3, 32, 30);
  assert.deepEqual(selections, [3]);
});

test("the 3D view pans at fit by drag or arrow keys without changing the zoom", () => {
  const { canvas, pointer, view, selections } = navigationFixture({ elevated: true });
  pointer("down", 1, 30, 30);
  pointer("move", 1, 60, 50);
  pointer("up", 1, 60, 50);
  assert.deepEqual(view.pan, [60, 40]);
  assert.deepEqual(selections, []);

  let prevented = 0;
  const preventDefault = () => { prevented++; };
  canvas.onkeydown({ key: "ArrowUp", preventDefault });
  canvas.onkeydown({ key: "ArrowDown", altKey: true, preventDefault });
  assert.deepEqual(view.pan, [60, 88]);
  assert.equal(view.zoom, 1);
  assert.equal(prevented, 1);
});

test("a pinch follows the moving midpoint and a remaining finger continues panning", () => {
  const { pointer, view, selections, WIDTH, HEIGHT } = navigationFixture();
  pointer("down", 1, 100, 100);
  pointer("down", 2, 200, 100);
  pointer("move", 2, 300, 100);
  const pinched = [WIDTH / 2 - 200, HEIGHT / 2 - 200];
  assert.equal(view.zoom, 2);
  assert.deepEqual(view.pan, pinched);

  pointer("up", 2, 300, 100);
  pointer("move", 1, 110, 108);
  pointer("up", 1, 110, 108);
  assert.deepEqual(view.pan, [pinched[0] + 20, pinched[1] + 16]);
  assert.deepEqual(selections, []);
});

test("the report viewport keeps its drag at fit, bounds a pinch, and drops old-map pointers", () => {
  const { canvas, pointer, view, selections, WIDTH, HEIGHT } =
    navigationFixture({ panAtFit: true, maxZoom: 8 });
  pointer("down", 1, 20, 20);
  pointer("move", 1, 35, 40);
  pointer("up", 1, 35, 40);
  assert.deepEqual(view.pan, [30, 40]);

  pointer("down", 1, 100, 100);
  pointer("down", 2, 120, 100);
  pointer("move", 2, 380, 100);
  assert.equal(view.zoom, 8);
  assert.ok(Math.abs(view.pan[0]) <= WIDTH * 4 && Math.abs(view.pan[1]) <= HEIGHT * 4);
  canvas.onlostpointercapture({ pointerId: 2 });
  view.map = {};
  const previous = view.pan;
  pointer("move", 1, 180, 125);
  pointer("up", 1, 180, 125);
  assert.equal(view.pan, previous);
  assert.deepEqual(selections, []);
});

function maintenanceCard() {
  const { card } = mockCard(0);
  const dialog = card.$("maintenance-dialog");
  dialog.open = false;
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  card.maintenanceSequence = 0;
  card.config = { entity: "vacuum.example" };
  return { card, dialog };
}

test("maintenance shows provider links, zero, and a dust bag with no counter", async () => {
  const { card, dialog } = maintenanceCard();
  const shop = "https://www.irobot.es/es_ES/4849916.html";
  const guide = "https://prod-help-content.care.irobotapi.com/web/es/70517.html";
  card._hass = {
    callWS: async (request) => {
      assert.deepEqual({ ...request }, { type: "roomba_home/maintenance", entity_id: "vacuum.example" });
      return { robot: "Roomba", counters_available: true, parts: [
        { part: "dust_bag", part_sku: "4849916", replacement_url: shop },
        { part: "filter", usage: 0, remaining: 10, count_type: "minutes" },
        { part: "dock_washing_system", maintenance_guide_url: guide },
      ] };
    },
  };
  await card.openMaintenance();
  assert.equal(dialog.open, true);
  assert.equal(card.$("maintenance-title").textContent, "Roomba maintenance");
  assert.equal(card.$("maintenance-status").textContent, "");
  const [bag, filter, washer] = card.$("maintenance-parts").children;
  assert.deepEqual(bag.children.map(({ textContent }) => textContent), ["Dust bag", "Part 4849916", "iRobot shop"]);
  const shopLink = bag.querySelector("a");
  assert.equal(shopLink.href, shop);
  assert.equal(shopLink.target, "_blank");
  assert.equal(shopLink.rel, "noopener noreferrer");
  assert.equal(shopLink["aria-label"], "iRobot shop for dust bag");
  assert.equal(filter.querySelector("p").textContent, "0% used · 10 min remaining");
  assert.equal(filter.querySelector("meter").value, 0);
  assert.equal(bag.querySelector("meter"), undefined);
  assert.equal(washer.querySelector("a").href, guide);
});

test("maintenance displays signed usage, native hours and part guidance", async () => {
  const { card } = maintenanceCard();
  const guide = "https://homesupport.irobot.com/articles/en_US/Knowledge/70505";
  card._hass = { callWS: async () => ({ robot: "Roomba", counters_available: true, parts: [
    { part: "filter", usage: 20, remaining: 125, count_type: "minutes",
      part_description: "The filter traps fine debris.", maintenance_guide_url: guide },
    { part: "mop_roller", usage: 100, remaining: 0, count_type: "combo_missions" },
    { part: "dust_bag", remaining: 80, count_type: "fixture" },
  ] }) };
  await card.openMaintenance();
  const [filter, roller, bag] = card.$("maintenance-parts").children;
  assert.equal(filter.querySelector("p").textContent, "20% used · 2 h remaining");
  assert.equal(filter.querySelector("p").title, "125 min remaining");
  const meter = filter.querySelector("meter");
  assert.equal(meter.max, 100);
  assert.equal(meter.value, 20);
  assert.equal(meter["aria-label"], "Filter usage");
  const guidance = filter.querySelector("details");
  assert.equal(guidance.querySelector("summary").textContent, "About this part");
  assert.equal(guidance.querySelector("p").textContent, "The filter traps fine debris.");
  assert.equal(filter.querySelector("a").href, guide);
  assert.equal(roller.querySelector("meter").value, 100);
  assert.equal(roller.querySelector("p").textContent, "100% used · 0 combo missions remaining");
  assert.equal(roller.querySelector("details"), undefined);
  assert.equal(bag.querySelector("p"), undefined);
});

test("maintenance ignores a reply after closing and reopening on a different robot", async () => {
  const { card, dialog } = maintenanceCard();
  let complete;
  card._hass = { callWS: () => new Promise((resolve) => { complete = resolve; }) };
  const old = card.openMaintenance();
  dialog.close();
  card.config.entity = "vacuum.next";
  card._hass.callWS = async () => ({ robot: "Other", parts: [], counters_available: false });
  await card.openMaintenance();
  complete({ robot: "Original", parts: [{ part: "filter" }], counters_available: true });
  await old;
  assert.equal(card.$("maintenance-title").textContent, "Other maintenance");
  assert.equal(card.$("maintenance-status").textContent, "Roomba has no maintenance details for this robot.");
  assert.deepEqual(card.$("maintenance-parts").children, []);
  dialog.close();
  card._hass.callWS = async () => { throw Error("Could not read Roomba"); };
  await card.openMaintenance();
  assert.equal(card.$("maintenance-status").textContent, "Could not read Roomba");
});

test("maintenance reviews one counter, sends once, and rereads after confirmation", async () => {
  const { card, dialog } = maintenanceCard();
  const calls = [];
  let finish;
  let count = 38;
  card._hass = {
    callWS: async () => ({ robot: "Roomba", counters_available: true, parts: [
      { part: "filter", usage: count, can_reset: true },
      { part: "dust_bag", part_sku: "4849916", can_reset: false },
    ] }),
    callService: (...request) => {
      calls.push(request);
      return new Promise((resolve) => { finish = resolve; });
    },
  };
  await card.openMaintenance();
  const [filter, bag] = card.$("maintenance-parts").children;
  const opener = filter.querySelector("button");
  assert.equal(opener["aria-label"], "Reset filter counter");
  assert.equal(bag.querySelector("button"), undefined);
  opener.onclick();
  assert.equal(card.$("maintenance-parts").hidden, true);
  assert.equal(card.$("maintenance-reset-review").hidden, false);
  assert.equal(card.$("maintenance-reset-prompt").textContent,
    "Reset the filter counter after completing maintenance?");
  assert.equal(card.$("back-maintenance-reset").focused, true);
  card.backFromMaintenanceReset();
  assert.equal(card.$("maintenance-parts").hidden, false);
  assert.equal(opener.focused, true);
  await card.confirmMaintenanceReset();
  assert.deepEqual(calls, []);

  opener.onclick();
  const reset = card.confirmMaintenanceReset();
  assert.equal(card.$("confirm-maintenance-reset").disabled, true);
  assert.equal(card.$("back-maintenance-reset").disabled, true);
  assert.equal(card.$("close-maintenance").disabled, true);
  card.backFromMaintenanceReset();
  assert.equal(card.$("maintenance-reset-review").hidden, false);
  await card.confirmMaintenanceReset();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [
    ["roomba_home", "reset_maintenance_counter", { part: "filter", confirmed: true },
      { entity_id: "vacuum.example" }],
  ]);
  count = 0;
  finish();
  await reset;
  assert.equal(dialog.open, true);
  assert.equal(card.$("maintenance-reset-review").hidden, true);
  assert.equal(card.$("maintenance-status").textContent, "Filter counter reset.");
  assert.equal(card.$("maintenance-parts").children[0].querySelector("p").textContent, "0% used");
  assert.equal(card.$("close-maintenance").focused, true);
});

test("maintenance reports a rejected reset and ignores a late result for another robot", async () => {
  const { card, dialog } = maintenanceCard();
  let finish;
  let error = Error("Roomba did not confirm the reset");
  card._hass = {
    callWS: async ({ entity_id }) => ({
      robot: entity_id, counters_available: true,
      parts: [{ part: "side_brush", usage: 15, can_reset: true }],
    }),
    callService: () => error ? Promise.reject(error)
      : new Promise((resolve) => { finish = resolve; }),
  };
  const button = () => card.$("maintenance-parts").children[0].querySelector("button");
  await card.openMaintenance();
  button().onclick();
  await card.confirmMaintenanceReset();
  assert.equal(card.$("maintenance-status").textContent, error.message);
  assert.equal(card.$("maintenance-parts").children[0].querySelector("p").textContent, "15% used");
  button().onclick();
  assert.equal(card.$("maintenance-reset-review").hidden, false);
  error = null;
  const pendingReset = card.confirmMaintenanceReset();
  dialog.close();
  card.config.entity = "vacuum.next";
  await card.openMaintenance();
  finish();
  await pendingReset;
  assert.equal(card.$("maintenance-title").textContent, "vacuum.next maintenance");
  assert.equal(card.$("maintenance-status").textContent, "");
});

function robotHelpCard() {
  const { card } = mockCard(0);
  const dialog = card.$("robot-help-dialog");
  dialog.open = false;
  dialog.modal = false;
  dialog.matches = (selector) => selector === ":modal" && dialog.modal;
  dialog.showModal = () => { dialog.open = dialog.modal = true; };
  dialog.close = () => { dialog.open = dialog.modal = false; };
  card.helpSequence = 0;
  card.config = { entity: "vacuum.example" };
  return { card, dialog };
}

test("robot help opens the model manual and distinguishes article families with the same code", async () => {
  const { card, dialog } = robotHelpCard();
  const manual = "https://prod-help-content.care.irobotapi.com/files/example.pdf";
  const setup = "https://prod-help-content.care.irobotapi.com/web/es/10503.html";
  const path = { family: "error", code: 48, url: "https://prod-help-content.care.irobotapi.com/web/es/10548.html" };
  const refusal = { family: "start_refusal", code: 48, url: "https://prod-help-content.care.irobotapi.com/web/es/10511.html" };
  card._hass = {
    callWS: async (request) => {
      assert.deepEqual({ ...request }, { type: "roomba_home/robot_help", entity_id: "vacuum.example" });
      return {
        robot: "Roomba", manual_url: manual, support_url: null, device_guides: { wifi_setup: setup },
        articles: [path, refusal], current_articles: [path],
      };
    },
  };
  await card.openRobotHelp();
  assert.equal(dialog.open, true);
  assert.equal(card.$("robot-help-title").textContent, "Roomba help");
  assert.equal(card.$("help-status").textContent, "");
  const guideLinks = card.$("help-guides").querySelectorAll("a");
  assert.deepEqual(guideLinks.map((link) => link.href), [manual, setup]);
  assert.ok(guideLinks.every((link) => link.target === "_blank" && link.rel === "noopener noreferrer"));
  assert.equal(card.$("help-current").hidden, false);
  assert.equal(card.$("help-current-articles").querySelector("a").textContent, "Error 48");
  const picker = card.$("help-code");
  const groups = picker.querySelectorAll("optgroup");
  assert.deepEqual(groups.map((group) => [group.label, group.children[0].value]), [
    ["Error", "error:48"], ["Start refusal", "start_refusal:48"],
  ]);
  picker.value = "start_refusal:48";
  picker.onchange();
  assert.equal(card.$("help-article").querySelector("a").href, refusal.url);
  picker.value = "";
  picker.onchange();
  assert.deepEqual(card.$("help-article").children, []);
});

test("robot help ignores a previous robot's reply and reports an empty or failed catalog", async () => {
  const { card, dialog } = robotHelpCard();
  let resolve;
  card._hass = { callWS: () => new Promise((complete) => { resolve = complete; }) };
  const previous = card.openRobotHelp();
  dialog.close();
  card.config.entity = "vacuum.next";
  card._hass.callWS = async () => ({ robot: "Other", device_guides: {}, articles: [], current_articles: [] });
  await card.openRobotHelp();
  resolve({ robot: "Previous" });
  await previous;
  assert.equal(card.$("robot-help-title").textContent, "Other help");
  assert.equal(card.$("help-status").textContent, "Roomba has no help articles for this model.");
  assert.equal(card.$("help-lookup").hidden, true);
  assert.equal(card.$("help-guides").hidden, true);
  dialog.close();
  card._hass.callWS = async () => { throw Error("Could not read help"); };
  await card.openRobotHelp();
  assert.equal(card.$("help-status").textContent, "Could not read help");
});

test("robot help shows an ordered preparation guide and hides it when the robot changes", async () => {
  const { card, dialog } = robotHelpCard();
  const reference = "https://homesupport.irobot.com/articles/en_US/Knowledge/20503";
  const steps = ["brushes", "water", "charge", "rooms"].map((id) => ({
    id, title: `Prepare ${id}`, instructions: `Instructions for ${id}`,
  }));
  const catalog = { device_guides: {}, articles: [], current_articles: [] };
  card._hass = { callWS: async () => ({ ...catalog, setup_guide: { steps, reference_url: reference } }) };
  await card.openRobotHelp();
  const panel = card.$("help-setup");
  const list = card.$("help-setup-steps");
  assert.equal(panel.hidden, false);
  assert.equal(panel.open, false);
  assert.equal(card.$("help-status").textContent, "");
  assert.deepEqual(list.querySelectorAll("strong").map((node) => node.textContent), steps.map((step) => step.title));
  assert.deepEqual(list.querySelectorAll("p").map((node) => node.textContent), steps.map((step) => step.instructions));
  const icons = list.querySelectorAll("ha-icon");
  assert.deepEqual(icons.map((icon) => icon.icon), ["mdi:broom", "mdi:water", "mdi:battery-charging", "mdi:door-open"]);
  assert.ok(icons.every((icon) => icon["aria-hidden"] === "true"));
  assert.equal(card.$("help-setup-reference").querySelector("a").href, reference);
  panel.open = true;
  dialog.close();
  card.config.entity = "vacuum.other";
  card._hass.callWS = async () => ({ ...catalog, setup_guide: null });
  await card.openRobotHelp();
  assert.equal(panel.hidden, true);
  assert.equal(panel.open, false);
  assert.deepEqual(list.children, []);
  assert.deepEqual(card.$("help-setup-reference").children, []);
});

test("robot help restores modal state and the selected article when the dashboard moves the card", async () => {
  const { card, dialog } = robotHelpCard();
  const article = { family: "charging_error", code: 101, url: "https://prod-help-content.care.irobotapi.com/web/es/10601.html" };
  let reads = 0;
  card._hass = {
    callWS: async () => {
      reads++;
      return { robot: "Roomba", device_guides: {}, articles: [article], current_articles: [] };
    },
  };
  await card.openRobotHelp();
  const picker = card.$("help-code");
  picker.value = "charging_error:101";
  picker.onchange();
  dialog.modal = false;
  assert.equal(dialog.open, true);
  card.connectedCallback();
  assert.equal(dialog.modal, true);
  await card.openRobotHelp();
  assert.equal(reads, 1);
  dialog.modal = false;
  await card.openRobotHelp();
  assert.equal(dialog.modal, true);
  assert.equal(reads, 1);
  assert.equal(picker.value, "charging_error:101");
  assert.equal(card.$("help-article").querySelector("a").href, article.url);
});

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

test("saved routine display order moves without discarding the open cleaning draft", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  const first = { id: "first", name: "First", editable: true, display_order: -3 };
  const second = { id: "second", name: "Second", editable: true, display_order: 1 };
  card.routineAreas = new Map();
  card.routines = [first, second];
  const draft = { saved: second, name: "Unsaved name", regions: [], ordered: false };
  card.routineDraft = draft;
  card.routineDialog.open = true;
  card.renderRoutine();
  assert.equal(card.$("move-routine-earlier").disabled, false);
  assert.equal(card.$("move-routine-later").disabled, true);
  const requests = [];
  card.callAction = async (...args) => {
    requests.push(JSON.parse(JSON.stringify(args)));
    return { routines: [{ ...second, display_order: 0 }, { ...first, display_order: 1 }] };
  };
  await card.moveRoutine(-1);
  assert.deepEqual(requests, [["reorder_cleaning_routine", {
    routine_id: "second", anchor_id: "first", position: "before", expected_order: ["first", "second"],
  }, card.config.entity]]);
  assert.equal(card.routineDraft, draft);
  assert.equal(draft.name, "Unsaved name");
  assert.equal(draft.ordered, false);
  assert.equal(card.$("routine-list").value, "second");
  assert.equal(card.$("move-routine-earlier").disabled, true);
  assert.equal(card.$("move-routine-later").disabled, false);
  card.callAction = async () => { throw new Error("The routine order changed."); };
  await card.moveRoutine(1);
  assert.equal(card.$("routine-status").textContent, "The routine order changed.");
  card.routines = [first, { ...second, display_order: first.display_order }];
  card.renderRoutine();
  assert.equal(card.$("routine-list-order").hidden, true);
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

function oneOffCleaningCard() {
  const card = draftEstimateCard();
  Object.assign(card.snapshot, {
    robot: "Example robot", can_clean_everywhere: true,
    cleaning: { modes: ["vacuum", "mop"], default_mode: "vacuum",
      suction_level: 4, wetness_level: 3, two_pass: true },
  });
  card.robotOverview = card.snapshot;
  card.geometry.regions = [{ id: "room-a", name: "Kitchen" }, { id: "room-b", name: "Hall" }];
  card.selected = new Set(["room-b", "room-a"]);
  for (const dialog of [card.dialog, card.routineDialog]) {
    dialog.open = false;
    dialog.showModal = () => { dialog.open = true; };
    dialog.close = () => { dialog.open = false; };
  }
  return card;
}

function cleaningSelectionCard() {
  const card = oneOffCleaningCard();
  card.geometry.regions = [
    { id: "room-a", name: "Kitchen", kind: "room", polygons: [] },
    { id: "room-b", name: "Hall", kind: "room", polygons: [] },
    { id: "zone-b", name: "Entry zone", kind: "zone", polygons: [] },
  ];
  card.geometry.furniture = {
    items: [{ id: "17", points: [[1, 1], [2, 1], [2, 2], [1, 2]] }],
    destinations: [{
      id: "fixture-map:furniture:17", name: "Dining table", object_id: "17",
      outline: [[0.6, 0.6], [2.4, 0.6], [2.4, 2.4], [0.6, 2.4]],
    }],
  };
  return card;
}

test("bulk room selection preserves the previous order, zones, and furniture", () => {
  const card = cleaningSelectionCard();
  card.draw = () => {};
  const table = card.furnitureDestinations[0].id;
  card.selected = new Set(["room-b", "zone-b", table]);
  card.renderAreas();
  card.updateSelection();
  const bulk = card.$("map-room-selection");
  assert.equal(bulk.textContent, "Select all rooms");
  card.review();
  assert.equal(card.dialog.open, true);
  card.toggleMapRooms();
  assert.equal(card.dialog.open, false);
  assert.equal(card.confirmation, null);
  assert.deepEqual([...card.selected], ["room-b", "zone-b", table, "room-a"]);
  assert.equal(bulk.textContent, "Deselect all rooms");
  card.toggleMapRooms();
  assert.deepEqual([...card.selected], ["zone-b", table]);
  const target = card.$("furniture-cleaning-areas").children[0];
  assert.equal(target["aria-pressed"], "true");
  target.onclick();
  assert.deepEqual([...card.selected], ["zone-b"]);
});

test("bulk room selection respects the current reviewed floor and the area limit", () => {
  const card = cleaningSelectionCard();
  card.draw = () => {};
  card.geometry.regions = Array.from({ length: 32 }, (_, i) =>
    ({ id: `room-${i}`, name: `Room ${i}`, kind: "room", polygons: [] }));
  card.selected = new Set(["zone-b"]);
  card.updateSelection();
  assert.equal(card.$("map-room-selection").disabled, true);
  card.toggleMapRooms();
  assert.deepEqual([...card.selected], ["zone-b"]);
  card.geometry.regions.length = 2;
  card.routineDraft.regions = [
    { id: "room-1", mode: "mop", wetness_level: 2 }, { id: "zone-b", mode: "vacuum" },
  ];
  card.routineAreas = new Map([["room-0", "Room 0"], ["room-1", "Room 1"], ["zone-b", "Zone"]]);
  card.routineDialog.open = true;
  card.renderRoutine();
  card.snapshot.map.version = "v2";
  card.toggleDraftRooms();
  assert.equal(card.routineDraft.regions.length, 2);
  card.snapshot.map.version = "v1";
  card.toggleDraftRooms();
  assert.deepEqual(JSON.parse(JSON.stringify(card.routineDraft.regions)), [
    { id: "room-1", mode: "mop", wetness_level: 2 }, { id: "zone-b", mode: "vacuum" }, { id: "room-0" },
  ]);
  card.toggleDraftRooms();
  assert.deepEqual(JSON.parse(JSON.stringify(card.routineDraft.regions)), [{ id: "zone-b", mode: "vacuum" }]);
});

test("the furniture hit area uses the object footprint and previews the requested outline", () => {
  const card = cleaningSelectionCard();
  const target = card.furnitureDestinations[0];
  card.selected = new Set([target.id]);
  card.targets = [];
  const previews = [];
  card.drawOutlinedDraft = (polygons) => previews.push(polygons);
  card.furnitureShown = false;
  card.drawFurnitureDestinations((point) => point);
  assert.deepEqual(card.targets, []);
  assert.equal(previews.length, 1);
  card.furnitureShown = true;
  card.drawFurnitureDestinations((point) => point);
  assert.equal(card.targets[0].id, target.id);
  assert.deepEqual(JSON.parse(JSON.stringify(card.targets[0].path.points)),
    [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]);
  assert.deepEqual(JSON.parse(JSON.stringify(previews[0][0][0])),
    [[0.6, 0.6], [2.4, 0.6], [2.4, 2.4], [0.6, 2.4], [0.6, 0.6]]);
});

test("a mixed furniture selection dispatches only after review through the typed draft action", async () => {
  const card = cleaningSelectionCard();
  card.draw = () => {};
  const table = card.furnitureDestinations[0].id;
  card.selected = new Set([table, "room-a"]);
  const calls = [];
  card._hass = { async callService(...args) { calls.push(JSON.parse(JSON.stringify(args))); } };
  await card.submit();
  assert.deepEqual(calls, []);
  card.review();
  assert.equal(card.$("confirm-text").textContent, "Example robot will clean Dining table, Kitchen.");
  await card.submit();
  assert.deepEqual(calls, [["roomba_home", "run_cleaning_draft", {
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
    regions: [{ id: table }, { id: "room-a" }],
  }, { entity_id: card.config.entity }]]);
});

test("the map review opens cleaning preferences and starts only the reviewed one-off", async () => {
  const card = oneOffCleaningCard();
  card.callAction = () => { throw Error("Opening or editing a one-off must not call an action"); };
  card.draw = () => {};
  const requests = [];
  card._hass = { async callService(...args) { requests.push(JSON.parse(JSON.stringify(args))); } };
  card.review();
  assert.equal(card.$("customize-cleaning").hidden, false);
  await card.customizeCleaning();
  assert.equal(card.dialog.open, false);
  assert.equal(card.routineDialog.open, true);
  assert.equal(card.$("routine-title").textContent, "Cleaning preferences");
  assert.equal(card.$("routine-picker").hidden, true);
  assert.equal(card.$("routine-name").required, false);
  assert.equal(card.$("save-routine").hidden, true);
  assert.equal(card.$("save-cleaning-as-routine").disabled, false);
  assert.deepEqual(Array.from(card.routineDraft.regions, ({ id }) => id), ["room-b", "room-a"]);
  Object.assign(card.routineDraft.regions[0], { mode: "vacuum", suction_level: 3 });
  Object.assign(card.routineDraft.regions[1], { mode: "mop", wetness_level: 1, two_pass: true });
  await card.saveRoutine();
  await card.runRoutine();
  assert.equal(card.$("routine-status").textContent, "Start cleaning: Hall → Kitchen?");
  card.routineDraft.regions[0].suction_level = 2;
  await card.runRoutine();
  assert.deepEqual(requests, []);
  await card.runRoutine();
  assert.deepEqual(requests, [["roomba_home", "run_cleaning_draft", {
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
    regions: [
      { id: "room-b", mode: "vacuum", suction_level: 2 },
      { id: "room-a", mode: "mop", wetness_level: 1, two_pass: true },
    ],
  }, { entity_id: card.config.entity }]]);
  assert.equal(card.routineDialog.open, false);
  assert.equal(card.selected.size, 0);
  assert.match(card.$("status").textContent, /Cleaning request accepted/);
});

test("one-off preferences can become a named routine with their order choice intact", async () => {
  const card = oneOffCleaningCard();
  const requests = [];
  card.callAction = async (...args) => {
    requests.push(JSON.parse(JSON.stringify(args)));
    return args[0] === "list_cleaning_routines" ? { routines: [] } : {
      id: "favorite", name: args[1].name, ordered: args[1].ordered, region_settings: args[1].regions,
    };
  };
  card.review();
  await card.customizeCleaning();
  card.routineDraft.ordered = false;
  card.routineDraft.regions[1].mode = "mop";
  const previous = card.routineDraft.regions;
  await card.saveCleaningAsRoutine();
  assert.equal(card.$("routine-title").textContent, "Cleaning routines");
  assert.equal(card.$("routine-name").focused, true);
  assert.equal(card.$("routine-name").required, true);
  assert.equal(card.$("routine-appearance").hidden, false);
  assert.equal(card.routineDraft.ordered, false);
  assert.notEqual(card.routineDraft.regions[1], previous[1]);
  assert.deepEqual(requests.map(([command]) => command), ["list_cleaning_routines"]);
  card.routineDraft.name = "Room preferences";
  await card.saveRoutine();
  assert.deepEqual(requests[1], ["create_cleaning_routine", {
    name: "Room preferences", ordered: false,
    regions: [{ id: "room-b" }, { id: "room-a", mode: "mop" }],
  }, card.config.entity]);
});

test("edit or duplicate a routine's icon and color without changing its cleaning plan", async () => {
  const card = draftEstimateCard();
  const original = {
    id: "favorite", name: "Kitchen routine", editable: true,
    icon: "😄", color: "#CBCBFB", region_settings: [{ id: "room-a", mode: "mop" }],
  };
  card.routines = [original];
  const requests = [];
  card.callAction = async (service, data) => {
    requests.push([service, JSON.parse(JSON.stringify(data))]);
    return { ...original, name: data.name, icon: data.icon ?? original.icon,
      color: data.color ?? original.color };
  };
  card.editRoutine(original.id);
  assert.match(card.$("routine-list").children[1].text, /😄 Kitchen routine/);
  assert.equal(card.$("routine-icon-preview").textContent, "😄");
  assert.equal(card.$("routine-icon-preview").style.backgroundColor, "#cbcbfb");
  const palette = card.$("routine-palette").children;
  assert.equal(palette.length, 7);
  assert.equal(palette.find(button => button["aria-label"] === "Violet")["aria-pressed"], "true");
  palette.find(button => button["aria-label"] === "Yellow").onclick();
  const input = card.$("routine-icon");
  input.value = "🧹";
  input.oninput();
  assert.equal(card.$("routine-icon-preview").textContent, "🧹");
  assert.equal(card.$("routine-icon-preview").style.backgroundColor, "#fdf4a9");
  await card.saveRoutine();
  assert.deepEqual(requests[0], ["update_cleaning_routine", {
    name: original.name, routine_id: original.id, icon: "🧹", color: "#FDF4A9",
  }]);
  card.copyRoutine();
  await card.saveRoutine();
  assert.deepEqual(requests[1], ["create_cleaning_routine", {
    name: "Kitchen routine (copy)", regions: original.region_settings, icon: "🧹", color: "#FDF4A9",
  }]);

  card.cleaningEditor = true;
  card.renderRoutine();
  assert.equal(card.$("routine-appearance").hidden, true);
  card.cleaningEditor = false;
  card.scheduleEditor = true;
  card.editRoutine(original.id);
  assert.equal(card.$("routine-appearance").hidden, true);
});

test("a changed floor invalidates one-off reviews and whole-area cleaning keeps its own confirmation", async () => {
  const card = oneOffCleaningCard();
  card.callAction = () => { throw Error("Invalid one-off must not call an action"); };
  card._hass = { callService() { throw Error("Invalid one-off must not start a mission"); } };
  card.reviewCleanEverywhere();
  assert.equal(card.$("customize-cleaning").hidden, true);
  await card.customizeCleaning();
  assert.equal(card.routineDialog.open, false);
  card.dialog.close();
  card.review();
  card.geometry.selection_id = "different rooms";
  await card.customizeCleaning();
  assert.equal(card.routineDialog.open, false);
  card.dialog.close();
  card.review();
  await card.customizeCleaning();
  card.snapshot.map.version = "v2";
  await card.runRoutine();
  assert.match(card.$("routine-status").textContent, /current floor plan/);
  await card.saveCleaningAsRoutine();
  assert.equal(card.cleaningEditor, true);
});

test("a draft can inspect and apply a room's remembered settings for its chosen mode", async () => {
  const card = draftEstimateCard();
  card.snapshot.cleaning = {
    default_mode: "vacuum_mop", modes: ["vacuum", "mop", "vacuum_mop"],
    suction_level: 4, wetness_level: 3, two_pass: true, smart_scrub: true,
  };
  card.snapshot.remembered_cleaning = {
    "room-a": {
      last_mode: "vacuum",
      preferred: { vacuum: 2, mop: 4, vacuum_mop: 6 },
      profiles: [
        { mode_code: 2, settings: { mode: "vacuum", suction_level: 1, two_pass: false } },
        { mode_code: 4, settings: { mode: "mop", wetness_level: 2, smart_scrub: false } },
        { mode_code: 6, settings: { mode: "vacuum_mop", suction_level: 1, wetness_level: 1 } },
        { mode_code: 32, preset: "normal", updated_at: "2023-11-14T22:13:20+00:00",
          settings: { mode: "vacuum_mop", suction_level: 3, wetness_level: 2 } },
      ],
    },
  };
  card.callAction = () => { throw Error("Changing a draft must not call an action"); };
  card.renderRoutine();
  const row = card.$("routine-regions").children[0];
  const details = row.querySelector("details");
  assert.equal(details.querySelector("p").textContent, "Last mode · Vacuum");
  assert.deepEqual(details.querySelector("ul").children.length, 4);
  assert.ok(details.querySelector("ul").children[3].textContent.includes("Mode 32 · Normal"));
  const choice = row.querySelector("[data-routine-preset]");
  assert.equal(choice.children[1].text, "Remembered by Roomba");
  choice.value = "remembered";
  await choice.onchange();
  assert.deepEqual(card.routineDraft.regions[0], {
    id: "room-a", mode: "mop", two_pass: false, wetness_level: 2, smart_scrub: false,
  });
  assert.deepEqual(card.routineDraft.regions[1], { id: "furniture-b", mode: "vacuum" });
});

test("applying remembered settings to all areas preserves order and checks the current revision", async () => {
  const card = draftEstimateCard();
  card.snapshot.cleaning = { default_mode: "vacuum_mop", modes: ["vacuum", "mop", "vacuum_mop"] };
  card.routineAreas = new Map([["room-b", "Hall"], ["room-a", "Kitchen"]]);
  card.routineDraft.regions = [{ id: "room-b" }, { id: "room-a" }];
  card.routineDraft.ordered = true;
  card.snapshot.remembered_cleaning = {
    "room-a": { last_mode: "vacuum", preferred: { vacuum: 2 },
      profiles: [{ mode_code: 2, settings: { mode: "vacuum", suction_level: 1 } }] },
    "room-b": { last_mode: "mop", preferred: { mop: 4 },
      profiles: [{ mode_code: 4, settings: { mode: "mop", wetness_level: 3 } }] },
  };
  card.renderRoutine();
  const preset = card.$("routine-preset-all");
  assert.equal(card.$("routine-preset-all-label").hidden, false);
  card.snapshot.map.version = "changed";
  preset.value = "remembered";
  await preset.onchange();
  assert.deepEqual(card.routineDraft.regions, [{ id: "room-b" }, { id: "room-a" }]);
  assert.deepEqual({ ...card.routinePresetsFor(card.routineDraft.regions[0]) }, {});
  card.snapshot.map.version = "v1";
  await preset.onchange();
  assert.deepEqual(card.routineDraft.regions, [
    { id: "room-b", mode: "mop", wetness_level: 3 },
    { id: "room-a", mode: "vacuum", suction_level: 1 },
  ]);
  assert.equal(card.routineDraft.ordered, true);
});

test("choose either remembered variant even when Roomba has no preferred one", () => {
  const card = draftEstimateCard();
  card.callAction = () => { throw Error("Copying a profile must only edit the draft"); };
  card.snapshot.cleaning = {
    default_mode: "vacuum_mop", modes: ["vacuum", "mop", "vacuum_mop"],
    suction_level: 4, wetness_level: 3, two_pass: true,
  };
  const reported = card.snapshot.remembered_cleaning = {
    "room-a": { last_mode: null, preferred: {}, profiles: [
      { mode_code: 6, can_apply: true, settings: {
        mode: "vacuum_mop", suction_level: 1, wetness_level: 1,
      } },
      { mode_code: 32, can_apply: true, settings: {
        mode: "vacuum_mop", suction_level: 3, wetness_level: 2,
      } },
      { mode_code: 512, can_apply: false, settings: { mode: "vacuum_then_mop", suction_level: 4 } },
    ] },
  };
  const currentDetails = () => card.$("routine-regions").children[0].querySelector("details");
  const rows = () => currentDetails().querySelector("ul").children;
  const button = (index) => rows()[index].querySelector("button");
  card.renderRoutine();
  assert.match(rows()[2].textContent, /Mode 512/);
  assert.equal(button(2), undefined);
  button(1).onclick();
  assert.deepEqual(card.routineDraft.regions[0], {
    id: "room-a", mode: "vacuum_mop", two_pass: false, suction_level: 3, wetness_level: 2,
  });
  assert.equal(currentDetails().open, true);
  assert.equal(currentDetails().querySelector("summary").focused, true);
  assert.match(card.$("routine-status").textContent, /Copied/);
  button(0).onclick();
  assert.equal(card.routineDraft.regions[0].suction_level, 1);
  assert.deepEqual(card.routineDraft.regions[1], { id: "furniture-b", mode: "vacuum" });

  const stale = button(1);
  reported["room-a"].profiles[1].settings.suction_level = 4;
  stale.onclick();
  assert.equal(card.routineDraft.regions[0].suction_level, 1);
  assert.match(card.$("routine-status").textContent, /changed/);
  const previousFloor = button(1);
  card.snapshot.map.version = "elsewhere";
  previousFloor.onclick();
  assert.equal(card.routineDraft.regions[0].suction_level, 1);
  assert.equal(currentDetails(), undefined);
});

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
  await card.openRoutines({ schedule: true });
  assert.equal(card.$("routine-title").textContent, "Cleaning schedules");
  assert.equal(card.routineAreas.get("furniture-b"), "Table");
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
  card.routineDraft.regions.push({ id: "furniture-b", mode: "mop", wetness_level: 2 });
  await card.saveSchedule();
  assert.deepEqual(calls[1], ["create_cleaning_schedule", {
    name: "Office cleaning", frequency: "weekly", time: "10:15", weekdays: [2, 5],
    regions: [{ id: "room-a", mode: "vacuum" }, { id: "furniture-b", mode: "mop", wetness_level: 2 }],
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

test("a routine selection opens a new schedule with its order and settings intact", async () => {
  const card = draftEstimateCard();
  const table = "fixture-map:furniture:table";
  const room = "fixture-map:rid:room-a";
  card.snapshot.can_manage_schedules = true;
  card.geometry.regions = [{ id: room, name: "Hall", kind: "room" }];
  card.geometry.furniture = { destinations: [{ id: table, name: "Table" }] };
  card.routineAreas = new Map([[room, "Hall"], [table, "Table"]]);
  const profiles = [{ id: table, mode: "mop", wetness_level: 3, smart_scrub: true },
    { id: room, mode: "vacuum", suction_level: 1, two_pass: false }];
  const saved = { id: "routine-id", name: "Entry and hall", ordered: true, region_settings: profiles };
  card.routines = [saved];
  card.editRoutine(saved.id);
  assert.equal(card.$("use-routine-in-schedule").hidden, false);
  card.routineDraft.ordered = false;
  assert.ok(!card.canUseRoutineInSchedule());
  card.routineDraft.ordered = true;
  card.routineDraft.regions[0].id = "fixture-map:furniture:unknown";
  assert.ok(!card.canUseRoutineInSchedule());
  card.routineDraft.regions[0].id = table;
  const calls = [];
  card.callAction = async (action, data, entity) => {
    calls.push([action, JSON.parse(JSON.stringify(data)), entity]);
    return action === "list_cleaning_schedules" ? { schedules: [] }
      : { id: "group:item", ...data, region_settings: data.regions, enabled: false };
  };
  card.snapshot.map.version = "stale";
  await card.useRoutineInSchedule();
  assert.equal(calls.length, 0);
  card.snapshot.map.version = "v1";
  await card.useRoutineInSchedule();
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "list_cleaning_schedules");
  assert.equal(card.routineDraft.name, saved.name);
  assert.equal(card.routineDraft.saved, undefined);
  assert.equal(card.routineDraft.time, "");
  assert.equal(card.routineAreas.get(table), "Table");
  assert.notEqual(card.routineDraft.regions[0], profiles[0]);
  assert.equal(card.$("schedule-frequency").focused, true);
  assert.equal(card.$("use-routine-in-schedule").hidden, true);
  card.routineDraft.frequency = "once";
  card.routineDraft.time = "15:30";
  await card.saveSchedule();
  assert.deepEqual(calls[1], ["create_cleaning_schedule", {
    name: saved.name, frequency: "once", time: "15:30", regions: profiles,
    floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
  }, card.config.entity]);
  assert.equal(card.routineDraft.saved.enabled, false);
  assert.equal(saved.region_settings[0].wetness_level, 3);
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

test("restriction recovery previews moved zones and missing walls before saving", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "a".repeat(64), map_id: "floor", version: "older" };
  const reviewId = "b".repeat(64);
  let changes = [
    { id: "100", kind: "keep_out", missing: false },
    { id: "101", kind: "no_mop", missing: true },
    { id: "102", kind: "wall", missing: true },
  ];
  const requests = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved,
      geometry: { regions: [region], virtual_walls: [[[2, 2], [3, 2]]] } };
    requests.push(JSON.parse(JSON.stringify(request)));
    if (request.confirmed) return { applied: true };
    return { changes, review_id: reviewId, applied: false };
  } };
  card.drawMapBackup = () => {};
  card.refresh = async () => {};
  await card.openMapBackups();
  assert.equal(card.$("review-map-backup-restrictions").hidden, false);
  await card.reviewMapBackupRestore("restrictions");
  const details = card.$("map-backup-restore-restrictions");
  assert.equal(details.hidden, false);
  assert.deepEqual(Array.from(details.children, ({ textContent }) => textContent), [
    "Restore outline · Keep-out zone · 100", "Recreate · No-mop zone · 101", "Recreate · Virtual wall · 102",
  ]);
  await card.confirmMapBackupRestore();
  assert.deepEqual(requests[1], { ...requests[0], confirmed: true, review_id: reviewId });
  assert.equal(card.$("map-backups-status").textContent, "Map restrictions restored.");
  changes = [];
  await card.reviewMapBackupRestore("restrictions");
  assert.equal(card.$("map-backup-restore").hidden, true);
  assert.equal(card.$("map-backups-status").textContent, "The recorded restrictions already match.");
});

test("room detail recovery selects one room and reports changed boundaries", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "a".repeat(64), map_id: "floor", version: "older" };
  const rooms = [
    { id: "room-1", status: "ready", name: { from: "Oficina", to: "Estudio" },
      room_type: { from: "kitchen", to: "other" }, review_id: "b".repeat(64) },
    { id: "room-2", status: "ready", name: { from: "Sótano", to: "Recibídor" },
      room_type: { from: "other", to: "hallway" }, review_id: "c".repeat(64) },
    { id: "room-3", status: "changed_boundary", name: { from: "Dormitorio", to: "Dormitorio" } },
  ];
  const requests = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved, geometry: {
      regions: [region], editable_rooms: [{ id: "room-1" }],
      room_naming: { types: { other: "Other", kitchen: "Kitchen", hallway: "Hallway" } },
    } };
    requests.push(JSON.parse(JSON.stringify(request)));
    return request.confirmed ? { applied: true } : { rooms, applied: false };
  } };
  card.drawMapBackup = () => {};
  card.refresh = async () => {};
  const select = card.$("map-backup-restore-room-choice");
  select.parentElement = {};
  select.value = "0";
  await card.openMapBackups();
  assert.equal(card.$("review-map-backup-room-details").hidden, false);
  await card.reviewMapBackupRestore("room_details");
  assert.match(card.$("map-backup-restore-room-status").children[0].textContent, /Dormitorio.*boundary has changed/);
  select.value = "1";
  card.showMapBackupRoomDetails();
  const rows = card.$("map-backup-restore-room-values").children;
  assert.deepEqual(Array.from(rows, ({ children }) => children.map(({ textContent }) => textContent)), [
    ["Room name", "Sótano → Recibídor"], ["Room type", "Other → Hallway"],
  ]);
  await card.confirmMapBackupRestore();
  assert.deepEqual(requests[1], { ...requests[0], confirmed: true, room_id: "room-2", review_id: rooms[1].review_id });
  assert.equal(card.$("map-backups-status").textContent, "Room details restored.");
});

test("furniture recovery previews placement, source, and affected routines", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = { map: { id: "floor", version: "current" }, inventory_id: "inventory",
    floor_settings: { id: "settings", name: "Ático", orientation: 0 } };
  const dialog = card.$("map-backups-dialog");
  dialog.showModal = function () { this.open = true; };
  const saved = { id: "a".repeat(64), map_id: "floor", version: "older" };
  const reviewId = "b".repeat(64);
  const changes = [
    { id: "1", kind: "chair/living", name: "Chair", source: "user", missing: false },
    { id: "2", kind: "table/coffee", name: "Coffee table", source: "robot", missing: true },
  ];
  const requests = [];
  card._hass = { callWS: async (request) => {
    if (request.type === "roomba_home/map_backups") return { snapshots: [saved], can_manage: true, retention: 5 };
    if (request.type === "roomba_home/read_map_backup") return { backup: saved,
      geometry: { regions: [region], furniture: { items: [{ id: "1" }, { id: "2" }] } } };
    requests.push(JSON.parse(JSON.stringify(request)));
    if (request.confirmed) return { applied: true };
    return { changes, review_id: reviewId, applied: false,
      dependencies: [{ kind: "routine", name: "Morning", objects: ["2"] }], unchecked: ["routine"] };
  } };
  card.drawMapBackup = () => {};
  card.refresh = async () => {};
  await card.openMapBackups();
  assert.equal(card.$("review-map-backup-furniture").hidden, false);
  await card.reviewMapBackupRestore("furniture");
  const items = card.$("map-backup-restore-furniture-list").children;
  assert.deepEqual(Array.from(items, ({ children }) => children.map(({ textContent }) => textContent)), [
    ["Restore Chair · 1", "Added by user"],
    ["Recreate Coffee table · 2", "Detected by Roomba · Routine · Morning"],
  ]);
  assert.match(card.$("map-backup-restore-furniture-status").textContent, /could not be checked/);
  await card.confirmMapBackupRestore();
  assert.deepEqual(requests[1], { ...requests[0], confirmed: true, review_id: reviewId });
  assert.equal(card.$("map-backups-status").textContent, "Furniture restored.");
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

test("the floor shortcuts open saved and recent plans with their reviewed area profiles", async () => {
  const card = cleaningSelectionCard();
  const panel = card.$("floor-shortcuts");
  const furniture = card.geometry.furniture.destinations[0].id;
  const regions = [{ id: furniture, mode: "vacuum", suction_level: 2 }, { id: "room-a", mode: "mop", wetness_level: 1 }];
  const calls = [];
  let reads = 0;
  card._hass = {
    async callWS(query) {
      reads++;
      assert.deepEqual(JSON.parse(JSON.stringify(query)), {
        type: "roomba_home/floor_routines", entity_id: card.config.entity,
        map_id: "fixture-map", version: "v1", include_saved: true,
      });
      return {
        map_id: "fixture-map", version: "v1",
        saved: [{ kind: "saved", name: "Table then kitchen", icon: "🧹", color: "#ABCDEF",
          estimate: { duration_minutes: 10.2 }, region_settings: regions }],
        routines: [{ kind: "recent", name: "Recent cleaning", region_settings: [{ id: "room-a", mode: "mop" }] },
          { kind: "recent", name: "Stale region", region_settings: [{ id: "unknown" }] }],
      };
    },
    async callService(...args) { calls.push(JSON.parse(JSON.stringify(args))); },
  };
  card.draw = () => {};
  card.updateFloorShortcuts();
  assert.equal(panel.hidden, false);
  await card.loadFloorShortcuts();
  assert.equal(reads, 0);
  panel.open = true;
  await card.loadFloorShortcuts();
  await card.loadFloorShortcuts();
  assert.equal(reads, 1);
  const [saved, recent] = card.$("floor-shortcut-list").children;
  assert.equal(card.$("floor-shortcut-list").children.length, 2);
  assert.equal(saved.children[0].textContent, "🧹 Table then kitchen · 11 min");
  assert.equal(saved.children[0].style.borderInlineStartColor, "#ABCDEF");
  await saved.children[0].onclick();
  assert.equal(card.routineDialog.open, true);
  assert.equal(card.routineDraft.saved, undefined);
  assert.deepEqual([...card.selected], [furniture, "room-a"]);
  assert.deepEqual(JSON.parse(JSON.stringify(card.routineDraft.regions)), regions);
  await card.runRoutine();
  assert.match(card.$("routine-status").textContent, /Dining table → Kitchen/);
  assert.equal(calls.length, 0);
  await card.runRoutine();
  assert.deepEqual(calls[0], ["roomba_home", "run_cleaning_draft", {
    regions, floor: { map_id: "fixture-map", version: "v1", inventory_id: "inventory" },
  }, { entity_id: card.config.entity }]);
  await recent.children[0].onclick();
  assert.deepEqual([...card.selected], ["room-a"]);
  assert.equal(calls.length, 1);
});

test("a replaced floor inventory discards quick routines and stale buttons", async () => {
  const card = cleaningSelectionCard();
  const panel = card.$("floor-shortcuts");
  panel.open = true;
  const result = { map_id: "fixture-map", version: "v1", saved: [], routines: [
    { name: "Clean the kitchen", region_settings: [{ id: "room-a" }] },
  ] };
  card._hass = { callWS: async () => result };
  await card.loadFloorShortcuts();
  const oldButton = card.$("floor-shortcut-list").children[0].children[0];
  let resolve;
  card._hass.callWS = () => new Promise((done) => { resolve = done; });
  const loading = card.loadFloorShortcuts(true);
  assert.equal(card.$("refresh-floor-shortcuts").disabled, true);
  card.geometry.selection_id = "new-inventory";
  card.updateFloorShortcuts();
  resolve(result);
  await loading;
  assert.equal(panel.open, false);
  assert.equal(card.$("floor-shortcut-list").hidden, true);
  await oldButton.onclick();
  assert.equal(card.routineDialog.open, false);
});

test("quick routines retry a failed read and open automatic or point drafts", async () => {
  const card = cleaningSelectionCard();
  const panel = card.$("floor-shortcuts");
  panel.open = true;
  card.draw = () => {};
  card._hass = { callWS: async () => { throw new Error("Roomba throttled the read."); } };
  await card.loadFloorShortcuts();
  assert.equal(card.$("floor-shortcut-status").textContent, "Roomba throttled the read.");
  assert.equal(card.$("refresh-floor-shortcuts").disabled, false);
  Object.defineProperty(card, "pointAvailable", { value: true });
  card.togglePointMode = () => { card.pointMode = !card.pointMode; };
  card._hass.callWS = async () => ({ map_id: "fixture-map", version: "v1", saved: [], routines: [
    { name: "Clean a point", choose_point: true },
    { kind: "recommended", name: "Recommended rooms", target_ids: ["room-b"],
      ordered: false, region_settings: [{ id: "room-b", mode: "vacuum" }] },
  ] });
  await card.loadFloorShortcuts(true);
  const [point, recommendation] = card.$("floor-shortcut-list").children;
  await point.children[0].onclick();
  assert.equal(card.pointMode, true);
  assert.equal(card.$("point-mode").focused, true);
  assert.equal(card.routineDialog.open, false);
  card.recommendationsHidden = true;
  await recommendation.children[0].onclick();
  assert.equal(card.pointMode, false);
  assert.equal(card.routineDraft.ordered, false);
  assert.equal(card.$("routine-order").value, "automatic");
  assert.deepEqual([...card.selected], ["room-b"]);
  assert.deepEqual([...card.recommendedRooms.targets], ["room-b"]);
  assert.equal(card.recommendationsHidden, false);
});

test("a selected recommended room keeps its amber fill and the selected outline", () => {
  const { card, fills } = mockCard(0);
  const id = card.geometry.regions[0].id;
  card.recommendedRooms = { targets: new Set([id]) };
  card.selected.add(id);
  const strokes = [];
  card.ctx.stroke = function (path) {
    if (path?.points) strokes.push([this.strokeStyle, this.lineWidth]);
  };
  card.draw();
  assert.ok(fills.some(([color, points]) => color === "#654727" && points?.length));
  assert.ok(strokes.some(([color, width]) => color === "#79ecd3" && width === 3));
  assert.equal(card.$("recommended-rooms-key").hidden, false);
});

test("recommended room highlighting uses the exact provider targets and keeps the selection intact", async () => {
  const card = draftEstimateCard();
  card.geometry.regions = [
    { id: "room-a", name: "Kitchen", kind: "room" },
    { id: "room-b", name: "Entryway", kind: "room" },
    { id: "zone-b", name: "Table zone", kind: "zone" },
  ];
  const selected = new Set(["room-a"]);
  card.selected = selected;
  card.draw = () => card.renderRecommendedRooms();
  card._hass = { callWS: async (query) => {
    assert.deepEqual(JSON.parse(JSON.stringify(query)), {
      type: "roomba_home/floor_routines", entity_id: card.config.entity, map_id: "fixture-map", version: "v1",
    });
    return { map_id: "fixture-map", version: "v1", routines: [
      { kind: "recent", target_ids: ["room-a"] },
      { kind: "recommended", target_ids: ["room-b", "zone-b", "other-room"] },
    ] };
  } };
  await card.loadRecommendedRooms();
  assert.deepEqual([...card.renderRecommendedRooms()], ["room-b"]);
  assert.equal(card.$("recommended-rooms-status").textContent, "Cleaning recommended for Entryway.");
  assert.equal(card.$("recommended-rooms-key").hidden, false);
  assert.deepEqual([...selected], ["room-a"]);
  await card.toggleRecommendedRooms();
  assert.deepEqual([...card.renderRecommendedRooms()], []);
  assert.equal(card.$("recommended-rooms-status").hidden, true);
  assert.equal(card.$("recommended-rooms-key").hidden, true);
});

test("recommended rooms ignore stale replies and report an unavailable floor", async () => {
  const card = draftEstimateCard();
  card.draw = () => card.renderRecommendedRooms();
  let resolve;
  card._hass = { callWS: () => new Promise((done) => { resolve = done; }) };
  const pending = card.loadRecommendedRooms();
  assert.equal(card.$("recommended-rooms-status").textContent, "Loading recommended rooms…");
  await card.toggleRecommendedRooms();
  resolve({ map_id: "fixture-map", version: "v1", routines: [{ kind: "recommended", target_ids: ["room-a"] }] });
  await pending;
  assert.equal(card.$("recommended-rooms-status").hidden, true);
  card._hass.callWS = async () => ({ map_id: "fixture-map", version: "older", routines: [] });
  await card.toggleRecommendedRooms();
  assert.match(card.$("recommended-rooms-status").textContent, /floor changed/);
  await card.toggleRecommendedRooms();
  card._hass.callWS = async () => ({ map_id: "fixture-map", version: "v1", routines: [] });
  await card.toggleRecommendedRooms();
  assert.match(card.$("recommended-rooms-status").textContent, /no recommended rooms/);
});

test("the floor view loads recommendations on revision changes and remembers hiding the layer", async () => {
  const { card, fills } = mockCard(0);
  const map = { id: "example", version: "one" };
  const geometry = card.geometry;
  const reads = [];
  let finishFirstRead;
  Object.assign(card, {
    isConnected: true,
    config: { entity: "vacuum.example" },
    sequence: 0,
    geometry: null,
    snapshot: null,
    renderMissionPlan() {},
    renderAreaResults() {},
    _hass: { async callWS(query) {
      if (query.type === "roomba_home/floor_plan") {
        return { robot: "Example", map: { ...map }, maps: [{ ...map }], geometry, inventory_id: "fixture" };
      }
      assert.equal(query.type, "roomba_home/floor_routines");
      reads.push([query.map_id, query.version]);
      const result = { map_id: query.map_id, version: query.version,
        routines: [{ kind: "recommended", target_ids: query.version === "one" ? [] : [region.id] }] };
      if (query.version === "one") return new Promise((resolve) => {
        finishFirstRead = () => resolve(result);
      });
      return result;
    } },
  });

  await card.refresh();
  assert.equal(card.$("recommended-rooms-status").textContent, "Loading recommended rooms…",
    card.$("status").textContent);
  await card.refresh();
  assert.deepEqual(reads, [["example", "one"]]);

  map.version = "two";
  await card.refresh();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(reads, [["example", "one"], ["example", "two"]]);
  assert.equal(card.$("recommended-rooms-key").hidden, false);
  assert.ok(fills.some(([color, points]) => color === "#654727" && points?.length));
  finishFirstRead();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual([...card.recommendedRooms.targets], [region.id]);

  await card.toggleRecommendedRooms();
  map.id = "other";
  await card.refresh();
  assert.equal(reads.length, 2);
  assert.equal(card.$("show-recommended-rooms")["aria-pressed"], "false");
  assert.equal(card.$("recommended-rooms-key").hidden, true);
  await card.toggleRecommendedRooms();
  assert.deepEqual(reads.at(-1), ["other", "two"]);
  assert.equal(card.$("show-recommended-rooms")["aria-pressed"], "true");
  assert.equal(card.$("recommended-rooms-key").hidden, false);
});

test("an open floor refreshes only expired recommendations and clears a removed recommendation", async () => {
  const card = draftEstimateCard();
  card.geometry.regions = [{ id: "room-a", name: "Kitchen", kind: "room" }];
  card.draw = () => card.renderRecommendedRooms();
  const floor = { map_id: "fixture-map", version: "v1" };
  let calls = 0;
  card._hass = { callWS: async () => {
    calls++;
    return { ...floor, routines: [{ kind: "recommended", target_ids: ["room-a"] }] };
  } };
  await card.loadRecommendedRooms();
  assert.deepEqual([...card.renderRecommendedRooms()], ["room-a"]);
  await card.loadRecommendedRooms();
  assert.equal(calls, 1);

  card.recommendedRooms.refreshAfter = 0;
  let finish;
  card._hass.callWS = () => new Promise((resolve) => { calls++; finish = resolve; });
  sandbox.document.hidden = true;
  try {
    await card.loadRecommendedRooms();
    assert.equal(calls, 1);
  } finally {
    delete sandbox.document.hidden;
  }
  const refresh = card.loadRecommendedRooms();
  await card.loadRecommendedRooms();
  assert.equal(calls, 2);
  assert.deepEqual([...card.renderRecommendedRooms()], ["room-a"]);
  finish({ ...floor, routines: [] });
  await refresh;
  assert.deepEqual([...card.renderRecommendedRooms()], []);
  assert.equal(card.$("recommended-rooms-key").hidden, true);
  assert.match(card.$("recommended-rooms-status").textContent, /no recommended rooms/);

  card.recommendedRooms.refreshAfter = 0;
  card._hass.callWS = async () => {
    calls++;
    throw new Error("Roomba unavailable");
  };
  await card.loadRecommendedRooms();
  await card.loadRecommendedRooms();
  assert.equal(calls, 3);
  assert.match(card.$("recommended-rooms-status").textContent, /unavailable/);
});

test("loading a native recommendation keeps automatic order and requires review before dispatch", async () => {
  const card = draftEstimateCard();
  card.callAction = async () => ({ map_id: "fixture-map", version: "v1", routines: [{
    kind: "recommended", name: "Clean recommended rooms", ordered: false,
    region_settings: [{ id: "room-a", mode: "vacuum", suction_level: 2 }],
  }] });
  await card.loadQuickRoutines();
  card.$("quick-routines").children[0].children[1].onclick();
  assert.equal(card.routineDraft.ordered, false);
  assert.equal(card.$("routine-order").value, "automatic");
  const commands = [];
  card._hass = { callService: async (...args) => commands.push(args) };
  await card.runRoutine();
  assert.match(card.$("routine-status").textContent, /Roomba will choose the order/);
  assert.equal(commands.length, 0);
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

test("historical layer controls keep archived restrictions, labels and the last position", () => {
  const { card } = mockCard(0);
  const geometry = historyGeometry();
  geometry.rooms[0].name = "Área principal";
  geometry.saved_zones = region.polygons;
  geometry.keep_out = region.polygons;
  geometry.no_mop = region.polygons;
  geometry.virtual_walls = [[[2, 2], [3, 3]]];
  geometry.coverage.push({ modes: ["traveling"], polygons: region.polygons });
  geometry.trajectories.push({ modes: [], points: [[8, 2], [9, 2]] });
  card.historyReport = { geometry };
  card.historyView = { zoom: 1, pan: [0, 0], angle: 0, elevated: false };
  const inputs = ["cleaning", "travel", "unclassified", "coverage"].map((layer) =>
    Object.assign(card.$(`history-${layer}`), { checked: true, parentElement: {} }));
  const paint = [];
  const ctx = {
    fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
    fill() { paint.push(this.fillStyle); },
    stroke() { paint.push(this.strokeStyle); },
    arc() {},
  };
  card.$("history-map").getContext = () => ctx;
  const labels = [];
  card.drawLabel = (name) => labels.push(name);
  const legend = () => card.$("history-map-legend").children.map(({ textContent }) => textContent);
  card.drawHistoryMap();
  assert.ok(inputs.every((input) => !input.parentElement.hidden));
  assert.deepEqual(labels, ["Área principal"]);
  assert.deepEqual(legend(), ["Mopping", "Travel", "Vacuum and mop", "Unclassified path",
    "Cleaning zone", "Keep-out area or wall", "No-mop area", "Dock", "Obstacle", "End of recorded path"]);
  assert.ok(paint.includes("#4ed9ad44"));
  inputs[1].checked = false;
  card.drawHistoryMap();
  assert.ok(!legend().includes("Travel"));
  assert.ok(legend().includes("Travel coverage"));
  for (const input of inputs) input.checked = false;
  paint.length = 0;
  card.drawHistoryMap();
  assert.deepEqual(legend(), ["Cleaning zone", "Keep-out area or wall", "No-mop area",
    "Dock", "Obstacle", "End of recorded path"]);
  for (const color of ["#9eafbf", "#b7c3cd", "#c39bff", "#4ed9ad44"]) assert.ok(!paint.includes(color));
  for (const color of ["#5bd4b0", "#ff7893", "#e8ab6a", "#eaf3f9"]) assert.ok(paint.includes(color));
  card.historyReport.geometry = { ...geometry, trajectories: [], coverage: [] };
  card.drawHistoryMap();
  assert.ok(inputs.every((input) => input.parentElement.hidden));
  assert.ok(!legend().includes("End of recorded path"));
});

test("the history panel opens the latest report and shows measurements when geometry is missing", async () => {
  const { card } = mockCard(0);
  const mission = { id: "report-a", finished_at: "2026-11-25T10:00:00Z", map_count: 1, duration_minutes: 2,
    outcome: "completed", area_m2: 0.5 };
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.renderAreaResults = () => {};
  const planView = card.$("history-plan");
  planView.append(mockElement("summary"), mockElement("div"));
  const plan = { ordered: true, total: 2, completed: 1, destinations: [
    { kind: "furniture", mode: "vacuum", status: "skipped", reported_pass_count: 0,
      requested_settings: { two_pass: false, suction_level: 2 } },
    { kind: "saved_zone", mode: "mop", status: "finished", reported_pass_count: 1,
      confirmed_completed_passes: 2, requested_settings: { wetness_level: 3 } },
  ] };
  card.$("mission-history-dialog").showModal = function () { this.open = true; };
  const calls = [];
  card._hass = { callWS: async (request) => {
    calls.push(request);
    return request.report_id ? { mission, geometry: null, map_index: 0, timeline: [
      { type: "error", timestamp: 1700000100, error_code: 48 },
      { type: "evac", timestamp: 1700000470, duration_seconds: 17, dock: { state_code: 301, error_code: 0 } },
      { type: "padWash", timestamp: 1700000488, dock: { state_code: null, error_code: 654 } },
      { type: "finish", timestamp: 1700000500 },
    ], evacuations: 0, modes: {}, rooms: [], zones: [], plan }
      : { missions: [mission] };
  } };
  await card.openMissionHistory();
  assert.equal(calls[0].entity_id, "vacuum.example");
  assert.equal(calls[1].report_id, "report-a");
  assert.equal(card.$("history-no-map").hidden, false);
  assert.equal(card.$("history-map-view").hidden, true);
  assert.equal(card.$("history-totals").textContent, "1 report · 2 min · 0.5 m²");
  assert.deepEqual(card.$("history-timeline").children.map((item) => item.textContent.split(" · ").slice(1)), [
    ["Error 48"], ["Bin emptying stage", "17 s", "Dock state 301"], ["Mop washing", "Dock error 654"], ["Finished"],
  ]);
  const emptyings = card.$("history-measurements").children.find(
    (field) => field.children[0].textContent === "Recorded bin emptyings",
  );
  assert.equal(emptyings.children[1].textContent, "0");
  assert.equal(planView.hidden, false);
  assert.equal(planView.querySelector("summary").textContent, "Requested order · 1 of 2 completed");
  assert.deepEqual(planView.querySelector("ol").children.map((item) =>
    item.children[0].children.map((field) => field.textContent)), [
    ["Furniture target", "Vacuum · Skipped · Reported pass value 0", "Requested · Suction 2 · Two passes off"],
    ["Saved zone", "Mop · Completed · Completed passes 2", "Requested · Mop wetness 3"],
  ]);
  card.renderMissionReport({ ...card.historyReport, plan: { ...plan, ordered: false } });
  assert.equal(planView.querySelector("summary").textContent, "Requested destinations · 1 of 2 completed");
  assert.ok(planView.querySelector("ul"));
  card.renderMissionReport({ ...card.historyReport, plan: null });
  assert.equal(planView.hidden, true);
  assert.equal(planView.querySelector("ul"), undefined);
});

test("a requested floor highlights its targets and keeps mission result layers hidden", () => {
  const { card } = mockCard(0);
  const archived = historyGeometry();
  const context = {
    ...archived, coverage: [], trajectories: [], hazards: [], temporary_zones: [],
    requested_areas: region.polygons,
  };
  const paint = [];
  const canvas = card.$("history-map");
  canvas.getContext = () => ({
    fillRect() {}, fill() { paint.push(this.fillStyle); }, stroke() { paint.push(this.strokeStyle); },
    beginPath() {}, moveTo() {}, lineTo() {}, arc() {}, save() {}, clip() {}, restore() {},
  });
  const inputs = ["cleaning", "travel", "unclassified", "coverage"].map((layer) =>
    Object.assign(card.$(`history-${layer}`), { checked: true, parentElement: {} }));
  card.historyView = { zoom: 1, pan: [0, 0], angle: 0, elevated: false };
  card.renderAreaResults = () => {};
  card.$("history-plan").append(mockElement("summary"), mockElement("div"));
  const report = { mission: { map_count: 0 }, geometry_source: "requested_floor", geometry: context,
    map_index: 0, timeline: [], modes: {}, rooms: [], zones: [] };
  card.historyReport = report;
  card.renderMissionReport(report);
  assert.equal(card.$("history-map-source").hidden, false);
  assert.match(canvas["aria-label"], /Requested floor plan/);
  assert.ok(inputs.every((input) => input.parentElement.hidden));
  assert.ok(card.$("history-map-legend").children.some(({ textContent }) => textContent === "Requested area"));
  assert.ok(paint.includes("#f4bf7c"));

  const backup = { ...report, geometry_source: "backup_floor", floor_source: "local_backup" };
  card.historyReport = backup;
  card.renderMissionReport(backup);
  assert.equal(card.$("history-map-source").hidden, false);
  assert.match(card.$("history-map-source").textContent, /From a local map backup/);
  assert.match(canvas["aria-label"], /Saved floor from a local map backup/);
  assert.ok(inputs.every((input) => input.parentElement.hidden));

  const local = { ...report, geometry_source: "local_capture", geometry: {
    ...context, trajectories: [{ index: 7, points: [[1, 1], [2, 1]], modes: ["vacuuming"] }],
    estimated_coverage: { cell_size: 0.025, rows: [[40, [[40, 80, 1]]]] },
  } };
  card.historyReport = local;
  card.renderMissionReport(local);
  assert.equal(card.$("history-map-source").hidden, false);
  assert.match(card.$("history-map-source").textContent, /Coverage is estimated from live positions/);
  assert.match(canvas["aria-label"], /Locally recorded route/);
  assert.equal(card.$("history-coverage-label").textContent, "Estimated coverage");
  assert.equal(inputs[3].parentElement.hidden, false);
  assert.ok(paint.some((color) => color.endsWith("60")));

  const localOnBackup = { ...local, floor_source: "local_backup" };
  card.historyReport = localOnBackup;
  card.renderMissionReport(localOnBackup);
  assert.match(card.$("history-map-source").textContent, /Floor from a local map backup/);
  assert.equal(card.$("history-coverage-label").textContent, "Estimated coverage");

  const traveling = { ...local, geometry: {
    ...context, trajectories: [{ index: 1, points: [[1, 1], [2, 1]], modes: ["traveling"] }],
  } };
  card.historyReport = traveling;
  card.renderMissionReport(traveling);
  assert.match(card.$("history-map-source").textContent, /Live positions saved by Home Assistant/);
  assert.equal(inputs[1].parentElement.hidden, false);
  assert.equal(inputs[3].parentElement.hidden, true);

  const recorded = { ...report, geometry: archived, geometry_source: "mission_archive" };
  card.historyReport = recorded;
  card.renderMissionReport(recorded);
  assert.equal(card.$("history-map-source").hidden, true);
  assert.match(canvas["aria-label"], /Recorded floor, coverage and robot route/);
  assert.equal(inputs[3].parentElement.hidden, false);
  assert.equal(card.$("history-coverage-label").textContent, "Coverage");
});

test("local route controls respect permissions and refresh the report after explicit deletion", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.$("mission-history-dialog").open = true;
  card.historyReport = { geometry_source: "local_capture", mission: { id: "report" }, map_index: 0 };
  const requests = [];
  const reloads = [];
  card.loadMissionReport = (...args) => reloads.push(args);
  card._hass = { callWS: async (input) => {
    requests.push(input);
    return { enabled: !input.clear, count: input.clear ? 0 : 1, can_manage: Boolean(input.clear) };
  } };
  await card.readRouteSettings();
  assert.match(card.$("history-route-status").textContent, /1 saved route$/);
  assert.equal(card.$("history-route-toggle").hidden, true);
  assert.equal(card.$("history-route-clear").hidden, true);
  assert.equal(requests.length, 1);
  await card.readRouteSettings({ clear: true });
  assert.equal(requests[1].clear, true);
  assert.equal(card.$("history-route-toggle").hidden, false);
  assert.equal(card.$("history-route-clear").hidden, true);
  assert.deepEqual(reloads, [["report", 0]]);
});

test("expanded history keeps its query scope when opening an archived report", async () => {
  const { card } = mockCard(0);
  const standard = { id: "completed", finished_at: "2026-11-27T17:00:00Z", outcome: "completed" };
  const canceled = { id: "canceled", finished_at: "2026-11-27T18:00:00Z", outcome: "cancelled" };
  const checkbox = card.$("history-include-short-canceled");
  const picker = card.$("history-mission");
  const dialog = card.$("mission-history-dialog");
  dialog.showModal = function () { this.open = true; };
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.renderMissionReport = () => {};
  const calls = [];
  card._hass = { async callWS(request) {
    calls.push(request);
    const missions = request.include_short_canceled ? [canceled, standard] : [standard];
    return request.report_id
      ? { mission: missions.find(({id}) => id === request.report_id), map_index: request.map_index }
      : { missions };
  } };

  checkbox.checked = true;
  await card.openMissionHistory();
  assert.equal(checkbox.checked, false);
  assert.equal(picker.value, standard.id);
  assert.equal(calls[0].include_short_canceled, undefined);

  checkbox.checked = true;
  await card.refreshMissionHistory(picker.value);
  assert.equal(picker.value, standard.id);
  assert.equal(card.$("history-totals").textContent, "2 reports");
  assert.equal(calls[2].include_short_canceled, true);
  assert.equal(calls[3].include_short_canceled, true);
  await card.loadMissionReport(canceled.id, 1);
  assert.equal(calls.at(-1).map_index, 1);
  assert.equal(calls.at(-1).include_short_canceled, true);
  assert.equal(card.historyReport.mission.id, canceled.id);

  checkbox.checked = false;
  await card.refreshMissionHistory(canceled.id);
  assert.equal(picker.value, standard.id);
  assert.equal(card.historyReport.mission.id, standard.id);
  assert.equal(calls.at(-1).include_short_canceled, undefined);
});

test("history discards an expanded list that arrives after the filter is turned off", async () => {
  const { card } = mockCard(0);
  const standard = { id: "completed", finished_at: "2026-11-27T17:00:00Z", outcome: "completed" };
  const canceled = { id: "canceled", finished_at: "2026-11-27T18:00:00Z", outcome: "cancelled" };
  card.$("mission-history-dialog").open = true;
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.renderMissionReport = () => {};
  let resolveExpanded;
  const calls = [];
  card._hass = { async callWS(request) {
    calls.push(request);
    if (request.include_short_canceled) return new Promise((resolve) => { resolveExpanded = resolve; });
    return request.report_id ? { mission: standard, map_index: 0 } : { missions: [standard] };
  } };
  const checkbox = card.$("history-include-short-canceled");
  checkbox.checked = true;
  const expanded = card.refreshMissionHistory();
  checkbox.checked = false;
  await card.refreshMissionHistory();
  resolveExpanded({ missions: [canceled, standard] });
  await expanded;
  assert.equal(card.$("history-mission").value, standard.id);
  assert.equal(card.$("history-totals").textContent, "1 report");
  assert.equal(calls.length, 3);
});

test("history keeps the selected period and cancellation filter when opening an older map", async () => {
  const { card } = mockCard(0);
  const recent = { id: "recent", finished_at: "2026-11-27T17:00:00Z", duration_minutes: 1 };
  const older = { id: "older", finished_at: "2026-11-12T17:00:00Z", duration_minutes: 4 };
  const extra = { id: "extra", finished_at: "2026-11-12T16:00:00Z", outcome: "cancelled" };
  const period = card.$("history-days");
  const checkbox = card.$("history-include-short-canceled");
  const picker = card.$("history-mission");
  card.$("mission-history-dialog").showModal = function () { this.open = true; };
  card.config = { entity: "vacuum.example" };
  card.historySequence = 0;
  card.renderMissionReport = () => {};
  let resolvePrevious;
  let waitForMonth = false;
  const calls = [];
  card._hass = { async callWS(request) {
    calls.push(request);
    const rows = request.history_days === 30 ? [recent, older] : [recent];
    if (request.include_short_canceled && request.history_days === 30) rows.push(extra);
    if (waitForMonth && request.history_days === 30 && !request.report_id) {
      waitForMonth = false;
      return new Promise((resolve) => { resolvePrevious = () => resolve({ missions: rows }); });
    }
    return request.report_id
      ? { mission: rows.find(({ id }) => id === request.report_id), map_index: request.map_index }
      : { missions: rows };
  } };

  period.value = "30";
  await card.openMissionHistory();
  assert.equal(period.value, "10");
  assert.equal(calls[0].history_days, undefined);

  period.value = "30";
  await card.refreshMissionHistory(picker.value);
  assert.equal(picker.value, recent.id);
  assert.equal(card.$("history-totals").textContent, "2 reports · 5 min");
  await card.loadMissionReport(older.id, 1);
  assert.equal(calls.at(-1).history_days, 30);
  assert.equal(calls.at(-1).map_index, 1);
  assert.equal(card.historyReport.mission.id, older.id);

  checkbox.checked = true;
  await card.refreshMissionHistory(older.id);
  assert.equal(picker.value, older.id);
  assert.equal(calls.at(-1).history_days, 30);
  assert.equal(calls.at(-1).include_short_canceled, true);
  assert.equal(card.$("history-totals").textContent, "3 reports · 5 min");

  waitForMonth = true;
  const previous = card.refreshMissionHistory(older.id);
  period.value = "10";
  await card.refreshMissionHistory(older.id);
  resolvePrevious();
  await previous;
  assert.equal(picker.value, recent.id);
  assert.equal(card.historyReport.mission.id, recent.id);
  assert.equal(calls.at(-1).history_days, undefined);
  assert.equal(calls.at(-1).include_short_canceled, true);
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

test("clean everywhere confirms the robot and sends a new untargeted mission", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.snapshot = null;
  card.robotOverview = { robot: "Example", can_clean_everywhere: true };
  card.geometry = null;
  card.draw = () => {};
  card.updateSelection = () => {};
  const calls = [];
  card._hass = { callService: async (...args) => calls.push(args) };
  const dialog = card.$("confirm-dialog");
  dialog.showModal = function () { this.open = true; };
  dialog.close = function () { this.open = false; };
  await card.submit();
  assert.equal(calls.length, 0);
  card.reviewCleanEverywhere();
  assert.equal(dialog.open, true);
  assert.equal(card.$("confirm-text").textContent,
    "Example will clean every reachable area using its next-cleaning preferences.");
  card.robotOverview.can_clean_everywhere = false;
  await card.submit();
  assert.equal(calls.length, 0);
  card.robotOverview.can_clean_everywhere = true;
  card.config.entity = "vacuum.other";
  await card.submit();
  assert.equal(calls.length, 0);
  card.config.entity = "vacuum.example";
  await card.submit();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["roomba_home", "clean_everywhere",
    { confirmed: true }, { entity_id: "vacuum.example" }]]);
  assert.equal(dialog.open, false);
  await card.submit();
  assert.equal(calls.length, 1);
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

function prepareRestrictionPlacement(card, kind) {
  card.restrictionFields = Array.from({ length: 4 }, () => ({
    value: "",
    get valueAsNumber() { return this.value === "" ? NaN : Number(this.value); },
  }));
  card.$("restriction-operation").value = "create";
  card.$("restriction-kind").value = kind;
  card.restrictionDraft = { operation: "create", kind, placing: 0 };
  card.canvas = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 920, height: 520 }) };
  card.setRestrictionBounds([]);
}

test("two clicks create a restriction in native coordinates on a rotated floor", () => {
  const { card } = mockCard(-Math.PI / 2);
  card.geometry.editable_restrictions = [];
  prepareRestrictionPlacement(card, "no_mop");
  const outline = card.targets[0].path.points;
  card.pick({ clientX: outline[0][0], clientY: outline[0][1] });
  assert.equal(card.restrictionDraft.placing, 1);
  assert.equal(card.$("restriction-edit-status").textContent, "Select the opposite corner on the map.");
  card.pick({ clientX: outline[2][0], clientY: outline[2][1] });
  assert.equal(card.restrictionDraft.placing, null);
  for (const [index, expected] of [0, 0, 10, 4].entries()) {
    close(card.restrictionDraft.bounds[index], expected);
  }
});

test("wall placement keeps vertical and diagonal endpoints and accepts stroke selection", async () => {
  const { card } = mockCard(-Math.PI / 2);
  const marks = [];
  card.drawPointMarker = (screenPoint) => marks.push(screenPoint);
  const wall = { id: "wall-1", kind: "wall", points: [[8, 1], [4, 3]] };
  const zone = { id: "zone-1", kind: "keep_out", points: [[1, 1], [2, 1], [2, 2], [1, 2]] };
  card.geometry.editable_restrictions = [wall, zone];
  card.geometry.virtual_walls = [wall.points];
  prepareRestrictionPlacement(card, "wall");
  assert.equal(card.$("place-restriction").textContent, "Place wall on map");
  assert.equal(card.$("restriction-y2-label").textContent, "Second endpoint Y");
  const [first, second] = [[6, 1], [6, 3]].map(card.screenPoint);
  card.pick({ clientX: first[0], clientY: first[1] });
  assert.equal(card.$("restriction-edit-status").textContent, "Select the second endpoint on the map.");
  assert.equal(card.$("review-restriction-edit").disabled, true);
  card.pick({ clientX: second[0], clientY: second[1] });
  assert.equal(card.$("review-restriction-edit").disabled, false);
  assert.ok(marks.length >= 3);
  const calls = [];
  card.config = { entity: "vacuum.example" };
  card.floor = "example";
  Object.assign(card.restrictionDraft, { id: card.floor, version: "abc", inventoryId: "inv" });
  card._hass = { callWS: async (request) => calls.push(request) };
  card.refresh = async () => {};
  card.$("restriction-edit-dialog").close = () => {};
  await card.saveRestrictionEdit();
  assert.equal(calls[0].kind, "wall");
  assert.equal(calls[0].operation, "create");
  calls[0].bounds.forEach((value, i) => close(value, [6, 1, 6, 3][i]));

  card.restrictionDraft = { operation: "update", kind: "keep_out", shape: zone };
  card.$("restriction-operation").value = "update";
  card.ctx.save = () => {};
  card.ctx.restore = () => {};
  card.ctx.isPointInPath = () => false;
  card.ctx.isPointInStroke = (path) => path.points.length === 2;
  card.draw();
  card.pick({ clientX: first[0], clientY: first[1] });
  assert.equal(card.restrictionDraft.shape.id, "wall-1");
  assert.deepEqual(Array.from(card.restrictionFields, ({ value }) => value), [8, 1, 4, 3]);
  assert.equal(card.$("review-restriction-edit").disabled, true);
  card.setRestrictionBounds([8, 3, 6, 1]);
  assert.equal(card.$("review-restriction-edit").disabled, false);
  card.setRestrictionBounds([3, 1, 3, 1]);
  assert.equal(card.$("review-restriction-edit").disabled, true);
});

test("room publication keeps an open confirmation valid when the available targets are unchanged", async () => {
  const { card } = mockCard(0);
  const map = { id: "example", version: "version.43" };
  const geometry = { ...card.geometry, selection_id: "visible-rooms-and-zones" };
  let reply = { map, robot: "Robot", maps: [], geometry, inventory_id: "published",
    current_room: "Office", on_mapped_carpet: true };
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
  assert.equal(element("activity").textContent, "Current room · Office · On mapped carpet");
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
    on_mapped_carpet: null,
  };
  await card.refresh();
  assert.equal(element("activity").textContent, "Current room · Office");
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
      if (query.type === "roomba_home/floor_routines") {
        return { map_id: query.map_id, version: query.version, routines: [] };
      }
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

test("mission actions match the active phase and dispatch to the reviewed robot", async () => {
  const { card } = mockCard(0);
  const elements = new Map([["mission-control-dialog", {
    open: false,
    showModal() { this.open = true; },
    close() { this.open = false; },
  }]]);
  const calls = [];
  const active = { review_id: "first", commands: ["pause", "stop", "dock"] };
  Object.assign(card, {
    config: { entity: "vacuum.example" },
    robotOverview: { robot: "Example robot", mission_controls: active },
    _hass: { async callService(...args) { calls.push(args); } },
    async refresh() {},
    $(id) {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
  });
  card.updateMissionControls(active);
  assert.equal(elements.get("mission-pause").hidden, false);
  assert.equal(elements.get("mission-resume").hidden, true);
  await card.reviewMissionCommand("resume");
  assert.equal(calls.length, 0);
  await card.reviewMissionCommand("pause");
  assert.deepEqual(calls[0].slice(0, 2), ["roomba_home", "control_current_mission"]);
  assert.equal(calls[0][2].command, "pause");
  assert.equal(calls[0][2].review_id, "first");
  assert.equal(calls[0][3].entity_id, "vacuum.example");

  card.reviewMissionCommand("stop");
  assert.equal(elements.get("mission-control-dialog").open, true);
  assert.equal(calls.length, 1);
  const next = { review_id: "second", commands: ["resume", "stop", "dock"] };
  card.robotOverview.mission_controls = next;
  card.updateMissionControls(next);
  assert.equal(elements.get("mission-control-dialog").open, false);
  await card.confirmMissionCommand();
  assert.equal(calls.length, 1);
  assert.equal(elements.get("mission-pause").hidden, true);
  assert.equal(elements.get("mission-resume").hidden, false);

  card.reviewMissionCommand("dock");
  assert.match(elements.get("mission-control-description").textContent, /its dock/);
  await card.confirmMissionCommand();
  assert.equal(calls[1][2].command, "dock");
  assert.equal(calls[1][2].review_id, "second");
  assert.equal(elements.get("mission-control-status").hidden, true);
  card.robotOverview.mission_controls = null;
  card.updateMissionControls(null);
  assert.equal(elements.get("mission-controls").hidden, true);
});

test("a pending mission command cannot be repeated and failures are visible", async () => {
  const { card } = mockCard(0);
  const elements = new Map();
  let fail;
  let calls = 0;
  const controls = { review_id: "mission", commands: ["resume"] };
  Object.assign(card, {
    config: { entity: "vacuum.example" },
    robotOverview: { mission_controls: controls },
    _hass: { callService() { calls++; return new Promise((_, reject) => { fail = reject; }); } },
    async refresh() {},
    $(id) {
      if (!elements.has(id)) elements.set(id, {});
      return elements.get(id);
    },
  });
  const pending = card.reviewMissionCommand("resume");
  assert.equal(elements.get("mission-resume").disabled, true);
  assert.equal(elements.get("mission-control-status").hidden, false);
  await card.reviewMissionCommand("resume");
  assert.equal(calls, 1);
  fail(new Error("The current mission changed."));
  await pending;
  assert.equal(elements.get("mission-resume").disabled, false);
  assert.equal(elements.get("mission-control-status").textContent, "The current mission changed.");
});

test("dock controls show reported activity and require review for the exact linked button", async () => {
  const { card } = mockCard(0);
  const dialog = card.$("dock-controls-dialog");
  dialog.showModal = () => { dialog.open = true; };
  const calls = [];
  card._hass = { async callService(...args) { calls.push(args); } };
  card.refresh = async () => {};
  card.robotOverview = { dock_controls: {
    dry_mop: { active: true, entity_id: null },
    stop_drying: { active: false, entity_id: "button.linked_stop_drying" },
    wash_mop: { active: false, entity_id: "button.linked_wash" },
    empty_bin: { active: false, entity_id: null },
  } };
  card.updateDockControls();
  assert.equal(card.$("open-dock-controls").hidden, false);
  assert.equal(card.$("dock-dry_mop").textContent, "Dry mop · In progress");
  assert.equal(card.$("dock-dry_mop").disabled, true);
  assert.equal(card.$("dock-refill_tank").hidden, true);
  assert.equal(card.$("dock-stop_drying").hidden, false);
  card.openDockControls();
  card.reviewDockAction("empty_bin");
  assert.equal(card.$("dock-action-review").hidden, true);
  card.reviewDockAction("wash_mop");
  assert.equal(card.$("dock-action-review").hidden, false);
  assert.equal(card.$("dock-action-prompt").textContent, "Wash mop and tray?");
  assert.equal(card.$("back-dock-action").focused, true);
  assert.equal(calls.length, 0);

  card.robotOverview.dock_controls.wash_mop.entity_id = "button.renamed_wash";
  card.updateDockControls();
  await card.confirmDockAction();
  assert.equal(calls.length, 0);
  assert.equal(card.$("dock-action-review").hidden, true);
  assert.equal(card.$("dock-action-status").textContent, "This dock action is no longer available.");

  card.reviewDockAction("wash_mop");
  await card.confirmDockAction();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].slice(0, 2), ["button", "press"]);
  assert.equal(calls[0][3].entity_id, "button.renamed_wash");
  assert.equal(card.$("dock-action-status").textContent, "Roomba confirmed the dock action.");
  card.robotOverview = null;
  card.updateDockControls();
  assert.equal(card.$("open-dock-controls").hidden, true);
  assert.equal(card.$("dock-unavailable").hidden, false);
});

test("a dock request cannot be duplicated and an error remains visible in its own dialog", async () => {
  const { card } = mockCard(0);
  const dialog = card.$("dock-controls-dialog");
  dialog.open = true;
  let calls = 0;
  let reject;
  card.refresh = async () => {};
  card._hass = {
    callService() {
      calls++;
      return new Promise((_, failure) => { reject = failure; });
    },
  };
  card.robotOverview = { dock_controls: { dry_mop: { active: false, entity_id: "button.dry" } } };
  card.reviewDockAction("dry_mop");
  const pending = card.confirmDockAction();
  assert.equal(card.$("dock-dry_mop").disabled, true);
  assert.match(card.$("dock-action-status").textContent, /Waiting/);
  card.reviewDockAction("dry_mop");
  await card.confirmDockAction();
  assert.equal(calls, 1);
  reject(new Error("The dock is busy."));
  await pending;
  assert.equal(card.$("dock-action-status").textContent, "The dock is busy.");
  assert.equal(card.$("dock-dry_mop").disabled, false);
});

test("a missing map keeps live robot status, errors and independent command reviews available", async () => {
  const { card } = mockCard(0);
  card.config = { entity: "vacuum.example" };
  card.isConnected = true;
  card.sequence = 0;
  card.snapshot = null;
  card.geometry = null;
  card.draw = () => {};
  card.renderAreas = () => {};
  card.updateSelection = () => {};
  card.updateFloorShortcuts = () => {};
  card.$("mission-plan").append(mockElement("summary"), mockElement("div"));
  card.$("active").append(mockElement("div"));
  card.$("history").append(mockElement("div"));
  const dialog = card.$("confirm-dialog");
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  const dockDialog = card.$("dock-controls-dialog");
  dockDialog.open = true;
  const requests = [];
  let overview = {
    robot: "Living room robot",
    robot_status: { connected: true, activity: "docked", battery_pct: 0 },
    dock_controls: {
      dry_mop: { active: true, entity_id: null },
      stop_drying: { active: false, entity_id: "button.stop_drying" },
    },
    active_errors: [{ source: "mission", code: 48, reason: "path_blocked" }],
    can_clean_everywhere: true,
  };
  let mapError = "map_unavailable";
  card._hass = { async callWS(request) {
    requests.push(request.type);
    if (request.type === "roomba_home/floor_plan") {
      throw Object.assign(new Error("Floor unavailable"), { code: mapError });
    }
    if (!overview) throw new Error("Device status unavailable");
    return overview;
  } };

  await card.refresh();
  assert.deepEqual(requests, ["roomba_home/floor_plan", "roomba_home/robot_overview"]);
  assert.equal(card.snapshot, null);
  assert.equal(card.$("scene").hidden, true);
  assert.equal(card.$("title").textContent, "Living room robot");
  assert.equal(card.$("robot-status").textContent, "At dock · Drying mop · Battery 0%");
  assert.equal(card.$("active-errors").hidden, false);
  assert.equal(card.$("clean-everywhere").hidden, false);
  card.reviewCleanEverywhere();
  card.reviewDockAction("stop_drying");
  await card.refresh();
  assert.equal(dialog.open, true);
  assert.equal(card.$("dock-action-review").hidden, false);

  overview = { robot: "Living room robot", robot_status: { connected: false } };
  await card.refresh();
  assert.equal(card.$("robot-status").textContent, "Offline");
  assert.equal(card.$("open-dock-controls").hidden, true);
  assert.equal(card.$("active-errors").hidden, true);
  assert.equal(dialog.open, false);
  overview.robot_status.connected = null;
  await card.refresh();
  assert.equal(card.$("robot-status").textContent, "Connectivity unknown");
  overview = null;
  await card.refresh();
  assert.equal(card.$("robot-status").hidden, true);

  mapError = "unauthorized";
  await card.refresh();
  assert.equal(requests.at(-1), "roomba_home/floor_plan");
  assert.equal(card.$("title").textContent, "Roomba floor plan");
});

test("late map-unavailable status cannot update a card after its robot changes", async () => {
  const { card } = mockCard(0);
  let resolve;
  card._hass = { callWS: () => new Promise((done) => { resolve = done; }) };
  card.sequence = 1;
  const pending = card.refreshRobotOverview("vacuum.previous", 1);
  card.sequence = 2;
  card.updateRobotOverview({ robot: "Current robot", robot_status: { connected: true } });
  resolve({ robot: "Previous robot", robot_status: { connected: false } });
  await pending;
  assert.equal(card.$("title").textContent, "Current robot");
  assert.equal(card.$("robot-status").textContent, "Connected");
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
      { kind: "saved_zone", name: "Entry", status: "finished", area: 106, total_area: 67,
        pass_count: 1, confirmed_completed_passes: 2, target_area_m2: 9.85, completed_passes_area_m2: 12.45 },
      { kind: "saved_zone", name: "Pantry", status: "finished", area: 0, total_area: 0,
        pass_count: 0, confirmed_completed_passes: 1, target_area_m2: 0, completed_passes_area_m2: 0 },
      { kind: "saved_zone", name: "Door", status: null, area: 7, total_area: 4,
        pass_count: null, target_area_m2: 0.65 },
      { kind: "temporary_zone", name: null, status: null, area: null, total_area: null, pass_count: null },
    ], "Unknown outcome");
    assert.equal(details.hidden, false);
    assert.deepEqual(rows.children.map((row) => row.children.map((child) => child.textContent)), [
      ["Sofa", "finished", "Reported pass value 0 · Reported area 8 / 10"],
      ["Entry", "finished", "Completed passes 2 · Target 9.85 m² · 12.45 m² in completed passes"],
      ["Pantry", "finished", "Completed passes 1 · Target 0 m² · 0 m² in completed passes"],
      ["Door", "Unknown outcome", "Target 0.65 m² · Provider total area 4"],
      ["Temporary zone 5", "Unknown outcome", ""],
    ]);
    card.renderAreaResults("active", [
      { kind: "saved_zone", name: "Entry", pass_count: 0, current_pass_number: 1, target_area_m2: 9.85 },
    ], "In progress");
    assert.deepEqual(rows.children[0].children.map((child) => child.textContent),
      ["Entry", "In progress", "Pass 1 · Target 9.85 m²"]);
  } finally {
    sandbox.document.createElement = createElement;
  }
});

test("mission header shows reported totals and phase without a destination plan", () => {
  const { card } = mockCard(0);
  const panel = card.$("current-mission");
  const rows = () => panel.children.map(({ children }) => children.map(({ textContent }) => textContent));
  const current = {
    activity: "cleaning", phase: "run", mode: "vacuum", elapsed_seconds: 65, cleaned_area_m2: 0,
  };
  card.renderCurrentMission(current);
  assert.equal(panel.hidden, false);
  assert.deepEqual(rows(), [["Phase", "Cleaning"], ["Mode", "Vacuum"],
    ["Time since start", "1:05"], ["Reported area", "0 m²"]]);
  const rendered = panel.children;
  card.renderCurrentMission({ ...current });
  assert.equal(panel.children, rendered);

  card.renderCurrentMission({ ...current, activity: "paused", elapsed_seconds: 91, cleaned_area_m2: 3.8 });
  assert.deepEqual(rows(), [["Phase", "Paused"], ["Mode", "Vacuum"],
    ["Time since start", "1:31"], ["Reported area", "3.8 m²"]]);
  card.renderCurrentMission({ phase: "padWash", activity: "cleaning" });
  assert.deepEqual(rows(), [["Phase", "Washing mop"]]);
  card.renderCurrentMission({ phase: "stuck", activity: "error", error_code: 48 });
  assert.deepEqual(rows(), [["Phase", "Needs attention"]]);
  card.renderCurrentMission({ phase: "hmPostMsn", activity: "error", error_code: 48 });
  assert.deepEqual(rows(), [["Phase", "Returning to dock"]]);
  card.renderCurrentMission({ phase: "charge", activity: "error", error_code: 48 });
  assert.deepEqual(rows(), [["Phase", "At dock"]]);
  card.renderCurrentMission({ activity: "error" });
  assert.deepEqual(rows(), [["Phase", "Needs attention"]]);
  card.renderCurrentMission(null);
  assert.equal(panel.hidden, true);
  assert.deepEqual(rows(), []);
});

test("active errors show their sources and stay visible independently of the mission readout", () => {
  const { card } = mockCard(0);
  const panel = card.$("active-errors");
  const current = [
    { source: "mission", code: 48, reason: "path_blocked" },
    { source: "dock", code: 654, reason: "unknown_code" },
    { source: "evacuation", code: 353, reason: "bag_full" },
  ];
  card.renderActiveErrors(current);
  const rendered = panel.children;
  assert.deepEqual(rendered.map(({ children }) => children.map(({ textContent }) => textContent)), [
    ["Mission error", "48 · Path blocked"], ["Dock error", "654"], ["Emptying error", "353 · Bag full"],
  ]);
  card.renderActiveErrors(current.map((error) => ({ ...error })));
  assert.equal(panel.children, rendered);
  card.renderCurrentMission(null);
  assert.equal(panel.hidden, false);
  card.renderActiveErrors();
  assert.equal(panel.hidden, true);
  assert.deepEqual(panel.children, []);
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
      { ...destination, status: "in_progress", stage_elapsed_seconds: 64,
        estimated_duration_seconds: 502, reported_pass_count: 0,
        requested_settings: { suction_level: 3, two_pass: true, carpet_boost: false } } : destination),
  });
  assert.equal(summary.textContent, "Planned order · 1 of 3 completed · About 7 min left");
  assert.equal(results.children[0].children[1].children[0].children[1].textContent,
    "Vacuum · In progress · 1:04 in current stage · Reported pass value 0 · 9 min planned");
  assert.equal(results.children[0].children[1].children[0].children[2].textContent,
    "Requested · Suction 3 · Two passes on · Carpet boost off");
  card.renderMissionPlan({
    ...plan, destinations: plan.destinations.map((destination) => destination.kind === "room"
      ? { ...destination, status: "paused", cleaning_elapsed_seconds: 29, stage_elapsed_seconds: 117 }
      : destination),
  });
  assert.equal(results.children[0].children[1].children[0].children[1].textContent,
    "Vacuum · Paused · 0:29 cleaning");
  card.renderMissionPlan({ ...plan, destinations: [
    { kind: "saved_zone", name: "Entry", status: "in_progress", current_pass_number: 2,
      reported_pass_count: 1, confirmed_completed_passes: 1 },
  ] });
  assert.equal(results.children[0].children[0].children[0].children[1].textContent,
    "In progress · Pass 2 · Completed passes 1");
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
