/*
 * Heating Controller card.
 *
 * Takes one heating_controller device and renders the whole room from it.
 * Entities are resolved by translation_key, never by entity_id patterns —
 * room slugs differ from area names and users rename entities.
 *
 * Vanilla ES module on purpose: this repo has no JS build tooling.
 */

const CARD_TAG = "heating-controller-card";
const EDITOR_TAG = "heating-controller-card-editor";
const DOMAIN = "heating_controller";

// translation_key -> role. See docs/card-design.md.
const ROLES = {
  heating_mode: "mode",
  heating_automation: "automation",
  heating_unblock: "unblock",
  comfort_temperature: "comfort",
  eco_offset: "eco",
  room_temperature: "roomTemp",
  min_flow_temperature: "minFlow",
  heating_demand: "demand",
};

const REQUIRED_ROLES = ["mode", "automation"];

const MODE_ICONS = {
  comfort: "mdi:sun-thermometer",
  eco: "mdi:sprout",
  boost: "mdi:fire",
  frost_protection: "mdi:snowflake-thermometer",
};

// Resolved against the card's own variables, which in turn fall back to a
// house palette if one defines --color-comfort and friends.
const MODE_COLORS = {
  comfort: "var(--hc-comfort)",
  eco: "var(--hc-eco)",
  boost: "var(--hc-boost)",
  frost_protection: "var(--hc-frost)",
};

const DEVICE_CLASS_UNITS = {
  humidity: "%",
  carbon_dioxide: "ppm",
  pm25: "µg/m³",
  temperature: "°C",
};

const DEVICE_CLASS_ICONS = {
  humidity: "mdi:water-percent",
  carbon_dioxide: "mdi:molecule-co2",
  pm25: "mdi:air-filter",
  temperature: "mdi:thermometer",
};

const num = (value, digits = 1) => {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "–";
};

const isOn = (stateObj) => stateObj?.state === "on";

const HEADER_KEY = "header_entities";
const DETAIL_KEY = "detail_entities";

// Identifies the auto-populated detail rows. TRVs and windows append their
// entity id; the room sensor is a singleton.
const ROOM_SENSOR_KEY = "room_sensor";

// Shared by card and editor so both resolve the controller's entities the
// same way — by translation_key, never by entity_id pattern.
const resolveRoles = (hass, deviceId) => {
  const roles = {};
  if (!hass || !deviceId) return roles;
  const byTranslationKey = {};
  for (const entry of Object.values(hass.entities ?? {})) {
    if (entry.device_id !== deviceId || entry.platform !== DOMAIN) continue;
    if (entry.translation_key) byTranslationKey[entry.translation_key] = entry.entity_id;
  }
  for (const [key, role] of Object.entries(ROLES)) {
    const entityId = byTranslationKey[key];
    if (entityId && hass.states[entityId]) roles[role] = hass.states[entityId];
  }
  return roles;
};

// The rows the card seeds itself: the raw room sensor, one per TRV, one per
// window contact. Each carries a stable `key` so the config can pin order,
// name and icon without hard-coding entity ids.
const managedDetailRows = (hass, roles) => {
  const rows = [];
  const roomAttrs = roles.roomTemp?.attributes ?? {};

  if (
    roomAttrs.used_strategy === "room_sensor" &&
    roomAttrs.room_sensor_temp_c != null
  ) {
    rows.push({
      key: ROOM_SENSOR_KEY,
      name: "Sensor",
      icon: "mdi:thermometer",
      value: `${num(roomAttrs.room_sensor_temp_c)} °C`,
      // The raw sensor is an attribute, not a standalone entity; link the row
      // to the room-temperature entity whose more-info shows that value.
      clickEntity: roles.roomTemp?.entity_id,
    });
  }

  const trvTemps = roomAttrs.trv_temperatures ?? {};
  const trvTargets = roles.demand?.attributes?.trv_target_temps ?? {};
  for (const [entityId, temp] of Object.entries(trvTemps)) {
    const stateObj = hass.states[entityId];
    const target = trvTargets[entityId];
    rows.push({
      key: `trv:${entityId}`,
      entity: entityId,
      name: stateObj?.attributes?.friendly_name || entityId,
      icon: "mdi:radiator",
      value:
        target != null
          ? `${num(temp)} °C → ${num(target)} °C`
          : `${num(temp)} °C`,
    });
  }

  const contacts = roles.automation?.attributes?.window_contact_entities ?? [];
  for (const entityId of contacts) {
    const stateObj = hass.states[entityId];
    if (!stateObj) continue;
    const open = stateObj.state === "on";
    rows.push({
      key: `window:${entityId}`,
      entity: entityId,
      name: stateObj.attributes.friendly_name || entityId,
      icon: open ? "mdi:window-open-variant" : "mdi:window-closed-variant",
      value: open ? "Offen" : "Geschlossen",
    });
  }
  return rows;
};

// A detail entry is a managed row ({key, ...}), a custom entity ({entity, ...})
// or a bare entity id. Anything without an anchor is dropped so a config
// damaged by an earlier version heals itself.
const normalizeDetail = (items) =>
  (items ?? [])
    .map((item) =>
      typeof item === "string" ? { entity: item } : { ...(item ?? {}) }
    )
    .filter((item) => item.entity || item.key);

// Accepts a bare entity id or an object with name/icon. Entries without an
// entity are dropped so a config damaged by an earlier version heals itself
// instead of rendering "undefined" rows forever.
const normalizeItems = (items) =>
  (items ?? [])
    .map((item) =>
      typeof item === "string" ? { entity: item } : { ...(item ?? {}) }
    )
    .filter((item) => item.entity);

// Earlier drafts used a single extra_entities list with a position field.
// Reading it keeps hand-written YAML from silently losing its sensors.
const migrateLegacyConfig = (config) => {
  if (!config.extra_entities) return config;
  const migrated = { ...config };
  delete migrated.extra_entities;
  for (const item of normalizeItems(config.extra_entities)) {
    const key = item.position === "header" ? HEADER_KEY : DETAIL_KEY;
    delete item.position;
    migrated[key] = [...(migrated[key] ?? []), item];
  }
  return migrated;
};

class HeatingControllerCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig() {
    return { device: "" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._expanded = false;
    this._editMode = false;
    this._rendered = false;
  }

  // Lovelace sets this while the dashboard is being edited. Expanding then
  // is what the expander-card this replaces does, and without it half the
  // card's content is invisible exactly when you are laying it out.
  set editMode(editMode) {
    this._editMode = Boolean(editMode);
    this._applyExpanded();
  }

  _isExpanded() {
    return this._expanded || this._editMode;
  }

  setConfig(config) {
    // Deliberately tolerant of a missing device: the visual editor starts out
    // with an empty one, and throwing here would leave the editor showing a
    // broken preview until the very first pick.
    this._config = migrateLegacyConfig(config ?? {});
    this._rendered = false;
  }

  getCardSize() {
    return this._isExpanded() ? 8 : 2;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  // ---------- entity resolution ----------

  _resolveEntities() {
    return resolveRoles(this._hass, this._config.device);
  }

  _missingRoles(roles) {
    return REQUIRED_ROLES.filter((role) => !roles[role]);
  }

  _deviceName() {
    if (this._config.title) return this._config.title;
    const device = this._hass.devices?.[this._config.device];
    return device?.name_by_user || device?.name || "Heizung";
  }

  // ---------- derived state ----------

  _status(roles) {
    const mode = roles.mode.state;
    const automation = isOn(roles.automation);
    const options = roles.mode.attributes.options ?? [];
    const labels = this._modeLabels(roles.mode, options);

    if (mode === "frost_protection" && automation) {
      return { text: "Frostschutz erzwungen", forcedFrost: true };
    }
    const prefix = automation ? "Automatik" : "Blockiert";
    return { text: `${prefix} – ${labels[mode] ?? mode}`, forcedFrost: false };
  }

  // Labels come from the translated select options, so the card never
  // duplicates the integration's mode naming.
  _modeLabels(modeState, options) {
    const labels = {};
    for (const option of options) {
      labels[option] = this._hass.formatEntityState
        ? this._hass.formatEntityState(modeState, option)
        : option;
    }
    return labels;
  }

  _openWindows(roles) {
    const contacts = roles.automation.attributes.window_contact_entities ?? [];
    return contacts.filter((entityId) => isOn(this._hass.states[entityId]));
  }

  // ---------- actions ----------

  _callService(domain, service, data) {
    this._hass.callService(domain, service, data);
  }

  _selectMode(roles, option) {
    this._callService("select", "select_option", {
      entity_id: roles.mode.entity_id,
      option,
    });
  }

  _toggle(entityId) {
    const domain = entityId.split(".")[0];
    this._callService(domain, "toggle", { entity_id: entityId });
  }

  _moreInfo(entityId) {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId },
        bubbles: true,
        composed: true,
      })
    );
  }

  // ---------- rendering ----------

  _render() {
    if (!this._hass || !this._config) return;

    if (!this._config.device) {
      this._renderHint("Bitte ein Heating-Controller-Gerät auswählen.");
      return;
    }

    const roles = this._resolveEntities();
    const missing = this._missingRoles(roles);
    if (missing.length) {
      this._renderError(
        `Diesem Gerät fehlen Entitäten (${missing.join(", ")}). ` +
          "Ist es ein Heating-Controller-Gerät?"
      );
      return;
    }

    if (!this._rendered) {
      this._buildSkeleton();
      this._rendered = true;
      this._applyExpanded();
    }
    this._update(roles);
  }

  _renderError(message) {
    this._renderNotice(message, "error");
  }

  _renderHint(message) {
    this._renderNotice(message, "hint");
  }

  _renderNotice(message, kind) {
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="${kind}">${message}</div>
      </ha-card>
      <style>
        .error, .hint { padding: 16px; }
        .error { color: var(--error-color, #db4437); }
        .hint { color: var(--secondary-text-color); }
      </style>`;
    this._rendered = false;
  }

  _buildSkeleton() {
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="header" id="header">
          <ha-icon id="statusIcon" class="status-icon"></ha-icon>
          <div class="titles">
            <div class="title" id="title"></div>
            <div class="subtitle" id="subtitle"></div>
          </div>
          <ha-icon id="windowIcon" class="window-icon" icon="mdi:window-open-variant"></ha-icon>
          <ha-icon id="chevron" class="chevron" icon="mdi:chevron-down"></ha-icon>
        </div>
        <div class="values" id="headerValues"></div>
        <div class="boost-row" id="boostRow"></div>
        <div class="details" id="details" hidden>
          <div class="section" id="sectionDetails">
            <div class="divider">Details</div>
            <div class="rows" id="detailRows"></div>
          </div>
          <div class="section">
            <div class="divider">Heizungssteuerung</div>
            <div class="controls" id="controls"></div>
          </div>
        </div>
      </ha-card>
      <style>
        :host {
          /* A dashboard that already defines a heating palette wins; the
             defaults keep the card usable everywhere else. */
          --hc-comfort: var(--color-comfort, #e5533d);
          --hc-eco: var(--color-eco, #43a047);
          --hc-boost: var(--color-boost, #ff6d00);
          --hc-frost: var(--color-frost, #33ccff);
        }
        ha-card { overflow: hidden; }
        .header {
          display: flex; align-items: center; gap: 12px;
          padding: 12px 16px; cursor: pointer;
        }
        /* ha-icon is a plain element: the tinted disc is just its own
           background, so no wrapper is needed. color-mix keeps the disc a
           faint version of the same mode colour that fills the glyph. */
        .status-icon {
          --mdc-icon-size: 24px;
          box-sizing: border-box;
          width: 40px; height: 40px; padding: 8px; border-radius: 50%;
          flex: none;
          color: var(--hc-mode-color, var(--state-icon-color));
          background: color-mix(
            in srgb, var(--hc-mode-color, transparent) 20%, transparent
          );
        }
        .titles { flex: 1; min-width: 0; }
        .title { font-size: 1.05rem; font-weight: 500; }
        .subtitle { font-size: 0.85rem; color: var(--secondary-text-color); }
        .window-icon { color: var(--error-color, #db4437); }
        .window-icon[hidden] { display: none; }
        .chevron { transition: transform 0.2s ease; color: var(--secondary-text-color); }
        .chevron.open { transform: rotate(180deg); }
        /* auto-fit fits as many equal columns as the min width allows, so a
           phone lands on four and a wide card on more — no hand-tuned
           breakpoint, and it never wraps a fourth value onto its own line. */
        .values {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(68px, 1fr));
          gap: 0 12px;
          padding: 0 16px 8px 16px;
        }
        .value {
          display: flex; align-items: center; justify-content: center;
          gap: 3px; cursor: pointer; min-width: 0;
          /* Same 44px touch target as the detail rows. */
          min-height: 44px; padding: 0 6px; margin: 0 -6px;
          border-radius: 8px; -webkit-tap-highlight-color: transparent;
        }
        .value:hover { background: var(--secondary-background-color); }
        .value:active { background: var(--divider-color); }
        .value ha-icon {
          --mdc-icon-size: 18px; flex: none;
          color: var(--secondary-text-color);
        }
        .value .num { font-size: 1.05rem; font-weight: 500; }
        .value .unit, .value .label {
          font-size: 0.8rem; color: var(--secondary-text-color);
          white-space: nowrap;
        }
        .boost-row { padding: 0 16px; }
        .boost-row:empty { display: none; }
        .details { border-top: 1px solid var(--divider-color); }
        .section { padding: 8px 16px 12px 16px; }
        .section[hidden] { display: none; }
        .divider {
          font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
          color: var(--secondary-text-color); margin: 4px 0 8px 0;
        }
        .rows { display: flex; flex-direction: column; }
        .row {
          display: flex; justify-content: space-between; gap: 8px;
          align-items: center; font-size: 0.95rem;
          /* Comfortable tap target on mobile — the whole row is clickable. */
          min-height: 44px; padding: 4px 8px; margin: 0 -8px;
          border-radius: 8px;
        }
        .row.clickable { cursor: pointer; -webkit-tap-highlight-color: transparent; }
        .row.clickable:hover { background: var(--secondary-background-color); }
        .row.clickable:active { background: var(--divider-color); }
        .row .k {
          color: var(--secondary-text-color);
          display: flex; align-items: center; gap: 8px; min-width: 0;
        }
        .row .k ha-icon { --mdc-icon-size: 20px; flex: none; }
        .row .v { white-space: nowrap; }
        .controls { display: flex; flex-direction: column; gap: 12px; }
        .modes { display: flex; flex-wrap: wrap; gap: 8px; }
        button.chip {
          display: inline-flex; align-items: center; gap: 6px;
          border: 1px solid var(--divider-color); border-radius: 16px;
          background: var(--card-background-color); color: var(--primary-text-color);
          padding: 6px 12px; font: inherit; font-size: 0.85rem; cursor: pointer;
        }
        button.chip.active {
          background: var(--primary-color); color: var(--text-primary-color);
          border-color: var(--primary-color);
        }
        button.chip.blocked { opacity: 0.6; }
        .setpoints { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
        .setpoint { display: flex; align-items: center; gap: 8px; }
        .setpoint input[type="range"] { width: 140px; }
        .flow { display: flex; justify-content: space-between; font-size: 0.9rem; }
        .flow .ok { color: var(--success-color, #43a047); }
        .flow .low { color: var(--warning-color, #ffa600); }
      </style>`;

    this.shadowRoot
      .getElementById("header")
      .addEventListener("click", () => this._toggleExpanded());
  }

  _toggleExpanded() {
    this._expanded = !this._expanded;
    this._applyExpanded();
  }

  _applyExpanded() {
    const details = this.shadowRoot?.getElementById("details");
    if (!details) return;
    const expanded = this._isExpanded();
    details.hidden = !expanded;
    this.shadowRoot.getElementById("chevron").classList.toggle("open", expanded);
  }

  _update(roles) {
    const root = this.shadowRoot;
    const status = this._status(roles);
    const openWindows = this._openWindows(roles);

    root.getElementById("title").textContent = this._deviceName();
    root.getElementById("subtitle").textContent = status.text;
    root.getElementById("windowIcon").hidden = openWindows.length === 0;

    const icon = root.getElementById("statusIcon");
    if (status.forcedFrost) icon.icon = "mdi:snowflake-alert";
    else if (isOn(roles.automation)) icon.icon = "mdi:auto-mode";
    else icon.icon = "mdi:stop-circle-outline";
    // The icon shape says what the controller is doing, the mode colour tints
    // both the glyph and the disc behind it — same split as the old card.
    icon.style.setProperty("--hc-mode-color", MODE_COLORS[roles.mode.state] ?? "");

    this._updateHeaderValues(roles);
    this._updateBoost(roles);
    this._updateDetails(roles);
    this._updateControls(roles);
  }

  _valueEl({ entityId, value, unit, label, icon }) {
    const el = document.createElement("div");
    el.className = "value";
    if (icon) {
      el.innerHTML = `<ha-icon icon="${icon}"></ha-icon>`;
    }
    el.innerHTML += `<span class="num">${value}</span><span class="unit">${unit ?? ""}</span>`;
    if (label) {
      el.innerHTML += `<span class="label">${label}</span>`;
    }
    if (entityId) {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._moreInfo(entityId);
      });
    }
    return el;
  }

  _entityList(key) {
    return normalizeItems(this._config[key]);
  }

  _updateHeaderValues(roles) {
    const container = this.shadowRoot.getElementById("headerValues");
    container.textContent = "";

    container.appendChild(
      this._valueEl({
        entityId: roles.roomTemp?.entity_id,
        value: num(roles.roomTemp?.state),
        unit: "°C",
        icon: DEVICE_CLASS_ICONS.temperature,
      })
    );

    for (const item of this._entityList(HEADER_KEY)) {
      const stateObj = this._hass.states[item.entity];
      if (!stateObj) continue;
      const deviceClass = stateObj.attributes.device_class;
      container.appendChild(
        this._valueEl({
          entityId: item.entity,
          value: num(stateObj.state, deviceClass === "temperature" ? 1 : 0),
          unit:
            stateObj.attributes.unit_of_measurement ??
            DEVICE_CLASS_UNITS[deviceClass] ??
            "",
          label: item.name,
          icon: item.icon ?? DEVICE_CLASS_ICONS[deviceClass],
        })
      );
    }
  }

  _updateBoost(roles) {
    const row = this.shadowRoot.getElementById("boostRow");
    row.textContent = "";
    const options = roles.mode.attributes.options ?? [];
    if (!options.includes("boost")) return;

    const active = roles.mode.state === "boost";
    const button = document.createElement("button");
    button.className = `chip${active ? " active" : ""}`;
    button.innerHTML = `<ha-icon icon="${MODE_ICONS.boost}"></ha-icon>Boost`;
    button.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._selectMode(roles, active ? "comfort" : "boost");
    });
    row.appendChild(button);
  }

  _row(name, value, icon, entityId) {
    const el = document.createElement("div");
    el.className = "row";
    const iconHtml = icon ? `<ha-icon icon="${icon}"></ha-icon>` : "";
    el.innerHTML =
      `<span class="k">${iconHtml}${name}</span><span class="v">${value}</span>`;
    if (entityId) {
      el.classList.add("clickable");
      el.addEventListener("click", () => this._moreInfo(entityId));
    }
    return el;
  }

  // Reconciles the seeded rows with the config: config order wins, hidden and
  // vanished rows drop out, and TRVs/windows added later append at the end.
  _detailRows(roles) {
    const managed = new Map(
      managedDetailRows(this._hass, roles).map((row) => [row.key, row])
    );
    const rows = [];
    const used = new Set();

    for (const entry of normalizeDetail(this._config[DETAIL_KEY])) {
      if (entry.key) {
        used.add(entry.key);
        const base = managed.get(entry.key);
        if (!base || entry.hidden) continue;
        rows.push({
          ...base,
          name: entry.name ?? base.name,
          icon: entry.icon ?? base.icon,
        });
      } else {
        const stateObj = this._hass.states[entry.entity];
        if (!stateObj) continue;
        const unit = stateObj.attributes.unit_of_measurement ?? "";
        rows.push({
          entity: entry.entity,
          name: entry.name ?? stateObj.attributes.friendly_name ?? entry.entity,
          icon: entry.icon ?? DEVICE_CLASS_ICONS[stateObj.attributes.device_class],
          value: `${num(stateObj.state, unit === "%" || unit === "ppm" ? 0 : 1)} ${unit}`,
        });
      }
    }
    for (const row of managed.values()) {
      if (!used.has(row.key)) rows.push(row);
    }
    return rows;
  }

  _updateDetails(roles) {
    const rows = this.shadowRoot.getElementById("detailRows");
    rows.textContent = "";
    for (const row of this._detailRows(roles)) {
      rows.appendChild(
        this._row(row.name, row.value, row.icon, row.clickEntity ?? row.entity)
      );
    }
    this.shadowRoot.getElementById("sectionDetails").hidden =
      rows.childElementCount === 0;
  }

  _shortName(stateObj) {
    return stateObj?.attributes?.friendly_name ?? "";
  }

  _updateControls(roles) {
    const container = this.shadowRoot.getElementById("controls");
    container.textContent = "";

    // Automation + mode
    const modeRow = document.createElement("div");
    modeRow.className = "modes";

    const automationActive = isOn(roles.automation);
    const autoButton = document.createElement("button");
    autoButton.className = `chip${automationActive ? " active" : " blocked"}`;
    autoButton.innerHTML = `<ha-icon icon="mdi:auto-mode"></ha-icon>${
      automationActive ? "Automatik" : "Entblocken"
    }`;
    autoButton.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (roles.unblock) {
        this._callService("button", "press", {
          entity_id: roles.unblock.entity_id,
        });
      }
    });
    modeRow.appendChild(autoButton);

    const options = roles.mode.attributes.options ?? [];
    const labels = this._modeLabels(roles.mode, options);
    for (const option of options) {
      if (option === "boost") continue; // has its own row
      const button = document.createElement("button");
      button.className = `chip${roles.mode.state === option ? " active" : ""}`;
      button.innerHTML = `<ha-icon icon="${MODE_ICONS[option] ?? ""}"></ha-icon>${
        labels[option] ?? option
      }`;
      button.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectMode(roles, option);
      });
      modeRow.appendChild(button);
    }
    container.appendChild(modeRow);

    // Room-specific comfort conditions
    const conditions =
      roles.automation.attributes.comfort_condition_entities ?? [];
    if (conditions.length) {
      const row = document.createElement("div");
      row.className = "modes";
      for (const entityId of conditions) {
        const stateObj = this._hass.states[entityId];
        if (!stateObj) continue;
        const domain = entityId.split(".")[0];
        const writable = domain === "input_boolean" || domain === "switch";
        const active = isOn(stateObj);
        const button = document.createElement("button");
        button.className = `chip${active ? " active" : ""}`;
        button.innerHTML = `<ha-icon icon="${
          stateObj.attributes.icon ?? "mdi:account-check"
        }"></ha-icon>${this._shortName(stateObj) || entityId}`;
        button.addEventListener("click", (ev) => {
          ev.stopPropagation();
          if (writable) this._toggle(entityId);
          else this._moreInfo(entityId);
        });
        row.appendChild(button);
      }
      container.appendChild(row);
    }

    // Setpoints
    const setpoints = document.createElement("div");
    setpoints.className = "setpoints";
    if (roles.comfort) setpoints.appendChild(this._numberControl(roles.comfort, "range"));
    if (roles.eco) setpoints.appendChild(this._numberControl(roles.eco, "number"));
    container.appendChild(setpoints);

    // Minimum flow temperature
    if (roles.minFlow) {
      const supplied = roles.minFlow.attributes.sufficiently_supplied;
      const flow = document.createElement("div");
      flow.className = "flow";
      flow.innerHTML =
        `<span class="k">Mind. Vorlauf</span>` +
        `<span class="${supplied ? "ok" : "low"}">${num(
          roles.minFlow.state
        )} °C${supplied ? "" : " ⚠"}</span>`;
      container.appendChild(flow);
    }
  }

  _numberControl(stateObj, kind) {
    const wrapper = document.createElement("div");
    wrapper.className = "setpoint";

    const input = document.createElement("input");
    input.type = kind;
    input.min = stateObj.attributes.min;
    input.max = stateObj.attributes.max;
    input.step = stateObj.attributes.step;
    input.value = stateObj.state;

    const readout = document.createElement("span");
    readout.textContent = `${num(stateObj.state)} °C`;

    input.addEventListener("click", (ev) => ev.stopPropagation());
    input.addEventListener("change", (ev) => {
      this._callService("number", "set_value", {
        entity_id: stateObj.entity_id,
        value: Number.parseFloat(ev.target.value),
      });
    });

    const icon = document.createElement("ha-icon");
    icon.setAttribute(
      "icon",
      stateObj.attributes.device_class === "temperature" &&
        stateObj.attributes.min < 0
        ? MODE_ICONS.eco
        : MODE_ICONS.comfort
    );

    wrapper.append(icon, input, readout);
    return wrapper;
  }
}

// ---------------------------------------------------------------------------
// Visual editor
// ---------------------------------------------------------------------------

const BASE_SCHEMA = [
  {
    name: "device",
    required: true,
    selector: { device: { integration: DOMAIN } },
  },
  { name: "title", selector: { text: {} } },
];

const ITEM_SCHEMA = [
  { name: "entity", required: true, selector: { entity: {} } },
  { name: "name", selector: { text: {} } },
  { name: "icon", selector: { icon: {} } },
];

// Managed detail rows have a fixed entity — only name and icon are editable.
const ITEM_SCHEMA_NO_ENTITY = [
  { name: "name", selector: { text: {} } },
  { name: "icon", selector: { icon: {} } },
];

const EDITOR_LABELS = {
  device: "Raum (Heating-Controller-Gerät)",
  title: "Titel (optional, sonst Gerätename)",
  entity: "Entität",
  name: "Name",
  icon: "Symbol",
};

const HEADER_LIST = {
  key: HEADER_KEY,
  heading: "Kopfzeile",
  hint: "Werte neben der Raumtemperatur, auch bei zugeklappter Karte sichtbar.",
};

const DETAIL_HINT =
  "Vorbelegte Zeilen (Raumsensor, Heizkörper, Fenster) und eigene Sensoren. " +
  "Sortierbar und umbenennbar; Vorbelegte lassen sich aus-/einblenden statt löschen.";

class HeatingControllerCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._edit = null; // {key, index} while the sub-view is open
  }

  setConfig(config) {
    this._config = { ...(config ?? {}) };
    this._migrateLegacy();
    this._render();
  }

  // Earlier drafts used a single extra_entities list with a position field.
  // Split it so nobody has to hand-edit YAML after updating.
  _migrateLegacy() {
    this._config = migrateLegacyConfig(this._config);
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    // Only the initial hass needs a full build; later updates just refresh
    // the child elements. Rebuilding on every state change re-created every
    // form field many times a second — which is where the "form field should
    // have an id or name" warnings came from.
    if (first) this._render();
    else this._propagateHass();
  }

  _items(key) {
    return normalizeItems(this._config[key]);
  }

  _emit(config) {
    if (!config.title) delete config.title;
    // Header is custom-only: compact bare entries to plain strings. Normalize
    // first, or mapping over an already-compacted string would read .entity
    // off it — undefined — and wipe every entry without a name or icon.
    const header = normalizeItems(config[HEADER_KEY]);
    if (header.length) {
      config[HEADER_KEY] = header.map((item) =>
        !item.name && !item.icon ? item.entity : item
      );
    } else {
      delete config[HEADER_KEY];
    }
    // Detail is serialized by _setDetail; here only drop it when empty.
    if (!config[DETAIL_KEY]?.length) delete config[DETAIL_KEY];

    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      })
    );
    this._render();
  }

  _setList(key, items) {
    this._emit({ ...this._config, [key]: items });
  }

  // The seeded rows reconciled with config: config order wins, hidden and
  // vanished rows stay flagged/dropped, newly added TRVs/windows append.
  _detailEditorItems() {
    const roles = resolveRoles(this._hass, this._config.device);
    const managed = new Map(
      managedDetailRows(this._hass, roles).map((row) => [row.key, row])
    );
    const items = [];
    const used = new Set();

    for (const entry of normalizeDetail(this._config[DETAIL_KEY])) {
      if (entry.key) {
        const base = managed.get(entry.key);
        if (!base) continue;
        used.add(entry.key);
        items.push({
          managed: true,
          key: entry.key,
          entity: base.entity,
          label: base.name,
          defaultIcon: base.icon,
          name: entry.name,
          icon: entry.icon,
          hidden: Boolean(entry.hidden),
        });
      } else {
        const stateObj = this._hass.states[entry.entity];
        items.push({
          managed: false,
          entity: entry.entity,
          label: stateObj?.attributes?.friendly_name ?? entry.entity,
          name: entry.name,
          icon: entry.icon,
          hidden: false,
        });
      }
    }
    for (const [key, base] of managed) {
      if (used.has(key)) continue;
      items.push({
        managed: true,
        key,
        entity: base.entity,
        label: base.name,
        defaultIcon: base.icon,
        hidden: false,
      });
    }
    return items;
  }

  _setDetail(items) {
    const roles = resolveRoles(this._hass, this._config.device);
    const defaultKeys = managedDetailRows(this._hass, roles).map((row) => row.key);
    // As long as nothing is touched, omit the config entirely so the card
    // keeps auto-populating and the YAML stays clean.
    const pristine =
      items.length === defaultKeys.length &&
      items.every(
        (item, index) =>
          item.managed &&
          item.key === defaultKeys[index] &&
          !item.name &&
          !item.icon &&
          !item.hidden
      );

    const config = { ...this._config };
    if (pristine) {
      delete config[DETAIL_KEY];
    } else {
      config[DETAIL_KEY] = items.map((item) => {
        if (item.managed) {
          const entry = { key: item.key };
          if (item.name) entry.name = item.name;
          if (item.icon && item.icon !== item.defaultIcon) entry.icon = item.icon;
          if (item.hidden) entry.hidden = true;
          return entry;
        }
        const entry = { entity: item.entity };
        if (item.name) entry.name = item.name;
        if (item.icon) entry.icon = item.icon;
        return entry;
      });
    }
    this._emit(config);
  }

  // ---------- rendering ----------

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._built) this._buildShell();

    const editing = Boolean(this._edit);
    this.shadowRoot.getElementById("main").hidden = editing;
    this.shadowRoot.getElementById("detail").hidden = !editing;

    if (editing) this._renderDetailView();
    else this._renderMainView();
  }

  // Both forms are created once and only ever get fresh data. Recreating them
  // on every value-changed would rip the focused input out of the DOM, which
  // loses focus after each keystroke.
  _buildShell() {
    this.shadowRoot.innerHTML = `
      <div id="main">
        <ha-form id="baseForm"></ha-form>
        <div id="lists"></div>
      </div>
      <div id="detail" hidden>
        <div class="subhead">
          <ha-icon-button id="back"><ha-icon icon="mdi:arrow-left"></ha-icon></ha-icon-button>
          <span class="label" id="detailLabel"></span>
        </div>
        <div id="detailEntity"></div>
        <ha-form id="itemForm"></ha-form>
      </div>
      <style>
        .list-section { margin-top: 24px; }
        .heading { font-weight: 500; }
        .hint {
          font-size: 0.8rem; color: var(--secondary-text-color);
          margin: 2px 0 10px 0;
        }
        .row {
          display: flex; align-items: center; gap: 4px;
          background: var(--secondary-background-color);
          border-radius: 8px; padding: 6px 8px; margin-bottom: 8px;
        }
        .handle { cursor: grab; color: var(--secondary-text-color); }
        .row .info { flex: 1; min-width: 0; }
        .row .primary {
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .row .secondary {
          font-size: 0.8rem; color: var(--secondary-text-color);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .adder { margin-top: 4px; }
        .subhead { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
        .subhead .label { font-weight: 500; }
        #detailEntity { margin-bottom: 16px; }
        .ro-field {
          display: flex; flex-direction: column; gap: 2px;
          padding: 8px 12px; border-radius: 4px;
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color);
        }
        .ro-field .ro-label {
          font-size: 0.75rem; color: var(--secondary-text-color);
        }
        .ro-field .ro-value {
          color: var(--secondary-text-color);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
      </style>`;

    const baseForm = this.shadowRoot.getElementById("baseForm");
    baseForm.schema = BASE_SCHEMA;
    baseForm.computeLabel = (schema) => EDITOR_LABELS[schema.name] ?? schema.name;
    baseForm.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      this._emit({ ...this._config, ...ev.detail.value });
    });

    const itemForm = this.shadowRoot.getElementById("itemForm");
    itemForm.schema = ITEM_SCHEMA;
    itemForm.computeLabel = (schema) => EDITOR_LABELS[schema.name] ?? schema.name;
    itemForm.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      if (!this._edit) return;
      const { list, index } = this._edit;
      const value = { ...ev.detail.value };
      if (!value.name) delete value.name;
      if (!value.icon) delete value.icon;

      if (list === "header") {
        const next = this._items(HEADER_KEY);
        next[index] = value;
        this._setList(HEADER_KEY, next);
      } else {
        const next = this._detailEditorItems();
        const item = next[index];
        item.name = value.name;
        item.icon = value.icon;
        if (!item.managed && value.entity) item.entity = value.entity;
        this._setDetail(next);
      }
    });

    this.shadowRoot.getElementById("back").addEventListener("click", () => {
      this._edit = null;
      this._render();
    });

    this._built = true;
  }

  _renderMainView() {
    const form = this.shadowRoot.getElementById("baseForm");
    form.hass = this._hass;
    form.data = { device: this._config.device, title: this._config.title };

    // Rebuild the lists only when their content actually changes — not on every
    // render. Typing in the title triggers a render too, and recreating the
    // entity pickers each keystroke is what floods the console with
    // "form field should have an id" and costs focus.
    const roles = resolveRoles(this._hass, this._config.device);
    const signature = JSON.stringify([
      this._config.device,
      this._config[HEADER_KEY] ?? null,
      this._config[DETAIL_KEY] ?? null,
      managedDetailRows(this._hass, roles).map((row) => row.key),
    ]);
    const lists = this.shadowRoot.getElementById("lists");
    if (this._listsSignature === signature && lists.childElementCount) return;
    this._listsSignature = signature;

    lists.textContent = "";
    lists.appendChild(this._buildListSection(HEADER_LIST));
    lists.appendChild(this._buildDetailSection());
  }

  _buildDetailSection() {
    const section = document.createElement("div");
    section.className = "list-section";
    section.innerHTML =
      `<div class="heading">Details</div><div class="hint">${DETAIL_HINT}</div>`;

    const container = document.createElement("div");
    this._detailEditorItems().forEach((item, index) =>
      container.appendChild(this._buildDetailRow(item, index))
    );

    const sortable = document.createElement("ha-sortable");
    sortable.setAttribute("handle-selector", ".handle");
    sortable.addEventListener("item-moved", (ev) => {
      ev.stopPropagation();
      const { oldIndex, newIndex } = ev.detail;
      const next = this._detailEditorItems();
      next.splice(newIndex, 0, ...next.splice(oldIndex, 1));
      this._setDetail(next);
    });
    sortable.appendChild(container);
    section.appendChild(sortable);

    const adder = document.createElement("ha-entity-picker");
    adder.className = "adder";
    adder.hass = this._hass;
    adder.label = "Eigenen Sensor hinzufügen";
    adder.allowCustomEntity = false;
    adder.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const entityId = ev.detail.value;
      if (!entityId) return;
      ev.target.value = "";
      this._setDetail([
        ...this._detailEditorItems(),
        { managed: false, entity: entityId },
      ]);
    });
    section.appendChild(adder);
    return section;
  }

  _buildDetailRow(item, index) {
    const row = document.createElement("div");
    row.className = "row";
    if (item.hidden) row.style.opacity = "0.5";

    const handle = document.createElement("ha-icon");
    handle.className = "handle";
    handle.setAttribute("icon", "mdi:drag");
    row.appendChild(handle);

    const info = document.createElement("div");
    info.className = "info";
    info.innerHTML =
      `<div class="primary">${item.name || item.label}</div>` +
      `<div class="secondary">${
        item.managed && !item.entity ? "Vorbelegt" : item.entity
      }</div>`;
    row.appendChild(info);

    if (item.managed) {
      row.appendChild(
        this._iconButton(item.hidden ? "mdi:eye-off" : "mdi:eye", () => {
          const next = this._detailEditorItems();
          next[index].hidden = !next[index].hidden;
          this._setDetail(next);
        })
      );
    } else {
      row.appendChild(
        this._iconButton("mdi:close", () => {
          const next = this._detailEditorItems();
          next.splice(index, 1);
          this._setDetail(next);
        })
      );
    }
    row.appendChild(
      this._iconButton("mdi:pencil", () => {
        this._edit = { list: "detail", index };
        this._render();
      })
    );
    return row;
  }

  _buildListSection({ key, heading, hint }) {
    const section = document.createElement("div");
    section.className = "list-section";
    section.innerHTML =
      `<div class="heading">${heading}</div><div class="hint">${hint}</div>`;

    const items = this._items(key);
    const container = document.createElement("div");
    items.forEach((item, index) =>
      container.appendChild(this._buildRow(key, item, index))
    );

    // ha-sortable is the same drag-and-drop wrapper Home Assistant's own
    // entity-row editors use; handle-selector keeps the row itself clickable.
    const sortable = document.createElement("ha-sortable");
    sortable.setAttribute("handle-selector", ".handle");
    sortable.addEventListener("item-moved", (ev) => {
      ev.stopPropagation();
      const { oldIndex, newIndex } = ev.detail;
      const next = this._items(key);
      next.splice(newIndex, 0, ...next.splice(oldIndex, 1));
      this._setList(key, next);
    });
    sortable.appendChild(container);
    section.appendChild(sortable);

    const adder = document.createElement("ha-entity-picker");
    adder.className = "adder";
    adder.hass = this._hass;
    adder.label = "Entität hinzufügen";
    adder.allowCustomEntity = false;
    adder.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      const entityId = ev.detail.value;
      if (!entityId) return;
      ev.target.value = "";
      this._setList(key, [...this._items(key), { entity: entityId }]);
    });
    section.appendChild(adder);

    return section;
  }

  _buildRow(key, item, index) {
    const stateObj = this._hass.states[item.entity];
    const row = document.createElement("div");
    row.className = "row";

    const handle = document.createElement("ha-icon");
    handle.className = "handle";
    handle.setAttribute("icon", "mdi:drag");
    row.appendChild(handle);

    const info = document.createElement("div");
    info.className = "info";
    const primary = item.name || stateObj?.attributes?.friendly_name || item.entity;
    info.innerHTML =
      `<div class="primary">${primary}</div>` +
      `<div class="secondary">${item.entity}</div>`;
    row.appendChild(info);

    row.appendChild(
      this._iconButton("mdi:close", () => {
        const next = this._items(key);
        next.splice(index, 1);
        this._setList(key, next);
      })
    );
    row.appendChild(
      this._iconButton("mdi:pencil", () => {
        this._edit = { list: "header", index };
        this._render();
      })
    );
    return row;
  }

  _iconButton(icon, onClick) {
    const button = document.createElement("ha-icon-button");
    const iconEl = document.createElement("ha-icon");
    iconEl.setAttribute("icon", icon);
    button.appendChild(iconEl);
    button.addEventListener("click", onClick);
    return button;
  }

  _renderDetailView() {
    const { list, index } = this._edit;
    const items =
      list === "header" ? this._items(HEADER_KEY) : this._detailEditorItems();
    const item = items[index];
    if (!item) {
      this._edit = null;
      this._render();
      return;
    }

    const heading = list === "header" ? "Kopfzeile" : "Details";
    this.shadowRoot.getElementById("detailLabel").textContent =
      `${index + 1} / ${items.length} \u00b7 ${heading}`;

    // Managed detail rows have a fixed entity: it is shown read-only above the
    // form so you can see what you are editing, but only name and icon are
    // editable in the form itself.
    const managed = list === "detail" && item.managed;
    this._renderReadonlyEntity(managed ? item : null);

    const form = this.shadowRoot.getElementById("itemForm");
    form.schema = managed ? ITEM_SCHEMA_NO_ENTITY : ITEM_SCHEMA;
    form.hass = this._hass;
    form.data = managed
      ? { name: item.name, icon: item.icon ?? item.defaultIcon }
      : item;
  }

  // Rebuilt only when the shown entity changes, not on every keystroke, so the
  // focused name field in the form below is never disturbed.
  _renderReadonlyEntity(item) {
    const identity = item ? item.entity ?? item.key : "";
    if (this._shownEntity === identity) return;
    this._shownEntity = identity;

    const container = this.shadowRoot.getElementById("detailEntity");
    container.textContent = "";
    if (!item) return;

    // A plain styled box, not ha-textfield/ha-entity-picker: those render
    // blank when disabled in this context. The room sensor has no standalone
    // entity, so its label stands in.
    const field = document.createElement("div");
    field.className = "ro-field";
    field.innerHTML =
      `<span class="ro-label">${EDITOR_LABELS.entity}</span>` +
      `<span class="ro-value">${item.entity ?? item.label}</span>`;
    container.appendChild(field);
  }

  _propagateHass() {
    if (!this.shadowRoot) return;
    for (const el of this.shadowRoot.querySelectorAll(
      "ha-form, ha-entity-picker"
    )) {
      el.hass = this._hass;
    }
  }
}
customElements.define(CARD_TAG, HeatingControllerCard);
customElements.define(EDITOR_TAG, HeatingControllerCardEditor);

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: CARD_TAG,
  name: "Heating Controller",
  description:
    "Raumsteuerung für den Heating Controller — Modus, Solltemperaturen und Mindestvorlauf aus einem Gerät.",
  preview: true,
  documentationURL:
    "https://github.com/DerOetzi/home-assistant-mcp-heating-controller",
});

console.info(`%c ${CARD_TAG} %c loaded`, "color: white; background: #d35400", "");
