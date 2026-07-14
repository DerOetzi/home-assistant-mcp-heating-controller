from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from heating_controller.const import (
    CONF_COMFORT_CONDITION_ENTITIES,
    CONF_DESIGN_TEMPERATURE_SYSTEM,
    CONF_FLOW_TEMPERATURE_ENTITY,
    CONF_HEATING_AVAILABLE_ENTITY,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PV_BOOST_ENTITY,
    CONF_ROOM_NAME,
    CONF_TRV_ENTITY_ID,
    CONF_TRVS,
    DOMAIN,
)


async def test_full_config_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"room_name": "Wohnzimmer", "trv_count": 1},
    )
    assert result["step_id"] == "trv"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "entity_id": "climate.heizung_wohnzimmer",
            "emitter_type": "panel",
            "min_target_temperature_c": 5.0,
            "max_target_temperature_c": 28.0,
            "target_temperature_step_c": 0.5,
        },
    )
    assert result["step_id"] == "trv_details"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"radiator_type": "22", "width_mm": 1000.0, "height_mm": 600.0},
    )
    assert result["step_id"] == "entities"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "window_contact_entities": [],
            "comfort_condition_entities": ["input_boolean.comfort_release"],
            "outdoor_temperature_entity": "sensor.outdoor_temperature",
            "flow_temperature_entity": "sensor.flow_temperature",
            "heating_available_entity": "binary_sensor.heat_available",
            "pv_boost_entity": "binary_sensor.pv_boost",
        },
    )
    assert result["step_id"] == "settings"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "boost_enabled": False,
            "boost_temperature_offset_c": 5.0,
            "frost_protection_temperature_c": 8.0,
            "pv_boost_enabled": False,
            "pv_boost_temperature_offset_c": 1.0,
        },
    )
    assert result["step_id"] == "mpc"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "design_indoor_temperature_c": 20.0,
            "design_outdoor_temperature_c": -12.0,
            "design_temperature_system": "system_55_45",
            "room_heat_load_w": 1000.0,
            "mpc_demand_hysteresis_pct": 5.0,
            "mpc_hold_time_s": 300.0,
            "mpc_hold_override_demand_pct": 40.0,
            "mpc_max_demand_step_pct": 20.0,
            "max_sensor_age_s": 1800.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wohnzimmer"
    data = result["data"]
    assert data[CONF_ROOM_NAME] == "Wohnzimmer"
    assert data[CONF_DESIGN_TEMPERATURE_SYSTEM] == "system_55_45"
    assert data[CONF_OUTDOOR_TEMPERATURE_ENTITY] == "sensor.outdoor_temperature"
    assert data[CONF_FLOW_TEMPERATURE_ENTITY] == "sensor.flow_temperature"
    assert data[CONF_HEATING_AVAILABLE_ENTITY] == "binary_sensor.heat_available"
    assert data[CONF_PV_BOOST_ENTITY] == "binary_sensor.pv_boost"
    assert data[CONF_COMFORT_CONDITION_ENTITIES] == ["input_boolean.comfort_release"]
    assert len(data[CONF_TRVS]) == 1
    assert data[CONF_TRVS][0][CONF_TRV_ENTITY_ID] == "climate.heizung_wohnzimmer"


async def test_duplicate_room_name_is_aborted(hass: HomeAssistant) -> None:
    async def _create_first_entry():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"room_name": "Kueche", "trv_count": 1}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "entity_id": "climate.heizung_kueche",
                "emitter_type": "towel",
                "min_target_temperature_c": 5.0,
                "max_target_temperature_c": 28.0,
                "target_temperature_step_c": 0.5,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"nominal_power_w": 500.0}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "comfort_condition_entities": ["input_boolean.comfort_release"],
                "outdoor_temperature_entity": "sensor.outdoor_temperature",
                "flow_temperature_entity": "sensor.flow_temperature",
                "heating_available_entity": "binary_sensor.heat_available",
                "pv_boost_entity": "binary_sensor.pv_boost",
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "boost_enabled": False,
                "boost_temperature_offset_c": 5.0,
                "frost_protection_temperature_c": 8.0,
                "pv_boost_enabled": False,
                "pv_boost_temperature_offset_c": 1.0,
            },
        )
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "design_indoor_temperature_c": 20.0,
                "design_outdoor_temperature_c": -12.0,
                "design_temperature_system": "system_55_45",
                "room_heat_load_w": 1000.0,
                "mpc_demand_hysteresis_pct": 5.0,
                "mpc_hold_time_s": 300.0,
                "mpc_hold_override_demand_pct": 40.0,
                "mpc_max_demand_step_pct": 20.0,
                "max_sensor_age_s": 1800.0,
            },
        )

    first = await _create_first_entry()
    assert first["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"room_name": "Kueche", "trv_count": 1}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
