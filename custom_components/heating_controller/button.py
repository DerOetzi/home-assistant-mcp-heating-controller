from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    async_add_entities([HeatingUnblockButton(coordinator)])


class HeatingUnblockButton(HeatingControllerEntity, ButtonEntity):
    _attr_translation_key = "heating_unblock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "heating_unblock")

    async def async_press(self) -> None:
        await self._coordinator.async_unblock()
