"""Comfort/eco/boost/frost-protection decision logic.

The coordinator seeds every configured comfort-condition entity via
set_comfort_condition() from a synchronous state read at integration setup,
before ever calling is_comfort(). If no condition has been recorded yet,
is_comfort() conservatively returns False — in practice this never happens,
since a room always has at least the shared comfort-release switch among its
comfort_condition_entities.

`boost_enabled` (whether "boost" is offered as a select option) is an
entity-layer concern and intentionally not part of this class.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..const import (
    DEFAULT_COMFORT_TEMPERATURE_C,
    DEFAULT_ECO_TEMPERATURE_OFFSET_C,
    HeatMode,
)


@dataclass
class HeatingStateConfig:
    """Static per-room settings for the comfort/eco/boost/frost decision."""

    boost_temperature_offset_c: float = 5.0
    frost_protection_temperature_c: float = 8.0
    pv_boost_enabled: bool = False
    pv_boost_temperature_offset_c: float = 1.0


class HeatingStateController:
    """Derives the effective heat mode and target temperature for a room."""

    def __init__(self, config: HeatingStateConfig) -> None:
        self._config = config
        self._comfort_conditions: dict[str, bool] = {}
        self._window_states: dict[str, bool] = {}
        self._comfort_temperature_c = DEFAULT_COMFORT_TEMPERATURE_C
        self._eco_temperature_offset_c = DEFAULT_ECO_TEMPERATURE_OFFSET_C
        self._pv_boost = False
        self._heating_available = True
        self._window_open = False
        self._active_heat_mode = HeatMode.ECO

    def reset(self) -> None:
        """Reset all runtime state back to construction-time defaults."""
        self._comfort_conditions = {}
        self._window_states = {}
        self._window_open = False
        self._heating_available = True
        self._comfort_temperature_c = DEFAULT_COMFORT_TEMPERATURE_C
        self._eco_temperature_offset_c = DEFAULT_ECO_TEMPERATURE_OFFSET_C
        self._pv_boost = False
        self._active_heat_mode = HeatMode.ECO

    def set_comfort_condition(self, key: str, value: bool) -> None:
        self._comfort_conditions[key] = value

    def set_comfort_temperature(self, value: float) -> None:
        self._comfort_temperature_c = value

    def set_eco_temperature_offset(self, value: float) -> None:
        self._eco_temperature_offset_c = value

    def set_pv_boost(self, value: bool) -> None:
        self._pv_boost = value

    def set_heating_available(self, value: bool) -> None:
        self._heating_available = value

    def set_active_heat_mode(self, heat_mode: HeatMode) -> None:
        self._active_heat_mode = heat_mode

    def update_window_state(self, key: str, is_open: bool) -> tuple[bool, bool]:
        """Update one window contact and return (previous, current) open state."""
        previous = self._window_open
        self._window_states[key] = is_open
        self._window_open = any(self._window_states.values())
        return previous, self._window_open

    def is_comfort(self) -> bool:
        if not self._comfort_conditions:
            return False
        return all(self._comfort_conditions.values())

    def automatic_mode_selection_allowed(self, active: bool, blocked: bool) -> bool:
        return active and not blocked and not self._window_open

    def desired_automatic_heat_mode(self, active: bool, blocked: bool) -> HeatMode:
        if not self.automatic_mode_selection_allowed(active, blocked):
            return self._active_heat_mode
        return HeatMode.COMFORT if self.is_comfort() else HeatMode.ECO

    def should_force_frost_protection(self) -> bool:
        return self._window_open or not self._heating_available

    def resolve_display_mode(self) -> HeatMode:
        if self.should_force_frost_protection():
            return HeatMode.FROST_PROTECTION
        return self._active_heat_mode

    def determine_base_target_temperature(
        self, heat_mode: HeatMode | None = None
    ) -> float:
        mode = heat_mode if heat_mode is not None else self._active_heat_mode
        if mode is HeatMode.COMFORT:
            return self._comfort_temperature_c
        if mode is HeatMode.ECO:
            return self._comfort_temperature_c + self._eco_temperature_offset_c
        if mode is HeatMode.BOOST:
            return (
                self._comfort_temperature_c
                + self._config.boost_temperature_offset_c
            )
        return self._config.frost_protection_temperature_c

    def effective_target_temperature(self, base_target_temperature_c: float) -> float:
        if self._config.pv_boost_enabled and self._pv_boost:
            return (
                base_target_temperature_c
                + self._config.pv_boost_temperature_offset_c
            )
        return base_target_temperature_c

    @property
    def is_window_open(self) -> bool:
        return self._window_open

    @property
    def is_heating_available(self) -> bool:
        return self._heating_available

    @property
    def is_pv_boost_active(self) -> bool:
        return self._pv_boost

    @property
    def current_heat_mode(self) -> HeatMode:
        return self._active_heat_mode
