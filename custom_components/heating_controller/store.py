"""Persistence for the learned UA/capacity factors of one room's config entry."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .controller.mpc.types import LearningFactors

STORAGE_VERSION = 1


class LearningFactorsStore:
    """Wraps a `Store` holding one room's learned `ua_factor`/`capacity_factor`."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_learning_factors"
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
            {"ua_factor": factors.ua_factor, "capacity_factor": factors.capacity_factor}
        )
