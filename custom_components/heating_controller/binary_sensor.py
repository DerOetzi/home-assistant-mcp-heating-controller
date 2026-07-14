"""binary_sensor.heating_automation_<room> — automatic mode active/blocked."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeatingRoomCoordinator
from .entity import HeatingControllerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HeatingRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatingAutomationBinarySensor(coordinator)])


class HeatingAutomationBinarySensor(HeatingControllerEntity, BinarySensorEntity):
    _attr_translation_key = "heating_automation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "heating_automation")

    @property
    def is_on(self) -> bool:
        return self._coordinator.is_automation_active
