"""Shared data types for the MPC (grey-box thermal model) subsystem."""

from __future__ import annotations

from dataclasses import dataclass

from ...const import (
    DesignTemperatureSystem,
    HeatEmitterType,
    LearningStatus,
    PanelRadiatorType,
)


@dataclass
class TrvConfig:
    """One TRV/heat-emitter configured for a room."""

    name: str
    emitter_type: HeatEmitterType = HeatEmitterType.PANEL

    min_target_temperature_c: float = 5.0
    max_target_temperature_c: float = 30.0
    target_temperature_step_c: float = 0.5

    # Panel radiator properties
    radiator_type: PanelRadiatorType | None = PanelRadiatorType.TYPE_22
    width_mm: float | None = 1000
    height_mm: float | None = 600

    # Towel radiator properties
    nominal_power_w: float | None = None


@dataclass
class RoomThermalConfig:
    """Design-point parameters used to derive the room's grey-box model."""

    design_indoor_temperature_c: float = 20.0
    design_outdoor_temperature_c: float = -12.0
    design_temperature_system: DesignTemperatureSystem = (
        DesignTemperatureSystem.SYSTEM_55_45
    )
    room_heat_load_w: float = 1000.0


@dataclass
class LearningFactors:
    ua_factor: float = 1.0
    capacity_factor: float = 1.0


@dataclass
class RoomModelPrediction:
    predicted_temp_c: float
    actual_temp_c: float
    predicted_delta_c: float
    actual_delta_c: float
    model_error_c: float
    timestamp: float


@dataclass
class RoomModelLearningState:
    status: LearningStatus
    learned_factors: LearningFactors
    prediction: RoomModelPrediction | None = None
    applied_heating_power_w: float | None = None
