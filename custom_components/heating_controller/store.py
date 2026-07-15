"""Persistence for the learned UA/capacity factors of one room's config entry.

One Store file per room (not one shared file for all rooms): each room's
30-minute learning cycle saves independently, and a shared file would need
every room to read-modify-write the whole blob, racing any other room that
saves around the same time. A per-room file needs no cross-room locking.

The filename/key includes the room slug purely so the file is recognizable
in `.storage/` — `entry_id` (not the room name) is still the authoritative,
stable identifier, since a room could in principle be renamed later.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import DOMAIN
from .controller.mpc.types import LearningFactors

STORAGE_VERSION = 1


def _storage_key(room_name: str, entry_id: str) -> str:
    return f"{DOMAIN}_{slugify(room_name)}_{entry_id}_learning_factors"


class LearningFactorsStore:
    """Wraps a `Store` holding one room's learned `ua_factor`/`capacity_factor`."""

    def __init__(self, hass: HomeAssistant, room_name: str, entry_id: str) -> None:
        self._room_name = room_name
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, _storage_key(room_name, entry_id)
        )

    async def async_load(self) -> LearningFactors | None:
        data = await self._store.async_load()
        if data is None:
            return None
        return LearningFactors(
            ua_factor=data["ua_factor"], capacity_factor=data["capacity_factor"]
        )

    async def async_save(self, factors: LearningFactors) -> None:
        await self._store.async_save(
            {
                "room_name": self._room_name,
                "ua_factor": factors.ua_factor,
                "capacity_factor": factors.capacity_factor,
            }
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()
