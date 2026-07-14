"""Per-room runtime coordinator.

Wires one room's config entry to the pure HeatingStateController/RoomMpcController
logic: reads the current state of every configured entity synchronously at
setup, keeps them in sync via state-change listeners, runs the 30-minute MPC
learning cycle, and calls the HA services that actually move the TRVs.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import slugify

from .const import (
    CONF_COMFORT_CONDITION_ENTITIES,
    CONF_DESIGN_INDOOR_TEMPERATURE,
    CONF_DESIGN_OUTDOOR_TEMPERATURE,
    CONF_DESIGN_TEMPERATURE_SYSTEM,
    CONF_FLOW_TEMPERATURE_ENTITY,
    CONF_HEATING_AVAILABLE_ENTITY,
    CONF_MAX_SENSOR_AGE,
    CONF_MPC_DEMAND_HYSTERESIS_PCT,
    CONF_MPC_HOLD_OVERRIDE_DEMAND_PCT,
    CONF_MPC_HOLD_TIME,
    CONF_MPC_MAX_DEMAND_STEP_PCT,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PV_BOOST_ENABLED,
    CONF_PV_BOOST_ENTITY,
    CONF_PV_BOOST_TEMPERATURE_OFFSET,
    CONF_ROOM_HEAT_LOAD,
    CONF_ROOM_NAME,
    CONF_ROOM_SENSOR_ENTITY,
    CONF_TRV_EMITTER_TYPE,
    CONF_TRV_ENTITY_ID,
    CONF_TRV_HEIGHT_MM,
    CONF_TRV_MAX_TARGET_TEMPERATURE,
    CONF_TRV_MIN_TARGET_TEMPERATURE,
    CONF_TRV_NOMINAL_POWER_W,
    CONF_TRV_RADIATOR_TYPE,
    CONF_TRV_TARGET_TEMPERATURE_STEP,
    CONF_TRV_WIDTH_MM,
    CONF_TRVS,
    CONF_WINDOW_CONTACT_ENTITIES,
    CONF_BOOST_TEMPERATURE_OFFSET,
    CONF_FROST_PROTECTION_TEMPERATURE,
    DesignTemperatureSystem,
    HeatEmitterType,
    HeatMode,
    LEARNING_CYCLE_INTERVAL_MINUTES,
    PanelRadiatorType,
)
from .controller.mpc.controller import MpcRateLimitConfig, RoomMpcController
from .controller.mpc.results import RoomMpcResult
from .controller.mpc.types import LearningFactors, RoomThermalConfig, TrvConfig
from .controller.state import HeatingStateConfig, HeatingStateController
from .store import LearningFactorsStore

_LOGGER = logging.getLogger(__name__)

LEARNING_CYCLE_INTERVAL = timedelta(minutes=LEARNING_CYCLE_INTERVAL_MINUTES)

WINDOW_OPEN_SUPPRESS_LEARNING_S = 60 * 60
WINDOW_CLOSED_SUPPRESS_LEARNING_S = 30 * 60


def _build_trv_configs(trv_entries: list[dict[str, Any]]) -> list[TrvConfig]:
    trvs: list[TrvConfig] = []
    for entry in trv_entries:
        emitter_type = HeatEmitterType(entry[CONF_TRV_EMITTER_TYPE])
        trvs.append(
            TrvConfig(
                name=entry[CONF_TRV_ENTITY_ID],
                emitter_type=emitter_type,
                min_target_temperature_c=entry[CONF_TRV_MIN_TARGET_TEMPERATURE],
                max_target_temperature_c=entry[CONF_TRV_MAX_TARGET_TEMPERATURE],
                target_temperature_step_c=entry[CONF_TRV_TARGET_TEMPERATURE_STEP],
                radiator_type=(
                    PanelRadiatorType(entry[CONF_TRV_RADIATOR_TYPE])
                    if CONF_TRV_RADIATOR_TYPE in entry
                    else None
                ),
                width_mm=entry.get(CONF_TRV_WIDTH_MM),
                height_mm=entry.get(CONF_TRV_HEIGHT_MM),
                nominal_power_w=entry.get(CONF_TRV_NOMINAL_POWER_W),
            )
        )
    return trvs


class HeatingRoomCoordinator:
    """Owns the control logic for one room and keeps it in sync with HA state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.data = entry.data
        self.room_name: str = self.data[CONF_ROOM_NAME]

        self._trv_entries: list[dict[str, Any]] = self.data[CONF_TRVS]
        self._trv_entity_ids: list[str] = [
            trv[CONF_TRV_ENTITY_ID] for trv in self._trv_entries
        ]

        self.state = HeatingStateController(
            HeatingStateConfig(
                boost_temperature_offset_c=self.data[CONF_BOOST_TEMPERATURE_OFFSET],
                frost_protection_temperature_c=self.data[
                    CONF_FROST_PROTECTION_TEMPERATURE
                ],
                pv_boost_enabled=self.data[CONF_PV_BOOST_ENABLED],
                pv_boost_temperature_offset_c=self.data[
                    CONF_PV_BOOST_TEMPERATURE_OFFSET
                ],
            )
        )

        thermal_config = RoomThermalConfig(
            design_indoor_temperature_c=self.data[CONF_DESIGN_INDOOR_TEMPERATURE],
            design_outdoor_temperature_c=self.data[CONF_DESIGN_OUTDOOR_TEMPERATURE],
            design_temperature_system=DesignTemperatureSystem(
                self.data[CONF_DESIGN_TEMPERATURE_SYSTEM]
            ),
            room_heat_load_w=self.data[CONF_ROOM_HEAT_LOAD],
        )
        rate_limit_config = MpcRateLimitConfig(
            demand_hysteresis_pct=self.data[CONF_MPC_DEMAND_HYSTERESIS_PCT],
            hold_time_s=self.data[CONF_MPC_HOLD_TIME],
            hold_override_demand_pct=self.data[CONF_MPC_HOLD_OVERRIDE_DEMAND_PCT],
            max_demand_step_pct=self.data[CONF_MPC_MAX_DEMAND_STEP_PCT],
        )
        self.mpc = RoomMpcController(
            thermal_config=thermal_config,
            trvs=_build_trv_configs(self._trv_entries),
            rate_limit_config=rate_limit_config,
            max_sensor_age_s=self.data[CONF_MAX_SENSOR_AGE],
        )

        self.store = LearningFactorsStore(hass, entry.entry_id)

        self.active = True
        self.blocked = False
        self.last_result: RoomMpcResult | None = None

        self._unsub: list[Callable[[], None]] = []
        self._listeners: list[Callable[[], None]] = []

    def async_add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback, returns an unsubscribe function."""
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    def _notify_listeners(self) -> None:
        for update_callback in self._listeners:
            update_callback()

    # -- setup / teardown ----------------------------------------------------

    async def async_setup(self) -> None:
        """Seed all inputs from current entity states and start listening."""
        factors = await self.store.async_load()
        if factors is not None:
            self.mpc.recalibrate_learning_factors(factors)
        else:
            await self._async_import_legacy_learning_factors()

        for entity_id in self.data[CONF_COMFORT_CONDITION_ENTITIES]:
            self.state.set_comfort_condition(entity_id, self._is_on(entity_id))

        for entity_id in self.data.get(CONF_WINDOW_CONTACT_ENTITIES, []):
            self.state.update_window_state(entity_id, self._is_on(entity_id))

        heating_available_entity = self.data[CONF_HEATING_AVAILABLE_ENTITY]
        heating_available = self._is_on(heating_available_entity)
        self.state.set_heating_available(heating_available)
        if heating_available:
            self.mpc.enable_learning()
        else:
            self.mpc.disable_learning()

        self.state.set_pv_boost(self._is_on(self.data[CONF_PV_BOOST_ENTITY]))

        for index, entity_id in enumerate(self._trv_entity_ids):
            self.mpc.set_trv_temperature(
                index, self._climate_current_temperature(entity_id)
            )

        room_sensor_entity = self.data.get(CONF_ROOM_SENSOR_ENTITY)
        if room_sensor_entity:
            self.mpc.set_room_sensor_temperature(self._float_state(room_sensor_entity))

        self.mpc.set_outdoor_temperature(
            self._float_state(self.data[CONF_OUTDOOR_TEMPERATURE_ENTITY])
        )
        self.mpc.set_flow_temperature(
            self._float_state(self.data[CONF_FLOW_TEMPERATURE_ENTITY])
        )

        tracked_entities = list(self._trv_entity_ids)
        tracked_entities.extend(self.data[CONF_COMFORT_CONDITION_ENTITIES])
        tracked_entities.extend(self.data.get(CONF_WINDOW_CONTACT_ENTITIES, []))
        tracked_entities.append(heating_available_entity)
        tracked_entities.append(self.data[CONF_PV_BOOST_ENTITY])
        tracked_entities.append(self.data[CONF_OUTDOOR_TEMPERATURE_ENTITY])
        tracked_entities.append(self.data[CONF_FLOW_TEMPERATURE_ENTITY])
        if room_sensor_entity:
            tracked_entities.append(room_sensor_entity)

        self._unsub.append(
            async_track_state_change_event(
                self.hass, tracked_entities, self._async_handle_state_change
            )
        )
        self._unsub.append(
            async_track_time_interval(
                self.hass, self._async_handle_learning_cycle, LEARNING_CYCLE_INTERVAL
            )
        )

        await self._async_recompute()

    def async_unload(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub = []
        self.mpc.destroy()

    async def _async_import_legacy_learning_factors(self) -> None:
        """One-time import of learning factors from a prior setup, if present."""
        slug = slugify(self.room_name)
        ua_state = self.hass.states.get(f"text.ua_factor_{slug}")
        capacity_state = self.hass.states.get(f"text.capacity_factor_{slug}")
        if ua_state is None or capacity_state is None:
            return

        try:
            factors = LearningFactors(
                ua_factor=float(ua_state.state),
                capacity_factor=float(capacity_state.state),
            )
        except ValueError:
            _LOGGER.warning(
                "Could not parse legacy learning factors for room %s", self.room_name
            )
            return

        self.mpc.recalibrate_learning_factors(factors)
        await self.store.async_save(factors)
        _LOGGER.info(
            "Imported legacy learning factors for room %s: ua_factor=%s capacity_factor=%s",
            self.room_name,
            factors.ua_factor,
            factors.capacity_factor,
        )

    # -- state helpers --------------------------------------------------------

    def _is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == STATE_ON

    def _float_state(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _climate_current_temperature(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        value = state.attributes.get("current_temperature")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _bool_from_state(state: State | None) -> bool:
        return state is not None and state.state == STATE_ON

    @staticmethod
    def _float_from_state(state: State | None) -> float | None:
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    # -- event handling --------------------------------------------------------

    @callback
    def _async_handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        self.hass.async_create_task(
            self._async_process_state_change(entity_id, new_state)
        )

    async def _async_process_state_change(
        self, entity_id: str, new_state: State | None
    ) -> None:
        if entity_id in self._trv_entity_ids:
            index = self._trv_entity_ids.index(entity_id)
            value = None
            if new_state is not None:
                try:
                    value = float(new_state.attributes.get("current_temperature"))
                except (TypeError, ValueError):
                    value = None
            self.mpc.set_trv_temperature(index, value)

        elif entity_id == self.data.get(CONF_ROOM_SENSOR_ENTITY):
            self.mpc.set_room_sensor_temperature(self._float_from_state(new_state))

        elif entity_id == self.data[CONF_OUTDOOR_TEMPERATURE_ENTITY]:
            self.mpc.set_outdoor_temperature(self._float_from_state(new_state))

        elif entity_id == self.data[CONF_FLOW_TEMPERATURE_ENTITY]:
            self.mpc.set_flow_temperature(self._float_from_state(new_state))

        elif entity_id in self.data[CONF_COMFORT_CONDITION_ENTITIES]:
            self.state.set_comfort_condition(
                entity_id, self._bool_from_state(new_state)
            )

        elif entity_id in self.data.get(CONF_WINDOW_CONTACT_ENTITIES, []):
            was_open = self.state.is_window_open
            _, is_open = self.state.update_window_state(
                entity_id, self._bool_from_state(new_state)
            )
            if is_open and not was_open:
                self.mpc.suppress_learning_for_interval(WINDOW_OPEN_SUPPRESS_LEARNING_S)
            elif was_open and not is_open:
                self.mpc.suppress_learning_for_interval(
                    WINDOW_CLOSED_SUPPRESS_LEARNING_S
                )

        elif entity_id == self.data[CONF_HEATING_AVAILABLE_ENTITY]:
            available = self._bool_from_state(new_state)
            self.state.set_heating_available(available)
            if available:
                self.mpc.enable_learning()
            else:
                self.mpc.disable_learning()

        elif entity_id == self.data[CONF_PV_BOOST_ENTITY]:
            self.state.set_pv_boost(self._bool_from_state(new_state))

        await self._async_recompute()

    async def _async_handle_learning_cycle(self, _now: Any) -> None:
        self.mpc.run_learning_cycle()
        persisted_factors = self.mpc.consume_persisted_learning_factors()
        if persisted_factors is not None:
            await self.store.async_save(persisted_factors)
        self._notify_listeners()

    async def _async_recompute(self) -> None:
        # No-op when blocked/inactive (desired_automatic_heat_mode then returns
        # the current mode unchanged), so this is safe to call unconditionally
        # before every compute cycle, including right after a manual override
        # or an unblock.
        desired_mode = self.state.desired_automatic_heat_mode(self.active, self.blocked)
        self.state.set_active_heat_mode(desired_mode)

        display_mode = self.state.resolve_display_mode()
        base_target = self.state.determine_base_target_temperature(display_mode)
        effective_target = self.state.effective_target_temperature(base_target)

        compute_result = self.mpc.compute(effective_target)
        if compute_result.valid:
            self.last_result = compute_result.result
            await self._async_apply_result(compute_result.result)
        else:
            _LOGGER.debug(
                "MPC compute failed for room %s: %s", self.room_name, compute_result.error
            )

        persisted_factors = self.mpc.consume_persisted_learning_factors()
        if persisted_factors is not None:
            await self.store.async_save(persisted_factors)

        self._notify_listeners()

    async def _async_apply_result(self, result: RoomMpcResult) -> None:
        for entity_id, target_temperature_c in zip(
            self._trv_entity_ids, result.trv_targets, strict=True
        ):
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": target_temperature_c},
                blocking=False,
            )

    # -- commands from entities/services --------------------------------------

    async def async_set_manual_heat_mode(self, mode: HeatMode) -> None:
        automatic_choice = self.state.desired_automatic_heat_mode(self.active, False)
        self.state.set_active_heat_mode(mode)
        self.blocked = mode != automatic_choice
        await self._async_recompute()

    async def async_unblock(self) -> None:
        self.blocked = False
        await self._async_recompute()

    async def async_set_comfort_temperature(self, value: float) -> None:
        self.state.set_comfort_temperature(value)
        await self._async_recompute()

    async def async_set_eco_temperature_offset(self, value: float) -> None:
        self.state.set_eco_temperature_offset(value)
        await self._async_recompute()

    # -- read-only properties for entity platforms ----------------------------

    @property
    def trv_entity_ids(self) -> list[str]:
        return self._trv_entity_ids

    @property
    def current_heat_mode(self) -> HeatMode:
        return self.state.resolve_display_mode()

    @property
    def is_automation_active(self) -> bool:
        return self.active and not self.blocked

    @property
    def status_text(self) -> str:
        parts = ["Blocked" if self.blocked else "Automatic"]
        parts.append(self.current_heat_mode.value.replace("_", " ").title())
        if self.data[CONF_PV_BOOST_ENABLED] and self.state.is_pv_boost_active:
            parts.append("PV boost")
        if self.state.is_window_open:
            parts.append("window open")
        return " - ".join(parts)
