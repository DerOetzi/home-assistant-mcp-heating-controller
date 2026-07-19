"""Logic tests for the shipped Lovelace card, executed in a real JS engine.

The card is plain ES2020 with no build tooling, so QuickJS runs the module
directly. Only DOM-free helpers are exercised here — enough to pin the config
round-trip, which is where a silent data-loss bug lived.
"""

import pytest

quickjs = pytest.importorskip("quickjs")

from heating_controller import frontend

_DOM_STUBS = """
var window = globalThis;
var console = { info: function(){}, warn: function(){}, error: function(){} };
var customElements = { define: function(){}, get: function(){} };
var document = { createElement: function(){ return {}; } };
var HTMLElement = function(){};
HTMLElement.prototype = {};
var CustomEvent = function(){};
"""


@pytest.fixture(scope="module")
def ctx() -> "quickjs.Context":
    context = quickjs.Context()
    context.eval(_DOM_STUBS)
    # A syntax error here means the browser could not load the card either.
    context.eval(open(frontend._CARD_PATH, encoding="utf-8").read())
    return context


def _json(ctx, expression: str):
    import json

    return json.loads(ctx.eval(f"JSON.stringify({expression})"))


def test_module_defines_card_and_editor(ctx) -> None:
    assert ctx.eval("typeof HeatingControllerCard") == "function"
    assert ctx.eval("typeof HeatingControllerCardEditor") == "function"


def test_normalize_accepts_both_forms(ctx) -> None:
    result = _json(
        ctx,
        'normalizeItems(["sensor.a", {entity: "sensor.b", name: "B"}])',
    )
    assert result == [{"entity": "sensor.a"}, {"entity": "sensor.b", "name": "B"}]


def test_normalize_drops_broken_entries(ctx) -> None:
    """Configs damaged by an earlier version must heal, not render undefined."""
    result = _json(ctx, 'normalizeItems(["sensor.a", null, {}, undefined])')
    assert result == [{"entity": "sensor.a"}]


def test_compact_form_survives_a_second_round_trip(ctx) -> None:
    """The editor writes entries without name/icon back as bare strings.

    Mapping over that result again used to read .entity off a string, which is
    undefined — so every plain entry vanished on the next edit.
    """
    ctx.eval(
        """
        var compact = function (items) {
          return normalizeItems(items).map(function (item) {
            return !item.name && !item.icon ? item.entity : item;
          });
        };
        var once = compact(["sensor.a", {entity: "sensor.b", name: "B"}]);
        var twice = compact(once);
        """
    )
    assert _json(ctx, "once") == ["sensor.a", {"entity": "sensor.b", "name": "B"}]
    assert _json(ctx, "twice") == _json(ctx, "once")


def test_legacy_extra_entities_are_split_by_position(ctx) -> None:
    result = _json(
        ctx,
        """migrateLegacyConfig({
             device: "abc",
             extra_entities: [
               "sensor.detail",
               {entity: "sensor.head", position: "header"}
             ]
           })""",
    )
    assert result == {
        "device": "abc",
        "detail_entities": [{"entity": "sensor.detail"}],
        "header_entities": [{"entity": "sensor.head"}],
    }


_HASS_FIXTURE = """
var hass = {
  entities: {
    "sensor.katharina_raumtemperatur": {
      device_id: "dev", platform: "heating_controller",
      translation_key: "room_temperature", entity_id: "sensor.katharina_raumtemperatur",
    },
    "binary_sensor.katharina_heizautomatik": {
      device_id: "dev", platform: "heating_controller",
      translation_key: "heating_automation",
      entity_id: "binary_sensor.katharina_heizautomatik",
    },
    "sensor.katharina_heating_demand": {
      device_id: "dev", platform: "heating_controller",
      translation_key: "heating_demand", entity_id: "sensor.katharina_heating_demand",
    },
  },
  states: {
    "sensor.katharina_raumtemperatur": {
      entity_id: "sensor.katharina_raumtemperatur",
      state: "21.4",
      attributes: {
        used_strategy: "room_sensor", room_sensor_temp_c: 21.4,
        trv_temperatures: { "climate.gross": 21.1, "climate.klein": 21.2 },
      },
    },
    "binary_sensor.katharina_heizautomatik": {
      entity_id: "binary_sensor.katharina_heizautomatik",
      state: "on",
      attributes: {
        window_contact_entities: ["binary_sensor.fenster_a"],
      },
    },
    "sensor.katharina_heating_demand": {
      state: "0",
      attributes: { trv_target_temps: { "climate.gross": 5, "climate.klein": 5 } },
    },
    "climate.gross": { state: "heat", attributes: { friendly_name: "Heizung groß" } },
    "climate.klein": { state: "heat", attributes: { friendly_name: "Heizung klein" } },
    "binary_sensor.fenster_a": { state: "off", attributes: { friendly_name: "Fenster A" } },
  },
};
var roles = resolveRoles(hass, "dev");
"""


def test_resolve_roles_maps_by_translation_key(ctx) -> None:
    ctx.eval(_HASS_FIXTURE)
    assert ctx.eval("roles.roomTemp.entity_id") == "sensor.katharina_raumtemperatur"
    assert ctx.eval("roles.automation.entity_id") == "binary_sensor.katharina_heizautomatik"


def test_managed_rows_seed_sensor_trvs_and_windows(ctx) -> None:
    ctx.eval(_HASS_FIXTURE)
    keys = _json(ctx, "managedDetailRows(hass, roles).map(function(r){return r.key;})")
    assert keys == [
        "room_sensor",
        "trv:climate.gross",
        "trv:climate.klein",
        "window:binary_sensor.fenster_a",
    ]


def test_managed_row_defaults(ctx) -> None:
    ctx.eval(_HASS_FIXTURE)
    rows = _json(ctx, "managedDetailRows(hass, roles)")
    by_key = {r["key"]: r for r in rows}
    assert by_key["room_sensor"]["value"] == "21.4 °C"
    assert by_key["trv:climate.gross"]["name"] == "Heizung groß"
    assert by_key["trv:climate.gross"]["value"] == "21.1 °C → 5.0 °C"
    assert by_key["window:binary_sensor.fenster_a"]["value"] == "Geschlossen"


def test_normalize_detail_keeps_key_and_entity_entries(ctx) -> None:
    result = _json(
        ctx,
        'normalizeDetail(["sensor.x", {key: "room_sensor"}, {entity: "sensor.y", name: "Y"}, {}, null])',
    )
    assert result == [
        {"entity": "sensor.x"},
        {"key": "room_sensor"},
        {"entity": "sensor.y", "name": "Y"},
    ]
