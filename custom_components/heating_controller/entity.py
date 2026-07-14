"""Shared base entity: device grouping + coordinator update subscription."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .coordinator import HeatingRoomCoordinator


class HeatingControllerEntity(Entity):
    """Base for all entities of one room's config entry.

    entity_id is left to HA's normal has_entity_name auto-generation (derived
    from the translated friendly name in the instance's configured language),
    not forced to an English slug.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: HeatingRoomCoordinator, unique_id_suffix: str) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.room_name,
            manufacturer="Heating Controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
