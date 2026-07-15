from homeassistant.core import HomeAssistant, ServiceCall
from pytest_homeassistant_custom_component.common import MockConfigEntry

from heating_controller.const import DOMAIN, HeatMode
from heating_controller.coordinator import HeatingRoomCoordinator

ENTRY_DATA = {
    "room_name": "Wohnzimmer",
    "trvs": [
        {
            "entity_id": "climate.heizung_wohnzimmer",
            "emitter_type": "panel",
            "min_target_temperature_c": 5.0,
            "max_target_temperature_c": 28.0,
            "target_temperature_step_c": 0.5,
            "radiator_type": "22",
            "width_mm": 1000.0,
            "height_mm": 600.0,
        }
    ],
    "room_sensor_entity": "sensor.wohnzimmer_temperatur",
    "window_contact_entities": ["binary_sensor.fenster_wohnzimmer"],
    "comfort_condition_entities": ["input_boolean.comfort_release"],
    "outdoor_temperature_entity": "sensor.outdoor_temperature",
    "flow_temperature_entity": "sensor.flow_temperature",
    "heating_available_entity": "binary_sensor.heat_available",
    "pv_boost_entity": "binary_sensor.pv_boost",
    "boost_enabled": False,
    "boost_temperature_offset_c": 5.0,
    "frost_protection_temperature_c": 8.0,
    "pv_boost_enabled": False,
    "pv_boost_temperature_offset_c": 1.0,
    "design_indoor_temperature_c": 20.0,
    "design_outdoor_temperature_c": -12.0,
    "design_temperature_system": "system_55_45",
    "room_heat_load_w": 1200.0,
    "mpc_demand_hysteresis_pct": 5.0,
    "mpc_hold_time_s": 300.0,
    "mpc_hold_override_demand_pct": 40.0,
    "mpc_max_demand_step_pct": 20.0,
    "max_sensor_age_s": 1800.0,
}


def _seed_entities(hass: HomeAssistant, *, comfort_release=True, heat_available=True) -> None:
    hass.states.async_set(
        "climate.heizung_wohnzimmer", "heat", {"current_temperature": 18.0}
    )
    hass.states.async_set("sensor.wohnzimmer_temperatur", "18.5")
    hass.states.async_set("binary_sensor.fenster_wohnzimmer", "off")
    hass.states.async_set(
        "input_boolean.comfort_release", "on" if comfort_release else "off"
    )
    hass.states.async_set("sensor.outdoor_temperature", "-3.0")
    hass.states.async_set("sensor.flow_temperature", "42.0")
    hass.states.async_set(
        "binary_sensor.heat_available", "on" if heat_available else "off"
    )
    hass.states.async_set("binary_sensor.pv_boost", "off")


def _register_fake_climate_set_temperature(hass: HomeAssistant) -> list[ServiceCall]:
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "set_temperature", handler)
    return calls


async def test_setup_seeds_state_and_computes_result(hass: HomeAssistant) -> None:
    _seed_entities(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    coordinator = HeatingRoomCoordinator(hass, entry)
    calls = _register_fake_climate_set_temperature(hass)

    await coordinator.async_setup()

    assert coordinator.state.is_comfort() is True
    assert coordinator.current_heat_mode == HeatMode.COMFORT
    assert coordinator.is_automation_active is True
    assert coordinator.last_result is not None
    assert coordinator.last_result.input.room_temp_c == 18.5

    assert calls, "expected at least one climate.set_temperature service call"
    assert calls[0].data["entity_id"] == "climate.heizung_wohnzimmer"

    coordinator.async_unload()


async def test_window_open_forces_frost_protection(hass: HomeAssistant) -> None:
    _seed_entities(hass)
    hass.states.async_set("binary_sensor.fenster_wohnzimmer", "on")
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    coordinator = HeatingRoomCoordinator(hass, entry)
    _register_fake_climate_set_temperature(hass)

    await coordinator.async_setup()

    assert coordinator.current_heat_mode == HeatMode.FROST_PROTECTION
    coordinator.async_unload()


async def test_manual_override_blocks_until_unblocked(hass: HomeAssistant) -> None:
    _seed_entities(hass)
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    coordinator = HeatingRoomCoordinator(hass, entry)
    _register_fake_climate_set_temperature(hass)
    await coordinator.async_setup()

    assert coordinator.current_heat_mode == HeatMode.COMFORT
    assert coordinator.is_automation_active is True

    await coordinator.async_set_manual_heat_mode(HeatMode.ECO)
    assert coordinator.current_heat_mode == HeatMode.ECO
    assert coordinator.is_automation_active is False

    await coordinator.async_unblock()
    assert coordinator.is_automation_active is True
    assert coordinator.current_heat_mode == HeatMode.COMFORT

    coordinator.async_unload()


async def test_heating_unavailable_disables_learning(hass: HomeAssistant) -> None:
    _seed_entities(hass, heat_available=False)
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    coordinator = HeatingRoomCoordinator(hass, entry)
    _register_fake_climate_set_temperature(hass)
    await coordinator.async_setup()

    assert coordinator.current_heat_mode == HeatMode.FROST_PROTECTION
    assert coordinator.mpc._learner._enabled is False

    coordinator.async_unload()


async def test_legacy_learning_factors_imported_from_room_prefixed_text_entities(
    hass: HomeAssistant,
) -> None:
    """Legacy entities are named <room>_ua_factor / <room>_capacity_factor
    (room-prefixed), not ua_factor_<room> — this pins that exact order."""
    _seed_entities(hass)
    hass.states.async_set("text.wohnzimmer_ua_factor", "0.9982289915877139")
    hass.states.async_set("text.wohnzimmer_capacity_factor", "1.0074397084454827")

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    coordinator = HeatingRoomCoordinator(hass, entry)
    _register_fake_climate_set_temperature(hass)
    await coordinator.async_setup()

    assert coordinator.mpc.learned_ua_factor == 0.9982289915877139
    assert coordinator.mpc.learned_capacity_factor == 1.0074397084454827

    saved = await coordinator.store.async_load()
    assert saved.ua_factor == 0.9982289915877139
    assert saved.capacity_factor == 1.0074397084454827

    coordinator.async_unload()
