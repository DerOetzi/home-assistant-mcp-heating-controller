"""Room thermal-capacity model."""

from __future__ import annotations

from ..math_helper import clamp
from ..types import RoomThermalConfig

DEFAULT_CAPACITY_SECONDS = 7200

MIN_LEARNED_CAPACITY_FACTOR = 0.5
MAX_LEARNED_CAPACITY_FACTOR = 3.0


class ThermalCapacityModel:
    """Thermal mass model, scaled by a learned correction factor."""

    def __init__(self, config: RoomThermalConfig) -> None:
        self._learned_capacity_factor = 1.0
        self._base_capacity_j_per_k = (
            config.room_heat_load_w * DEFAULT_CAPACITY_SECONDS
        )

    def predict_temperature_change_c(
        self, net_heating_power_w: float, duration_seconds: float
    ) -> float:
        return (net_heating_power_w * duration_seconds) / self.effective_capacity_j_per_k

    def calculate_required_energy_j(
        self, current_temperature_c: float, target_temperature_c: float
    ) -> float:
        return (
            target_temperature_c - current_temperature_c
        ) * self.effective_capacity_j_per_k

    @property
    def learned_capacity_factor(self) -> float:
        return self._learned_capacity_factor

    @learned_capacity_factor.setter
    def learned_capacity_factor(self, value: float) -> None:
        self._learned_capacity_factor = clamp(
            value, MIN_LEARNED_CAPACITY_FACTOR, MAX_LEARNED_CAPACITY_FACTOR
        )

    @property
    def effective_capacity_j_per_k(self) -> float:
        return self._base_capacity_j_per_k * self._learned_capacity_factor
