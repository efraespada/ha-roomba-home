const WIDTH = 920;
const HEIGHT = 520;
const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter() : null;
const THEMES = {
  room: ["#243b4d", "#688294"],
  zone: ["#44366b", "#bc9af9"],
  selected: ["#195f57", "#79ecd3"],
  exclusion: ["#643e37", "#f6ac9d"],
};

const template = document.createElement("template");
template.innerHTML = `
  <style>
    :host { display:block; color:var(--primary-text-color,#e8edf2); }
    ha-card { display:block; overflow:hidden; container-type:inline-size; }
    header, footer, .content { padding:16px; }
    header { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    h2,h3,p { margin:0; } h2 { font-size:20px; font-weight:650; } h3 { font-size:14px; margin-bottom:8px; }
    .muted { color:var(--secondary-text-color,#a9b8c5); font-size:13px; }
    .scene { position:relative; isolation:isolate; background:#101e2a; }
    canvas { width:100%; height:auto; display:block; touch-action:pan-y; cursor:crosshair; }
    .zoom { position:absolute; right:10px; top:10px; display:grid; gap:4px; }
    button,select {
      color:inherit; background:var(--card-background-color,#293747);
      border:1px solid var(--divider-color,#647382); border-radius:8px; padding:7px 10px;
      min-height:34px; font:inherit; font-size:13px; cursor:pointer;
    }
    button:focus-visible, select:focus-visible { outline:2px solid var(--primary-color,#54d2b7); outline-offset:2px; }
    button[aria-pressed="true"], .primary { background:#116853; color:white; border-color:#4ac5a4; }
    button:disabled { cursor:default; opacity:.54; }
    .zoom button { min-width:36px; }
    #regions,.legend { display:flex; gap:7px; flex-wrap:wrap; }
    .legend { gap:14px; margin:0 0 14px; }
    .legend span::before { content:""; display:inline-block; margin-right:6px; width:9px; height:9px; border-radius:2px; background:var(--swatch); }
    footer { display:flex; align-items:center; justify-content:space-between; border-top:1px solid var(--divider-color,#647382); gap:8px; }
    #status { min-height:1.4em; }
    dialog { color:inherit; background:var(--card-background-color,#243141); border:1px solid var(--divider-color,#647382); border-radius:12px; max-width:min(380px,90vw); }
    dialog::backdrop { background:#0b1726ad; }
    dialog p { margin:10px 0 18px; }
    dialog .actions { display:flex; justify-content:flex-end; gap:8px; }
    details { margin-top:15px; }
    summary { cursor:pointer; }
    .result { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 12px; margin-top:9px; }
    .result div { grid-column:1/-1; }
    @container (max-width:360px) { footer { align-items:flex-start; flex-direction:column; } }
    [hidden] { display:none !important; }
  </style>
  <ha-card>
    <header>
      <div><h2 id="title">Roomba floor plan</h2><p id="activity" class="muted"></p></div>
      <select id="maps" aria-label="Floor plan" hidden></select>
    </header>
    <div class="scene">
      <canvas width="${WIDTH}" height="${HEIGHT}" aria-label="Floor plan. Use the area buttons to select without a pointer."></canvas>
      <div class="zoom">
        <button id="zoom-in" aria-label="Zoom in">+</button>
        <button id="zoom-out" aria-label="Zoom out">−</button>
        <button id="reset" aria-label="Reset map view">↺</button>
      </div>
    </div>
    <div class="content">
      <div class="legend muted">
        <span style="--swatch:#79ecd3">Selected</span>
        <span id="zone-key" style="--swatch:#bc9af9" hidden>Saved zone</span>
        <span id="exclusion-key" style="--swatch:#f6ac9d" hidden>Keep-out area or wall</span>
      </div>
      <h3>Cleaning areas</h3><div id="regions"></div>
      <details id="active" hidden><summary>Current mission measurements</summary><div></div></details>
      <details id="history" hidden><summary>Last mission by room</summary><div></div></details>
    </div>
    <footer><span id="status" class="muted" role="status">Loading floor plan…</span>
      <button id="review" class="primary" disabled>Review selection</button>
    </footer>
    <dialog aria-labelledby="confirm-title">
      <h3 id="confirm-title">Start cleaning?</h3><p id="confirm-text"></p>
      <div class="actions"><button id="cancel">Cancel</button><button id="start" class="primary">Start cleaning</button></div>
    </dialog>
  </ha-card>`;

function pathFor(rings, xy) {
  const path = new Path2D();
  for (const ring of rings) {
    const [first, ...points] = ring;
    path.moveTo(...xy(first));
    for (const point of points) path.lineTo(...xy(point));
    path.closePath();
  }
  return path;
}

class RoombaHomeMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).append(template.content.cloneNode(true));
    this.canvas = this.shadowRoot.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.selected = new Set();
    this.zoom = 1;
    this.pan = [0, 0];
    this.sequence = 0;
    this.$("maps").onchange = (event) => {
      this.floor = event.target.value;
      this.geometry = null;
      this.clearSelection();
      this.resetView();
      this.refresh(true);
    };
    this.$("zoom-in").onclick = () => this.setZoom(this.zoom * 1.25);
    this.$("zoom-out").onclick = () => this.setZoom(this.zoom / 1.25);
    this.$("reset").onclick = () => this.resetView();
    this.$("review").onclick = () => this.review();
    this.$("cancel").onclick = () => this.dialog.close();
    this.$("start").onclick = () => this.submit();
    this.canvas.onpointerdown = (event) => {
      this.pointer = { x: event.clientX, y: event.clientY, pan: [...this.pan], moving: false };
    };
    this.canvas.onpointermove = (event) => this.panMap(event);
    this.canvas.onpointerup = (event) => {
      if (this.pointer && !this.pointer.moving) this.pick(event);
      this.pointer = null;
    };
    this.canvas.onpointercancel = () => { this.pointer = null; };
  }

  $(id) { return this.shadowRoot.getElementById(id); }

  get dialog() { return this.shadowRoot.querySelector("dialog"); }

  setConfig(config) {
    if (!/^vacuum\.[a-z0-9_]+$/.test(config.entity ?? "")) {
      throw new Error("Choose a Roomba vacuum entity.");
    }
    if (this.config?.entity === config.entity) return;
    this.config = config;
    this.floor = null;
    this.geometry = null;
    this.snapshot = null;
    this.clearSelection();
    this.resetView();
    this.refresh(true);
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this.refresh();
  }

  connectedCallback() {
    this.timer = window.setInterval(() => { this.draw(); this.refresh(); }, 5000);
    this.refresh();
  }

  disconnectedCallback() {
    window.clearInterval(this.timer);
    this.timer = null;
    this.sequence++;
    this.loading = false;
  }

  async refresh(force = false) {
    if (!this.isConnected || !this.config || !this._hass || (this.loading && !force)) return;
    const sequence = ++this.sequence;
    this.loading = true;
    const query = { type: "roomba_home/floor_plan", entity_id: this.config.entity };
    if (this.floor) query.map_id = this.floor;
    if (this.geometry) query.known_version = this.snapshot.map.version;
    try {
      const data = await this._hass.callWS(query);
      if (sequence !== this.sequence) return;
      const changed = this.snapshot?.map.id !== data.map.id ||
        this.snapshot?.map.version !== data.map.version;
      if (changed) {
        this.clearSelection();
        this.resetView();
      }
      this.snapshot = data;
      this.floor = data.map.id;
      if (data.geometry) this.geometry = data.geometry;
      if (changed || !this.geometry || this.renderedGeometry !== this.geometry) this.renderAreas();
      this.$("title").textContent = data.robot;
      this.$("activity").textContent = data.current_room ? `Current room · ${data.current_room}` : "";
      this.renderRoomResults("active", data.active_rooms ?? [], "In progress");
      this.renderRoomResults("history", data.last_mission_rooms, "Unknown outcome");
      this.draw();
      this.updateSelection();
    } catch (error) {
      if (sequence !== this.sequence) return;
      this.snapshot = null;
      this.geometry = null;
      this.clearSelection();
      this.renderAreas();
      this.renderRoomResults("active", [], "In progress");
      this.renderRoomResults("history", [], "Unknown outcome");
      this.draw();
      this.$("activity").textContent = "";
      this.$("status").textContent = error?.message || "Floor plan unavailable.";
    } finally {
      if (sequence === this.sequence) this.loading = false;
    }
  }

  renderAreas() {
    this.renderedGeometry = this.geometry;
    const container = this.$("regions");
    const floors = this.$("maps");
    floors.replaceChildren();
    for (const [index, map] of (this.snapshot?.maps ?? []).entries()) {
      const option = document.createElement("option");
      option.value = map.id;
      option.textContent = map.name || `Floor ${index + 1}`;
      floors.append(option);
    }
    floors.value = this.floor ?? "";
    floors.hidden = floors.options.length < 2;
    container.replaceChildren();
    this.buttons = new Map();
    for (const region of this.geometry?.regions ?? []) {
      if (!region.id) continue;
      const button = document.createElement("button");
      button.textContent = region.name;
      button.dataset.kind = region.kind;
      button.onclick = () => this.toggle(region.id);
      container.append(button);
      this.buttons.set(region.id, button);
    }
    this.$("zone-key").hidden = !this.geometry?.regions.some((region) => region.kind === "zone");
    this.$("exclusion-key").hidden = !this.geometry?.keep_out.length && !this.geometry?.virtual_walls.length;
  }

  renderRoomResults(id, rooms, defaultStatus) {
    const view = this.$(id);
    const rows = view.querySelector("div");
    const signature = JSON.stringify(rooms);
    if (signature === view.dataset.results) return;
    view.dataset.results = signature;
    view.hidden = !rooms.length;
    rows.replaceChildren();
    for (const [index, room] of rooms.entries()) {
      const row = document.createElement("div");
      row.className = "result";
      const name = document.createElement("strong");
      name.textContent = room.room || `Room ${index + 1}`;
      const status = document.createElement("span");
      status.className = "muted";
      status.textContent = room.status?.replaceAll("_", " ") ?? defaultStatus;
      const metrics = document.createElement("div");
      const values = [];
      if (room.pass_count !== null) values.push(`Passes ${room.pass_count}`);
      if (room.area !== null) values.push(`Reported area ${room.area}${room.total_area !== null ? ` / ${room.total_area}` : ""}`);
      metrics.className = "muted";
      metrics.textContent = values.join(" · ");
      row.append(name, status, metrics);
      rows.append(row);
    }
  }

  clearSelection() {
    this.selected.clear();
    if (this.dialog.open) this.dialog.close();
    this.updateSelection();
  }

  toggle(id) {
    this.operationMessage = null;
    if (this.selected.has(id)) this.selected.delete(id);
    else if (this.selected.size < 32) this.selected.add(id);
    this.updateSelection();
    this.draw();
  }

  updateSelection() {
    for (const [id, button] of this.buttons ?? []) {
      button.setAttribute("aria-pressed", this.selected.has(id));
    }
    this.$("review").disabled = !this.selected.size || this.submitting;
    if (this.snapshot && !this.operationMessage) {
      this.$("status").textContent = this.selected.size
        ? `${this.selected.size} selected` : "Select a room or saved zone.";
    }
  }

  review() {
    const data = this.snapshot;
    if (!data || !this.selected.size || this.submitting) return;
    this.operationMessage = null;
    const names = this.geometry.regions.filter((area) => this.selected.has(area.id)).map((area) => area.name);
    this.confirmation = { ...data.map, regions: [...this.selected] };
    this.$("confirm-text").textContent = `${data.robot} will clean ${names.join(", ")}.`;
    this.dialog.showModal();
  }

  async submit() {
    const choice = this.confirmation;
    if (!choice || this.submitting || !this.snapshot ||
        choice.id !== this.snapshot.map.id || choice.version !== this.snapshot.map.version) return;
    this.submitting = true;
    this.dialog.close();
    this.updateSelection();
    this.operationMessage = "Sending cleaning request…";
    this.$("status").textContent = this.operationMessage;
    try {
      await this._hass.callService("roomba_home", "clean_map_selection", {
        map_id: choice.id, version: choice.version, regions: choice.regions,
      }, { entity_id: this.config.entity });
      this.selected.clear();
      this.draw();
      this.operationMessage = "Cleaning request sent. Check the robot state.";
    } catch (error) {
      this.operationMessage = error?.message || "The robot did not accept the request.";
    } finally {
      this.submitting = false;
      this.$("status").textContent = this.operationMessage;
      this.updateSelection();
    }
  }

  setZoom(zoom) {
    this.zoom = Math.min(4, Math.max(1, zoom));
    if (this.zoom === 1) this.pan = [0, 0];
    this.draw();
  }

  resetView() {
    this.pan = [0, 0];
    this.setZoom(1);
  }

  panMap(event) {
    if (!this.pointer || this.zoom === 1) return;
    const dx = event.clientX - this.pointer.x;
    const dy = event.clientY - this.pointer.y;
    if (!this.pointer.moving && Math.hypot(dx, dy) < 5) return;
    this.pointer.moving = true;
    const bounds = this.canvas.getBoundingClientRect();
    const limit = (pan, extent) => Math.min(extent * this.zoom / 2, Math.max(-extent * this.zoom / 2, pan));
    this.pan = [
      limit(this.pointer.pan[0] + dx * WIDTH / bounds.width, WIDTH),
      limit(this.pointer.pan[1] + dy * HEIGHT / bounds.height, HEIGHT),
    ];
    this.draw();
  }

  pick(event) {
    const bounds = this.canvas.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * WIDTH / bounds.width;
    const y = (event.clientY - bounds.top) * HEIGHT / bounds.height;
    if (this.exclusions.some((path) => this.ctx.isPointInPath(path, x, y, "evenodd"))) return;
    this.ctx.lineWidth = 12;
    if (this.walls.some((path) => this.ctx.isPointInStroke(path, x, y))) return;
    const hit = this.targets.findLast(({ path }) => this.ctx.isPointInPath(path, x, y, "evenodd"));
    if (hit) this.toggle(hit.id);
  }

  draw() {
    const ctx = this.ctx;
    ctx.fillStyle = "#101e2a";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    this.targets = [];
    this.exclusions = [];
    this.walls = [];
    if (!this.geometry) return;
    const { regions, keep_out: keepOut, virtual_walls: walls } = this.geometry;
    const points = regions.flatMap((region) => region.polygons.flat(2));
    if (!points.length) return;
    const extent = points.reduce(([left, top, right, bottom], [x, y]) =>
      [Math.min(left, x), Math.min(top, y), Math.max(right, x), Math.max(bottom, y)],
      [Infinity, Infinity, -Infinity, -Infinity]);
    const [left, top, right, bottom] = extent;
    const scale = this.zoom * Math.min((WIDTH - 60) / (right - left || 1),
      (HEIGHT - 60) / (bottom - top || 1));
    const xy = ([x, y]) => [WIDTH / 2 + this.pan[0] + (x - (left + right) / 2) * scale,
      HEIGHT / 2 + this.pan[1] - (y - (top + bottom) / 2) * scale];

    for (const kind of ["room", "zone"]) {
      for (const region of regions.filter((area) => area.kind === kind)) {
        for (const polygon of region.polygons) {
          const path = pathFor(polygon, xy);
          [ctx.fillStyle, ctx.strokeStyle] = THEMES[this.selected.has(region.id) ? "selected" : kind];
          ctx.lineWidth = this.selected.has(region.id) ? 3 : 1.5;
          ctx.fill(path, "evenodd");
          ctx.stroke(path);
          if (region.id) this.targets.push({ path, id: region.id });
          this.drawLabel(region.name, polygon[0], path, xy);
        }
      }
    }
    for (const polygon of keepOut) {
      const path = pathFor(polygon, xy);
      [ctx.fillStyle, ctx.strokeStyle] = THEMES.exclusion;
      ctx.fill(path, "evenodd");
      ctx.setLineDash([6, 4]);
      ctx.stroke(path);
      ctx.setLineDash([]);
      this.exclusions.push(path);
    }
    ctx.strokeStyle = THEMES.exclusion[1];
    ctx.lineWidth = 3;
    ctx.setLineDash([6, 4]);
    for (const [start, ...points] of walls) {
      const path = new Path2D();
      path.moveTo(...xy(start));
      for (const point of points) path.lineTo(...xy(point));
      ctx.stroke(path);
      this.walls.push(path);
    }
    ctx.setLineDash([]);
    this.drawLive(xy);
  }

  drawLabel(name, outer, path, xy) {
    if (!name) return;
    name = name.normalize("NFC");
    const ctx = this.ctx;
    const [left, top, right, bottom] = outer.map(xy).reduce(
      ([x0, y0, x1, y1], [x, y]) => [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)],
      [Infinity, Infinity, -Infinity, -Infinity],
    );
    const x = (left + right) / 2;
    const y = (top + bottom) / 2;
    const maxWidth = right - left - 16;
    if (maxWidth < 34 || !ctx.isPointInPath(path, x, y, "evenodd")) return;
    ctx.font = "600 16px system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#eef7fb";
    const fits = (label) => {
      const half = ctx.measureText(label).width / 2;
      return half * 2 <= maxWidth && [-half, half].every((offset) =>
        [-8, 8].every((height) => ctx.isPointInPath(path, x + offset, y + height, "evenodd")));
    };
    if (fits(name)) {
      ctx.fillText(name, x, y);
      return;
    }
    const graphemes = segmenter ? Array.from(segmenter.segment(name), ({ segment }) => segment) : Array.from(name);
    while (graphemes.length > 1) {
      graphemes.pop();
      const label = `${graphemes.join("")}…`;
      if (fits(label)) {
        ctx.fillText(label, x, y);
        return;
      }
    }
  }

  drawLive(xy) {
    const ctx = this.ctx;
    const live = this.snapshot?.live;
    if (!live) return;
    ctx.strokeStyle = "#80e9ff";
    ctx.lineWidth = 3;
    ctx.beginPath();
    let previous = null;
    for (const [sequence, x, y] of live.trail) {
      if (sequence === previous + 1 && previous !== null) ctx.lineTo(...xy([x, y]));
      else ctx.moveTo(...xy([x, y]));
      previous = sequence;
    }
    ctx.stroke();
    const position = live.position;
    if (!position || position.expires_at <= Date.now() / 1000) return;
    const [x, y] = xy([position.x, position.y]);
    const heading = position.orientation + Math.PI;
    ctx.fillStyle = "#80e9ff";
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = "#f1f9ff";
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 18 * Math.cos(heading), y - 18 * Math.sin(heading));
    ctx.stroke();
  }

  getCardSize() { return 6; }
}

customElements.define("roomba-home-map-card", RoombaHomeMapCard);
(window.customCards ??= []).push({
  type: "roomba-home-map-card",
  name: "Roomba Home floor plan",
  description: "View live cleaning and select rooms or saved zones.",
});
