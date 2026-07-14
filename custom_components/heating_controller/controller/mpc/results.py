"""Result/error types shared by sensors.py and controller.py."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ...const import RoomTemperatureStrategy
from .types import RoomModelLearningState


class RoomMpcErrorCode(StrEnum):
    MISSING_ROOM_TEMPERATURE = "missing_room_temperature"
    MISSING_OUTDOOR_TEMPERATURE = "missing_outdoor_temperature"
    NO_HEATING_POWER_AVAILABLE = "no_heating_power_available"


@dataclass
class RoomMpcError:
    code: RoomMpcErrorCode
    message: str
    details: dict[str, object] | None = None


@dataclass
class RoomTemperatureResult:
    valid: bool
    temperature_c: float | None = None
    used_strategy: RoomTemperatureStrategy | None = None
    trv_temperatures: list[float | None] | None = None
    error: RoomMpcError | None = None


@dataclass
class RoomMpcInput:
    now_ts: float
    target_temp_c: float
    room_temp_c: float
    outdoor_temp_c: float
    used_room_sensor_strategy: RoomTemperatureStrategy
    trv_temperatures: list[float | None]
    flow_temp_c: float | None = None


@dataclass
class RoomMpcInputResult:
    valid: bool
    input: RoomMpcInput | None = None
    error: RoomMpcError | None = None


@dataclass
class RoomMpcResult:
    trv_targets: list[float]
    input: RoomMpcInput
    demand_pct: float
    requested_heating_power_w: float
    available_heating_power_w: float
    recommended_flow_temperature_c: float | None
    learning_state: RoomModelLearningState | None = None

    def get_mpc_in_attributes(self) -> dict[str, object]:
        attributes: dict[str, object] = {
            "mpc_in_target_temp_c": self.input.target_temp_c,
            "mpc_in_room_temp_c": self.input.room_temp_c,
            "mpc_in_room_sensor_strategy": self.input.used_room_sensor_strategy,
            "mpc_in_outdoor_temp_c": self.input.outdoor_temp_c,
            "mpc_in_flow_temp_c": self.input.flow_temp_c,
        }
        for index, trv_temp in enumerate(self.input.trv_temperatures):
            attributes[f"mpc_in_trv{index + 1}_temp_c"] = trv_temp
        return attributes

    def get_mpc_out_attributes(self) -> dict[str, object]:
        attributes: dict[str, object] = {
            "mpc_out_demand_pct": self.demand_pct,
            "mpc_out_requested_heating_power_w": self.requested_heating_power_w,
            "mpc_out_available_heating_power_w": self.available_heating_power_w,
            "mpc_out_recommended_flow_temperature_c": self.recommended_flow_temperature_c,
        }
        for index, trv_target in enumerate(self.trv_targets):
            attributes[f"mpc_out_trv{index + 1}_target_temp_c"] = trv_target
        return attributes

    def get_mpc_learning_attributes(self) -> dict[str, object]:
        if self.learning_state is None:
            return {}
        return {
            "mpc_learning_status": self.learning_state.status,
            "mpc_learning_ua_factor": self.learning_state.learned_factors.ua_factor,
            "mpc_learning_capacity_factor": (
                self.learning_state.learned_factors.capacity_factor
            ),
            "mpc_learning_prediction": self.learning_state.prediction,
            "mpc_learning_applied_heating_power_w": (
                self.learning_state.applied_heating_power_w
            ),
        }

    def get_mpc_additional_attributes(self) -> dict[str, object]:
        attributes: dict[str, object] = {}
        attributes.update(self.get_mpc_in_attributes())
        attributes.update(self.get_mpc_out_attributes())
        attributes.update(self.get_mpc_learning_attributes())
        return attributes
