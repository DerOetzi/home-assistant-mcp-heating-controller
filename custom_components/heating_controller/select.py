"""select.heating_mode_<room> — manual heat-mode selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BOOST_ENABLED, DOMAIN, HeatMode
from .coordinator import HeatingRoomCoordinator
from .entity import HeatingControllerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HeatingRoomCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeatingModeSelect(coordinator)])


class HeatingModeSelect(HeatingControllerEntity, SelectEntity):
    _attr_translation_key = "heating_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HeatingRoomCoordinator) -> None:
        super().__init__(coordinator, "heating_mode")
        options = [HeatMode.COMFORT.value, HeatMode.ECO.value]
        if coordinator.data.get(CONF_BOOST_ENABLED):
            options.append(HeatMode.BOOST.value)
        options.append(HeatMode.FROST_PROTECTION.value)
        self._attr_options = options

    @property
    def current_option(self) -> str:
        return self._coordinator.current_heat_mode.value

    async def async_select_option(self, option: str) -> None:
        await self._coordinator.async_set_manual_heat_mode(HeatMode(option))
