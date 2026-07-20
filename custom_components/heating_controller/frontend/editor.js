// Visual editor for the card.

import { DOMAIN, HEADER_KEY, DETAIL_KEY, ROOM_SENSOR_KEY } from "./const.js";
import { resolveRoles, managedDetailRows } from "./entities.js";
import {
  migrateLegacyConfig,
  normalizeItems,
  normalizeDetail,
} from "./config.js";
import { EDITOR_STYLES } from "./editor-styles.js";
import { t } from "./translations.js";

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

export class HeatingControllerCardEditor extends HTMLElement {
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
      <style>${EDITOR_STYLES}</style>`;

    const baseForm = this.shadowRoot.getElementById("baseForm");
    baseForm.schema = BASE_SCHEMA;
    baseForm.computeLabel = (schema) => this._label(schema.name);
    baseForm.addEventListener("value-changed", (ev) => {
      ev.stopPropagation();
      this._emit({ ...this._config, ...ev.detail.value });
    });

    const itemForm = this.shadowRoot.getElementById("itemForm");
    itemForm.schema = ITEM_SCHEMA;
    itemForm.computeLabel = (schema) => this._label(schema.name);
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
    lists.appendChild(
      this._buildListSection({
        key: HEADER_KEY,
        heading: t(this._hass, "editor_header_heading"),
        hint: t(this._hass, "editor_header_hint"),
      })
    );
    lists.appendChild(this._buildDetailSection());
  }

  _buildDetailSection() {
    const section = document.createElement("div");
    section.className = "list-section";
    section.innerHTML =
      `<div class="heading">${t(this._hass, "section_details")}</div>` +
      `<div class="hint">${t(this._hass, "editor_detail_hint")}</div>`;

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
    adder.label = t(this._hass, "editor_add_custom_sensor");
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
        item.managed && !item.entity
          ? t(this._hass, "editor_seeded")
          : item.entity
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
    adder.label = t(this._hass, "editor_add_entity");
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

    const heading = t(
      this._hass,
      list === "header" ? "editor_header_heading" : "section_details"
    );
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
      `<span class="ro-label">${t(this._hass, "editor_entity")}</span>` +
      `<span class="ro-value">${item.entity ?? item.label}</span>`;
    container.appendChild(field);
  }

  // ha-form asks for a label per schema field; the schema itself stays
  // language-free so it can be shared between the two forms.
  _label(name) {
    return t(this._hass, `editor_${name}`);
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
