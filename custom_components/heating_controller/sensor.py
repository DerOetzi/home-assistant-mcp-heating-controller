"""Diagnostic sensors: status text + MPC demand/temperature/learning telemetry."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeatingRoomCoordinator
from .entity import HeatingControllerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HeatingRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HeatingStatusSensor(coordinator),
            MinFlowTemperatureSensor(coordinator),
            HeatingDemandSensor(coordinator),
            RoomTemperatureSensor(coordinator),
            MpcLearningStatusSensor(coordinator),
            UaFactorSensor(coordinator),
            CapacityFactorSensor(coordinator),
        ]
    )


class _DiagnosticSensor(HeatingControllerEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class HeatingStatusSensor(_DiagnosticSensor):
    _attr_translation_key = "heating_status"

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "heating_status")

    @property
    def native_value(self) -> str:
        return self._coordinator.status_text


class MinFlowTemperatureSensor(_DiagnosticSensor):
    _attr_translation_key = "min_flow_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "min_flow_temperature")

    @property
    def native_value(self) -> float | None:
        result = self._coordinator.last_result
        return result.recommended_flow_temperature_c if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._coordinator.last_result
        if result is None:
            return {}
        trv_entity_ids = self._coordinator.trv_entity_ids
        return {
            "trv_target_temps": dict(zip(trv_entity_ids, result.trv_targets, strict=True))
        }


class HeatingDemandSensor(_DiagnosticSensor):
    _attr_translation_key = "heating_demand"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "heating_demand")

    @property
    def native_value(self) -> float | None:
        result = self._coordinator.last_result
        return result.demand_pct if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._coordinator.last_result
        if result is None:
            return {}
        return {
            "requested_heating_power_w": result.requested_heating_power_w,
            "available_heating_power_w": result.available_heating_power_w,
        }


class RoomTemperatureSensor(_DiagnosticSensor):
    _attr_translation_key = "room_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "room_temperature")

    @property
    def native_value(self) -> float | None:
        result = self._coordinator.last_result
        return result.input.room_temp_c if result else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._coordinator.last_result
        if result is None:
            return {}
        trv_entity_ids = self._coordinator.trv_entity_ids
        return {
            "used_strategy": result.input.used_room_sensor_strategy,
            "trv_temperatures": dict(
                zip(trv_entity_ids, result.input.trv_temperatures, strict=True)
            ),
        }


class MpcLearningStatusSensor(_DiagnosticSensor):
    _attr_translation_key = "mpc_learning_status"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "mpc_learning_status")
        self._attr_options = ["learned", "disabled", "skipped", "suppressed", "waiting_interval"]

    @property
    def native_value(self) -> str | None:
        result = self._coordinator.last_result
        if result is None or result.learning_state is None:
            return None
        return result.learning_state.status.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._coordinator.last_result
        if result is None or result.learning_state is None:
            return {}
        prediction = result.learning_state.prediction
        return {
            "prediction": asdict(prediction) if prediction else None,
            "applied_heating_power_w": result.learning_state.applied_heating_power_w,
        }


class UaFactorSensor(_DiagnosticSensor):
    _attr_translation_key = "ua_factor"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "ua_factor")

    @property
    def native_value(self) -> float:
        return self._coordinator.mpc.learned_ua_factor


class CapacityFactorSensor(_DiagnosticSensor):
    _attr_translation_key = "capacity_factor"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "capacity_factor")

    @property
    def native_value(self) -> float:
        return self._coordinator.mpc.learned_capacity_factor
