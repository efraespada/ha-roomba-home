const WIDTH = 920;
const HEIGHT = 520;
const QUARTER_TURN = Math.PI / 2;
const MAX_LIVE_POINTS = 2048;
const MAX_LIVE_TRANSITION_SECONDS = 6;
const MAX_LIVE_TRANSITION_MS = 1800;
const WALL_HEIGHT = 2.2;
const OBLIQUE_PITCH = 0.55;
const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter() : null;
const THEMES = {
  room: ["#243b4d", "#688294"],
  zone: ["#44366b", "#bc9af9"],
  selected: ["#195f57", "#79ecd3"],
  exclusion: ["#643e37", "#f6ac9d"],
  noMop: ["#f3cf7233", "#f3cf72"],
  furniture: ["#adbfd83d", "#bfd1e5"],
};
const MODES = {
  vacuum: "Vacuum",
  mop: "Mop",
  vacuum_mop: "Vacuum and mop",
  vacuum_then_mop: "Vacuum then mop",
};
const SETTINGS = {
  suction_level: "Suction",
  wetness_level: "Mop wetness",
  two_pass: "Two passes",
  smart_scrub: "SmartScrub",
  carpet_boost: "Carpet boost",
};
const PRESET_LABELS = { light: "Light", normal: "Normal", deep: "Deep", smart: "Smart recommendations" };
const RESTRICTION_TYPES = { keep_out: "Keep-out zone", no_mop: "No-mop zone", wall: "Virtual wall" };
const PROGRAM_RECOVERY_STATUS = {
  missing_program: "Program deleted",
  unsupported_selection: "Current selection cannot be edited",
  changed_selection: "Destinations or settings have changed",
  unchanged: "Saved destinations already match",
  restore_zones_first: "Restore the matching cleaning zones first",
  restore_areas_first: "Restore the matching furniture and cleaning zones first",
  unavailable_destination: "A destination or setting is unavailable",
  source_unavailable: "Roomba could not load this program",
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
    #live-marker { position:absolute; inset:0; pointer-events:none; }
    .zoom { position:absolute; right:10px; top:10px; display:grid; gap:4px; }
    button,select,input {
      color:inherit; background:var(--card-background-color,#293747);
      border:1px solid var(--divider-color,#647382); border-radius:8px; padding:7px 10px;
      min-height:34px; font:inherit; font-size:13px; cursor:pointer;
    }
    button:focus-visible, select:focus-visible { outline:2px solid var(--primary-color,#54d2b7); outline-offset:2px; }
    button[aria-pressed="true"], .primary { background:#116853; color:white; border-color:#4ac5a4; }
    button:disabled { cursor:default; opacity:.54; }
    .zoom button { min-width:36px; }
    #regions,.legend { display:flex; gap:7px; flex-wrap:wrap; }
    #zone-notice { margin-top:10px; }
    .map-actions { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
    .map-editor { display:grid; gap:10px; margin:0 0 16px; padding:12px; border:1px solid var(--divider-color,#647382); border-radius:8px; }
    .map-editor label { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
    .divider-coordinates { display:grid; grid-template-columns:repeat(auto-fit,minmax(125px,1fr)); gap:6px; margin-top:8px; }
    .divider-coordinates input { min-width:0; width:100%; box-sizing:border-box; }
    #impact-list { padding-left:22px; }
    .legend { gap:14px; margin:0 0 14px; }
    #coverage-vacuum { accent-color:#59adff; }
    #coverage-mop { accent-color:#4ed9ad; }
    #live-obstacles { accent-color:#ffad55; }
    .legend span::before { content:""; display:inline-block; margin-right:6px; width:9px; height:9px; border-radius:2px; background:var(--swatch); }
    footer { display:flex; align-items:center; justify-content:space-between; border-top:1px solid var(--divider-color,#647382); gap:8px; }
    #status { min-height:1.4em; }
    dialog { color:inherit; background:var(--card-background-color,#243141); border:1px solid var(--divider-color,#647382); border-radius:12px; max-width:min(380px,90vw); }
    dialog::backdrop { background:#0b1726ad; }
    dialog p { margin:10px 0 18px; }
    dialog .actions { display:flex; justify-content:flex-end; gap:8px; }
    #routine-dialog { width:min(34rem, calc(100vw - 3rem)); max-width:none; }
    #mission-history-dialog { width:min(55rem, calc(100vw - 3rem)); max-width:none; }
    #cleaning-scores-dialog { width:min(36rem, calc(100vw - 3rem)); max-width:none; }
    #scores-rooms section { border-top:1px solid var(--divider-color,#647382); margin:12px 0; padding-top:10px; }
    #mission-history-dialog select { max-width:100%; }
    #history-map { background:#101e2a; cursor:grab; touch-action:none; }
    #history-status:empty, #scores-status:empty { display:none; }
    .measurements { display:grid; grid-template-columns:repeat(auto-fit,minmax(100px,1fr)); gap:8px; }
    .measurements dd { margin:0; font-weight:650; }
    #history-timeline { padding-inline-start:22px; }
    #routine-dialog .actions { flex-wrap:wrap; margin-top:12px; }
    #map-backups-dialog .actions { flex-wrap:wrap; margin-top:8px; }
    #map-backup-choice { max-width:100%; }
    #map-backup-controls details { margin-top:8px; }
    #routine-form { display:grid; gap:10px; }
    #routine-form label, .routine-field { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:6px; }
    #schedule-fields { display:grid; gap:8px; }
    #schedule-days .actions { justify-content:flex-start; margin-top:0; }
    #routine-list { flex:1; min-width:0; }
    #quick-routines { margin:8px 0; padding-inline-start:22px; }
    #quick-routines li + li { margin-top:6px; }
    #quick-routines li > :last-child { margin-inline-start:8px; }
    #routine-regions { display:grid; gap:10px; margin:0; padding-left:24px; }
    #routine-regions li { padding:8px; border:1px solid var(--divider-color,#647382); border-radius:8px; }
    .routine-region-controls { display:flex; gap:4px; flex-wrap:wrap; margin:6px 0; }
    details { margin-top:15px; }
    summary { cursor:pointer; }
    .result { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 12px; margin-top:9px; }
    .result div { grid-column:1/-1; }
    #mission-plan ol, #mission-plan ul { padding-inline-start:22px; }
    #mission-plan li { margin-block:5px; }
    #mission-plan li .result {
      grid-template-columns:minmax(0,1fr) fit-content(50%); margin-top:0; overflow-wrap:anywhere;
    }
    #mission-plan li .muted { text-align:end; }
    @container (max-width:360px) { footer { align-items:flex-start; flex-direction:column; } }
    [hidden] { display:none !important; }
  </style>
  <ha-card>
    <header>
      <div>
        <h2 id="title">Roomba floor plan</h2>
        <p id="floor-name" class="muted" hidden></p>
        <p id="activity" class="muted"></p>
      </div>
      <select id="maps" aria-label="Floor plan" hidden></select>
      <button id="open-mission-history">Cleaning history</button>
    </header>
    <div id="scene" class="scene">
      <canvas width="${WIDTH}" height="${HEIGHT}" aria-label="Floor plan. Use the controls below to select with the keyboard."></canvas>
      <canvas id="live-marker" width="${WIDTH}" height="${HEIGHT}" aria-hidden="true"></canvas>
      <div class="zoom">
        <button id="zoom-in" aria-label="Zoom in">+</button>
        <button id="zoom-out" aria-label="Zoom out">−</button>
        <button id="reset" aria-label="Reset map view">↺</button>
        <button id="orbit-map" aria-label="Rotate 3D view clockwise" hidden>⟳</button>
      </div>
    </div>
    <div class="content">
      <p id="live-map-legend" class="legend muted" aria-label="Live route legend" hidden></p>
      <div id="live-path-controls" class="legend muted" role="group" aria-label="Live path layers" hidden>
        <label><input id="live-cleaning-path" type="checkbox" checked> Cleaning path</label>
        <label><input id="live-travel-path" type="checkbox" checked> Travel path</label>
      </div>
      <div id="live-coverage-controls" class="legend muted" role="group" aria-label="Estimated coverage" hidden>
        <strong>Estimated coverage</strong>
        <label><input id="coverage-vacuum" type="checkbox" checked> Vacuum</label>
        <label><input id="coverage-mop" type="checkbox" checked> Mop</label>
      </div>
      <div id="live-obstacle-controls" class="legend muted" hidden>
        <label><input id="live-obstacles" type="checkbox" checked> Temporary obstacles</label>
      </div>
      <section id="floor-editor" class="map-editor" aria-label="Edit floor settings" hidden>
        <label>Operation
          <select id="floor-operation">
            <option value="rename">Rename floor</option>
            <option value="rotate">Rotate floor</option>
          </select>
        </label>
        <label id="floor-name-label">Floor name <input id="edit-floor-name" maxlength="16" autocomplete="off"></label>
        <div id="floor-rotate-controls" hidden>
          <button id="floor-rotate-left">Rotate left 90°</button>
          <button id="floor-rotate-right">Rotate right 90°</button>
          <p id="floor-rotation-preview" class="muted" aria-live="polite"></p>
        </div>
        <p id="floor-edit-status" class="muted" role="status"></p>
        <div class="map-actions">
          <button id="close-floor-editor">Cancel</button>
          <button id="review-floor-edit" class="primary">Review floor edit</button>
        </div>
      </section>
      <section id="room-editor" class="map-editor" aria-label="Room editor" hidden>
        <label>Operation
          <select id="room-operation">
            <option value="split">Divide a room</option>
            <option value="merge">Merge rooms</option>
            <option id="rename-room-option" value="rename" hidden>Rename a room</option>
          </select>
        </label>
        <label>Room <select id="edit-room-first"></select></label>
        <label id="edit-room-second-label">Adjacent room <select id="edit-room-second"></select></label>
        <div id="rename-room-controls" hidden>
          <label>Room type <select id="edit-room-type"></select></label>
          <label>Room name <input id="edit-room-name" autocomplete="off"></label>
        </div>
        <div id="split-controls">
          <p class="muted">Place the divider across the selected room, from one side of the boundary to the other.</p>
          <button id="place-divider">Place divider on map</button>
          <details><summary>Divider coordinates</summary>
            <div class="divider-coordinates">
              <label>Start X <input id="divider-x1" type="number" step="any"></label>
              <label>Start Y <input id="divider-y1" type="number" step="any"></label>
              <label>End X <input id="divider-x2" type="number" step="any"></label>
              <label>End Y <input id="divider-y2" type="number" step="any"></label>
            </div>
          </details>
        </div>
        <p id="room-edit-status" class="muted" role="status"></p>
        <div class="map-actions"><button id="close-room-editor">Cancel</button><button id="review-room-edit" class="primary">Review map edit</button></div>
      </section>
      <section id="zone-editor" class="map-editor" aria-label="Cleaning zones" hidden>
        <label>Operation
          <select id="zone-operation">
            <option value="create">Add a cleaning zone</option>
            <option value="update">Edit a cleaning zone</option>
            <option value="delete">Remove a cleaning zone</option>
          </select>
        </label>
        <label id="zone-select-label">Zone <select id="edit-zone"></select></label>
        <p id="zone-availability" class="muted" hidden></p>
        <div id="zone-shape">
          <label>Zone name <input id="zone-name" maxlength="16" autocomplete="off"></label>
          <div class="map-actions"><button id="place-zone">Place rectangle on map</button></div>
          <details><summary>Rectangle coordinates</summary>
            <div class="divider-coordinates">
              <label>First corner X <input id="zone-x1" type="number" step="any"></label>
              <label>First corner Y <input id="zone-y1" type="number" step="any"></label>
              <label>Opposite corner X <input id="zone-x2" type="number" step="any"></label>
              <label>Opposite corner Y <input id="zone-y2" type="number" step="any"></label>
            </div>
          </details>
        </div>
        <p id="zone-edit-status" class="muted" role="status"></p>
        <div class="map-actions"><button id="close-zone-editor">Cancel</button><button id="review-zone-edit" class="primary">Review zone edit</button></div>
      </section>
      <section id="restriction-editor" class="map-editor" aria-label="Edit restrictions" hidden>
        <label>Operation
          <select id="restriction-operation">
            <option value="create">Add a restriction</option>
            <option value="update">Move or resize a restriction</option>
            <option value="delete">Remove a restriction</option>
          </select>
        </label>
        <label id="restriction-kind-label">Type
          <select id="restriction-kind">
            <option value="keep_out">Keep-out zone</option>
            <option value="no_mop">No-mop zone</option>
            <option value="wall">Virtual wall</option>
          </select>
        </label>
        <label id="restriction-select-label">Restriction <select id="restriction-target"></select></label>
        <div id="restriction-shape">
          <button id="place-restriction">Place rectangle on map</button>
          <details><summary id="restriction-coordinate-title">Rectangle coordinates</summary>
            <div class="divider-coordinates">
              <label><span id="restriction-x1-label">First corner X</span> <input id="restriction-x1" type="number" step="any"></label>
              <label><span id="restriction-y1-label">First corner Y</span> <input id="restriction-y1" type="number" step="any"></label>
              <label><span id="restriction-x2-label">Opposite corner X</span> <input id="restriction-x2" type="number" step="any"></label>
              <label><span id="restriction-y2-label">Opposite corner Y</span> <input id="restriction-y2" type="number" step="any"></label>
            </div>
          </details>
        </div>
        <p id="restriction-edit-status" class="muted" role="status"></p>
        <div class="map-actions">
          <button id="close-restriction-editor">Cancel</button>
          <button id="review-restriction-edit" class="primary">Review restriction</button>
        </div>
      </section>
      <section id="furniture-editor" class="map-editor" aria-label="Furniture editor" hidden>
        <label>Operation
          <select id="furniture-operation">
            <option value="create">Add furniture</option>
            <option value="update">Move, resize, or rotate</option>
            <option value="delete">Remove furniture</option>
          </select>
        </label>
        <label id="furniture-kind-label">Type <select id="furniture-kind"></select></label>
        <label id="furniture-target-label">Furniture <select id="furniture-target"></select></label>
        <div id="furniture-placement">
          <button id="place-furniture">Place on map</button>
          <div class="divider-coordinates">
            <label>Center X <input id="furniture-x" type="number" step="any"></label>
            <label>Center Y <input id="furniture-y" type="number" step="any"></label>
            <label>Width (m) <input id="furniture-width" type="number" step="any" min="0"></label>
            <label>Depth (m) <input id="furniture-depth" type="number" step="any" min="0"></label>
            <label>Rotation (°) <input id="furniture-angle" type="number" step="any" min="-360" max="360"></label>
          </div>
        </div>
        <p id="furniture-status" class="muted" role="status"></p>
        <div class="map-actions">
          <button id="close-furniture-editor">Cancel</button>
          <button id="review-furniture-edit" class="primary">Review furniture edit</button>
        </div>
      </section>
      <div class="legend muted">
        <span style="--swatch:#79ecd3">Selected</span>
        <span id="zone-key" style="--swatch:#bc9af9" hidden>Saved zone</span>
        <span id="exclusion-key" style="--swatch:#f6ac9d" hidden>Keep-out area or wall</span>
        <span id="no-mop-key" style="--swatch:#f3cf72" hidden>No-mop area</span>
        <span id="carpet-key" style="--swatch:#90aeb970" hidden>Detected carpet</span>
        <span id="dock-key" style="--swatch:#7dd9e4" hidden>Dock</span>
        <span id="point-key" style="--swatch:#fcf6e8" hidden></span>
      </div>
      <h3 id="target-heading">Cleaning areas</h3><div id="regions"></div>
      <label id="point-cleaning-settings" hidden>Cleaning mode <select id="point-cleaning-mode"></select></label>
      <details id="point-picker" hidden>
        <summary>Enter a position in a room</summary>
        <div class="divider-coordinates">
          <label>Room <select id="point-room"></select></label>
          <label>Map X (%) <input id="point-x" type="number" min="0" max="100" step="any" value="50"></label>
          <label>Map Y (%) <input id="point-y" type="number" min="0" max="100" step="any" value="50"></label>
        </div>
        <button id="place-point">Place point</button>
      </details>
      <p id="zone-notice" class="muted" role="status" hidden></p>
      <div class="map-actions">
        <button id="review-mapping" hidden>Map a floor</button>
        <button id="point-mode" hidden aria-pressed="false">Clean a point</button>
        <button id="edit-floor" hidden>Floor settings</button>
        <button id="review-remove-floor" hidden>Remove floor</button>
        <button id="edit-rooms" hidden>Edit rooms</button>
        <button id="edit-zones" hidden>Edit cleaning zones</button>
        <button id="edit-restrictions" hidden>Edit restrictions</button>
        <button id="show-3d" hidden aria-pressed="false">3D view</button>
        <button id="show-furniture" hidden aria-pressed="false">Show furniture</button>
        <button id="edit-furniture" hidden>Edit furniture</button>
        <button id="manage-routines" hidden>Manage routines</button>
        <button id="manage-schedules" hidden>Manage schedules</button>
        <button id="open-map-backups">Map backups</button>
        <button id="open-cleaning-scores" hidden>Room cleaning scores</button>
        <button id="map-impact" hidden disabled>Review map dependencies</button>
        <button id="review-skip" hidden>Skip current area</button>
      </div>
      <details id="mission-plan" open hidden><summary></summary><div></div></details>
      <details id="active" hidden><summary>Current mission measurements</summary><div></div></details>
      <details id="history" hidden><summary>Last mission by area</summary><div></div></details>
    </div>
    <footer><span id="status" class="muted" role="status">Loading floor plan…</span>
      <button id="review" class="primary" disabled>Review selection</button>
    </footer>
    <dialog id="cleaning-scores-dialog" aria-labelledby="cleaning-scores-title">
      <h3 id="cleaning-scores-title">Room cleaning scores</h3>
      <p id="scores-status" class="muted" role="status"></p>
      <dl id="scores-summary" class="measurements" hidden></dl>
      <div id="scores-rooms"></div>
      <div class="actions"><button id="close-cleaning-scores">Close</button></div>
    </dialog>
    <dialog id="mission-history-dialog" aria-labelledby="mission-history-title">
      <h3 id="mission-history-title">Recent cleaning reports</h3>
      <p id="history-status" class="muted" role="status"></p>
      <p id="history-totals" class="muted" hidden></p>
      <label id="history-selector" hidden>Report <select id="history-mission"></select></label>
      <div id="history-detail" hidden>
        <dl id="history-measurements" class="measurements"></dl>
        <label id="history-map-selector" hidden>Mission map <select id="history-map-index"></select></label>
        <section id="history-map-view" aria-label="Mission map" hidden>
          <canvas id="history-map" width="${WIDTH}" height="${HEIGHT}" aria-label="Recorded floor, coverage and robot route"></canvas>
          <div class="map-actions">
            <button id="history-zoom-in" aria-label="Zoom in on recorded map">+</button>
            <button id="history-zoom-out" aria-label="Zoom out of recorded map">−</button>
            <button id="history-reset">Reset map view</button>
            <button id="history-3d" aria-pressed="false" hidden>3D view</button>
            <button id="history-orbit" aria-label="Rotate recorded map" hidden>⟳</button>
          </div>
          <p class="legend muted" id="history-map-legend"></p>
        </section>
        <p id="history-no-map" class="muted" hidden>Roomba has no map for this report.</p>
        <details id="history-area-results" hidden><summary>Results by area</summary><div></div></details>
        <details id="history-chronology" hidden><summary>Timeline</summary><ol id="history-timeline"></ol></details>
      </div>
      <div class="actions"><button id="close-mission-history">Close</button></div>
    </dialog>
    <dialog id="confirm-dialog" aria-labelledby="confirm-title">
      <h3 id="confirm-title">Start cleaning?</h3><p id="confirm-text"></p>
      <div class="actions"><button id="cancel">Cancel</button><button id="start" class="primary">Start cleaning</button></div>
    </dialog>
    <dialog id="map-backups-dialog" aria-labelledby="map-backups-title">
      <h3 id="map-backups-title">Map backups</h3>
      <p id="map-backups-status" class="muted" role="status"></p>
      <section id="map-backup-detail" hidden>
        <label>Backup <select id="map-backup-choice"></select></label>
        <p id="map-backup-comparison" class="muted" hidden></p>
        <canvas id="map-backup-preview" width="${WIDTH}" height="${HEIGHT}" role="img" aria-label="Saved floor plan"></canvas>
        <p id="map-backup-legend" class="legend muted"></p>
        <div class="actions">
          <button id="export-map-backup">Export backup</button>
          <button id="review-map-backup-restore" hidden>Restore floor settings</button>
          <button id="review-map-backup-room-details" hidden>Restore room names and types</button>
          <button id="review-map-backup-zones" hidden>Restore cleaning zones</button>
          <button id="review-map-backup-restrictions" hidden>Restore restrictions</button>
          <button id="review-map-backup-furniture" hidden>Restore furniture</button>
          <button id="review-map-backup-programs" hidden>Recover program destinations</button>
          <button id="pin-map-backup" hidden>Pin backup</button>
          <button id="delete-map-backup" hidden>Delete backup</button>
        </div>
        <section id="map-backup-restore" hidden aria-labelledby="map-backup-restore-title">
          <h4 id="map-backup-restore-title">Restore floor settings?</h4>
          <dl id="map-backup-restore-changes" class="measurements"></dl>
          <div id="map-backup-restore-room-details" hidden>
            <label>Room <select id="map-backup-restore-room-choice"></select></label>
            <dl id="map-backup-restore-room-values" class="measurements"></dl>
            <ul id="map-backup-restore-room-status"></ul>
          </div>
          <div id="map-backup-restore-zone-detail" hidden>
            <ul id="map-backup-restore-zone-list"></ul>
            <p id="map-backup-restore-dependency-status" class="muted" role="status" hidden></p>
          </div>
          <ul id="map-backup-restore-restrictions" hidden></ul>
          <div id="map-backup-restore-furniture" hidden>
            <ul id="map-backup-restore-furniture-list"></ul>
            <p id="map-backup-restore-furniture-status" class="muted" role="status" hidden></p>
          </div>
          <div id="map-backup-restore-program-detail" hidden>
            <label>Program <select id="map-backup-restore-program-choice"></select></label>
            <p id="map-backup-restore-program-order" class="muted"></p>
            <ol id="map-backup-restore-program-areas"></ol>
            <ul id="map-backup-restore-program-status"></ul>
            <p id="map-backup-restore-program-unchecked" class="muted"></p>
          </div>
          <div class="actions">
            <button id="cancel-map-backup-restore">Back</button>
            <button id="confirm-map-backup-restore" class="primary">Restore settings</button>
          </div>
        </section>
      </section>
      <div id="map-backup-controls" hidden>
        <button id="capture-map-backup">Back up current floor</button>
        <details>
          <summary>Backup settings</summary>
          <label><input id="automatic-map-backups" type="checkbox"> Back up before saving map edits or removing a floor</label>
          <label>Unpinned backups to keep <input id="map-backup-retention" type="number" min="1" max="20" required></label>
          <button id="save-map-backup-settings">Save backup settings</button>
        </details>
      </div>
      <div class="actions"><button id="close-map-backups">Close</button></div>
    </dialog>
    <dialog id="mapping-dialog" aria-labelledby="mapping-title">
      <h3 id="mapping-title">Start a mapping run?</h3>
      <p>Place the robot on its dock and prepare the floor for exploration. Roomba may replace its oldest map if it has reached its map limit.</p>
      <div class="actions">
        <button id="cancel-mapping">Cancel</button>
        <button id="start-mapping" class="primary">Start mapping</button>
      </div>
    </dialog>
    <dialog id="skip-dialog" aria-labelledby="skip-title">
      <h3 id="skip-title">Skip current area?</h3>
      <p id="skip-text"></p>
      <div class="actions">
        <button id="cancel-skip">Cancel</button>
        <button id="confirm-skip" class="primary">Confirm skip</button>
      </div>
    </dialog>
    <dialog id="floor-edit-dialog" aria-labelledby="floor-edit-title">
      <h3 id="floor-edit-title">Save floor settings?</h3>
      <p id="floor-edit-description"></p>
      <div class="actions">
        <button id="cancel-floor-edit">Back</button>
        <button id="save-floor-edit" class="primary">Save floor</button>
      </div>
    </dialog>
    <dialog id="remove-floor-dialog" aria-labelledby="remove-floor-title">
      <h3 id="remove-floor-title">Remove saved floor?</h3>
      <p id="remove-floor-description"></p>
      <div class="actions">
        <button id="cancel-remove-floor">Keep floor</button>
        <button id="remove-floor" class="primary">Remove floor</button>
      </div>
    </dialog>
    <dialog id="routine-dialog" aria-labelledby="routine-title">
      <h3 id="routine-title">Cleaning routines</h3>
      <form id="routine-form">
        <label><span id="routine-list-label">Routine</span> <select id="routine-list"></select></label>
        <div id="quick-routine-fields">
          <button id="load-quick-routines" type="button">Recent and suggested routines</button>
          <p id="quick-routines-status" class="muted" role="status" hidden></p>
          <ul id="quick-routines" aria-label="Recent and suggested routines" hidden></ul>
        </div>
        <label>Name <input id="routine-name" required maxlength="120" autocomplete="off"></label>
        <div id="schedule-fields" hidden>
          <label>Repeat <select id="schedule-frequency"><option value="weekly">Weekly</option><option value="once">Once</option></select></label>
          <label>Start time <input id="schedule-time" type="time"></label>
          <fieldset id="schedule-days"><legend>Days of the week</legend><div id="schedule-day-options" class="actions"></div></fieldset>
        </div>
        <p id="routine-estimate" class="muted" hidden></p>
        <label id="routine-preset-all-label" hidden>Apply preset to all areas <select id="routine-preset-all"></select></label>
        <label id="routine-order-label" hidden>Cleaning order
          <select id="routine-order">
            <option value="listed">Use listed order</option>
            <option value="automatic">Let Roomba choose</option>
          </select>
        </label>
        <p id="routine-region-note" class="muted" hidden></p>
        <ol id="routine-regions" aria-label="Cleaning order"></ol>
        <label id="add-routine-region-label">Add a cleaning area <select id="add-routine-region"></select></label>
        <div>
          <button id="estimate-routine" type="button">Estimate draft</button>
          <p id="routine-draft-time" class="muted" role="status" hidden></p>
          <ul id="routine-area-times" class="muted" aria-label="Estimated time by area" hidden></ul>
        </div>
        <p id="routine-status" class="muted" role="status"></p>
        <div class="actions">
          <button id="copy-routine" type="button">Duplicate</button>
          <button id="remove-routine" type="button">Delete</button>
          <button id="run-routine" type="button">Run saved routine</button>
          <button id="toggle-schedule" type="button" hidden>Enable</button>
          <button id="close-routines" type="button">Close</button>
          <button id="save-routine" class="primary">Save routine</button>
        </div>
      </form>
    </dialog>
    <dialog id="impact-dialog" aria-labelledby="impact-title">
      <h3 id="impact-title">Map dependencies</h3>
      <p id="impact-areas"></p>
      <p id="impact-status" class="muted" role="status"></p>
      <ul id="impact-list"></ul>
      <div class="actions"><button id="close-impact">Close</button></div>
    </dialog>
    <dialog id="room-edit-dialog" aria-labelledby="room-edit-title">
      <h3 id="room-edit-title">Save room boundaries?</h3>
      <p id="room-edit-description"></p>
      <p id="room-boundary-notice" class="muted">Roomba can reset cleaning settings for these rooms. Saved routines and schedules that reference them may need review.</p>
      <div class="actions"><button id="cancel-room-edit">Back</button><button id="save-room-edit" class="primary">Save map</button></div>
    </dialog>
    <dialog id="zone-edit-dialog" aria-labelledby="zone-edit-title">
      <h3 id="zone-edit-title">Save cleaning zone?</h3>
      <p id="zone-edit-description"></p>
      <p id="zone-removal-notice" class="muted" hidden>Deleting this zone can remove its destination from saved routines and schedules.</p>
      <div class="actions"><button id="cancel-zone-edit">Back</button><button id="save-zone-edit" class="primary">Save map</button></div>
    </dialog>
    <dialog id="restriction-edit-dialog" aria-labelledby="restriction-edit-title">
      <h3 id="restriction-edit-title">Save restriction?</h3>
      <p id="restriction-edit-description"></p>
      <div class="actions">
        <button id="cancel-restriction-edit">Back</button>
        <button id="save-restriction-edit" class="primary">Save map</button>
      </div>
    </dialog>
    <dialog id="furniture-edit-dialog" aria-labelledby="furniture-edit-title">
      <h3 id="furniture-edit-title">Save furniture?</h3>
      <p id="furniture-edit-description"></p>
      <div class="actions">
        <button id="cancel-furniture-edit">Back</button>
        <button id="save-furniture-edit" class="primary">Save map</button>
      </div>
    </dialog>
  </ha-card>`;

const ROUTE_COLORS = {
  traveling: "#9eafbf", vacuuming: "#59adff", mopping: "#4ed9ad", vacuum_mop: "#c39bff",
};
const ROUTE_LABELS = {
  traveling: "Travel", vacuuming: "Vacuuming", mopping: "Mopping", vacuum_mop: "Vacuum and mop",
};
const HISTORY_EVENT_LABELS = {
  start: "Started", pause: "Paused", travel: "Travelled", reloc: "Relocalized", room: "Room result",
  zone: "Zone result", charge: "Docked to charge", padWash: "Washed mop", refill: "Refilled tank",
  evac: "Emptied bin", error: "Error",
};

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

function openPath([start, ...points], xy) {
  const path = new Path2D();
  path.moveTo(...xy(start));
  for (const point of points) path.lineTo(...xy(point));
  return path;
}

function option(value, label) {
  return new Option(label, value);
}

function mapBounds(points) {
  return points.reduce(([left, top, right, bottom], [x, y]) =>
    [Math.min(left, x), Math.min(top, y), Math.max(right, x), Math.max(bottom, y)],
    [Infinity, Infinity, -Infinity, -Infinity]);
}

function roomBounds(room) {
  return mapBounds(room.polygons.flatMap(([outer]) => outer));
}

function interiorFractions(values) {
  return values.every((value) => value > 0 && value < 1);
}

function rectangleRing([x1, y1, x2, y2]) {
  return [[x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]];
}

function furnitureRing([x, y, width, depth, angle]) {
  const heading = angle * Math.PI / 180;
  const c = Math.cos(heading);
  const s = Math.sin(heading);
  return rectangleRing([-width / 2, -depth / 2, width / 2, depth / 2])
    .map(([u, v]) => [x + u * c - v * s, y + u * s + v * c]);
}

function floorProjection(points, angle, zoom, pan, elevated) {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  const pitch = elevated ? OBLIQUE_PITCH : 1;
  const elevation = elevated ? WALL_HEIGHT : 0;
  const rotate = ([x, y]) => [x * cosine - y * sine, x * sine + y * cosine];
  const [left, top, right, bottom] = mapBounds(points.map(rotate));
  const scale = zoom * Math.min((WIDTH - 60) / (right - left || 1),
    (HEIGHT - 60) / ((bottom - top) * pitch + elevation || 1));
  const xCenter = (left + right) / 2;
  const yCenter = (top + bottom) / 2;
  const viewX = WIDTH / 2 + pan[0];
  const viewY = HEIGHT / 2 + pan[1] + elevation * scale / 2;
  return {
    project(point) {
      const [x, y] = rotate(point);
      return [viewX + (x - xCenter) * scale, viewY - (y - yCenter) * pitch * scale];
    },
    unproject(screenX, screenY) {
      const x = (screenX - viewX) / scale + xCenter;
      const y = (viewY - screenY) / (pitch * scale) + yCenter;
      return [x * cosine + y * sine, y * cosine - x * sine];
    },
    depth(point) { return rotate(point)[1] - yCenter; },
    rise: (height) => height * scale,
  };
}

function paintSurface(ctx, points, fill, stroke) {
  const path = pathFor([points], (point) => point);
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1;
  ctx.fill(path);
  ctx.stroke(path);
}

function drawElevation(ctx, walls, furniture, projection) {
  const { project, depth, rise } = projection;
  const surfaces = [];
  for (const { kind, points } of walls) {
    if (kind === "door") continue;
    for (let index = 1; index < points.length; index++) {
      const a = points[index - 1];
      const b = points[index];
      const distance = (depth(a) + depth(b)) / 2;
      const far = distance > 0;
      const [x1, y1] = project(a);
      const [x2, y2] = project(b);
      const height = rise(far ? WALL_HEIGHT : 0.48);
      surfaces.push({ distance, faces: [{
        points: [[x1, y1], [x2, y2], [x2, y2 - height], [x1, y1 - height]],
        fill: far ? "#38556cdb" : "#6988a23d", stroke: "#89a7bcaa",
      }] });
    }
  }
  for (const { kind, points } of furniture) {
    const distance = points.reduce((sum, point) => sum + depth(point), 0) / points.length;
    const height = rise(kind.startsWith("refrigerator/") ? 1.55 : 0.65);
    const base = points.map(project);
    const top = base.map(([x, y]) => [x, y - height]);
    const faces = [];
    for (let index = 0; index < points.length; index++) {
      const next = (index + 1) % points.length;
      if ((depth(points[index]) + depth(points[next])) / 2 < distance) {
        faces.push({ points: [base[index], base[next], top[next], top[index]],
          fill: "#496478", stroke: "#8ca7ba" });
      }
    }
    faces.push({ points: top, fill: "#7d9aaf", stroke: "#b8cddc" });
    surfaces.push({ distance, faces });
  }
  surfaces.sort((a, b) => b.distance - a.distance);
  for (const { faces } of surfaces) {
    for (const { points, fill, stroke } of faces) paintSurface(ctx, points, fill, stroke);
  }
}

function historyMode(modes) {
  if (modes.includes("vacuuming") && modes.includes("mopping")) return "vacuum_mop";
  return modes.find((mode) => mode !== "traveling") ?? modes[0];
}

function renderMapLegend(element, entries) {
  element.hidden = entries.length === 0;
  element.replaceChildren(...entries.map(([label, color]) => {
    const chip = document.createElement("span");
    chip.textContent = label;
    chip.style.setProperty("--swatch", color);
    return chip;
  }));
}

function drawMissionMap(canvas, geometry, view) {
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#101e2a";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  const polygons = geometry.rooms.flatMap((room) => room.polygons).concat(geometry.borders);
  const points = polygons.flat(2);
  if (!points.length) return;
  const frame = view.elevated ? points.concat(geometry.walls.flatMap((wall) => wall.points)) : points;
  const projection = floorProjection(frame, view.angle, view.zoom, view.pan, view.elevated);
  const project = projection.project;
  const area = (shapes, fill, stroke) => {
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1;
    for (const shape of shapes) {
      const path = pathFor(shape, project);
      ctx.fill(path, "evenodd");
      if (stroke) ctx.stroke(path);
    }
  };
  area(polygons, "#223747", "#647f90");
  area(geometry.carpets, "#7b637260");
  area(geometry.saved_zones ?? [], "#22504560", "#5bd4b0");
  area(geometry.keep_out ?? [], "#862f555c", "#ff7893");
  area(geometry.no_mop ?? [], "#62452456", "#e8ab6a");
  for (const item of geometry.coverage) {
    const color = ROUTE_COLORS[historyMode(item.modes)] ?? "#74889b";
    area(item.polygons, `${color}44`);
  }
  area(geometry.temporary_zones, "#00000000", "#ffffffa0");
  if (view.elevated) drawElevation(ctx, geometry.walls, geometry.furniture, projection);
  else area(geometry.furniture.map(({ points }) => [points]), "#43535d", "#8aa1aa");
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#ff7893";
  for (const wall of geometry.virtual_walls ?? []) {
    ctx.beginPath();
    ctx.moveTo(...project(wall[0]));
    for (const point of wall.slice(1)) ctx.lineTo(...project(point));
    ctx.stroke();
  }
  for (const item of geometry.trajectories) {
    ctx.strokeStyle = ROUTE_COLORS[historyMode(item.modes)] ?? "#b7c3cd";
    ctx.beginPath();
    ctx.moveTo(...project(item.points[0]));
    for (const point of item.points.slice(1)) ctx.lineTo(...project(point));
    ctx.stroke();
  }
  const finalPoint = geometry.trajectories.at(-1)?.points.at(-1);
  const markers = [[geometry.docks, "#f0c674"], [geometry.hazards, "#ff8080"]];
  if (finalPoint) markers.push([[finalPoint], "#eaf3f9"]);
  for (const [points, color] of markers) {
    ctx.fillStyle = color;
    for (const point of points) {
      ctx.beginPath();
      ctx.arc(...project(point), 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  if (view.label) {
    for (const room of geometry.rooms) {
      for (const polygon of room.polygons) view.label(room.name, polygon[0], pathFor(polygon, project), project);
    }
  }
}

function historyTime(timestamp, timeOnly = false) {
  if (!timestamp) return "Unknown time";
  const time = new Date(typeof timestamp === "number" ? timestamp * 1000 : timestamp);
  return timeOnly ? time.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : time.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function renderMeasurements(element, values) {
  element.replaceChildren(...values.flatMap(([label, value]) => {
    if (value == null || value === "") return [];
    const field = document.createElement("div");
    const title = document.createElement("dt");
    title.className = "muted";
    title.textContent = label;
    const body = document.createElement("dd");
    body.textContent = String(value);
    field.append(title, body);
    return [field];
  }));
}

function showPresetChoices(select, keys, locked) {
  select.replaceChildren(option("", "Choose a preset"),
    ...keys.map((key) => option(key, PRESET_LABELS[key])));
  select.value = "";
  select.disabled = locked || !keys.length;
}

function historyLabel(value) {
  return value ? value.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase()) : "Unknown";
}

class RoombaHomeMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" }).append(template.content.cloneNode(true));
    this.canvas = this.shadowRoot.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.markerCtx = this.$("live-marker").getContext("2d");
    this.$("coverage-vacuum").onchange = () => this.draw();
    this.$("coverage-mop").onchange = () => this.draw();
    this.$("live-cleaning-path").onchange = () => this.draw();
    this.$("live-travel-path").onchange = () => this.draw();
    this.$("live-obstacles").onchange = () => this.draw();
    this.selected = new Set();
    this.zoom = 1;
    this.pan = [0, 0];
    this.orbit = 0;
    this.sequence = 0;
    this.scoreSequence = 0;
    this.$("maps").onchange = (event) => {
      this.closeLiveSubscription();
      this.removalDraft = null;
      if (this.$("remove-floor-dialog").open) this.$("remove-floor-dialog").close();
      if (this.$("cleaning-scores-dialog").open) this.$("cleaning-scores-dialog").close();
      this.selectedFloor = event.target.value || null;
      this.geometry = null;
      this.clearSelection();
      this.renderAreas();
      this.resetView();
      this.refresh(true);
    };
    this.$("zoom-in").onclick = () => this.setZoom(this.zoom * 1.25);
    this.$("zoom-out").onclick = () => this.setZoom(this.zoom / 1.25);
    this.$("reset").onclick = () => this.resetView();
    this.$("orbit-map").onclick = () => {
      this.orbit = (this.orbit + 1) % 4;
      this.draw();
    };
    this.$("review").onclick = () => this.review();
    this.$("cancel").onclick = () => this.dialog.close();
    this.$("start").onclick = () => this.submit();
    this.$("review-mapping").onclick = () => this.reviewMapping();
    this.$("open-mission-history").onclick = () => this.openMissionHistory();
    this.$("open-cleaning-scores").onclick = () => this.openCleaningScores();
    this.$("close-cleaning-scores").onclick = () => this.$("cleaning-scores-dialog").close();
    this.$("close-mission-history").onclick = () => this.$("mission-history-dialog").close();
    this.$("mission-history-dialog").onclose = () => { this.historySequence++; };
    this.$("history-mission").onchange = (event) => this.loadMissionReport(event.target.value, 0);
    this.$("history-map-index").onchange = (event) => this.loadMissionReport(this.historyReport.mission.id, Number(event.target.value));
    this.$("history-zoom-in").onclick = () => this.changeHistoryView(1.25);
    this.$("history-zoom-out").onclick = () => this.changeHistoryView(0.8);
    this.$("history-reset").onclick = () => this.resetHistoryView();
    this.$("history-3d").onclick = () => {
      this.historyView.elevated = !this.historyView.elevated;
      this.historyView.angle = this.historyView.elevated ? Math.PI / 4 : 0;
      this.drawHistoryMap();
    };
    this.$("history-orbit").onclick = () => {
      this.historyView.angle += QUARTER_TURN;
      this.drawHistoryMap();
    };
    this.historySequence = 0;
    this.$("history-map").onpointerdown = (event) => {
      event.currentTarget.setPointerCapture(event.pointerId);
      this.historyPointer = [event.clientX, event.clientY];
    };
    this.$("history-map").onpointermove = (event) => this.panHistoryMap(event);
    this.$("history-map").onpointerup = this.$("history-map").onpointercancel = () => { this.historyPointer = null; };
    this.$("cancel-mapping").onclick = () => this.$("mapping-dialog").close();
    this.$("start-mapping").onclick = () => this.startMapping();
    this.$("point-mode").onclick = () => this.togglePointMode();
    this.$("point-cleaning-mode").onchange = (event) => this.setPointCleaningMode(event.target.value);
    this.$("place-point").onclick = () => this.placePoint();
    this.$("manage-routines").onclick = () => this.openRoutines();
    this.$("manage-schedules").onclick = () => this.openRoutines(true);
    this.$("open-map-backups").onclick = () => this.openMapBackups();
    this.$("close-map-backups").onclick = () => this.$("map-backups-dialog").close();
    this.$("map-backup-choice").onchange = (event) => this.showMapBackup(event.target.value);
    this.$("capture-map-backup").onclick = () => this.captureMapBackup();
    this.$("save-map-backup-settings").onclick = () => this.saveMapBackupSettings();
    this.$("export-map-backup").onclick = () => this.exportMapBackup();
    this.$("review-map-backup-restore").onclick = () => this.reviewMapBackupRestore();
    this.$("review-map-backup-room-details").onclick = () => this.reviewMapBackupRestore("room_details");
    this.$("map-backup-restore-room-choice").onchange = () => this.showMapBackupRoomDetails();
    this.$("review-map-backup-zones").onclick = () => this.reviewMapBackupRestore("zones");
    this.$("review-map-backup-restrictions").onclick = () => this.reviewMapBackupRestore("restrictions");
    this.$("review-map-backup-furniture").onclick = () => this.reviewMapBackupRestore("furniture");
    this.$("review-map-backup-programs").onclick = () => this.reviewMapBackupRestore("programs");
    this.$("map-backup-restore-program-choice").onchange = () => this.showMapBackupProgram();
    this.$("confirm-map-backup-restore").onclick = () => this.confirmMapBackupRestore();
    this.$("cancel-map-backup-restore").onclick = () => {
      this.backups.restore = null;
      this.updateMapBackupControls(this.backups);
    };
    this.$("pin-map-backup").onclick = () => this.modifyMapBackup("pin");
    this.$("delete-map-backup").onclick = () => this.modifyMapBackup("delete");
    this.$("map-impact").onclick = () => this.reviewMapImpact();
    this.$("edit-floor").onclick = () => this.openFloorEditor();
    this.$("review-remove-floor").onclick = () => this.reviewFloorRemoval();
    this.$("cancel-remove-floor").onclick = () => this.$("remove-floor-dialog").close();
    this.$("remove-floor").onclick = () => this.removeFloor();
    this.$("close-floor-editor").onclick = () => {
      this.closeFloorEditor();
      this.updateSelection();
      this.draw();
    };
    this.$("floor-operation").onchange = () => { this.updateFloorEdit(); this.draw(); };
    this.$("edit-floor-name").oninput = () => this.updateFloorEdit();
    this.$("floor-rotate-left").onclick = () => this.rotateFloorDraft(-1);
    this.$("floor-rotate-right").onclick = () => this.rotateFloorDraft(1);
    this.$("review-floor-edit").onclick = () => this.reviewFloorEdit();
    this.$("cancel-floor-edit").onclick = () => this.$("floor-edit-dialog").close();
    this.$("save-floor-edit").onclick = () => this.saveFloorSettings();
    this.$("edit-rooms").onclick = () => this.openRoomEditor();
    this.$("close-room-editor").onclick = () => { this.closeRoomEditor(); this.updateSelection(); this.draw(); };
    this.$("room-operation").onchange = () => this.renderRoomEditor();
    this.$("edit-room-first").onchange = () => this.renderRoomEditor(this.$("edit-room-first").value);
    this.$("edit-room-second").onchange = () => { this.updateRoomEdit(); this.draw(); };
    this.$("edit-room-name").oninput = () => { this.updateRoomEdit(); this.draw(); };
    this.$("edit-room-type").onchange = () => this.updateRoomEdit();
    this.$("place-divider").onclick = () => {
      this.roomDraft.placing = 0;
      this.setDivider([]);
      this.$("room-edit-status").textContent = "Select the first endpoint on the map.";
      this.canvas.focus();
    };
    this.dividerFields = ["x1", "y1", "x2", "y2"].map((id) => this.$(`divider-${id}`));
    for (const input of this.dividerFields) {
      input.oninput = () => { this.roomDraft.placing = null; this.updateRoomEdit(); this.draw(); };
    }
    this.canvas.tabIndex = 0;
    this.$("review-room-edit").onclick = () => this.reviewRoomEdit();
    this.$("cancel-room-edit").onclick = () => this.$("room-edit-dialog").close();
    this.$("save-room-edit").onclick = () => this.saveRoomEdit();
    this.$("edit-zones").onclick = () => this.openZoneEditor();
    this.$("close-zone-editor").onclick = () => {
      this.closeZoneEditor();
      this.updateSelection();
      this.draw();
    };
    this.$("zone-operation").onchange = () => this.renderZoneEditor(this.$("edit-zone").value);
    this.$("edit-zone").onchange = () => this.renderZoneEditor(this.$("edit-zone").value);
    this.$("zone-name").oninput = () => this.updateZoneEdit();
    this.zoneFields = ["x1", "y1", "x2", "y2"].map((id) => this.$(`zone-${id}`));
    for (const input of this.zoneFields) {
      input.oninput = () => {
        this.zoneDraft.placing = null;
        this.zoneDraft.changedBounds = true;
        this.updateZoneEdit();
        this.draw();
      };
    }
    this.$("place-zone").onclick = () => {
      this.zoneDraft.placing = 0;
      this.setZoneBounds([]);
      this.$("zone-edit-status").textContent = "Select the first corner on the map.";
      this.canvas.focus();
    };
    this.$("review-zone-edit").onclick = () => this.reviewZoneEdit();
    this.$("cancel-zone-edit").onclick = () => this.$("zone-edit-dialog").close();
    this.$("save-zone-edit").onclick = () => this.saveZoneEdit();
    this.$("review-skip").onclick = () => this.reviewSkip();
    this.$("cancel-skip").onclick = () => this.$("skip-dialog").close();
    this.$("confirm-skip").onclick = () => this.skipArea();
    this.$("edit-restrictions").onclick = () => this.openRestrictionEditor();
    this.$("close-restriction-editor").onclick = () => {
      this.closeRestrictionEditor();
      this.updateSelection();
      this.draw();
    };
    this.$("restriction-operation").onchange = () => this.renderRestrictionEditor();
    this.$("restriction-target").onchange = () => this.renderRestrictionEditor();
    this.$("restriction-kind").onchange = () => {
      this.updateRestrictionEdit();
      this.draw();
    };
    this.restrictionFields = ["x1", "y1", "x2", "y2"].map((id) => this.$(`restriction-${id}`));
    for (const input of this.restrictionFields) {
      input.oninput = () => {
        this.restrictionDraft.placing = null;
        this.restrictionDraft.changedBounds = true;
        this.updateRestrictionEdit();
        this.draw();
      };
    }
    this.$("place-restriction").onclick = () => {
      this.restrictionDraft.placing = 0;
      this.setRestrictionBounds([]);
      this.canvas.focus();
    };
    this.$("review-restriction-edit").onclick = () => this.reviewRestrictionEdit();
    this.$("cancel-restriction-edit").onclick = () => this.$("restriction-edit-dialog").close();
    this.$("save-restriction-edit").onclick = () => this.saveRestrictionEdit();
    this.$("show-3d").onclick = () => {
      this.elevated = !this.elevated;
      this.resetView();
    };
    this.$("show-furniture").onclick = () => {
      this.furnitureShown = !this.showFurniture;
      this.draw();
    };
    this.$("edit-furniture").onclick = () => this.openFurnitureEditor();
    this.$("close-furniture-editor").onclick = () => {
      this.closeFurnitureEditor();
      this.updateSelection();
      this.draw();
    };
    this.$("furniture-operation").onchange = () => this.renderFurnitureEditor();
    this.$("furniture-target").onchange = () => this.renderFurnitureEditor();
    this.$("furniture-kind").onchange = () => this.updateFurnitureDraft();
    this.furnitureFields = ["x", "y", "width", "depth", "angle"].map((id) => this.$(`furniture-${id}`));
    for (const input of this.furnitureFields) {
      input.oninput = () => {
        this.furnitureDraft.placing = false;
        this.updateFurnitureDraft();
      };
    }
    this.$("place-furniture").onclick = () => {
      this.furnitureDraft.placing = true;
      this.$("furniture-status").textContent = "Choose the center on the map.";
      this.canvas.focus();
    };
    this.$("review-furniture-edit").onclick = () => this.reviewFurnitureEdit();
    this.$("cancel-furniture-edit").onclick = () => this.$("furniture-edit-dialog").close();
    this.$("save-furniture-edit").onclick = () => this.saveFurnitureEdit();
    this.$("close-impact").onclick = () => this.$("impact-dialog").close();
    this.$("routine-list").onchange = (event) => this.editRoutine(event.target.value);
    this.$("routine-name").oninput = (event) => { this.routineDraft.name = event.target.value; };
    this.$("schedule-frequency").onchange = (event) => {
      this.routineDraft.frequency = event.target.value;
      this.renderScheduleTiming(this.routineBusy);
    };
    this.$("schedule-time").oninput = (event) => { this.routineDraft.time = event.target.value; };
    this.$("routine-order").onchange = (event) => {
      this.routineDraft.ordered = event.target.value === "listed";
      this.renderRoutine();
    };
    this.$("add-routine-region").onchange = (event) => {
      const id = event.target.value;
      if (id.includes(":furniture:")) this.routineDraft.ordered = true;
      this.routineDraft.regions.push({ id });
      this.renderRoutine();
    };
    this.$("copy-routine").onclick = () => this.copyRoutine();
    this.$("load-quick-routines").onclick = () => this.loadQuickRoutines();
    this.$("estimate-routine").onclick = () => this.estimateRoutine();
    this.$("remove-routine").onclick = () => this.removeRoutine();
    this.$("run-routine").onclick = () => this.runRoutine();
    this.$("toggle-schedule").onclick = () => this.toggleSchedule();
    this.$("close-routines").onclick = () => this.routineDialog.close();
    this.$("routine-form").onsubmit = (event) => {
      event.preventDefault();
      if (this.scheduleEditor) this.saveSchedule();
      else this.saveRoutine();
    };
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

  get dialog() { return this.$("confirm-dialog"); }

  get routineDialog() { return this.$("routine-dialog"); }

  get pointRooms() {
    return this.geometry?.regions.filter(({ id, kind, polygons }) =>
      id && kind === "room" && polygons.length) ?? [];
  }

  get pointAvailable() {
    return Boolean(this.pointModes.length && this.pointRooms.length &&
      !this.geometry.virtual_walls.length);
  }

  get pointModes() {
    return this.snapshot?.can_clean_point
      ? (this.snapshot.point_modes ?? []).filter((mode) => Object.hasOwn(MODES, mode))
      : [];
  }

  get editingMap() {
    return Boolean(this.floorDraft || this.roomDraft || this.zoneDraft ||
      this.restrictionDraft || this.furnitureDraft);
  }

  get showElevation() {
    return Boolean(this.elevated && !this.editingMap && this.hasWalls);
  }

  get hasWalls() { return this.geometry?.presentation?.walls.some(({ kind }) => kind !== "door"); }

  get showFurniture() { return this.furnitureShown ?? this.showElevation; }

  setConfig(config) {
    if (!/^vacuum\.[a-z0-9_]+$/.test(config.entity ?? "")) {
      throw new Error("Choose a Roomba vacuum entity.");
    }
    if (this.config?.entity === config.entity) return;
    this.closeLiveSubscription();
    if (this.routineDialog.open) this.routineDialog.close();
    if (this.$("mission-history-dialog").open) this.$("mission-history-dialog").close();
    if (this.$("map-backups-dialog").open) this.$("map-backups-dialog").close();
    if (this.$("cleaning-scores-dialog").open) this.$("cleaning-scores-dialog").close();
    if (this.$("mapping-dialog").open) this.$("mapping-dialog").close();
    if (this.$("remove-floor-dialog").open) this.$("remove-floor-dialog").close();
    this.removalDraft = null;
    this.config = config;
    this.floor = null;
    this.selectedFloor = null;
    this.geometry = null;
    this.snapshot = null;
    this.pointMode = false;
    this.pointCleaningMode = null;
    this.elevated = false;
    this.furnitureShown = undefined;
    this.clearSelection();
    this.renderAreas();
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
    this.closeLiveSubscription();
    this.timer = null;
    this.sequence++;
    this.loading = false;
  }

  async refresh(force = false) {
    if (!this.isConnected || !this.config || !this._hass || (this.loading && !force)) return;
    const sequence = ++this.sequence;
    this.loading = true;
    const query = { type: "roomba_home/floor_plan", entity_id: this.config.entity };
    const editing = this.editingMap || this.selected.size || this.pointMode ||
      this.removalDraft || this.routineDialog.open;
    const requested = this.selectedFloor ?? (editing ? this.floor : null);
    if (requested) query.map_id = requested;
    if (this.geometry) {
      query.known_map_id = this.snapshot.map.id;
      query.known_version = this.snapshot.map.version;
      if (this.snapshot.inventory_id) query.known_inventory = this.snapshot.inventory_id;
    }
    try {
      const data = await this._hass.callWS(query);
      if (sequence !== this.sequence) return;
      const changed = this.snapshot?.map?.id !== data.map?.id ||
        this.snapshot?.map?.version !== data.map?.version;
      const settingsChanged = this.snapshot?.floor_settings?.id !== data.floor_settings?.id;
      const angleChanged = this.snapshot?.floor_settings?.orientation !== data.floor_settings?.orientation;
      const staleFloorDraft = settingsChanged && this.floorDraft && !this.floorSaving;
      const inventoryChanged = this.snapshot?.inventory_id !== data.inventory_id;
      if ((changed || inventoryChanged) && this.$("cleaning-scores-dialog").open) this.$("cleaning-scores-dialog").close();
      const selectionId = this.geometry?.selection_id;
      if (changed || (inventoryChanged && (!selectionId || selectionId !== data.geometry?.selection_id))) {
        this.clearSelection(!changed);
      } else if (inventoryChanged) this.closeMapDrafts(true);
      else if (settingsChanged) this.closeFloorEditor();
      if (changed || angleChanged) {
        this.zoom = 1;
        this.pan = [0, 0];
      }
      const floorsChanged = JSON.stringify(this.snapshot?.maps) !== JSON.stringify(data.maps);
      if (this.selectedFloor && !data.maps.some((map) => map.id === this.selectedFloor)) {
        this.selectedFloor = null;
      }
      this.snapshot = data;
      this.updateLiveSubscription(data.map);
      this.updateSkipControl(data.skip_review);
      this.updateMappingControl(data.mapping);
      this.updateFloorRemoval();
      this.floor = data.map?.id ?? null;
      if (!data.map) this.geometry = null;
      if (data.geometry) this.geometry = data.geometry;
      if (this.routineDialog.open) {
        this.renderRoutineEstimate();
        if (changed || inventoryChanged) this.renderQuickRoutines();
      }
      if (floorsChanged || this.renderedGeometry !== this.geometry) this.renderAreas();
      this.$("title").textContent = data.robot;
      this.$("floor-name").textContent = data.floor_settings?.name ?? "";
      this.$("floor-name").hidden = !data.floor_settings?.name ||
        (data.maps.length > 1 && Boolean(this.selectedFloor));
      this.$("manage-routines").hidden = !data.cleaning;
      this.$("manage-schedules").hidden = !data.can_manage_schedules || !data.map;
      this.$("open-cleaning-scores").hidden = !data.map;
      this.$("map-impact").hidden = !data.cleaning;
      this.$("edit-floor").hidden = !data.can_edit_rooms || !data.floor_settings ||
        !this.geometry?.floor_settings_supported;
      this.$("edit-rooms").hidden = !data.can_edit_rooms || !this.geometry?.editable_rooms?.length;
      this.$("edit-zones").hidden = !data.can_edit_rooms || !this.geometry?.editable_zones;
      this.$("edit-restrictions").hidden = !data.can_edit_rooms ||
        !this.geometry?.floor_settings_supported;
      this.$("edit-restrictions").title = this.geometry?.editable_restrictions
        ? "" : "This floor contains restrictions the editor cannot preserve.";
      this.$("edit-furniture").hidden = !data.can_edit_rooms || !this.geometry?.furniture;
      this.$("edit-furniture").title = this.geometry?.furniture?.editable
        ? "" : "This floor contains furniture the editor cannot preserve.";
      this.$("activity").textContent = data.mapping?.activity ?
        (data.mapping.activity === "paused" ? "Mapping paused" : "Mapping in progress") :
        (data.current_room ? `Current room · ${data.current_room}` : "");
      if (staleFloorDraft) {
        this.operationMessage = "The floor settings changed. Open the editor again.";
        this.$("status").textContent = this.operationMessage;
      }
      this.renderMissionPlan(data.live_plan);
      this.renderAreaResults("active", [
        ...(data.active_rooms ?? []), ...(data.active_zones ?? []),
      ], "In progress");
      this.renderAreaResults("history", [
        ...(data.last_mission_rooms ?? []), ...(data.last_mission_zones ?? []),
      ], "Unknown outcome");
      this.draw();
      this.updateSelection();
    } catch (error) {
      if (sequence !== this.sequence) return;
      this.snapshot = null;
      this.closeLiveSubscription();
      this.updateSkipControl(null);
      this.updateMappingControl(null);
      this.updateFloorRemoval();
      this.geometry = null;
      if (this.routineDialog.open) {
        this.renderRoutineEstimate();
        this.renderQuickRoutines();
      }
      this.clearSelection();
      this.renderAreas();
      this.renderMissionPlan(null);
      this.renderAreaResults("active", [], "In progress");
      this.renderAreaResults("history", [], "Unknown outcome");
      this.draw();
      this.$("activity").textContent = "";
      this.$("floor-name").hidden = true;
      this.$("manage-routines").hidden = true;
      this.$("manage-schedules").hidden = true;
      this.$("open-cleaning-scores").hidden = true;
      if (this.$("cleaning-scores-dialog").open) this.$("cleaning-scores-dialog").close();
      this.$("map-impact").hidden = true;
      this.$("edit-floor").hidden = true;
      this.$("edit-rooms").hidden = true;
      this.$("edit-zones").hidden = true;
      this.$("edit-restrictions").hidden = true;
      this.$("edit-furniture").hidden = true;
      this.$("status").textContent = error?.message || "Floor plan unavailable.";
    } finally {
      if (sequence === this.sequence) {
        this.loading = false;
        if (this.backups && this.backupsOpen(this.backups)) this.updateMapBackupControls(this.backups);
      }
    }
  }

  updateLiveSubscription(map) {
    if (!map || !this._hass.connection?.subscribeMessage) {
      this.closeLiveSubscription();
      return;
    }
    const scope = JSON.stringify([this.config.entity, map.id, map.version]);
    if (this.liveStream?.scope === scope) return;
    this.closeLiveSubscription();
    const stream = { scope };
    this.liveStream = stream;
    this._hass.connection.subscribeMessage((event) => this.receiveLivePositions(stream, event), {
      type: "roomba_home/live_positions", entity_id: this.config.entity,
      map_id: map.id, version: map.version,
    }).then((unsubscribe) => {
      if (this.liveStream === stream) stream.close = unsubscribe;
      else Promise.resolve(unsubscribe()).catch(() => {});
    }).catch(() => {
      if (this.liveStream === stream) this.closeLiveSubscription();
    });
  }

  closeLiveSubscription() {
    const stream = this.liveStream;
    this.liveStream = null;
    this.liveTween = null;
    if (this.liveFrame != null) window.cancelAnimationFrame(this.liveFrame);
    this.liveFrame = null;
    if (stream?.close) Promise.resolve(stream.close()).catch(() => {});
  }

  receiveLivePositions(stream, event) {
    if (this.liveStream !== stream) return;
    const before = event.reset ? null : stream.reading;
    const trail = new Map((before?.trail ?? []).map((point) => [point[0], point]));
    for (const point of event.trail) trail.set(point[0], point);
    let coverage = before?.coverage;
    if (event.coverage) {
      const rows = new Map(coverage?.rows ?? []);
      for (const [row, runs] of event.coverage.rows) rows.set(row, runs);
      coverage = {cell_size: event.coverage.cell_size, rows: [...rows]};
    }
    const previous = before?.position;
    const next = event.position;
    const samePosition = previous && next &&
      ["index", "timestamp", "x", "y", "orientation", "expires_at"].every((key) => previous[key] === next[key]);
    stream.reading = {
      trail: [...trail.values()].sort((a, b) => a[0] - b[0]).slice(-MAX_LIVE_POINTS),
      position: samePosition ? previous : next,
      coverage,
      obstacles: event.obstacles ?? before?.obstacles,
    };
    if (!samePosition) this.liveTween = this.positionTransition(previous, next, trail);
    this.draw();
    this.animateLivePosition();
  }

  positionTransition(from, to, trail) {
    if (!from || !to || to.index <= from.index || to.index - from.index > MAX_LIVE_POINTS) return null;
    const seconds = to.timestamp - from.timestamp;
    if (seconds <= 0 || seconds > MAX_LIVE_TRANSITION_SECONDS ||
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return null;
    const path = [[from.x, from.y, 0]];
    for (let index = from.index + 1; index <= to.index; index++) {
      const point = index === to.index ? [index, to.x, to.y] : trail.get(index);
      if (!point) return null;
      const [, x, y] = point;
      const [prevX, prevY, priorDistance] = path.at(-1);
      const distance = priorDistance + Math.hypot(x - prevX, y - prevY);
      if (distance > seconds) return null;
      path.push([x, y, distance]);
    }
    const start = performance.now();
    const duration = Math.min(MAX_LIVE_TRANSITION_MS, 1000 * seconds);
    const active = this.liveTween;
    if (!active || active.to !== from || start >= active.start + active.duration) {
      return { from, to, path, start, duration };
    }
    // Resume from the displayed position and finish the remaining reported legs.
    const origin = this.liveMarker(from, start);
    const distance = active.path.at(-1)[2];
    const traveled = distance * this.transitionFraction(active, start);
    const pending = active.path
      .filter((point) => point[2] > traveled)
      .map(([x, y, offset]) => [x, y, offset - traveled]);
    if (pending.length + path.length > MAX_LIVE_POINTS) return null;
    const remaining = distance - traveled;
    return {
      from: origin, to, start, duration,
      path: [[origin.x, origin.y, 0], ...pending,
        ...path.slice(1).map(([x, y, offset]) => [x, y, offset + remaining])],
    };
  }

  animateLivePosition() {
    if (!this.liveTween || this.liveFrame != null) return;
    this.liveFrame = window.requestAnimationFrame((now) => {
      this.liveFrame = null;
      const tween = this.liveTween;
      if (tween && now >= tween.start + tween.duration) this.liveTween = null;
      this.drawLiveMarker();
      this.animateLivePosition();
    });
  }

  transitionFraction({ start, duration }, now) {
    return Math.max(0, Math.min(1, (now - start) / duration));
  }

  liveMarker(position, now) {
    const tween = this.liveTween;
    if (!tween || tween.to !== position) return position;
    const { from, to, path } = tween;
    const fraction = this.transitionFraction(tween, now);
    const distance = fraction * path.at(-1)[2];
    const end = path.findIndex((point, index) => index > 0 && point[2] >= distance);
    const [x0, y0, length0] = path[end - 1];
    const [x1, y1, length1] = path[end];
    const leg = length1 > length0 ? (distance - length0) / (length1 - length0) : 0;
    const turn = to.orientation - from.orientation;
    return {
      ...to,
      x: x0 + leg * (x1 - x0),
      y: y0 + leg * (y1 - y0),
      orientation: from.orientation + fraction * Math.atan2(Math.sin(turn), Math.cos(turn)),
    };
  }

  renderAreas() {
    this.renderedGeometry = this.geometry;
    const container = this.$("regions");
    const floors = this.$("maps");
    floors.replaceChildren();
    const maps = this.snapshot?.maps ?? [];
    if (maps.length > 1) floors.append(option("", "Follow active floor"));
    for (const [index, map] of maps.entries()) {
      const option = document.createElement("option");
      option.value = map.id;
      option.textContent = map.name || `Floor ${index + 1}`;
      floors.append(option);
    }
    floors.value = this.selectedFloor ?? "";
    floors.hidden = maps.length < 2;
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
    const pointRoom = this.$("point-room");
    const previousRoom = pointRoom.value;
    const rooms = this.pointRooms;
    pointRoom.replaceChildren(...rooms.map(({ id, name }) => option(id, name)));
    if (rooms.some(({ id }) => id === previousRoom)) pointRoom.value = previousRoom;
    this.$("zone-key").hidden = !this.geometry?.regions.some((region) =>
      region.kind === "zone" && region.polygons.length);
    this.$("exclusion-key").hidden = !this.geometry?.keep_out.length && !this.geometry?.virtual_walls.length;
    this.$("no-mop-key").hidden = !this.geometry?.no_mop?.length;
    const notice = this.$("zone-notice");
    const unlinked = this.geometry?.unlinked_zone_count ?? 0;
    const listOnly = this.geometry?.regions.filter((region) => region.kind === "zone" &&
      region.id && !region.polygons.length).length ?? 0;
    const messages = [];
    if (unlinked) messages.push(unlinked === 1
      ? "Roomba has not made 1 map zone available for cleaning."
      : `Roomba has not made ${unlinked} map zones available for cleaning.`);
    if (listOnly) messages.push(listOnly === 1
      ? "1 saved zone is available in the list only."
      : `${listOnly} saved zones are available in the list only.`);
    notice.textContent = messages.join(" ");
    notice.hidden = !messages.length;
  }

  updateMappingControl(mapping) {
    const button = this.$("review-mapping");
    button.hidden = !mapping?.can_start || Boolean(mapping.activity);
    button.disabled = Boolean(this.mappingPending);
    const dialog = this.$("mapping-dialog");
    if (button.hidden && dialog.open) dialog.close();
  }

  async openCleaningScores() {
    const map = this.snapshot?.map;
    if (!this.config || !this._hass || !map) return;
    const entity = this.config.entity;
    const dialog = this.$("cleaning-scores-dialog");
    const status = this.$("scores-status");
    const summary = this.$("scores-summary");
    const rooms = this.$("scores-rooms");
    const sequence = ++this.scoreSequence;
    const current = () => dialog.open && sequence === this.scoreSequence && entity === this.config.entity &&
      map.id === this.snapshot?.map?.id && map.version === this.snapshot.map.version;
    summary.hidden = true;
    rooms.replaceChildren();
    status.textContent = "Loading room cleaning scores…";
    dialog.showModal();
    try {
      const scores = await this._hass.callWS({
        type: "roomba_home/cleaning_scores", entity_id: entity, map_id: map.id, version: map.version,
      });
      if (!current()) return;
      if (!scores.rooms.length) {
        status.textContent = "Roomba has no cleaning scores for this floor.";
        return;
      }
      const lastProcessed = scores.last_processed_mission_started_at;
      renderMeasurements(summary, [
        ["Reported score ranges", scores.ranges.join(", ")],
        ["Last processed mission started", lastProcessed && historyTime(lastProcessed)],
      ]);
      summary.hidden = !scores.ranges.length && !lastProcessed;
      rooms.replaceChildren(...scores.rooms.map((room) => {
        const section = document.createElement("section");
        const name = document.createElement("h4");
        name.textContent = room.name ?? "Room";
        const fields = document.createElement("dl");
        fields.className = "measurements";
        const preferences = room.preferences ?? {};
        renderMeasurements(fields, [
          ["Roomba score", room.score],
          ["Traffic", room.traffic && historyLabel(room.traffic)],
          ["Score updated", room.score_updated_at && historyTime(room.score_updated_at)],
          ["Last cleaned mission started", room.last_cleaned_mission_started_at && historyTime(room.last_cleaned_mission_started_at)],
          ["Last unfinished mission started", room.last_unfinished_mission_started_at && historyTime(room.last_unfinished_mission_started_at)],
          ["Suggested mode", MODES[preferences.mode]],
          ...Object.entries(SETTINGS).map(([key, label]) => {
            const value = preferences[key];
            return [label, typeof value === "boolean" ? (value ? "On" : "Off") : value];
          }),
        ]);
        section.append(name, fields);
        return section;
      }));
      status.textContent = "";
    } catch (error) {
      if (current()) status.textContent = error?.message || "Room cleaning scores are unavailable.";
    }
  }

  async openMapBackups() {
    if (!this.config || !this._hass) return;
    const backup = this.backups = { entity: this.config.entity, busy: false, snapshots: [] };
    this.$("map-backups-dialog").showModal();
    this.$("map-backup-detail").hidden = true;
    this.$("map-backup-controls").hidden = true;
    this.$("map-backups-status").textContent = "Loading local backups…";
    try {
      await this.refreshMapBackups(backup);
    } catch (error) {
      if (this.backupsOpen(backup)) this.$("map-backups-status").textContent = error.message;
    }
  }

  backupsOpen(backup) {
    return this.backups === backup && this.config.entity === backup.entity && this.$("map-backups-dialog").open;
  }

  mapBackupRequest(backup, type, payload = {}) {
    return this._hass.callWS({ type: `roomba_home/${type}`, entity_id: backup.entity, ...payload });
  }

  async refreshMapBackups(backup, selected) {
    const result = await this.mapBackupRequest(backup, "map_backups");
    if (!this.backupsOpen(backup)) return;
    Object.assign(backup, result);
    this.$("automatic-map-backups").checked = backup.automatic;
    this.$("map-backup-retention").value = backup.retention;
    this.$("map-backup-controls").hidden = !backup.can_manage;
    this.$("map-backup-detail").hidden = !backup.snapshots.length;
    const choices = this.$("map-backup-choice");
    choices.replaceChildren(...backup.snapshots.map((item) => option(item.id,
      [item.name ?? "Saved floor", historyTime(item.captured_at), item.pinned ? "Pinned" : ""]
        .filter(Boolean).join(" · "))));
    backup.selected = backup.snapshots.find(({ id }) => id === selected)?.id ?? backup.snapshots[0]?.id;
    backup.preview = false;
    this.updateMapBackupControls(backup);
    if (backup.selected) await this.showMapBackup(backup.selected);
    else this.$("map-backups-status").textContent = "No local map backups yet.";
  }

  updateMapBackupControls(backup) {
    const saved = backup.snapshots.find(({ id }) => id === backup.selected);
    const scope = this.mapBackupFloor();
    const canRestore = Boolean(backup.can_manage && saved && scope?.map_id === saved.map_id);
    if (backup.restore && JSON.stringify(backup.restore.floor) !== JSON.stringify(scope)) {
      backup.restore = null;
      this.$("map-backups-status").textContent = "The current floor changed. Review the restore again.";
    }
    const pin = this.$("pin-map-backup");
    const remove = this.$("delete-map-backup");
    pin.hidden = remove.hidden = !backup.can_manage;
    pin.disabled = backup.busy || !backup.preview;
    remove.disabled = backup.busy || !backup.selected;
    pin.textContent = saved?.pinned ? "Unpin backup" : "Pin backup";
    remove.textContent = backup.deletePending === backup.selected && backup.selected
      ? "Confirm delete" : "Delete backup";
    this.$("capture-map-backup").disabled = backup.busy || !scope;
    this.$("export-map-backup").disabled = backup.busy || !backup.preview;
    this.$("map-backup-choice").disabled = backup.busy;
    this.$("save-map-backup-settings").disabled = backup.busy;
    const restore = this.$("review-map-backup-restore");
    restore.hidden = !canRestore || Boolean(backup.restore);
    restore.disabled = backup.busy || !backup.preview;
    const rooms = this.$("review-map-backup-room-details");
    rooms.hidden = restore.hidden || !backup.savedRooms;
    rooms.disabled = restore.disabled;
    const zones = this.$("review-map-backup-zones");
    zones.hidden = restore.hidden || !backup.savedZones;
    zones.disabled = restore.disabled;
    const restrictions = this.$("review-map-backup-restrictions");
    restrictions.hidden = restore.hidden || !backup.savedRestrictions;
    restrictions.disabled = restore.disabled;
    const furniture = this.$("review-map-backup-furniture");
    furniture.hidden = restore.hidden || !backup.savedFurniture;
    furniture.disabled = restore.disabled;
    const programs = this.$("review-map-backup-programs");
    programs.hidden = restore.hidden || !(saved?.program_count || saved?.programs_unchecked?.length);
    programs.disabled = restore.disabled;
    this.$("map-backup-restore").hidden = !backup.restore;
    const selectedReview = ["programs", "room_details"].includes(backup.restore?.kind);
    this.$("confirm-map-backup-restore").disabled = backup.busy ||
      (selectedReview && !backup.restore.review_id);
  }

  async showMapBackup(id) {
    const backup = this.backups;
    const request = backup.request = {};
    const status = this.$("map-backups-status");
    const canvas = this.$("map-backup-preview");
    const comparison = this.$("map-backup-comparison");
    backup.selected = id;
    backup.preview = false;
    backup.savedRooms = false;
    backup.savedZones = false;
    backup.savedRestrictions = false;
    backup.savedFurniture = false;
    backup.deletePending = null;
    backup.restore = null;
    this.$("map-backup-choice").value = id;
    this.updateMapBackupControls(backup);
    canvas.hidden = true;
    comparison.hidden = true;
    this.$("map-backup-legend").replaceChildren();
    status.textContent = "Opening local map…";
    try {
      const { backup: saved, geometry } = await this.mapBackupRequest(backup, "read_map_backup", { backup_id: id });
      if (!this.backupsOpen(backup) || backup.request !== request) return;
      this.drawMapBackup(canvas, saved, geometry);
      backup.savedRooms = Boolean(geometry.editable_rooms?.length);
      backup.roomTypes = geometry.room_naming?.types ?? {};
      backup.savedZones = geometry.regions.some(({ kind }) => kind === "zone");
      backup.savedRestrictions = Boolean(geometry.keep_out?.length || geometry.no_mop?.length || geometry.virtual_walls?.length);
      backup.savedFurniture = Boolean(geometry.furniture?.items?.length);
      const current = this.snapshot;
      if (current?.map && current.map.id === saved.map_id) {
        const angle = current.floor_settings?.orientation;
        const delta = typeof angle === "number" && typeof saved.orientation === "number"
          ? angle - saved.orientation : Infinity;
        const rotationChanged = angle !== saved.orientation &&
          (!Number.isFinite(delta) || Math.abs(Math.atan2(Math.sin(delta), Math.cos(delta))) > 1e-6);
        const changes = [
          current.map.version !== saved.version ? "Map revision" : "",
          current.floor_settings?.name !== saved.name ? "Floor name" : "",
          rotationChanged ? "Rotation" : "",
        ].filter(Boolean);
        comparison.hidden = false;
        comparison.textContent = changes.length ? `Changed since backup · ${changes.join(" · ")}`
          : "Matches the current floor revision, name and rotation.";
      }
      canvas.hidden = false;
      backup.preview = true;
      this.updateMapBackupControls(backup);
      status.textContent = "";
    } catch (error) {
      if (this.backupsOpen(backup) && backup.request === request) status.textContent = error.message;
    }
  }

  drawMapBackup(canvas, saved, geometry) {
    const layers = geometry.presentation ?? {};
    const rooms = geometry.regions.filter(({ kind }) => kind === "room");
    const ctx = canvas.getContext("2d");
    const savedZones = geometry.regions.filter(({ kind }) => kind === "zone").flatMap(({ polygons }) => polygons);
    const furniture = geometry.furniture?.items ?? [];
    const docks = layers.docks ?? [];
    drawMissionMap(canvas, {
      rooms, borders: [], walls: layers.walls ?? [], carpets: layers.carpets ?? [], docks,
      furniture, coverage: [], trajectories: [], temporary_zones: [], hazards: [], saved_zones: savedZones,
      keep_out: geometry.keep_out, no_mop: geometry.no_mop, virtual_walls: geometry.virtual_walls,
    }, { angle: saved.orientation ?? 0, zoom: 1, pan: [0, 0], elevated: false,
      label: (...args) => this.drawLabel.call({ ctx }, ...args),
    });
    renderMapLegend(this.$("map-backup-legend"), [
      [savedZones.length, "Cleaning zone", "#5bd4b0"],
      [geometry.keep_out.length || geometry.virtual_walls.length, "Keep-out area or wall", "#ff7893"],
      [geometry.no_mop.length, "No-mop area", "#e8ab6a"],
      [furniture.length, "Furniture", "#8aa1aa"], [docks.length, "Dock", "#f0c674"],
    ].filter(([count]) => count > 0).map(([, label, color]) => [label, color]));
  }

  async changeMapBackups(type, data, success, refreshFloor = false) {
    const backup = this.backups;
    if (!backup.can_manage || backup.busy) return;
    backup.busy = true;
    this.updateMapBackupControls(backup);
    const status = this.$("map-backups-status");
    try {
      const record = await this.mapBackupRequest(backup, type, data);
      if (!this.backupsOpen(backup)) return;
      if (refreshFloor) await this.refresh(true);
      await this.refreshMapBackups(backup, record?.id ?? backup.selected);
      if (this.backupsOpen(backup) && (!backup.selected || backup.preview)) status.textContent = success;
    } catch (error) {
      if (this.backupsOpen(backup)) status.textContent = error.message;
    } finally {
      backup.busy = false;
      if (this.backupsOpen(backup)) this.updateMapBackupControls(backup);
    }
  }

  async captureMapBackup() {
    const floor = this.mapBackupFloor();
    if (!floor) return;
    await this.changeMapBackups("capture_map_backup", floor, "Floor backup saved locally.");
  }

  mapBackupFloor() {
    const floor = this.snapshot;
    if (!floor?.map || !floor.floor_settings) return null;
    return {
      map_id: floor.map.id, version: floor.map.version, inventory_id: floor.inventory_id,
      settings_id: floor.floor_settings.id,
    };
  }

  async reviewMapBackupRestore(kind = "settings") {
    const backup = this.backups;
    const saved = backup.snapshots.find(({ id }) => id === backup.selected);
    const floor = this.mapBackupFloor();
    if (!backup.can_manage || backup.busy || !backup.preview || !floor || saved?.map_id !== floor.map_id) return;
    const status = this.$("map-backups-status");
    backup.busy = true;
    this.updateMapBackupControls(backup);
    status.textContent = "Checking the current floor…";
    try {
      const review = await this.mapBackupRequest(backup, `restore_map_backup_${kind}`, {
        ...floor, backup_id: saved.id,
      });
      if (!this.backupsOpen(backup)) return;
      if (kind !== "programs" && !Object.keys(review.changes ?? review.rooms).length) {
        const unchanged = {
          zones: "The recorded zones already match.", settings: "The recorded floor settings already match.",
          restrictions: "The recorded restrictions already match.", furniture: "The recorded furniture already matches.",
          room_details: "The recorded room names and types already match.",
        };
        status.textContent = unchanged[kind];
        return;
      }
      backup.restore = { floor, backup_id: saved.id, kind, review_id: review.review_id };
      this.renderMapBackupRestore(kind, review);
      status.textContent = "";
    } catch (error) {
      if (this.backupsOpen(backup)) status.textContent = error.message;
    } finally {
      backup.busy = false;
      if (this.backupsOpen(backup)) this.updateMapBackupControls(backup);
    }
  }

  renderMapBackupRestore(kind, { changes, dependencies, unchecked, programs, rooms }) {
    const zones = kind === "zones";
    const labels = {
      zones: ["Restore cleaning zones?", "Restore zones"],
      restrictions: ["Restore map restrictions?", "Restore restrictions"],
      furniture: ["Restore saved furniture?", "Restore furniture"],
      settings: ["Restore floor settings?", "Restore settings"],
      programs: ["Recover program destinations", "Restore destinations"],
      room_details: ["Restore room names and types?", "Restore room details"],
    };
    const [title, action] = labels[kind];
    this.$("map-backup-restore-title").textContent = title;
    this.$("confirm-map-backup-restore").textContent = action;
    this.$("map-backup-restore-zone-detail").hidden = !zones;
    const restrictions = this.$("map-backup-restore-restrictions");
    restrictions.hidden = kind !== "restrictions";
    this.$("map-backup-restore-furniture").hidden = kind !== "furniture";
    this.$("map-backup-restore-program-detail").hidden = kind !== "programs";
    this.$("map-backup-restore-room-details").hidden = kind !== "room_details";
    const settings = this.$("map-backup-restore-changes");
    settings.hidden = kind !== "settings";
    if (kind === "programs") {
      this.renderMapBackupPrograms(programs, unchecked);
      return;
    }
    if (kind === "room_details") {
      this.renderMapBackupRoomDetails(rooms);
      return;
    }
    if (kind === "restrictions") {
      restrictions.replaceChildren(...changes.map(({ id, kind, missing }) => {
        const item = document.createElement("li");
        const label = RESTRICTION_TYPES[kind];
        item.textContent = `${missing ? "Recreate" : "Restore outline"} · ${label} · ${id}`;
        return item;
      }));
      return;
    }
    if (kind === "furniture") {
      this.renderMapBackupFurniture(changes, dependencies, unchecked);
      return;
    }
    if (!zones) {
      const rotation = (angle) => angle == null ? "Default" : `${Math.round(angle * 1800 / Math.PI) / 10}°`;
      renderMeasurements(settings, [
        ["Floor name", changes.name && `${changes.name.from ?? "Unnamed floor"} → ${changes.name.to}`],
        ["Rotation", changes.orientation && `${rotation(changes.orientation.from)} → ${rotation(changes.orientation.to)}`],
      ]);
      return;
    }
    this.$("map-backup-restore-zone-list").replaceChildren(...changes.map((zone) => {
      const item = document.createElement("li");
      const label = document.createElement("strong");
      label.textContent = zone.missing ? `Recreate ${zone.name}` : `Restore ${zone.name}`;
      item.append(label);
      const details = [];
      if (!zone.missing && zone.current_name !== zone.name) details.push(`Current name: ${zone.current_name ?? "Unnamed"}`);
      if (!zone.missing && zone.outline_changed) details.push("Restore saved outline");
      for (const entry of dependencies) {
        if (!entry.zones.includes(zone.id)) continue;
        details.push(`${entry.kind === "routine" ? "Routine" : "Schedule"} · ${entry.name ?? "Unnamed"}`);
      }
      for (const detail of details) {
        const line = document.createElement("div");
        line.textContent = detail;
        item.append(line);
      }
      return item;
    }));
    const notes = [];
    if (changes.some(({ missing }) => missing)) {
      notes.push("Check routines and schedules that used recreated zones. Their destinations may need to be added again.");
    }
    if (unchecked.length) notes.push(`Some ${unchecked.map((kind) => `${kind}s`).join(" and ")} could not be checked.`);
    const status = this.$("map-backup-restore-dependency-status");
    status.textContent = notes.join(" ");
    status.hidden = !notes.length;
  }

  renderMapBackupRoomDetails(rooms) {
    const choice = this.$("map-backup-restore-room-choice");
    const ready = this.backups.restore.rooms = rooms.filter(({ status }) => status === "ready");
    choice.replaceChildren(...ready.map((room, index) => option(index, room.name.from ?? room.id)));
    choice.parentElement.hidden = !ready.length;
    const explanations = {
      missing_room: "Room is missing from the active map",
      changed_boundary: "Room boundary has changed",
      unsupported_details: "Saved name or type is unavailable for recovery",
    };
    this.$("map-backup-restore-room-status").replaceChildren(...rooms
      .filter(({ status }) => status !== "ready")
      .map((room) => {
        const item = document.createElement("li");
        item.textContent = `${room.name.to ?? room.id} · ${explanations[room.status]}`;
        return item;
      }));
    this.showMapBackupRoomDetails();
  }

  showMapBackupRoomDetails() {
    const backup = this.backups;
    const review = backup.restore;
    const room = review.rooms[this.$("map-backup-restore-room-choice").value];
    review.room = room;
    review.review_id = room?.review_id;
    const typeLabel = (type) => backup.roomTypes[type] ?? type ?? "Default";
    renderMeasurements(this.$("map-backup-restore-room-values"), room ? [
      ["Room name", `${room.name.from ?? "Unnamed room"} → ${room.name.to}`],
      ["Room type", `${typeLabel(room.room_type.from)} → ${typeLabel(room.room_type.to)}`],
    ] : []);
    this.updateMapBackupControls(backup);
  }

  renderMapBackupFurniture(changes, dependencies, unchecked) {
    this.$("map-backup-restore-furniture-list").replaceChildren(...changes.map((object) => {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${object.missing ? "Recreate" : "Restore"} ${object.name} · ${object.id}`;
      item.append(title);
      const details = [object.source === "robot" ? "Detected by Roomba" : "Added by user"];
      for (const routine of dependencies) {
        if (routine.objects.includes(object.id)) details.push(`Routine · ${routine.name ?? "Unnamed"}`);
      }
      const line = document.createElement("div");
      line.textContent = details.join(" · ");
      item.append(line);
      return item;
    }));
    const status = this.$("map-backup-restore-furniture-status");
    status.textContent = unchecked.length ? "Some routines could not be checked." : "";
    status.hidden = !unchecked.length;
  }

  renderMapBackupPrograms(programs, unchecked) {
    const label = ({ name, kind }) => `${kind === "routine" ? "Routine" : "Schedule"} · ${name ?? "Unnamed"}`;
    const ready = this.backups.restore.programs = programs.filter(({ status }) => status === "ready");
    const choice = this.$("map-backup-restore-program-choice");
    choice.replaceChildren(...ready.map((program, index) => option(index, label(program))));
    choice.parentElement.hidden = !ready.length;
    this.$("map-backup-restore-program-status").replaceChildren(...programs
      .filter(({ status }) => status !== "ready")
      .map((program) => {
        const item = document.createElement("li");
        item.textContent = `${label(program)} · ${PROGRAM_RECOVERY_STATUS[program.status]}`;
        return item;
      }));
    this.$("map-backup-restore-program-unchecked").textContent = unchecked.length
      ? `Backup coverage is incomplete for ${unchecked.map((kind) => `${kind}s`).join(" and ")}.` : "";
    this.showMapBackupProgram();
  }

  showMapBackupProgram() {
    const backup = this.backups;
    const review = backup.restore;
    const program = review.programs[this.$("map-backup-restore-program-choice").value];
    review.review_id = program?.review_id;
    review.program = program;
    const order = this.$("map-backup-restore-program-order");
    order.textContent = program ? (program.ordered ? "Listed order" : "Automatic order") : "";
    this.$("map-backup-restore-program-areas").replaceChildren(...(program?.destinations ?? []).map((area) => {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${area.name ?? area.id}${area.restore ? " · Restore" : ""}`;
      const details = document.createElement("div");
      const settings = Object.entries(SETTINGS)
        .filter(([key]) => area[key] != null)
        .map(([key, label]) => `${label} ${typeof area[key] === "boolean" ? (area[key] ? "on" : "off") : area[key]}`);
      details.textContent = [MODES[area.mode], ...settings].join(" · ");
      item.append(title, details);
      return item;
    }));
    this.updateMapBackupControls(backup);
  }

  async confirmMapBackupRestore() {
    const backup = this.backups;
    const review = backup.restore;
    if (!review || backup.busy) return;
    this.updateMapBackupControls(backup);
    if (!backup.restore) return;
    backup.restore = null;
    const data = {
      ...review.floor, backup_id: review.backup_id, confirmed: true,
    };
    if (review.review_id) data.review_id = review.review_id;
    if (review.kind === "programs") {
      if (!review.program || !review.review_id) return;
      data.kind = review.program.kind;
      data.program_id = review.program.id;
    }
    if (review.kind === "room_details") {
      if (!review.room || !review.review_id) return;
      data.room_id = review.room.id;
    }
    const success = {
      programs: "Cleaning destinations restored.", zones: "Cleaning zones restored.",
      settings: "Floor settings restored.", restrictions: "Map restrictions restored.",
      furniture: "Furniture restored.",
      room_details: "Room details restored.",
    };
    await this.changeMapBackups(`restore_map_backup_${review.kind}`, data,
      success[review.kind], true);
  }

  async saveMapBackupSettings() {
    const input = this.$("map-backup-retention");
    if (!input.reportValidity()) return;
    await this.changeMapBackups("configure_map_backups", {
      retention: input.valueAsNumber, automatic: this.$("automatic-map-backups").checked,
    }, "Backup settings saved.");
  }

  async modifyMapBackup(operation) {
    const backup = this.backups;
    if (!backup.selected || backup.busy) return;
    if (operation === "delete" && backup.deletePending !== backup.selected) {
      backup.deletePending = backup.selected;
      this.updateMapBackupControls(backup);
      return;
    }
    if (operation === "pin" && backup.snapshots.find(({ id }) => id === backup.selected)?.pinned) operation = "unpin";
    await this.changeMapBackups("modify_map_backup", { backup_id: backup.selected, operation },
      operation === "delete" ? "Backup deleted." : "Backup updated.");
  }

  async exportMapBackup() {
    const backup = this.backups;
    if (!backup.preview || backup.busy) return;
    const selected = backup.selected;
    try {
      const record = await this.mapBackupRequest(backup, "read_map_backup", { backup_id: selected, download: true });
      if (!this.backupsOpen(backup) || backup.selected !== selected) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(record)], { type: "application/json" }));
      const download = document.createElement("a");
      download.href = url;
      download.download = `roomba-map-${selected.slice(0, 12)}.json`;
      download.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (this.backupsOpen(backup)) this.$("map-backups-status").textContent = error.message;
    }
  }

  async openMissionHistory() {
    if (!this.config || !this._hass) return;
    const entity = this.config.entity;
    const dialog = this.$("mission-history-dialog");
    const status = this.$("history-status");
    const totals = this.$("history-totals");
    const sequence = ++this.historySequence;
    dialog.showModal();
    status.textContent = "Loading cleaning history…";
    totals.hidden = true;
    this.$("history-selector").hidden = true;
    this.$("history-detail").hidden = true;
    try {
      const { missions } = await this._hass.callWS({ type: "roomba_home/mission_history", entity_id: entity });
      if (sequence !== this.historySequence || !dialog.open || entity !== this.config.entity) return;
      if (!missions.length) {
        status.textContent = "Roomba returned no recent cleaning reports.";
        return;
      }
      const measurements = [
        ["duration_minutes", "min"], ["area_m2", "m²"],
      ].flatMap(([key, unit]) => {
        const measured = missions.map((mission) => mission[key]).filter(Number.isFinite);
        return measured.length ? [`${Number(measured.reduce((sum, value) => sum + value, 0).toFixed(1))} ${unit}`] : [];
      });
      totals.textContent = [`${missions.length} ${missions.length === 1 ? "report" : "reports"}`, ...measurements].join(" · ");
      totals.hidden = false;
      this.$("history-mission").replaceChildren(...missions.map((mission) => option(mission.id,
        [historyTime(mission.started_at ?? mission.finished_at), historyLabel(mission.outcome),
          mission.duration_minutes == null ? "" : `${mission.duration_minutes} min`,
          mission.area_m2 == null ? "" : `${mission.area_m2} m²`].filter(Boolean).join(" · "))));
      this.$("history-selector").hidden = false;
      await this.loadMissionReport(missions[0].id, 0);
    } catch (error) {
      if (sequence === this.historySequence && dialog.open) status.textContent = error?.message || "Cleaning history is unavailable.";
    }
  }

  async loadMissionReport(reportId, mapIndex) {
    const entity = this.config.entity;
    const dialog = this.$("mission-history-dialog");
    const status = this.$("history-status");
    const sequence = ++this.historySequence;
    status.textContent = "Loading cleaning report…";
    this.$("history-detail").hidden = true;
    try {
      const report = await this._hass.callWS({
        type: "roomba_home/mission_history", entity_id: entity, report_id: reportId, map_index: mapIndex,
      });
      if (sequence !== this.historySequence || !dialog.open || entity !== this.config.entity) return;
      this.historyReport = report;
      this.historyView = { zoom: 1, pan: [0, 0], angle: 0, elevated: false };
      status.textContent = "";
      this.renderMissionReport(report);
    } catch (error) {
      if (sequence === this.historySequence && dialog.open) status.textContent = error?.message || "The cleaning report is unavailable.";
    }
  }

  renderMissionReport(report) {
    const mission = report.mission;
    const units = (value, unit) => value == null ? null : `${value} ${unit}`;
    const values = [
      ["Outcome", historyLabel(mission.outcome)],
      ["Started", mission.started_at && historyTime(mission.started_at)],
      ["Recorded", historyTime(mission.finished_at)],
      ["Duration", units(mission.duration_minutes, "min")], ["Cleaned", units(mission.area_m2, "m²")],
      ["Active", units(report.active_minutes, "min")], ["Paused", units(report.pause_minutes, "min")],
      ["Charging", units(report.charge_minutes, "min")], ["Recharges", report.recharges],
      ["Bin emptyings", report.evacuations], ["Error code", mission.error_code],
      ["Started at dock", report.started_at_dock == null ? null : (report.started_at_dock ? "Yes" : "No")],
      ["Initiated by", report.initiator === "rmtApp" ? "Remote app" : report.initiator],
      ["Target", mission.target && historyLabel(mission.target)],
      ...Object.entries(report.modes).map(([mode, result]) => [historyLabel(mode),
        [units(result.duration_minutes, "min"), units(result.area_m2, "m²")].filter(Boolean).join(" · ")]),
    ];
    renderMeasurements(this.$("history-measurements"), values);
    const floor = this.$("history-map-index");
    floor.replaceChildren(...Array.from({ length: mission.map_count }, (_, i) => option(i, `Map ${i + 1}`)));
    floor.value = String(report.map_index);
    this.$("history-map-selector").hidden = mission.map_count < 2;
    this.renderAreaResults("history-area-results", [...report.rooms, ...report.zones], "Unknown outcome");
    this.$("history-timeline").replaceChildren(...report.timeline.map((event) => {
      const line = document.createElement("li");
      const duration = units(event.duration_seconds, "s");
      line.textContent = [historyTime(event.timestamp, true), HISTORY_EVENT_LABELS[event.type], duration].filter(Boolean).join(" · ");
      return line;
    }));
    this.$("history-chronology").hidden = !report.timeline.length;
    this.$("history-detail").hidden = false;
    this.$("history-map-view").hidden = !report.geometry;
    this.$("history-no-map").hidden = Boolean(report.geometry);
    if (report.geometry) this.drawHistoryMap();
  }

  drawHistoryMap() {
    const geometry = this.historyReport?.geometry;
    if (!geometry) return;
    const view = this.historyView;
    this.$("history-3d").hidden = !geometry.walls.length && !geometry.furniture.length;
    this.$("history-3d").setAttribute("aria-pressed", view.elevated);
    this.$("history-orbit").hidden = !view.elevated;
    const modes = new Set([...geometry.coverage, ...geometry.trajectories].map((layer) => historyMode(layer.modes)).filter(Boolean));
    const legend = [...modes].map((mode) => [ROUTE_LABELS[mode], ROUTE_COLORS[mode]]);
    if (geometry.docks.length) legend.push(["Dock", "#f0c674"]);
    if (geometry.hazards.length) legend.push(["Obstacle", "#ff8080"]);
    if (geometry.trajectories.length) legend.push(["End of recorded path", "#eaf3f9"]);
    renderMapLegend(this.$("history-map-legend"), legend);
    drawMissionMap(this.$("history-map"), geometry, view);
  }

  resetHistoryView() {
    const view = this.historyView;
    view.zoom = 1;
    view.pan = [0, 0];
    view.angle = view.elevated ? Math.PI / 4 : 0;
    this.drawHistoryMap();
  }

  changeHistoryView(factor) {
    this.historyView.zoom = Math.min(8, Math.max(1, this.historyView.zoom * factor));
    this.drawHistoryMap();
  }

  panHistoryMap(event) {
    if (!this.historyPointer) return;
    const view = this.historyView;
    const bounds = event.currentTarget.getBoundingClientRect();
    view.pan[0] += (event.clientX - this.historyPointer[0]) * WIDTH / bounds.width;
    view.pan[1] += (event.clientY - this.historyPointer[1]) * HEIGHT / bounds.height;
    this.historyPointer = [event.clientX, event.clientY];
    this.drawHistoryMap();
  }

  reviewMapping() {
    const button = this.$("review-mapping");
    if (!button.hidden && !button.disabled) this.$("mapping-dialog").showModal();
  }

  async startMapping() {
    const dialog = this.$("mapping-dialog");
    const mapping = this.snapshot?.mapping;
    if (!dialog.open || !mapping?.can_start || mapping.activity || this.mappingPending) return;
    const entity = this.config.entity;
    this.mappingPending = true;
    dialog.close();
    this.updateMappingControl(mapping);
    this.$("status").textContent = "Waiting for Roomba to start mapping…";
    try {
      await this._hass.callService("roomba_home", "start_mapping", { confirmed: true }, { entity_id: entity });
      if (this.config.entity === entity) this.operationMessage = "Roomba confirmed the mapping run.";
    } catch (error) {
      if (this.config.entity === entity) this.operationMessage = error?.message || "Roomba did not confirm mapping.";
    } finally {
      this.mappingPending = false;
      if (this.config.entity === entity) this.$("status").textContent = this.operationMessage;
      await this.refresh(true);
    }
  }

  floorRemovalReview() {
    const data = this.snapshot;
    if (!data?.can_edit_rooms || !data.map || data.mapping?.activity ||
        !data.inventory_id || !data.floor_settings?.id) return null;
    return {
      type: "roomba_home/remove_floor", entity_id: this.config.entity, map_id: data.map.id,
      version: data.map.version, inventory_id: data.inventory_id, settings_id: data.floor_settings.id,
    };
  }

  updateFloorRemoval() {
    const current = this.floorRemovalReview();
    const button = this.$("review-remove-floor");
    button.hidden = !current;
    button.disabled = Boolean(this.floorRemoving);
    if (this.removalDraft && JSON.stringify(this.removalDraft) !== JSON.stringify(current)) {
      this.removalDraft = null;
      this.$("remove-floor-dialog").close();
    }
  }

  reviewFloorRemoval() {
    const review = this.floorRemovalReview();
    if (!review || this.floorRemoving) return;
    this.removalDraft = review;
    const name = this.snapshot.floor_settings.name || "this floor";
    this.$("remove-floor-description").textContent =
      `Remove ${name} from Roomba? Its saved rooms and zones will no longer be available to routines and schedules.`;
    this.$("remove-floor-dialog").showModal();
  }

  async removeFloor() {
    const dialog = this.$("remove-floor-dialog");
    const review = this.removalDraft;
    if (!dialog.open || !review || this.floorRemoving ||
        JSON.stringify(review) !== JSON.stringify(this.floorRemovalReview())) return;
    this.floorRemoving = true;
    this.removalDraft = null;
    dialog.close();
    this.updateFloorRemoval();
    this.$("status").textContent = "Waiting for Roomba to remove the floor…";
    try {
      await this._hass.callWS({ ...review, confirmed: true });
      if (this.config.entity === review.entity_id) this.operationMessage = "Roomba removed the floor.";
    } catch (error) {
      if (this.config.entity === review.entity_id) this.operationMessage = error?.message || "Roomba did not confirm removal.";
    } finally {
      this.floorRemoving = false;
      if (this.config.entity === review.entity_id) this.$("status").textContent = this.operationMessage;
      await this.refresh(true);
    }
  }

  updateSkipControl(review) {
    const button = this.$("review-skip");
    button.hidden = !review;
    button.disabled = Boolean(this.skipPending);
    if (this.skipDraft && this.skipDraft !== review) {
      this.skipDraft = null;
      this.$("skip-dialog").close();
    }
  }

  reviewSkip() {
    const review = this.snapshot?.skip_review;
    if (!review || this.skipPending) return;
    this.skipDraft = review;
    this.$("skip-text").textContent = `${this.snapshot.robot} will omit this area from the current mission.`;
    this.$("skip-dialog").showModal();
  }

  async skipArea() {
    const review = this.skipDraft;
    if (!review || review !== this.snapshot?.skip_review || this.skipPending) return;
    const entity = this.config.entity;
    this.skipPending = true;
    this.$("skip-dialog").close();
    this.updateSkipControl(review);
    this.operationMessage = "Waiting for Roomba to confirm the skip…";
    this.$("status").textContent = this.operationMessage;
    try {
      await this._hass.callService("roomba_home", "skip_current_area",
        { review_id: review }, { entity_id: entity });
      if (this.config.entity === entity) this.operationMessage = "Roomba confirmed the area was skipped.";
    } catch (error) {
      if (this.config.entity === entity) this.operationMessage = error?.message || "Roomba did not confirm the skip.";
    } finally {
      this.skipPending = false;
      this.skipDraft = null;
      if (this.config.entity === entity) this.$("status").textContent = this.operationMessage;
      await this.refresh(true);
    }
  }

  renderMissionPlan(plan) {
    const view = this.$("mission-plan");
    const signature = JSON.stringify(plan ?? null);
    if (signature === view.dataset.plan) return;
    view.dataset.plan = signature;
    view.hidden = !plan;
    const summary = view.querySelector("summary");
    const rows = view.querySelector("div");
    rows.replaceChildren();
    summary.textContent = "";
    if (!plan) return;
    const heading = plan.ordered ? "Planned order" : "Selected destinations";
    const remaining = plan.estimated_remaining_seconds;
    const estimate = remaining != null ? ` · About ${Math.ceil(remaining / 60)} min left` : "";
    summary.textContent = `${heading} · ${plan.completed} of ${plan.total} completed${estimate}`;
    const list = document.createElement(plan.ordered ? "ol" : "ul");
    const labels = {
      room: "Room", furniture: "Furniture target", saved_zone: "Saved zone", temporary_zone: "Temporary zone",
    };
    const statuses = {
      pending: "Pending", traveling: "On the way", in_progress: "In progress", finished: "Completed",
      finished_with_more_passes: "More passes expected", partial_incomplete: "Partially cleaned",
      partial_skipped: "Partially skipped", kidnapped: "Robot moved", user_ended: "Ended by user",
      robot_aborted: "Ended by robot", skipped: "Skipped", skipped_will_return: "Skipped, will return",
      unknown: "Unknown outcome",
    };
    for (const destination of plan.destinations) {
      const item = document.createElement("li");
      const row = document.createElement("div");
      row.className = "result";
      const name = document.createElement("strong");
      name.textContent = destination.name || labels[destination.kind];
      const status = document.createElement("span");
      status.className = "muted";
      const duration = destination.estimated_duration_seconds;
      const planned = duration != null ? `${Math.ceil(duration / 60)} min planned` : null;
      status.textContent = [MODES[destination.mode], statuses[destination.status], planned]
        .filter(Boolean).join(" · ");
      row.append(name, status);
      item.append(row);
      list.append(item);
    }
    rows.append(list);
  }

  renderAreaResults(id, areas, defaultStatus) {
    const view = this.$(id);
    const rows = view.querySelector("div");
    const signature = JSON.stringify(areas);
    if (signature === view.dataset.results) return;
    view.dataset.results = signature;
    view.hidden = !areas.length;
    rows.replaceChildren();
    const labels = {
      furniture: "Furniture target", saved_zone: "Saved zone", temporary_zone: "Temporary zone", zone: "Zone",
    };
    for (const [index, area] of areas.entries()) {
      const row = document.createElement("div");
      row.className = "result";
      const name = document.createElement("strong");
      name.textContent = area.name || area.room || `${labels[area.kind] ?? "Room"} ${index + 1}`;
      const status = document.createElement("span");
      status.className = "muted";
      status.textContent = area.status?.replaceAll("_", " ") ?? defaultStatus;
      const metrics = document.createElement("div");
      const values = [];
      if (area.pass_count !== null) values.push(`Passes ${area.pass_count}`);
      if (area.area !== null) values.push(`Reported area ${area.area}${area.total_area !== null ? ` / ${area.total_area}` : ""}`);
      metrics.className = "muted";
      metrics.textContent = values.join(" · ");
      row.append(name, status, metrics);
      rows.append(row);
    }
  }

  clearSelection(keepRoomDraft = false) {
    this.selected.clear();
    this.point = null;
    this.confirmation = null;
    if (this.dialog.open) this.dialog.close();
    this.closeMapDrafts(keepRoomDraft);
    this.updateSelection();
  }

  closeMapDrafts(keepRoomDraft = false) {
    if (this.$("impact-dialog").open) this.$("impact-dialog").close();
    this.closeFloorEditor();
    if (!keepRoomDraft) this.closeRoomEditor();
    this.closeZoneEditor();
    this.closeRestrictionEditor();
    this.closeFurnitureEditor();
  }

  toggle(id) {
    if (this.pointMode || this.floorDraft || this.floorSaving || this.restrictionDraft || this.restrictionSaving ||
        this.furnitureDraft || this.furnitureSaving) return;
    this.operationMessage = null;
    if (this.selected.has(id)) this.selected.delete(id);
    else if (this.selected.size < 32) this.selected.add(id);
    this.updateSelection();
    this.draw();
  }

  togglePointMode() {
    const control = this.$("point-mode");
    if (control.disabled || !this.pointAvailable) return;
    this.pointMode = !this.pointMode;
    this.operationMessage = null;
    this.selected.clear();
    this.point = null;
    this.confirmation = null;
    if (this.dialog.open) this.dialog.close();
    this.updateSelection();
    this.draw();
  }

  setPointCleaningMode(mode) {
    if (!this.pointMode || this.submitting || !this.pointModes.includes(mode)) return;
    this.pointCleaningMode = mode;
    this.confirmation = null;
    if (this.dialog.open) this.dialog.close();
    if (this.point && this.screenPoint) this.pickPoint(...this.screenPoint(this.point.native), this.point.id);
  }

  updateSelection() {
    for (const [id, button] of this.buttons ?? []) {
      button.setAttribute("aria-pressed", this.selected.has(id));
    }
    const editing = this.editingMap;
    const saving = this.floorSaving || this.roomSaving || this.zoneSaving ||
      this.restrictionSaving || this.furnitureSaving;
    const modes = this.pointModes;
    const modeOptions = modes.join();
    const selector = this.$("point-cleaning-mode");
    if (this.renderedPointModes !== modeOptions) {
      this.renderedPointModes = modeOptions;
      selector.replaceChildren(...modes.map((mode) => option(mode, MODES[mode])));
    }
    if (!modes.includes(this.pointCleaningMode)) {
      this.pointCleaningMode = modes[0];
      this.point = null;
      if (this.confirmation?.point) {
        this.confirmation = null;
        if (this.dialog.open) this.dialog.close();
      }
    }
    selector.value = this.pointCleaningMode ?? "";
    selector.disabled = this.submitting;
    const available = this.pointAvailable;
    if (this.pointMode && !available) {
      this.pointMode = false;
      this.point = null;
      this.confirmation = null;
      if (this.dialog.open) this.dialog.close();
    }
    const pointMode = Boolean(this.pointMode);
    const modeButton = this.$("point-mode");
    modeButton.hidden = !modes.length || !this.pointRooms.length;
    modeButton.disabled = !available || editing || saving || this.submitting;
    modeButton.title = this.geometry?.virtual_walls.length
      ? "Point cleaning requires a map without virtual walls." : "";
    modeButton.setAttribute("aria-pressed", pointMode);
    this.$("regions").hidden = pointMode;
    this.$("point-cleaning-settings").hidden = !pointMode || modes.length < 2;
    this.$("point-picker").hidden = !pointMode;
    this.$("target-heading").textContent = pointMode ? "Cleaning point" : "Cleaning areas";
    this.$("target-heading").hidden = !this.geometry;
    this.$("review").hidden = !this.geometry;
    const hasSelection = pointMode ? this.point : this.selected.size;
    this.$("review").disabled = !hasSelection || this.submitting || editing || saving;
    this.$("map-impact").disabled = !this.selected.size || editing;
    const editDisabled = editing || saving || pointMode;
    this.$("edit-floor").disabled = editDisabled;
    this.$("edit-rooms").disabled = editDisabled;
    this.$("edit-zones").disabled = editDisabled;
    this.$("edit-restrictions").disabled = editDisabled || !this.geometry?.editable_restrictions;
    this.$("edit-furniture").disabled = editDisabled || !this.geometry?.furniture?.editable;
    if (this.snapshot && !this.operationMessage) {
      this.$("status").textContent = pointMode
        ? (this.point ? `Point selected in ${this.point.name}.` : "Choose a point inside a room.")
        : (this.snapshot.map === null ? "No saved floor plans yet." :
          this.selected.size ? `${this.selected.size} selected` : "Select a room or saved zone.");
    }
  }

  openFloorEditor() {
    if (this.$("edit-floor").disabled || this.$("edit-floor").hidden) return;
    const settings = this.snapshot.floor_settings;
    this.floorDraft = {
      ...this.snapshot.map,
      inventoryId: this.snapshot.inventory_id,
      settingsId: settings.id,
      originalName: settings.name,
      quarterTurns: 0,
    };
    this.$("floor-editor").hidden = false;
    this.$("floor-operation").value = "rename";
    const name = this.$("edit-floor-name");
    name.maxLength = settings.name_max_length ?? 16;
    name.value = settings.name ?? "";
    this.$("floor-edit-status").textContent = "";
    this.updateFloorEdit();
    this.updateSelection();
    this.$("floor-operation").focus();
  }

  closeFloorEditor() {
    this.floorDraft = null;
    this.$("floor-editor").hidden = true;
    const dialog = this.$("floor-edit-dialog");
    if (dialog.open) dialog.close();
  }

  rotateFloorDraft(turns) {
    this.floorDraft.quarterTurns = (this.floorDraft.quarterTurns + turns + 4) % 4;
    this.updateFloorEdit();
    this.resetView();
  }

  updateFloorEdit() {
    const draft = this.floorDraft;
    draft.operation = this.$("floor-operation").value;
    draft.name = this.$("edit-floor-name").value;
    const rename = draft.operation === "rename";
    this.$("floor-name-label").hidden = !rename;
    this.$("floor-rotate-controls").hidden = rename;
    draft.rotationLabel = draft.quarterTurns === 3
      ? "90° counterclockwise" : `${draft.quarterTurns * 90}° clockwise`;
    this.$("floor-rotation-preview").textContent = draft.quarterTurns
      ? `Preview · ${draft.rotationLabel}` : "Showing saved orientation";
    const valid = rename ? draft.name.trim() && draft.name !== draft.originalName : draft.quarterTurns;
    this.$("review-floor-edit").disabled = this.floorSaving || !valid;
  }

  reviewFloorEdit() {
    const draft = this.floorDraft;
    if (!draft || this.$("review-floor-edit").disabled) return;
    const floor = draft.originalName || "this floor";
    this.$("floor-edit-description").textContent = draft.operation === "rename"
      ? `Rename ${floor} to ${draft.name}?` : `Rotate ${floor} ${draft.rotationLabel}?`;
    this.$("floor-edit-dialog").showModal();
  }

  async saveFloorSettings() {
    const draft = this.floorDraft;
    if (!draft || this.floorSaving) return;
    const entity = this.config.entity;
    this.floorSaving = true;
    this.$("floor-edit-dialog").close();
    this.$("review-floor-edit").disabled = true;
    this.$("floor-edit-status").textContent = "Saving floor settings…";
    const rename = draft.operation === "rename";
    try {
      await this._hass.callWS({
        type: "roomba_home/edit_floor_settings",
        entity_id: entity,
        map_id: draft.id,
        version: draft.version,
        inventory_id: draft.inventoryId,
        settings_id: draft.settingsId,
        operation: draft.operation,
        ...(rename ? { name: draft.name } : { quarter_turns: draft.quarterTurns }),
      });
      if (this.floorDraft === draft) this.closeFloorEditor();
      if (this.config.entity !== entity || this.floor !== draft.id) return;
      this.operationMessage = rename ? "Floor name saved." : "Floor orientation saved.";
      this.$("status").textContent = this.operationMessage;
    } catch (error) {
      if (this.floorDraft === draft) this.$("floor-edit-status").textContent = error.message;
    } finally {
      this.floorSaving = false;
      if (this.floorDraft === draft) this.updateFloorEdit();
      await this.refresh(true);
    }
  }

  openRoomEditor() {
    if (this.$("edit-rooms").disabled || this.$("edit-rooms").hidden) return;
    this.roomDraft = { ...this.snapshot.map };
    const naming = this.geometry.room_naming;
    this.$("rename-room-option").hidden = !naming;
    if (naming) {
      this.$("edit-room-name").maxLength = naming.max_length;
      this.$("edit-room-type").replaceChildren(
        ...Object.entries(naming.types).map(([id, name]) => option(id, name))
      );
    } else if (this.$("room-operation").value === "rename") {
      this.$("room-operation").value = "split";
    }
    this.$("room-editor").hidden = false;
    this.$("edit-rooms").disabled = true;
    this.updateSelection();
    this.renderRoomEditor();
    this.$("room-operation").focus();
  }

  closeRoomEditor() {
    this.roomDraft = null;
    this.$("room-editor").hidden = true;
    this.$("edit-rooms").disabled = false;
    const dialog = this.$("room-edit-dialog");
    if (dialog.open) dialog.close();
  }

  renderRoomEditor(roomId) {
    const rooms = this.geometry.editable_rooms;
    const operation = this.$("room-operation").value;
    const split = operation === "split";
    const merge = operation === "merge";
    const rename = operation === "rename";
    const first = this.$("edit-room-first");
    const second = this.$("edit-room-second");
    const candidates = rooms.filter((room) => rename || (split ? room.can_split : room.adjacent.length));
    const choices = candidates.map((room) => option(room.id, room.name ?? "Room"));
    if (merge) choices.unshift(option("", "Select a room"));
    first.replaceChildren(...choices);
    if (candidates.some((room) => room.id === roomId)) first.value = roomId;
    const selected = candidates.find((room) => room.id === first.value);
    second.replaceChildren(option("", "Select an adjacent room"), ...rooms.filter((room) =>
      selected?.adjacent.includes(room.id) && room.adjacent.includes(selected.id)
    ).map((room) => option(room.id, room.name ?? "Room")));
    this.$("edit-room-second-label").hidden = !merge;
    this.$("split-controls").hidden = !split;
    this.$("rename-room-controls").hidden = !rename;
    if (rename) {
      this.$("edit-room-name").value = selected?.name ?? "";
      const types = this.geometry.room_naming.types;
      this.$("edit-room-type").value =
        Object.hasOwn(types, selected?.room_type) ? selected.room_type : "other";
    }
    this.roomDraft.placing = null;
    const instructions = merge ? "Select two adjacent rooms on the map or in the lists." : "";
    this.$("room-edit-status").textContent =
      candidates.length ? instructions : "No rooms support this operation.";
    const shape = this.geometry.regions.find((area) =>
      area.id === `${this.roomDraft.id}:rid:${first.value}`);
    if (split && shape?.polygons.length) {
      const [left, top, right, bottom] = mapBounds(shape.polygons.flat(2));
      const middle = (top + bottom) / 2;
      const margin = (right - left) * 0.02;
      this.setDivider([left - margin, middle, right + margin, middle]);
    } else {
      this.setDivider([]);
    }
  }

  setDivider(points) {
    this.dividerFields.forEach((input, index) => { input.value = points[index] ?? ""; });
    this.updateRoomEdit();
    this.draw();
  }

  updateRoomEdit() {
    const ids = [this.$("edit-room-first").value];
    const operation = this.$("room-operation").value;
    if (operation === "merge") ids.push(this.$("edit-room-second").value);
    const points = this.dividerFields.map((input) => input.valueAsNumber);
    this.roomDraft.operation = operation;
    this.roomDraft.roomIds = ids;
    this.roomDraft.points = operation === "split" ? points : null;
    this.roomDraft.name = operation === "rename" ? this.$("edit-room-name").value : null;
    this.roomDraft.roomType = operation === "rename" ? this.$("edit-room-type").value : null;
    const selected = this.geometry.editable_rooms.find((room) => room.id === ids[0]);
    this.$("review-room-edit").disabled = this.roomSaving || !ids.every(Boolean) ||
      (operation === "split" && !points.every(Number.isFinite)) ||
      (operation === "rename" && (!this.roomDraft.name.trim() || !this.roomDraft.roomType ||
        (this.roomDraft.name === selected?.name && this.roomDraft.roomType === selected.room_type)));
  }

  reviewRoomEdit() {
    if (!this.roomDraft || this.$("review-room-edit").disabled) return;
    const rooms = this.geometry.editable_rooms;
    const names = this.roomDraft.roomIds.map((id) => rooms.find((room) => room.id === id)?.name ?? "Room");
    const { operation, name, roomType } = this.roomDraft;
    const rename = operation === "rename";
    this.$("room-edit-title").textContent = rename ? "Save room name?" : "Save room boundaries?";
    this.$("room-boundary-notice").hidden = rename;
    const descriptions = {
      split: `Divide ${names[0]} on ${this.snapshot.robot}'s map?`,
      merge: `Merge ${names.join(" and ")} on ${this.snapshot.robot}'s map?`,
      rename: `Save ${name} as the name for ${names[0]} on ${this.snapshot.robot}'s map?`,
    };
    this.$("room-edit-description").textContent = descriptions[operation];
    if (rename) {
      this.$("room-edit-description").append(
        ` Room type: ${this.geometry.room_naming.types[roomType]}.`
      );
    }
    this.$("room-edit-dialog").showModal();
  }

  async saveRoomEdit() {
    const draft = this.roomDraft;
    if (!draft || this.roomSaving) return;
    this.roomSaving = true;
    this.$("room-edit-dialog").close();
    this.$("review-room-edit").disabled = true;
    const rename = draft.operation === "rename";
    this.$("room-edit-status").textContent = rename ? "Saving room name…" : "Saving room boundaries…";
    try {
      await this._hass.callWS({
        type: "roomba_home/edit_rooms",
        entity_id: this.config.entity,
        map_id: draft.id,
        version: draft.version,
        inventory_id: this.snapshot.inventory_id,
        operation: draft.operation,
        room_ids: draft.roomIds,
        ...(draft.points ? { split_points: draft.points } : {}),
        ...(rename ? { name: draft.name, room_type: draft.roomType } : {}),
      });
      if (this.roomDraft === draft) this.closeRoomEditor();
      this.operationMessage = rename ? "Room name saved."
        : draft.operation === "split" ? "Room divided." : "Rooms merged.";
      this.$("status").textContent = this.operationMessage;
    } catch (error) {
      if (this.roomDraft === draft) this.$("room-edit-status").textContent = error.message;
    } finally {
      this.roomSaving = false;
      if (this.roomDraft === draft) this.updateRoomEdit();
      await this.refresh(true);
    }
  }

  openZoneEditor() {
    if (this.$("edit-zones").disabled || this.$("edit-zones").hidden) return;
    this.zoneDraft = { ...this.snapshot.map, inventoryId: this.snapshot.inventory_id };
    this.$("zone-operation").value = "create";
    this.$("zone-editor").hidden = false;
    this.renderZoneEditor();
    this.updateSelection();
    this.$("zone-operation").focus();
  }

  closeZoneEditor() {
    this.zoneDraft = null;
    this.$("zone-editor").hidden = true;
    const dialog = this.$("zone-edit-dialog");
    if (dialog.open) dialog.close();
  }

  renderZoneEditor(zoneId) {
    const operation = this.$("zone-operation").value;
    const zones = this.geometry.editable_zones;
    const picker = this.$("edit-zone");
    picker.replaceChildren(...zones.map((zone) => option(zone.id, zone.name ?? "Unnamed zone")));
    if (zones.some((zone) => zone.id === zoneId)) picker.value = zoneId;
    const zone = operation === "create" ? null : zones.find((entry) => entry.id === picker.value);
    this.$("zone-select-label").hidden = operation === "create";
    this.$("zone-shape").hidden = operation === "delete" || (operation === "update" && !zone);
    this.$("zone-name").value = zone?.name ?? "";
    const availability = this.$("zone-availability");
    availability.hidden = !zone;
    availability.textContent = zone?.destination_available ? "Available for cleaning." :
      "Saved on the map. Waiting for Roomba to publish the cleaning destination.";
    this.$("zone-edit-status").textContent = operation !== "create" && !zone ? "No zones saved." : "";
    this.zoneDraft.placing = null;
    const points = zone?.polygons.flat(2);
    const bounds = points?.length ? mapBounds(points) : [];
    this.setZoneBounds(bounds, false);
  }

  setZoneBounds(bounds, changed = true) {
    this.zoneDraft.changedBounds = changed;
    this.zoneFields.forEach((input, index) => { input.value = bounds[index] ?? ""; });
    this.updateZoneEdit();
    this.draw();
  }

  updateZoneEdit() {
    const draft = this.zoneDraft;
    const operation = this.$("zone-operation").value;
    draft.operation = operation;
    draft.zone = operation === "create" ? null :
      this.geometry.editable_zones.find((zone) => zone.id === this.$("edit-zone").value);
    draft.name = this.$("zone-name").value.trim();
    draft.bounds = draft.changedBounds ? this.zoneFields.map((input) => input.valueAsNumber) : null;
    const boundsValid = draft.bounds?.every(Number.isFinite) &&
      draft.bounds[0] !== draft.bounds[2] && draft.bounds[1] !== draft.bounds[3];
    const hasOutline = draft.changedBounds ? boundsValid : draft.zone?.can_rename;
    this.$("review-zone-edit").disabled = this.zoneSaving || (operation === "delete"
      ? !draft.zone : !draft.name || !hasOutline);
  }

  reviewZoneEdit() {
    const draft = this.zoneDraft;
    if (!draft || this.$("review-zone-edit").disabled) return;
    const remove = draft.operation === "delete";
    const name = remove ? draft.zone.name ?? "Unnamed zone" : draft.name;
    const floor = this.snapshot.maps.find((map) => map.id === draft.id)?.name ?? "this floor";
    this.$("zone-edit-title").textContent = remove ? "Remove cleaning zone?" : "Save cleaning zone?";
    this.$("zone-edit-description").textContent = `${remove ? "Remove" : "Save"} ${name} on ${floor}?`;
    this.$("zone-removal-notice").hidden = !remove;
    this.$("zone-edit-dialog").showModal();
  }

  async saveZoneEdit() {
    const draft = this.zoneDraft;
    if (!draft || this.zoneSaving) return;
    const entity = this.config.entity;
    this.zoneSaving = true;
    this.$("zone-edit-dialog").close();
    this.$("review-zone-edit").disabled = true;
    this.$("zone-edit-status").textContent = "Saving cleaning zone…";
    const remove = draft.operation === "delete";
    try {
      const result = await this._hass.callWS({
        type: "roomba_home/edit_zones",
        entity_id: entity,
        map_id: draft.id,
        version: draft.version,
        inventory_id: draft.inventoryId,
        operation: draft.operation,
        ...(draft.zone ? { zone_id: draft.zone.id } : {}),
        ...(remove ? {} : { name: draft.name, ...(draft.bounds ? { bounds: draft.bounds } : {}) }),
      });
      if (this.zoneDraft === draft) this.closeZoneEditor();
      if (this.config.entity !== entity || this.floor !== draft.id) return;
      this.operationMessage = remove
        ? (result.destination_available ? "Outline removed. Roomba still lists the destination." : "Cleaning zone removed.")
        : (result.destination_available ? "Cleaning zone saved." : "Zone saved on the map. Waiting for Roomba to publish the destination.");
      this.$("status").textContent = this.operationMessage;
    } catch (error) {
      if (this.zoneDraft === draft) this.$("zone-edit-status").textContent = error.message;
    } finally {
      this.zoneSaving = false;
      if (this.zoneDraft === draft) this.updateZoneEdit();
      await this.refresh(true);
    }
  }

  openRestrictionEditor() {
    if (this.$("edit-restrictions").disabled || this.$("edit-restrictions").hidden) return;
    this.restrictionDraft = { ...this.snapshot.map, inventoryId: this.snapshot.inventory_id };
    this.$("restriction-editor").hidden = false;
    this.$("restriction-operation").value = "create";
    this.renderRestrictionEditor();
    this.updateSelection();
    this.$("restriction-operation").focus();
  }

  closeRestrictionEditor() {
    this.restrictionDraft = null;
    this.$("restriction-editor").hidden = true;
    const dialog = this.$("restriction-edit-dialog");
    if (dialog.open) dialog.close();
  }

  renderRestrictionEditor(identifier = this.$("restriction-target").value) {
    const operation = this.$("restriction-operation").value;
    const shapes = this.geometry.editable_restrictions;
    const picker = this.$("restriction-target");
    picker.replaceChildren(...shapes.map((shape, index) =>
      option(shape.id, `${RESTRICTION_TYPES[shape.kind]} ${index + 1}`)));
    if (shapes.some((shape) => shape.id === identifier)) picker.value = identifier;
    const create = operation === "create";
    const shape = create ? null : shapes.find((item) => item.id === picker.value);
    this.$("restriction-kind-label").hidden = !create;
    this.$("restriction-select-label").hidden = create;
    this.$("restriction-shape").hidden = operation === "delete" || (!create && !shape);
    this.$("restriction-edit-status").textContent = !create && !shape ? "No restrictions saved." : "";
    this.restrictionDraft.placing = null;
    const bounds = shape?.kind === "wall" ? shape.points.flat() : shape ? mapBounds(shape.points) : [];
    this.setRestrictionBounds(bounds, false);
  }

  setRestrictionBounds(bounds, changed = true) {
    this.restrictionDraft.changedBounds = changed;
    this.restrictionFields.forEach((input, index) => { input.value = bounds[index] ?? ""; });
    this.updateRestrictionEdit();
    this.draw();
  }

  updateRestrictionEdit() {
    const draft = this.restrictionDraft;
    draft.operation = this.$("restriction-operation").value;
    const create = draft.operation === "create";
    draft.shape = create ? null : this.geometry.editable_restrictions.find((shape) =>
      shape.id === this.$("restriction-target").value);
    draft.kind = create ? this.$("restriction-kind").value : draft.shape?.kind;
    const wall = draft.kind === "wall";
    this.$("place-restriction").textContent = wall ? "Place wall on map" : "Place rectangle on map";
    this.$("restriction-coordinate-title").textContent = wall ? "Endpoint coordinates" : "Rectangle coordinates";
    for (const axis of ["x", "y"]) {
      this.$(`restriction-${axis}1-label`).textContent = `First ${wall ? "endpoint" : "corner"} ${axis.toUpperCase()}`;
      this.$(`restriction-${axis}2-label`).textContent = `${wall ? "Second endpoint" : "Opposite corner"} ${axis.toUpperCase()}`;
    }
    if (draft.placing != null) {
      const first = wall ? "first endpoint" : "first corner";
      const second = wall ? "second endpoint" : "opposite corner";
      this.$("restriction-edit-status").textContent = `Select the ${draft.placing === 0 ? first : second} on the map.`;
    }
    draft.bounds = draft.changedBounds ? this.restrictionFields.map((input) => input.valueAsNumber) : null;
    const [x1, y1, x2, y2] = draft.bounds ?? [];
    const boundsValid = draft.bounds?.every(Number.isFinite) &&
      (wall ? x1 !== x2 || y1 !== y2 : x1 !== x2 && y1 !== y2);
    this.$("review-restriction-edit").disabled = this.restrictionSaving ||
      (!create && !draft.shape) || (draft.operation !== "delete" && !boundsValid);
  }

  reviewRestrictionEdit() {
    const draft = this.restrictionDraft;
    if (!draft || this.$("review-restriction-edit").disabled) return;
    const remove = draft.operation === "delete";
    const floor = this.snapshot.floor_settings?.name ?? "this floor";
    const type = RESTRICTION_TYPES[draft.kind].toLowerCase();
    this.$("restriction-edit-title").textContent = remove ? "Remove restriction?" : "Save restriction?";
    this.$("restriction-edit-description").textContent =
      `${remove ? "Remove" : "Save"} the ${type} on ${floor}?`;
    this.$("restriction-edit-dialog").showModal();
  }

  async saveRestrictionEdit() {
    const draft = this.restrictionDraft;
    if (!draft || this.restrictionSaving) return;
    const entity = this.config.entity;
    const remove = draft.operation === "delete";
    this.restrictionSaving = true;
    this.$("restriction-edit-dialog").close();
    this.$("review-restriction-edit").disabled = true;
    this.$("restriction-edit-status").textContent = "Saving restriction…";
    try {
      await this._hass.callWS({
        type: "roomba_home/edit_restrictions",
        entity_id: entity,
        map_id: draft.id,
        version: draft.version,
        inventory_id: draft.inventoryId,
        operation: draft.operation,
        ...(draft.shape ? { zone_id: draft.shape.id } : { kind: draft.kind }),
        ...(remove ? {} : { bounds: draft.bounds }),
      });
      if (this.restrictionDraft === draft) this.closeRestrictionEditor();
      if (this.config.entity !== entity || this.floor !== draft.id) return;
      this.operationMessage = remove ? "Restriction removed." : "Restriction saved.";
      this.$("status").textContent = this.operationMessage;
    } catch (error) {
      if (this.restrictionDraft === draft) this.$("restriction-edit-status").textContent = error.message;
    } finally {
      this.restrictionSaving = false;
      if (this.restrictionDraft === draft) this.updateRestrictionEdit();
      await this.refresh(true);
    }
  }

  openFurnitureEditor() {
    const button = this.$("edit-furniture");
    if (button.disabled || button.hidden) return;
    this.furnitureDraft = { ...this.snapshot.map, inventoryId: this.snapshot.inventory_id };
    this.$("furniture-kind").replaceChildren(...Object.entries(this.geometry.furniture.types)
      .map(([kind, label]) => option(kind, label)));
    this.$("furniture-editor").hidden = false;
    this.$("furniture-operation").value = "create";
    this.renderFurnitureEditor();
    this.updateSelection();
    this.$("furniture-operation").focus();
  }

  closeFurnitureEditor() {
    this.furnitureDraft = null;
    this.$("furniture-editor").hidden = true;
    const dialog = this.$("furniture-edit-dialog");
    if (dialog.open) dialog.close();
  }

  renderFurnitureEditor(identifier = this.$("furniture-target").value) {
    const { items, types } = this.geometry.furniture;
    const picker = this.$("furniture-target");
    picker.replaceChildren(...items.map(({ id, kind, source }, index) =>
      option(id, `${types[kind]} ${index + 1} · ${source === "robot" ? "Detected" : "Added"}`)));
    if (items.some((item) => item.id === identifier)) picker.value = identifier;
    const draft = this.furnitureDraft;
    draft.operation = this.$("furniture-operation").value;
    const create = draft.operation === "create";
    draft.item = create ? null : items.find(({ id }) => id === picker.value);
    draft.placing = false;
    this.$("furniture-kind-label").hidden = !create;
    this.$("furniture-target-label").hidden = create;
    this.$("furniture-placement").hidden = draft.operation === "delete" || (!create && !draft.item);
    this.$("furniture-status").textContent = !create && !draft.item ? "No furniture on this floor." : "";
    this.setFurnitureFields(draft.item?.pose ?? ["", "", 1, 1, 0]);
  }

  setFurnitureFields(values) {
    values.forEach((value, index) => { this.furnitureFields[index].value = value; });
    this.updateFurnitureDraft();
  }

  updateFurnitureDraft() {
    const draft = this.furnitureDraft;
    const create = draft.operation === "create";
    draft.kind = create ? this.$("furniture-kind").value : draft.item?.kind;
    const pose = this.furnitureFields.map((input) => input.valueAsNumber);
    draft.pose = pose.every(Number.isFinite) && pose[2] > 0 && pose[3] > 0 && Math.abs(pose[4]) <= 360
      ? pose : null;
    const changed = draft.pose?.some((value, index) => value !== draft.item?.pose[index]);
    this.$("review-furniture-edit").disabled = this.furnitureSaving || !draft.kind ||
      (!create && !draft.item) || (draft.operation !== "delete" && !changed);
    this.draw();
  }

  reviewFurnitureEdit() {
    const draft = this.furnitureDraft;
    if (!draft || this.$("review-furniture-edit").disabled) return;
    const remove = draft.operation === "delete";
    const name = this.geometry.furniture.types[draft.kind];
    const floor = this.snapshot.floor_settings?.name?.trim() || "this floor";
    this.$("furniture-edit-title").textContent = remove ? "Remove furniture?" : "Save furniture?";
    this.$("furniture-edit-description").textContent = `${remove ? "Remove" : "Save"} ${name} on ${floor}?`;
    this.$("furniture-edit-dialog").showModal();
  }

  async saveFurnitureEdit() {
    const draft = this.furnitureDraft;
    if (!draft || this.furnitureSaving) return;
    const entity = this.config.entity;
    const remove = draft.operation === "delete";
    this.furnitureSaving = true;
    this.$("furniture-edit-dialog").close();
    this.$("review-furniture-edit").disabled = true;
    this.$("furniture-status").textContent = "Saving furniture…";
    try {
      await this._hass.callWS({
        type: "roomba_home/edit_furniture",
        entity_id: entity,
        map_id: draft.id,
        version: draft.version,
        inventory_id: draft.inventoryId,
        operation: draft.operation,
        ...(draft.item ? { object_id: draft.item.id } : { kind: draft.kind }),
        ...(remove ? {} : { pose: draft.pose }),
      });
      if (this.furnitureDraft === draft) this.closeFurnitureEditor();
      if (this.config.entity !== entity || this.floor !== draft.id) return;
      this.operationMessage = remove ? "Furniture removed." : "Furniture saved.";
      this.$("status").textContent = this.operationMessage;
    } catch (error) {
      if (this.furnitureDraft === draft) this.$("furniture-status").textContent = error.message;
    } finally {
      this.furnitureSaving = false;
      if (this.furnitureDraft === draft) this.updateFurnitureDraft();
      await this.refresh(true);
    }
  }

  review() {
    const data = this.snapshot;
    const point = this.pointMode ? this.point : null;
    if (!data || !this.geometry || !(point || this.selected.size) || this.submitting) return;
    this.operationMessage = null;
    this.confirmation = {
      ...data.map,
      selectionId: this.geometry.selection_id ?? data.inventory_id,
      regions: [...this.selected],
      point,
      mode: point ? this.pointCleaningMode : null,
    };
    const names = this.geometry.regions.filter((area) => this.selected.has(area.id)).map((area) => area.name);
    this.$("confirm-text").textContent = point
      ? `${data.robot} will ${MODES[this.pointCleaningMode].toLowerCase()} around the marked point in ${point.name}.`
      : `${data.robot} will clean ${names.join(", ")}.`;
    this.dialog.showModal();
  }

  async submit() {
    const choice = this.confirmation;
    if (!choice || this.submitting || !this.snapshot ||
        (choice.point && (!this.pointAvailable || !this.pointModes.includes(choice.mode))) ||
        choice.id !== this.snapshot.map.id || choice.version !== this.snapshot.map.version ||
        choice.selectionId !== (this.geometry?.selection_id ?? this.snapshot.inventory_id)) return;
    this.submitting = true;
    this.confirmation = null;
    this.dialog.close();
    this.updateSelection();
    this.operationMessage = "Sending cleaning request…";
    this.$("status").textContent = this.operationMessage;
    try {
      const review = { map_id: choice.id, version: choice.version };
      if (choice.selectionId) review.inventory_id = choice.selectionId;
      const [service, selection] = choice.point
        ? ["clean_point", {region_id: choice.point.id, x: choice.point.x, y: choice.point.y, mode: choice.mode, review}]
        : ["clean_map_selection", {...review, regions: choice.regions}];
      await this._hass.callService("roomba_home", service, selection, { entity_id: this.config.entity });
      this.selected.clear();
      this.point = null;
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

  async callAction(service, data, entity) {
    const result = await this._hass.callWS({
      type: "call_service", domain: "roomba_home", service,
      service_data: data, target: { entity_id: entity }, return_response: true,
    });
    const response = result.response?.[entity];
    if (!response) throw new Error("Home Assistant did not return an action response.");
    return response;
  }

  async reviewMapImpact() {
    if (!this.geometry || !this.selected.size || this.impactLoading) return;
    const entity = this.config.entity;
    const chosen = new Set(this.selected);
    const areas = this.geometry.regions.filter(({ id }) => chosen.has(id));
    const list = this.$("impact-list");
    const status = this.$("impact-status");
    list.replaceChildren();
    this.$("impact-areas").textContent = areas.map(({ name }) => name).join(", ");
    status.textContent = "Checking saved routines and weekly schedules…";
    status.hidden = false;
    this.impactLoading = true;
    this.$("impact-dialog").showModal();
    const sources = [["routines", "Routine"], ["schedules", "Weekly schedule"]];
    const results = await Promise.allSettled(sources.map(([source]) =>
      this.callAction(`list_cleaning_${source}`, {}, entity)));
    this.impactLoading = false;
    const messages = [];
    for (const [index, result] of results.entries()) {
      const [source, label] = sources[index];
      if (result.status === "rejected" || !Array.isArray(result.value[source])) {
        messages.push(`Could not check ${source}.`);
        continue;
      }
      let unknown = 0;
      for (const row of result.value[source]) {
        if (row.regions?.some((id) => chosen.has(id))) {
          const item = document.createElement("li");
          item.textContent = `${label} · ${row.name ?? "Unnamed"}`;
          list.append(item);
        } else if (!row.regions?.length || (source === "routines" && !row.region_settings)) {
          unknown++;
        }
      }
      if (unknown) messages.push(`Some ${source} have unverified destinations.`);
    }
    if (!list.childElementCount && !messages.length) {
      messages.push("No matching routines or weekly schedules were returned.");
    }
    status.textContent = messages.join(" ");
    status.hidden = !messages.length;
  }

  async openRoutines(scheduleEditor = false) {
    if (!this.snapshot || !this.geometry || this.routineBusy || this.routineDialog.open) return;
    const entity = this.config.entity;
    this.routineMap = {
      ...this.snapshot.map,
      selectionId: this.geometry.selection_id ?? this.snapshot.inventory_id,
    };
    this.scheduleEditor = scheduleEditor;
    const furniture = scheduleEditor ? [] : this.geometry.furniture?.destinations ?? [];
    const areas = [...this.geometry.regions, ...furniture];
    this.routineAreas = new Map(areas.filter((area) => area.id)
      .map((area) => [area.id, area.name]));
    this.routines = [];
    this.quickRoutines = null;
    this.routineBusy = true;
    this.editRoutine("");
    const kind = scheduleEditor ? "schedules" : "routines";
    this.$("routine-status").textContent = `Loading ${kind}…`;
    this.routineDialog.showModal();
    try {
      const result = await this.callAction(`list_cleaning_${kind}`, {}, entity);
      if (this.config.entity === entity) this.routines = result[kind];
      this.$("routine-status").textContent = "";
    } catch (error) {
      this.$("routine-status").textContent = error?.message || `Could not load ${kind}.`;
    } finally {
      this.routineBusy = false;
      this.renderRoutine();
    }
  }

  editRoutine(id) {
    const saved = this.routines.find((routine) => routine.id === id);
    const settings = saved?.region_settings;
    const canReplace = settings?.every(({ id }) => this.routineAreas.has(id));
    const selected = this.scheduleEditor ? [...this.selected].filter((id) => this.routineAreas.has(id)) : this.selected;
    this.routineDraft = {
      saved,
      name: saved?.name ?? "",
      regions: saved ? (canReplace ? settings.map((region) => ({ ...region })) : null)
        : [...selected].map((id) => ({ id })),
      ordered: saved?.ordered !== false,
    };
    if (this.scheduleEditor) Object.assign(this.routineDraft, {
      frequency: saved?.frequency ?? "weekly", weekdays: [...(saved?.weekdays ?? [])], time: saved?.time ?? "",
    });
    this.$("routine-status").textContent = "";
    this.renderRoutine();
  }

  renderRoutine() {
    const { saved, name, regions } = this.routineDraft;
    const busy = this.routineBusy;
    const locked = busy || saved?.editable === false;
    const schedule = Boolean(this.scheduleEditor);
    this.$("routine-title").textContent = schedule ? "Cleaning schedules" : "Cleaning routines";
    this.$("routine-list-label").textContent = schedule ? "Schedule" : "Routine";
    this.$("quick-routine-fields").hidden = schedule;
    const source = this.$("routine-list");
    source.replaceChildren(option("", schedule ? "New schedule" : "New routine"), ...this.routines
      .map((routine) => option(routine.id, schedule
        ? [routine.name, routine.time, routine.enabled ? "Enabled" : "Disabled"].filter(Boolean).join(" · ")
        : routine.name)));
    source.value = saved?.id ?? "";
    source.disabled = busy;
    const input = this.$("routine-name");
    input.value = name;
    input.disabled = locked;
    input.required = !schedule || !saved;
    this.renderScheduleTiming(locked);
    const estimate = this.$("routine-estimate");
    const minutes = saved?.estimate?.duration_minutes;
    estimate.hidden = minutes == null;
    if (minutes != null) {
      const confidence = saved.estimate.confidence;
      const suffix = confidence ? ` · ${historyLabel(confidence)} confidence` : "";
      estimate.textContent = `Saved estimate: ${Math.ceil(minutes)} min${suffix}`;
    }
    const note = this.$("routine-region-note");
    note.hidden = regions !== null;
    note.textContent = "Some destinations or settings could not be resolved on this floor plan.";
    const order = this.$("routine-order");
    this.$("routine-order-label").hidden = schedule || !regions?.length ||
      regions.some(({ id }) => id.includes(":furniture:"));
    order.disabled = locked;
    order.value = this.routineDraft.ordered === false ? "automatic" : "listed";
    this.$("routine-regions").replaceChildren(...(regions ?? []).map((region, index) =>
      this.routineRegion(region, index, regions, locked)));
    this.renderRoutineGlobalPreset();
    const add = this.$("add-routine-region");
    const remaining = [...this.routineAreas].filter(([id]) => !regions?.some((area) => area.id === id));
    add.replaceChildren(option("", "Choose an area"), ...remaining.map(([id, label]) => option(id, label)));
    this.$("add-routine-region-label").hidden = regions === null || locked || regions.length >= 32;
    add.disabled = !remaining.length;
    this.$("copy-routine").disabled = busy || !saved || !regions?.length;
    const deleteButton = this.$("remove-routine");
    deleteButton.textContent = "Delete";
    deleteButton.disabled = locked || !saved;
    const runButton = this.$("run-routine");
    runButton.hidden = schedule;
    runButton.textContent = saved ? "Run saved routine" : "Run draft";
    runButton.disabled = busy || !regions?.length || Boolean(saved && !saved.region_settings?.length);
    const toggle = this.$("toggle-schedule");
    toggle.hidden = !schedule || !saved;
    toggle.disabled = locked;
    toggle.textContent = saved?.enabled ? "Disable schedule" : "Enable schedule";
    const save = this.$("save-routine");
    save.textContent = schedule ? "Save schedule" : "Save routine";
    save.disabled = locked || (!saved && !regions?.length);
    this.renderRoutineEstimate();
    this.renderQuickRoutines();
  }

  renderScheduleTiming(locked) {
    const fields = this.$("schedule-fields");
    const time = this.$("schedule-time");
    fields.hidden = !this.scheduleEditor;
    time.required = Boolean(this.scheduleEditor);
    if (!this.scheduleEditor) return;
    const { weekdays, frequency, time: start } = this.routineDraft;
    time.value = start;
    time.disabled = locked;
    const repeat = this.$("schedule-frequency");
    repeat.value = frequency;
    repeat.disabled = locked;
    const days = this.$("schedule-days");
    days.hidden = frequency !== "weekly";
    days.disabled = locked;
    this.$("schedule-day-options").replaceChildren(...["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
      .map((day, index) => {
        const label = document.createElement("label");
        const check = document.createElement("input");
        const weekday = index + 1;
        check.type = "checkbox";
        check.checked = weekdays.includes(weekday);
        check.onchange = () => {
          if (check.checked) weekdays.push(weekday);
          else weekdays.splice(weekdays.indexOf(weekday), 1);
        };
        label.append(check, day);
        return label;
      }));
  }

  renderQuickRoutines() {
    const current = this.routineFloorIsCurrent();
    if (!current) this.quickRoutines = null;
    const reading = this.quickRoutines;
    const button = this.$("load-quick-routines");
    const status = this.$("quick-routines-status");
    const list = this.$("quick-routines");
    button.disabled = !current || this.routineBusy || Boolean(reading?.pending);
    const options = reading?.options ?? [];
    status.textContent = reading?.pending ? "Reading Roomba's routines…"
      : (reading?.error ?? (reading && !options.length ? "Roomba returned no routines for this floor." : ""));
    status.hidden = !status.textContent;
    list.hidden = !options.length;
    list.replaceChildren(...options.map((option) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      const details = [option.name];
      if (option.last_run) details.push(historyTime(option.last_run));
      if (option.duration_seconds != null) details.push(`${Math.ceil(option.duration_seconds / 60)} min`);
      name.textContent = details.join(" · ");
      item.append(name);
      const regions = option.region_settings;
      const loadable = regions?.length && regions.every(({ id }) => this.routineAreas.has(id));
      if (loadable || (option.choose_point && this.pointAvailable)) {
        const load = document.createElement("button");
        load.type = "button";
        load.textContent = option.choose_point ? "Choose point" : "Load draft";
        load.setAttribute("aria-label", `${load.textContent} · ${details.join(" · ")}`);
        load.disabled = Boolean(this.routineBusy);
        load.onclick = () => this.loadQuickDraft(option, reading);
        item.append(load);
      } else {
        const unavailable = document.createElement("span");
        unavailable.className = "muted";
        unavailable.textContent = "Unavailable on this floor plan";
        item.append(unavailable);
      }
      return item;
    }));
  }

  async loadQuickRoutines() {
    if (this.$("load-quick-routines").disabled || !this.routineFloorIsCurrent()) return;
    const entity = this.config.entity;
    const { id, version } = this.routineMap;
    const reading = { pending: true };
    this.quickRoutines = reading;
    this.renderQuickRoutines();
    try {
      const response = await this.callAction("list_map_routines", { map_id: id, version }, entity);
      if (response.map_id !== id || response.version !== version) throw new Error("The floor changed. Open routines again.");
      reading.options = response.routines;
    } catch (error) {
      reading.error = error?.message || "Roomba's routines are unavailable.";
    } finally {
      reading.pending = false;
      if (this.quickRoutines === reading && this.config.entity === entity && this.routineDialog.open) {
        this.renderQuickRoutines();
      }
    }
  }

  loadQuickDraft(option, reading) {
    if (this.routineBusy || this.quickRoutines !== reading || !this.routineFloorIsCurrent()) return;
    if (option.choose_point && this.pointAvailable) {
      this.routineDialog.close();
      if (!this.pointMode) this.togglePointMode();
      this.$("point-mode").focus();
      return;
    }
    const regions = option.region_settings;
    if (!regions?.length || !regions.every(({ id }) => this.routineAreas.has(id))) return;
    this.routineDraft = { name: option.name, regions: regions.map((region) => ({ ...region })) };
    this.$("routine-status").textContent = "Review the loaded areas and preferences.";
    this.renderRoutine();
    this.$("routine-name").focus();
  }

  renderRoutineEstimate() {
    const regions = this.routineDraft.regions;
    const available = Boolean(regions?.length && this.routineFloorIsCurrent());
    let reading = this.routineEstimate;
    if (reading && (!available || reading.draft !== this.routineDraft || reading.regions !== JSON.stringify(regions))) {
      this.routineEstimate = reading = null;
    }
    const button = this.$("estimate-routine");
    button.disabled = !available || this.routineBusy || Boolean(reading?.pending);
    button.hidden = !regions?.length;
    const message = this.$("routine-draft-time");
    const areas = this.$("routine-area-times");
    const result = reading?.result;
    message.hidden = !reading;
    areas.hidden = !result;
    if (!result) {
      message.textContent = reading?.pending ? "Reading Roomba's estimates…" : (reading?.error ?? "");
      areas.replaceChildren();
      return;
    }
    const duration = (seconds) => `${Math.ceil(seconds / 60)} min`;
    if (result.duration_seconds != null) message.textContent = `Draft estimate · ${duration(result.duration_seconds)}`;
    else if (result.partial_duration_seconds != null) {
      const known = result.areas.filter(({ duration_seconds }) => duration_seconds != null).length;
      message.textContent = `Known time · ${duration(result.partial_duration_seconds)} for ${known} of ${result.areas.length} areas`;
    } else message.textContent = "Roomba has no estimate for this draft.";
    areas.replaceChildren(...result.areas.map((area) => {
      const row = document.createElement("li");
      const time = area.duration_seconds != null ? duration(area.duration_seconds)
        : (area.ambiguous ? "Choose more specific preferences" : "Unavailable");
      row.textContent = `${this.routineAreas.get(area.id) ?? "Area"} · ${time}`;
      return row;
    }));
  }

  async estimateRoutine() {
    const { regions } = this.routineDraft;
    if (this.$("estimate-routine").disabled || !regions?.length || !this.routineFloorIsCurrent()) return;
    const entity = this.config.entity;
    const { id, version, selectionId } = this.routineMap;
    const reading = { draft: this.routineDraft, regions: JSON.stringify(regions), pending: true };
    this.routineEstimate = reading;
    this.renderRoutineEstimate();
    try {
      reading.result = await this.callAction("estimate_cleaning_routine", {
        regions: JSON.parse(reading.regions), floor: { map_id: id, version, inventory_id: selectionId },
      }, entity);
    } catch (error) {
      reading.error = error?.message || "Roomba could not estimate this draft.";
    } finally {
      reading.pending = false;
      if (this.routineEstimate === reading && this.config.entity === entity && this.routineDialog.open) {
        this.renderRoutineEstimate();
      }
    }
  }

  routinePresetsFor(region) {
    const cleaning = this.snapshot?.cleaning;
    return cleaning?.presets?.[region.mode ?? cleaning.default_mode] ?? {};
  }

  canApplySmartPreset(region) {
    return this.snapshot?.cleaning?.supports_smart_presets === true &&
      this.routineMap && region.id.startsWith(`${this.routineMap.id}:rid:`);
  }

  async applySmartPresets(areas) {
    if (this.routineBusy || !this.routineFloorIsCurrent()) return;
    const entity = this.config.entity;
    const draft = this.routineDraft;
    const { id, version } = this.routineMap;
    const defaultMode = this.snapshot.cleaning.default_mode;
    const regions = JSON.stringify(draft.regions);
    const request = this.smartPresetRequest = {};
    const status = this.$("routine-status");
    const reading = "Reading Roomba's room recommendations…";
    status.textContent = reading;
    const current = () => this.smartPresetRequest === request && this.routineDialog.open &&
      this.config.entity === entity && this.routineDraft === draft && !this.routineBusy &&
      this.routineFloorIsCurrent() && this.snapshot.cleaning.default_mode === defaultMode &&
      JSON.stringify(draft.regions) === regions;
    try {
      const scores = await this._hass.callWS({
        type: "roomba_home/cleaning_scores", entity_id: entity, map_id: id, version,
      });
      if (!current()) return;
      if (scores.map?.id !== id || scores.map?.version !== version) {
        status.textContent = "The floor changed. Review the current map and try again.";
        return;
      }
      let updated = 0;
      for (const area of areas) {
        const mode = area.mode ?? defaultMode;
        const settings = scores.smart_presets?.[area.id]?.[mode];
        if (!settings) continue;
        Object.assign(area, settings, { mode });
        updated++;
      }
      this.renderRoutine();
      if (!updated) status.textContent = "Roomba has no compatible recommendations for these areas.";
      else if (areas.length === 1) status.textContent = "Applied Roomba's recommendations to this area.";
      else status.textContent = `Applied Roomba's recommendations to ${updated} of ${areas.length} areas.`;
    } catch (error) {
      if (current()) status.textContent = error?.message || "Roomba's room recommendations are unavailable.";
    } finally {
      if (this.smartPresetRequest === request) {
        this.smartPresetRequest = null;
        if (status.textContent === reading) status.textContent = "";
      }
    }
  }

  renderRoutineGlobalPreset() {
    const { saved, regions } = this.routineDraft;
    const locked = this.routineBusy || saved?.editable === false;
    const select = this.$("routine-preset-all");
    const recipes = (regions ?? []).map((region) => this.routinePresetsFor(region));
    const keys = Object.keys(recipes[0] ?? {}).filter((key) =>
      recipes.every((choices) => Object.hasOwn(choices, key)));
    if (regions?.some((region) => this.canApplySmartPreset(region))) keys.push("smart");
    this.$("routine-preset-all-label").hidden = recipes.length < 2 || !keys.length;
    showPresetChoices(select, keys, locked);
    select.onchange = async () => {
      const key = select.value;
      if (locked || recipes.length < 2 || !keys.includes(key)) return;
      if (key === "smart") {
        select.value = "";
        await this.applySmartPresets(regions);
      } else {
        regions.forEach((region, index) => Object.assign(region, recipes[index][key]));
        this.renderRoutine();
      }
      select.focus();
    };
  }

  routineRegion(region, index, regions, locked) {
    const item = document.createElement("li");
    const label = this.routineAreas.get(region.id);
    const title = document.createElement("strong");
    title.textContent = label;
    item.append(title);
    const actions = document.createElement("div");
    actions.className = "routine-region-controls";
    for (const [text, offset] of [["Move up", -1], ["Move down", 1], ["Remove", 0]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.setAttribute("aria-label", `${text} ${label}`);
      const next = index + offset;
      button.disabled = locked || next < 0 || next >= regions.length;
      button.onclick = () => {
        regions.splice(index, 1);
        if (offset) {
          regions.splice(next, 0, region);
          this.routineDraft.ordered = true;
        }
        this.renderRoutine();
      };
      actions.append(button);
    }
    item.append(actions);
    const capabilities = this.snapshot?.cleaning ?? {};
    const modes = (capabilities.modes ?? []).map((mode) => option(mode, MODES[mode]));
    const presetField = document.createElement("label");
    presetField.className = "routine-field";
    presetField.textContent = "Cleaning preset";
    const preset = document.createElement("select");
    preset.dataset.routinePreset = "";
    presetField.append(preset);
    preset.onchange = async () => {
      const choices = this.routinePresetsFor(region);
      const key = preset.value;
      if (locked) return;
      if (key === "smart" && this.canApplySmartPreset(region)) {
        preset.value = "";
        await this.applySmartPresets([region]);
      } else if (Object.hasOwn(choices, key)) {
        Object.assign(region, choices[key]);
        this.renderRoutine();
      } else return;
      this.$("routine-regions").children[index]?.querySelector("[data-routine-preset]")?.focus();
    };
    const updateFields = () => {
      const keys = Object.keys(this.routinePresetsFor(region));
      if (this.canApplySmartPreset(region)) keys.push("smart");
      presetField.hidden = !keys.length;
      showPresetChoices(preset, keys, locked);
      const mode = region.mode ?? capabilities.default_mode;
      for (const field of item.querySelectorAll("[data-setting]")) {
        const key = field.dataset.setting;
        field.hidden = (mode === "vacuum" && ["wetness_level", "smart_scrub"].includes(key)) ||
          (mode === "mop" && ["suction_level", "carpet_boost"].includes(key));
      }
    };
    this.routineField(item, region, "mode", "Mode", modes, locked, String, () => {
      updateFields();
      this.renderRoutineGlobalPreset();
      this.renderRoutineEstimate();
    });
    item.append(presetField);
    for (const [key, text] of Object.entries(SETTINGS)) {
      const maximum = capabilities[key];
      if (!maximum) continue;
      const levels = typeof maximum === "number";
      const choices = levels ? Array.from({ length: maximum }, (_, i) => option(i + 1, i + 1))
        : [option("true", "On"), option("false", "Off")];
      this.routineField(item, region, key, text, choices, locked,
        levels ? Number : (value) => value === "true", () => this.renderRoutineEstimate()).dataset.setting = key;
    }
    updateFields();
    return item;
  }

  routineField(item, region, key, label, choices, locked, parse, updated) {
    const field = document.createElement("label");
    field.className = "routine-field";
    field.textContent = label;
    const input = document.createElement("select");
    input.append(option("", "Robot default"));
    if (key !== "mode") input.append(option("omit", "Use firmware default"));
    input.append(...choices);
    input.value = region[key] === null ? "omit" : (region[key]?.toString() ?? "");
    input.disabled = locked;
    input.onchange = () => {
      if (input.value === "") delete region[key];
      else region[key] = input.value === "omit" ? null : parse(input.value);
      updated?.();
    };
    field.append(input);
    item.append(field);
    return field;
  }

  copyRoutine() {
    const draft = this.routineDraft;
    draft.name = `${draft.name.slice(0, 113)} (copy)`;
    draft.saved = undefined;
    this.renderRoutine();
    this.$("routine-name").focus();
  }

  routineFloorIsCurrent() {
    const map = this.snapshot?.map;
    const review = this.routineMap;
    return Boolean(map && review && map.id === review.id && map.version === review.version &&
      (this.geometry?.selection_id ?? this.snapshot.inventory_id) === review.selectionId);
  }

  async saveRoutine() {
    const { saved, name, regions } = this.routineDraft;
    const ordered = this.routineDraft.ordered !== false;
    if (this.routineBusy || saved?.editable === false || !name.trim()) return;
    const data = { name: name.trim() };
    if (!saved || (regions && (JSON.stringify(regions) !== JSON.stringify(saved.region_settings) ||
        ordered !== (saved.ordered !== false)))) {
      if (!regions?.length || !this.routineFloorIsCurrent()) {
        this.$("routine-status").textContent = "Review an area selection on the current floor plan.";
        return;
      }
      data.regions = regions;
      if (!ordered) data.ordered = false;
    }
    if (saved) data.routine_id = saved.id;
    await this.mutateRoutine(saved ? "update_cleaning_routine" : "create_cleaning_routine", data);
  }

  async saveSchedule() {
    const { saved, name, regions, frequency, time, weekdays } = this.routineDraft;
    if (this.routineBusy) return;
    const status = this.$("routine-status");
    const data = {};
    if (!saved || name.trim() !== (saved.name ?? "")) {
      if (!name.trim()) {
        status.textContent = "Enter a schedule name.";
        return;
      }
      data.name = name.trim();
    }
    const days = [...weekdays].sort((a, b) => a - b);
    if (!saved || saved.time !== time || (saved.frequency ?? "weekly") !== frequency ||
        frequency === "weekly" && JSON.stringify(saved.weekdays) !== JSON.stringify(days)) {
      if (!time || frequency === "weekly" && !days.length) {
        status.textContent = "Choose a start time and, for a weekly schedule, at least one day.";
        return;
      }
      Object.assign(data, { frequency, time });
      if (frequency === "weekly") data.weekdays = days;
    }
    if (!saved || regions && JSON.stringify(regions) !== JSON.stringify(saved.region_settings)) {
      if (!regions?.length || !this.routineFloorIsCurrent()) {
        status.textContent = "Review an area selection on the current floor plan.";
        return;
      }
      const { id, version, selectionId } = this.routineMap;
      data.floor = { map_id: id, version, inventory_id: selectionId };
      data.regions = regions;
    }
    if (!Object.keys(data).length) {
      status.textContent = "No changes to save.";
      return;
    }
    if (saved) data.schedule_id = saved.id;
    await this.mutateRoutine(saved ? "update_cleaning_schedule" : "create_cleaning_schedule", data);
  }

  async toggleSchedule() {
    const { saved } = this.routineDraft;
    if (!saved || this.routineBusy) return;
    await this.mutateRoutine("set_cleaning_schedule_enabled", {
      schedule_id: saved.id, enabled: !saved.enabled,
    });
  }

  async removeRoutine() {
    const saved = this.routineDraft.saved;
    if (!saved || saved.editable === false || this.routineBusy) return;
    const button = this.$("remove-routine");
    if (button.textContent !== "Confirm delete") {
      button.textContent = "Confirm delete";
      this.$("routine-status").textContent = `Delete ${saved.name || "this schedule"}?`;
      return;
    }
    if (this.scheduleEditor) {
      await this.mutateRoutine("remove_cleaning_schedule", { schedule_id: saved.id });
    } else await this.mutateRoutine("remove_cleaning_routine", { routine_id: saved.id });
  }

  async runRoutine() {
    const { saved } = this.routineDraft;
    const regions = saved?.region_settings ?? this.routineDraft.regions;
    const ordered = (saved ?? this.routineDraft).ordered !== false;
    const button = this.$("run-routine");
    const status = this.$("routine-status");
    if (button.disabled || this.routineBusy || !regions?.length) return;
    if (!this.routineFloorIsCurrent()) {
      button.textContent = saved ? "Run saved routine" : "Run draft";
      status.textContent = "Reopen routines to review the current floor plan.";
      return;
    }
    const draftReview = saved ? null : JSON.stringify([regions, ordered]);
    if (button.textContent !== "Confirm start" || (!saved && this.routineRunReview !== draftReview)) {
      button.textContent = "Confirm start";
      this.routineRunReview = draftReview;
      const order = regions.map(({ id }) => this.routineAreas.get(id));
      const label = saved?.name ?? (this.routineDraft.name || "draft");
      status.textContent = ordered ? `Start ${label}: ${order.join(" → ")}?` :
        `Start ${label} in ${order.join(", ")}? Roomba will choose the order.`;
      return;
    }
    const { id, version, selectionId } = this.routineMap ?? {};
    const service = saved ? "run_cleaning_routine" : "run_cleaning_draft";
    const data = saved ? { routine_id: saved.id }
      : { regions, floor: { map_id: id, version, inventory_id: selectionId } };
    if (!saved && !ordered) data.ordered = false;
    this.routineRunReview = null;
    this.routineBusy = true;
    this.renderRoutine();
    status.textContent = "Waiting for Roomba to start…";
    try {
      await this._hass.callService("roomba_home", service, data, { entity_id: this.config.entity });
      status.textContent = "Routine request accepted. Check the robot state.";
    } catch (error) {
      status.textContent = error?.message || "Roomba did not confirm the start.";
    } finally {
      this.routineBusy = false;
      this.renderRoutine();
    }
  }

  async mutateRoutine(service, data) {
    const entity = this.config.entity;
    this.routineBusy = true;
    this.renderRoutine();
    this.$("routine-status").textContent = "Waiting for Roomba to confirm…";
    try {
      const result = await this.callAction(service, data, entity);
      if (this.config.entity !== entity) return;
      this.routines = this.routines.filter((routine) => routine.id !== result.id);
      const removed = service === "remove_cleaning_routine" || service === "remove_cleaning_schedule";
      if (!removed) this.routines.push(result);
      this.editRoutine(removed ? "" : result.id);
      const kind = this.scheduleEditor ? "Schedule" : "Routine";
      this.$("routine-status").textContent = `${kind} ${removed ? "deleted" : "saved"}.`;
    } catch (error) {
      this.$("routine-status").textContent = error?.message || "Roomba could not confirm the change.";
    } finally {
      this.routineBusy = false;
      this.renderRoutine();
    }
  }

  setZoom(zoom) {
    this.zoom = Math.min(4, Math.max(1, zoom));
    if (this.zoom === 1) this.pan = [0, 0];
    this.draw();
  }

  resetView() {
    this.pan = [0, 0];
    this.orbit = 0;
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

  placePoint() {
    const id = this.$("point-room").value;
    const room = this.pointRooms.find((area) => area.id === id);
    const fractions = [this.$("point-x").valueAsNumber / 100, this.$("point-y").valueAsNumber / 100];
    if (!room || !this.screenPoint || !interiorFractions(fractions)) {
      this.setPoint(null);
      return;
    }
    const [left, bottom, right, top] = roomBounds(room);
    const [x, y] = fractions;
    this.pickPoint(...this.screenPoint([left + x * (right - left), bottom + y * (top - bottom)]), id);
  }

  pickPoint(x, y, expectedRoom) {
    const contains = (path) => this.ctx.isPointInPath(path, x, y, "evenodd");
    const hits = new Set(this.targets.filter(({ kind, path }) => kind === "room" && contains(path))
      .map(({ id }) => id));
    const [id] = hits;
    const room = this.pointRooms.find((area) => area.id === id);
    const mops = this.pointCleaningMode !== "vacuum";
    if (!this.mapPoint || hits.size !== 1 || !room || (expectedRoom && expectedRoom !== id) ||
        this.exclusions.some(contains) || (mops && this.noMopPaths.some(contains))) {
      this.setPoint(null);
      return;
    }
    const native = this.mapPoint(x, y);
    const [left, bottom, right, top] = roomBounds(room);
    const relative = [(native[0] - left) / (right - left), (native[1] - bottom) / (top - bottom)];
    this.setPoint(interiorFractions(relative)
      ? { id, name: room.name, native, x: relative[0], y: relative[1] } : null);
  }

  setPoint(point) {
    if (!this.pointMode || !this.pointAvailable || this.submitting) return;
    this.point = point;
    this.confirmation = null;
    this.operationMessage = point ? null : "Choose an open point inside one room.";
    if (point) {
      this.$("point-room").value = point.id;
      this.$("point-x").value = Math.round(point.x * 10000) / 100;
      this.$("point-y").value = Math.round(point.y * 10000) / 100;
    } else this.$("status").textContent = this.operationMessage;
    this.updateSelection();
    this.draw();
  }

  pick(event) {
    if (this.floorDraft) return;
    const bounds = this.canvas.getBoundingClientRect();
    const x = (event.clientX - bounds.left) * WIDTH / bounds.width;
    const y = (event.clientY - bounds.top) * HEIGHT / bounds.height;
    if (this.furnitureDraft) {
      if (this.furnitureSaving) return;
      const draft = this.furnitureDraft;
      if (draft.placing && this.mapPoint) {
        draft.placing = false;
        this.$("furniture-status").textContent = "";
        this.setFurnitureFields(this.mapPoint(x, y));
      } else if (draft.operation !== "create") {
        const hit = this.furnitureTargets.findLast(({ path }) =>
          this.ctx.isPointInPath(path, x, y, "evenodd"));
        if (hit && hit.id !== draft.item?.id) this.renderFurnitureEditor(hit.id);
      }
      return;
    }
    if (this.restrictionDraft) {
      if (this.restrictionSaving) return;
      const draft = this.restrictionDraft;
      const slot = draft.placing;
      if (slot != null && this.mapPoint) {
        const point = this.mapPoint(x, y);
        draft.placing = slot === 0 ? 1 : null;
        if (slot !== 0) this.$("restriction-edit-status").textContent = "";
        this.setRestrictionBounds(slot === 0 ? point : [...draft.bounds.slice(0, 2), ...point]);
      } else if (draft.operation !== "create") {
        this.ctx.save();
        this.ctx.lineWidth = 12 * WIDTH / bounds.width;
        const hit = this.restrictionTargets.findLast(({ path, kind }) => kind === "wall"
          ? this.ctx.isPointInStroke(path, x, y)
          : this.ctx.isPointInPath(path, x, y, "evenodd"));
        this.ctx.restore();
        if (hit && hit.id !== draft.shape?.id) this.renderRestrictionEditor(hit.id);
      }
      return;
    }
    if (this.zoneDraft) {
      const slot = this.zoneDraft.placing;
      if (slot != null && this.mapPoint) {
        const point = this.mapPoint(x, y);
        this.setZoneBounds(slot === 0 ? point : [...this.zoneDraft.bounds.slice(0, 2), ...point]);
        this.zoneDraft.placing = slot === 0 ? 1 : null;
        this.$("zone-edit-status").textContent = slot === 0 ? "Select the opposite corner." : "";
      }
      return;
    }
    if (this.roomDraft) {
      if (this.roomSaving) return;
      const { id: mapId, operation, placing: slot, roomIds } = this.roomDraft;
      if (operation === "split" && slot != null && this.mapPoint) {
        const point = this.mapPoint(x, y);
        this.setDivider(slot === 0 ? point : [...this.roomDraft.points.slice(0, 2), ...point]);
        this.roomDraft.placing = slot === 0 ? 1 : null;
        this.$("room-edit-status").textContent = slot === 0 ? "Select the other endpoint." : "";
      } else {
        const prefix = `${mapId}:rid:`;
        const hit = this.targets.findLast(({ path, id }) =>
          id.startsWith(prefix) && this.ctx.isPointInPath(path, x, y, "evenodd"));
        const id = hit?.id.slice(prefix.length);
        if (!id || id === roomIds[0]) return;
        const second = this.$("edit-room-second");
        if (operation === "merge" && [...second.options].some((entry) => entry.value === id)) {
          second.value = id;
          this.updateRoomEdit();
          this.draw();
        } else if ([...this.$("edit-room-first").options].some((entry) => entry.value === id)) {
          this.renderRoomEditor(id);
        }
      }
      return;
    }
    if (this.pointMode) {
      this.pickPoint(x, y);
      return;
    }
    if (this.exclusions.some((path) => this.ctx.isPointInPath(path, x, y, "evenodd"))) return;
    this.ctx.lineWidth = 12;
    if (this.walls.some((path) => this.ctx.isPointInStroke(path, x, y))) return;
    const hit = this.targets.findLast(({ path }) => this.ctx.isPointInPath(path, x, y, "evenodd"));
    if (hit) this.toggle(hit.id);
  }

  draw() {
    this.liveMarkerProjection = null;
    this.markerCtx?.clearRect(0, 0, WIDTH, HEIGHT);
    this.$("scene").hidden = !this.geometry;
    const ctx = this.ctx;
    ctx.fillStyle = "#101e2a";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);
    this.targets = [];
    this.restrictionTargets = [];
    this.furnitureTargets = [];
    this.exclusions = [];
    this.noMopPaths = [];
    this.walls = [];
    this.mapPoint = null;
    this.screenPoint = null;
    const { walls: floorWalls = [], carpets = [], docks = [] } = this.geometry?.presentation ?? {};
    const elevated = this.showElevation;
    const view = this.$("show-3d");
    view.hidden = !this.hasWalls;
    view.disabled = this.editingMap;
    view.setAttribute("aria-pressed", elevated);
    this.$("orbit-map").hidden = !elevated;
    const furniture = this.$("show-furniture");
    furniture.hidden = !this.geometry?.furniture?.items.length;
    furniture.setAttribute("aria-pressed", this.showFurniture);
    this.$("carpet-key").hidden = !carpets.length;
    this.$("dock-key").hidden = !docks.length;
    const activePoint = this.snapshot?.active_point;
    const pointKey = this.$("point-key");
    const showPoint = Boolean(this.geometry && activePoint?.expires_at > Date.now() / 1000);
    pointKey.hidden = !showPoint;
    if (showPoint) pointKey.textContent = `${MODES[activePoint.mode]} point`;
    this.$("live-map-legend").hidden = true;
    this.$("live-path-controls").hidden = true;
    this.$("live-coverage-controls").hidden = true;
    this.$("live-obstacle-controls").hidden = true;
    if (!this.geometry) return;
    const { regions, keep_out: keepOut, virtual_walls: walls, no_mop: noMop = [] } = this.geometry;
    const points = regions.flatMap((region) => region.polygons.flat(2));
    if (!points.length) return;
    const orientation = this.snapshot?.floor_settings?.orientation ?? 0;
    const turns = this.floorDraft?.operation === "rotate" ? this.floorDraft.quarterTurns : 0;
    const orbit = elevated ? (0.5 - this.orbit) * QUARTER_TURN : 0;
    const angle = orientation - turns * QUARTER_TURN + orbit;
    const frame = elevated ? points.concat(floorWalls.flatMap(({ points }) => points)) : points;
    const projection = floorProjection(frame, angle, this.zoom, this.pan, elevated);
    const { project: xy, unproject } = projection;
    this.mapPoint = unproject;
    this.screenPoint = xy;
    const selected = this.roomDraft
      ? new Set((this.roomDraft.roomIds ?? []).map((id) => `${this.roomDraft.id}:rid:${id}`))
      : this.selected;

    const labels = [];
    for (const kind of ["room", "zone"]) {
      for (const region of regions.filter((area) => area.kind === kind)) {
        for (const polygon of region.polygons) {
          const path = pathFor(polygon, xy);
          [ctx.fillStyle, ctx.strokeStyle] = THEMES[selected.has(region.id) ? "selected" : kind];
          ctx.lineWidth = selected.has(region.id) ? 3 : 1.5;
          ctx.fill(path, "evenodd");
          ctx.stroke(path);
          if (region.id) this.targets.push({ path, id: region.id, kind });
          const name = this.roomDraft?.operation === "rename" && selected.has(region.id)
            ? this.roomDraft.name || region.name : region.name;
          labels.push([name, polygon[0], path]);
        }
      }
      if (kind === "room") {
        ctx.fillStyle = "#90aeb945";
        for (const polygon of carpets) ctx.fill(pathFor(polygon, xy), "evenodd");
      }
    }
    this.drawLiveCoverage(xy, regions);
    if (elevated) {
      const items = this.showFurniture ? this.geometry.furniture?.items ?? [] : [];
      drawElevation(ctx, floorWalls, items, projection);
    } else if (this.showFurniture || this.furnitureDraft) this.drawFurniture(xy);
    for (const [name, outer, path] of labels) this.drawLabel(name, outer, path, xy);
    for (const polygon of noMop) {
      const path = pathFor(polygon, xy);
      this.noMopPaths.push(path);
      [ctx.fillStyle, ctx.strokeStyle] = THEMES.noMop;
      ctx.fill(path, "evenodd");
      ctx.setLineDash([3, 5]);
      ctx.stroke(path);
      ctx.setLineDash([]);
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
    for (const points of walls) {
      const path = openPath(points, xy);
      ctx.stroke(path);
      this.walls.push(path);
    }
    ctx.setLineDash([]);
    for (const point of docks) this.drawDock(xy(point));
    if (showPoint) this.drawPointMarker(xy(activePoint.center), "#fcf6e8");
    this.drawLive(xy);
    if (this.pointMode && this.pointAvailable && this.point) {
      this.drawPointMarker(xy(this.point.native), "#79ecd3");
    }
    const divider = this.roomDraft?.points;
    if (divider?.every(Number.isFinite)) {
      ctx.beginPath();
      ctx.moveTo(...xy(divider.slice(0, 2)));
      ctx.lineTo(...xy(divider.slice(2)));
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#f3cf72";
      ctx.setLineDash([8, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (this.zoneDraft) this.drawZoneDraft(xy);
    if (this.restrictionDraft) {
      this.restrictionTargets = this.geometry.editable_restrictions.map(({ id, kind, points }) =>
        ({ id, kind, path: kind === "wall" ? openPath(points, xy) : pathFor([[...points, points[0]]], xy) }));
      this.drawRestrictionDraft(xy);
    }
  }

  drawDock([x, y]) {
    this.ctx.fillStyle = "#7dd9e4";
    this.ctx.fillRect(x - 6, y - 6, 12, 12);
    this.ctx.fillStyle = "#101e2a";
    this.ctx.fillRect(x - 3, y - 2, 6, 4);
  }

  drawZoneDraft(xy) {
    const draft = this.zoneDraft;
    const shapes = draft.bounds?.every(Number.isFinite)
      ? [[rectangleRing(draft.bounds)]] : draft.zone?.polygons ?? [];
    const remove = draft.operation === "delete";
    this.drawOutlinedDraft(shapes, xy, remove ? "#f6ac9d44" : "#f3cf7255",
      remove ? "#f6ac9d" : "#f3cf72");
  }

  drawFurniture(xy) {
    const ctx = this.ctx;
    const draft = this.furnitureDraft;
    for (const { id, points } of this.geometry.furniture?.items ?? []) {
      const path = pathFor([[...points, points[0]]], xy);
      this.furnitureTargets.push({ id, path });
      [ctx.fillStyle, ctx.strokeStyle] = THEMES.furniture;
      ctx.lineWidth = 1;
      ctx.fill(path, "evenodd");
      ctx.stroke(path);
    }
    if (!draft) return;
    const remove = draft.operation === "delete";
    const points = draft.item?.points;
    const ring = !remove && draft.pose ? furnitureRing(draft.pose) : points ? [...points, points[0]] : null;
    if (!ring) return;
    this.drawOutlinedDraft([[ring]], xy, remove ? "#f6ac9d44" : "#bfd1e53d",
      remove ? "#f6ac9d" : "#bfd1e5");
    // Highlight the directed edge so that rotating square furniture changes its preview.
    if (!remove && draft.pose) {
      ctx.beginPath();
      ctx.moveTo(...xy(ring[0]));
      ctx.lineTo(...xy(ring[1]));
      ctx.strokeStyle = "#79ecd3";
      ctx.lineWidth = 3;
      ctx.stroke();
    }
  }

  drawRestrictionDraft(xy) {
    const draft = this.restrictionDraft;
    if (draft.kind === "wall") {
      const [x1, y1, x2, y2] = draft.bounds ?? draft.shape?.points.flat() ?? [];
      if (![x1, y1].every(Number.isFinite)) return;
      this.drawPointMarker(xy([x1, y1]), "#f6ac9d");
      if ([x2, y2].every(Number.isFinite)) {
        const ctx = this.ctx;
        ctx.strokeStyle = "#f6ac9d";
        ctx.lineWidth = 3;
        ctx.setLineDash([8, 4]);
        ctx.stroke(openPath([[x1, y1], [x2, y2]], xy));
        ctx.setLineDash([]);
        this.drawPointMarker(xy([x2, y2]), "#f6ac9d");
      }
      return;
    }
    const ring = draft.bounds?.every(Number.isFinite) ? rectangleRing(draft.bounds)
      : draft.shape ? [...draft.shape.points, draft.shape.points[0]] : null;
    if (!ring) return;
    const amber = draft.kind === "no_mop" && draft.operation !== "delete";
    this.drawOutlinedDraft([[ring]], xy, amber ? "#f3cf7255" : "#f6ac9d44",
      amber ? "#f3cf72" : "#f6ac9d");
  }

  drawOutlinedDraft(shapes, xy, fill, stroke) {
    const ctx = this.ctx;
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 3;
    ctx.setLineDash([8, 4]);
    for (const polygon of shapes) {
      const path = pathFor(polygon, xy);
      ctx.fill(path, "evenodd");
      ctx.stroke(path);
    }
    ctx.setLineDash([]);
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

  drawPointMarker([x, y], color) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.arc(x, y, 8, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "#101e2a";
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  drawLive(xy) {
    const ctx = this.ctx;
    const { trail = [], obstacles = [] } = this.liveStream?.reading ?? this.snapshot?.live ?? {};
    this.$("live-path-controls").hidden = trail.length < 2;
    const showCleaning = this.$("live-cleaning-path").checked !== false;
    const showTravel = this.$("live-travel-path").checked !== false;
    const legend = new Map();
    ctx.lineWidth = 3;
    let previous = null;
    let color = null;
    for (const [sequence, x, y, activity] of trail) {
      const point = xy([x, y]);
      const adjacent = previous?.sequence + 1 === sequence;
      const visible = activity === "traveling" ? showTravel
        : activity ? showCleaning : showCleaning && showTravel;
      const nextColor = adjacent && visible ? ROUTE_COLORS[activity] ?? "#80e9ff" : null;
      if (color !== nextColor) {
        if (color) ctx.stroke();
        if (nextColor) {
          ctx.beginPath();
          ctx.strokeStyle = nextColor;
          ctx.moveTo(...previous.point);
          legend.set(nextColor, ROUTE_LABELS[activity] ?? "Route");
        }
        color = nextColor;
      }
      if (nextColor) ctx.lineTo(...point);
      previous = { sequence, point };
    }
    if (color) ctx.stroke();
    renderMapLegend(this.$("live-map-legend"), Array.from(legend, ([swatch, label]) => [label, swatch]));
    this.$("live-obstacle-controls").hidden = obstacles.length === 0;
    if (obstacles.length && this.$("live-obstacles").checked) {
      ctx.beginPath();
      for (const obstacle of obstacles) {
        const [x, y] = xy(obstacle);
        ctx.moveTo(x, y - 7);
        ctx.lineTo(x + 7, y + 5);
        ctx.lineTo(x - 7, y + 5);
        ctx.closePath();
      }
      ctx.fillStyle = "#ffad55";
      ctx.fill();
      ctx.strokeStyle = "#513517";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    this.liveMarkerProjection = xy;
    this.drawLiveMarker();
  }

  drawLiveCoverage(xy, regions) {
    const { coverage } = this.liveStream?.reading ?? this.snapshot?.live ?? {};
    if (!coverage?.rows.length) return;
    this.$("live-coverage-controls").hidden = false;
    const selected = (this.$("coverage-vacuum").checked ? 1 : 0) |
      (this.$("coverage-mop").checked ? 2 : 0);
    if (!selected) return;
    const clip = new Path2D();
    for (const {kind, polygons} of regions) {
      if (kind === "room") {
        for (const polygon of polygons) clip.addPath(pathFor(polygon, xy));
      }
    }
    const layers = [null, new Path2D(), new Path2D(), new Path2D()];
    const size = coverage.cell_size;
    for (const [row, runs] of coverage.rows) {
      for (const [start, end, mask] of runs) {
        const layer = layers[mask & selected];
        if (!layer) continue;
        const x0 = start * size;
        const x1 = end * size;
        const y0 = row * size;
        const y1 = (row + 1) * size;
        layer.moveTo(...xy([x0, y0]));
        layer.lineTo(...xy([x1, y0]));
        layer.lineTo(...xy([x1, y1]));
        layer.lineTo(...xy([x0, y1]));
        layer.closePath();
      }
    }
    const ctx = this.ctx;
    ctx.save();
    ctx.clip(clip, "evenodd");
    for (const [index, mode] of ["vacuuming", "mopping", "vacuum_mop"].entries()) {
      ctx.fillStyle = `${ROUTE_COLORS[mode]}60`;
      ctx.fill(layers[index + 1]);
    }
    ctx.restore();
  }

  drawLiveMarker() {
    const ctx = this.markerCtx;
    const xy = this.liveMarkerProjection;
    if (!ctx || !xy) return;
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    const latest = this.liveStream?.reading ?? this.snapshot?.live;
    const position = this.liveMarker(latest?.position, this.liveTween ? performance.now() : 0);
    if (!position || position.expires_at <= Date.now() / 1000) return;
    const [x, y] = xy([position.x, position.y]);
    const heading = position.orientation + Math.PI;
    const [headingX, headingY] = xy([
      position.x + Math.cos(heading), position.y + Math.sin(heading),
    ]);
    const length = Math.hypot(headingX - x, headingY - y);
    if (!length) return;
    ctx.fillStyle = "#80e9ff";
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = "#f1f9ff";
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 18 * (headingX - x) / length, y + 18 * (headingY - y) / length);
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
