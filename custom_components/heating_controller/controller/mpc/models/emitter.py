"""Per-TRV heat-emitter model.

Converts a 0-100% demand into per-TRV target temperatures, and converts
room/flow temperatures into available heating power, using EN 442 panel
radiator exponents/reference power tables (or a flat nominal power for towel
rails), weighted by each emitter's share of total design power.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil

from ....const import DesignTemperatureSystem, HeatEmitterType, PanelRadiatorType
from ..math_helper import clamp, round_to_step
from ..types import RoomThermalConfig, TrvConfig

RADIATOR_EXPONENTS: dict[PanelRadiatorType, float] = {
    PanelRadiatorType.TYPE_10: 1.2,
    PanelRadiatorType.TYPE_11: 1.25,
    PanelRadiatorType.TYPE_21: 1.3,
    PanelRadiatorType.TYPE_22: 1.35,
    PanelRadiatorType.TYPE_33: 1.4,
}

PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER: dict[int, dict[PanelRadiatorType, float]] = {
    300: {
        PanelRadiatorType.TYPE_10: 450,
        PanelRadiatorType.TYPE_11: 600,
        PanelRadiatorType.TYPE_21: 900,
        PanelRadiatorType.TYPE_22: 1200,
        PanelRadiatorType.TYPE_33: 1800,
    },
    600: {
        PanelRadiatorType.TYPE_10: 800,
        PanelRadiatorType.TYPE_11: 1100,
        PanelRadiatorType.TYPE_21: 1600,
        PanelRadiatorType.TYPE_22: 2000,
        PanelRadiatorType.TYPE_33: 3000,
    },
    900: {
        PanelRadiatorType.TYPE_10: 1200,
        PanelRadiatorType.TYPE_11: 1600,
        PanelRadiatorType.TYPE_21: 2400,
        PanelRadiatorType.TYPE_22: 3100,
        PanelRadiatorType.TYPE_33: 4500,
    },
}

MIN_ACTIVE_TRV_TEMPERATURE_C = 18.0

INFINITE_LOOP_GUARD = 20

DISTRIBUTION_ALPHA = 0.7


@dataclass
class _DesignTemperatures:
    flow_temperature_c: float
    overtemperature_c: float
    spread_c: float


DESIGN_SYSTEM_TEMPERATURES: dict[DesignTemperatureSystem, _DesignTemperatures] = {
    DesignTemperatureSystem.SYSTEM_75_65: _DesignTemperatures(75, 50, 10),
    DesignTemperatureSystem.SYSTEM_70_55: _DesignTemperatures(70, 42.5, 15),
    DesignTemperatureSystem.SYSTEM_55_45: _DesignTemperatures(55, 30, 10),
    DesignTemperatureSystem.SYSTEM_45_35: _DesignTemperatures(45, 20, 10),
    DesignTemperatureSystem.SYSTEM_35_30: _DesignTemperatures(35, 12.5, 5),
}


@dataclass
class _PreparedEmitter:
    trv: TrvConfig
    design_reference_power_w: float
    exponent: float
    distribution_weight: float = 0.0


class HeatEmitterModel:
    """Per-room collection of 1-3 TRVs and their heat-emitter curves."""

    def __init__(self, thermal_config: RoomThermalConfig, trvs: list[TrvConfig]) -> None:
        self._design_temperatures = DESIGN_SYSTEM_TEMPERATURES[
            thermal_config.design_temperature_system
        ]
        prepared = [self._create_prepared_emitter(trv) for trv in trvs]
        self._emitters = self._calculate_distribution_weights(prepared)

    def _create_prepared_emitter(self, trv: TrvConfig) -> _PreparedEmitter:
        exponent = self._get_emitter_exponent(trv)
        table_reference_power_w = self._calculate_emitter_table_reference_power_w(trv)
        design_reference_power_w = self._convert_reference_power_to_design_system(
            table_reference_power_w, exponent
        )
        return _PreparedEmitter(
            trv=trv,
            design_reference_power_w=design_reference_power_w,
            exponent=exponent,
        )

    @staticmethod
    def _get_emitter_exponent(trv: TrvConfig) -> float:
        if trv.emitter_type == HeatEmitterType.PANEL:
            return RADIATOR_EXPONENTS[trv.radiator_type or PanelRadiatorType.TYPE_22]
        return 1.3

    def _calculate_emitter_table_reference_power_w(self, trv: TrvConfig) -> float:
        if trv.emitter_type == HeatEmitterType.PANEL:
            return self._calculate_panel_radiator_table_reference_power_w(trv)
        if trv.emitter_type == HeatEmitterType.TOWEL:
            return trv.nominal_power_w or 0
        return 0

    def _calculate_panel_radiator_table_reference_power_w(self, trv: TrvConfig) -> float:
        if trv.height_mm is None or trv.width_mm is None or trv.radiator_type is None:
            return 0
        interpolated_power_per_meter = self._interpolate_panel_radiator_power_per_meter(
            trv.height_mm, trv.radiator_type
        )
        return round_to_step(interpolated_power_per_meter * (trv.width_mm / 1000), 0.01)

    @staticmethod
    def _interpolate_panel_radiator_power_per_meter(
        height_mm: float, radiator_type: PanelRadiatorType
    ) -> float:
        available_heights = sorted(PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER.keys())
        if not available_heights:
            return 0

        if height_mm in available_heights:
            return PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER[height_mm].get(
                radiator_type, 0
            )

        if height_mm <= available_heights[0]:
            return PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER[
                available_heights[0]
            ].get(radiator_type, 0)

        last_index = len(available_heights) - 1
        if height_mm >= available_heights[last_index]:
            return PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER[
                available_heights[last_index]
            ].get(radiator_type, 0)

        lower_height = available_heights[0]
        upper_height = available_heights[last_index]
        for i in range(last_index):
            current_height = available_heights[i]
            next_height = available_heights[i + 1]
            if current_height < height_mm < next_height:
                lower_height = current_height
                upper_height = next_height
                break

        lower_power = PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER[lower_height].get(
            radiator_type, 0
        )
        upper_power = PANEL_RADIATOR_REFERENCE_POWER_W_PER_METER[upper_height].get(
            radiator_type, 0
        )

        if lower_height == upper_height:
            return lower_power

        interpolation_factor = (height_mm - lower_height) / (upper_height - lower_height)
        return lower_power + (upper_power - lower_power) * interpolation_factor

    def _convert_reference_power_to_design_system(
        self, table_reference_power_w: float, exponent: float
    ) -> float:
        if table_reference_power_w <= 0 or self._design_temperatures.overtemperature_c <= 0:
            return 0
        reference_overtemperature_c = DESIGN_SYSTEM_TEMPERATURES[
            DesignTemperatureSystem.SYSTEM_75_65
        ].overtemperature_c
        return table_reference_power_w * (
            self._design_temperatures.overtemperature_c / reference_overtemperature_c
        ) ** exponent

    @staticmethod
    def _calculate_distribution_weights(
        emitters: list[_PreparedEmitter],
    ) -> list[_PreparedEmitter]:
        total_reference_power = sum(e.design_reference_power_w for e in emitters)
        if total_reference_power <= 0:
            return [replace(e, distribution_weight=0.0) for e in emitters]

        weighted_distribution = [
            (e.design_reference_power_w / total_reference_power) ** DISTRIBUTION_ALPHA
            for e in emitters
        ]
        weighted_sum = sum(weighted_distribution)

        return [
            replace(e, distribution_weight=weighted_distribution[i] / weighted_sum)
            for i, e in enumerate(emitters)
        ]

    def calculate_available_heating_power_w(
        self, room_temperature_c: float, flow_temperature_c: float | None = None
    ) -> float:
        total = 0.0
        for emitter in self._emitters:
            effective_flow_temperature_c = (
                flow_temperature_c
                if flow_temperature_c is not None
                else self._design_temperatures.flow_temperature_c
            )
            return_temperature_c = (
                effective_flow_temperature_c - self._design_temperatures.spread_c
            )
            current_mean_temperature_c = (
                effective_flow_temperature_c + return_temperature_c
            ) / 2
            current_overtemperature_c = current_mean_temperature_c - room_temperature_c

            if current_overtemperature_c <= 0:
                continue

            total += emitter.design_reference_power_w * (
                current_overtemperature_c / self._design_temperatures.overtemperature_c
            ) ** emitter.exponent

        return round_to_step(total, 0.01)

    def calculate_target_temperatures(self, demand_pct: float) -> list[float]:
        demand = demand_pct / 100
        return [self._calculate_target_temperature(e, demand) for e in self._emitters]

    @staticmethod
    def _calculate_target_temperature(emitter: _PreparedEmitter, demand: float) -> float:
        trv = emitter.trv
        if demand < 0.05:
            return trv.min_target_temperature_c

        weighted_demand = clamp(demand * emitter.distribution_weight, 0, 1)
        effective_demand = weighted_demand ** (1 / emitter.exponent)

        min_active_target_temperature = max(
            MIN_ACTIVE_TRV_TEMPERATURE_C, trv.min_target_temperature_c
        )
        target_temperature = min_active_target_temperature + effective_demand * (
            trv.max_target_temperature_c - min_active_target_temperature
        )

        return clamp(
            round_to_step(target_temperature, trv.target_temperature_step_c),
            trv.min_target_temperature_c,
            trv.max_target_temperature_c,
        )

    def calculate_recommended_flow_temperature_c(
        self, required_heating_power_w: float, target_room_temperature_c: float
    ) -> float | None:
        if required_heating_power_w <= 0:
            return 0.0

        low, high = 20.0, 75.0
        optimal_flow = high

        if (
            self.calculate_available_heating_power_w(target_room_temperature_c, high)
            < required_heating_power_w
        ):
            return high

        iterations = 0
        while high - low > 0.1:
            mid = (low + high) / 2
            available_power_w = self.calculate_available_heating_power_w(
                target_room_temperature_c, mid
            )
            if available_power_w >= required_heating_power_w:
                optimal_flow = mid
                high = mid
            else:
                low = mid

            iterations += 1
            if iterations > INFINITE_LOOP_GUARD:
                break

        return ceil(optimal_flow / 0.5) * 0.5
