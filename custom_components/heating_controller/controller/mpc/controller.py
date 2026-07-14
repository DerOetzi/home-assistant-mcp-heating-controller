"""Brute-force demand search + rate limiting for one room.

The constructor never auto-enables learning: the HA coordinator reads the
configured heating-available entity synchronously at setup and calls
enable_learning()/disable_learning() itself based on its current state.
"""

from __future__ import annotations

from dataclasses import dataclass

from .learner import LearnerPrediction, RoomMpcModelLearner
from .math_helper import clamp, round_to_step
from .models.capacity import ThermalCapacityModel
from .models.emitter import HeatEmitterModel
from .models.loss import RoomLossModel
from .results import (
    RoomMpcError,
    RoomMpcErrorCode,
    RoomMpcInput,
    RoomMpcResult,
)
from .sensors import RoomMpcSensors
from .types import LearningFactors, RoomThermalConfig, TrvConfig

MPC_PREDICTION_HORIZON_S = 1800
MPC_SIMULATION_STEP_S = 150


@dataclass
class MpcRateLimitConfig:
    """Demand-change rate limiting to avoid TRV/valve oscillation."""

    demand_hysteresis_pct: float = 5.0
    hold_time_s: float = 300.0
    hold_override_demand_pct: float = 40.0
    max_demand_step_pct: float = 20.0


@dataclass
class _DemandPrediction:
    demand_pct: float
    predicted_temperature_c: float
    prediction_error: float


@dataclass
class RoomMpcComputeResult:
    valid: bool
    result: RoomMpcResult | None = None
    error: RoomMpcError | None = None


class RoomMpcController:
    """Per-room grey-box thermal model: demand search + rate limiting + learning."""

    def __init__(
        self,
        thermal_config: RoomThermalConfig,
        trvs: list[TrvConfig],
        rate_limit_config: MpcRateLimitConfig,
        max_sensor_age_s: float,
    ) -> None:
        self._rate_limit_config = rate_limit_config

        self._sensors = RoomMpcSensors(trvs, max_sensor_age_s)
        self._emitter_model = HeatEmitterModel(thermal_config, trvs)
        self._loss_model = RoomLossModel(thermal_config)
        self._capacity_model = ThermalCapacityModel(thermal_config)
        self._learner = RoomMpcModelLearner(self._loss_model, self._capacity_model)

        self._target_demand_pct = 0.0
        self._last_output_demand_pct = 0.0
        self._last_demand_update_ts = 0.0

    def destroy(self) -> None:
        self._learner.destroy()

    @property
    def learned_ua_factor(self) -> float:
        return self._loss_model.learned_ua_factor

    @property
    def learned_capacity_factor(self) -> float:
        return self._capacity_model.learned_capacity_factor

    def set_trv_temperature(self, index: int, value: float | None) -> None:
        self._sensors.set_trv_temperature(index, value)

    def set_room_sensor_temperature(self, value: float | None) -> None:
        self._sensors.set_room_sensor_temperature(value)

    def set_outdoor_temperature(self, value: float | None) -> None:
        self._sensors.set_outdoor_temperature(value)

    def set_flow_temperature(self, value: float | None) -> None:
        self._sensors.set_flow_temperature(value)

    def compute(self, target_temperature_c: float) -> RoomMpcComputeResult:
        input_result = self._sensors.create_input(target_temperature_c)
        if not input_result.valid:
            return RoomMpcComputeResult(valid=False, error=input_result.error)

        mpc_input = input_result.input

        available_heating_power_w = self._emitter_model.calculate_available_heating_power_w(
            mpc_input.room_temp_c, mpc_input.flow_temp_c
        )

        if available_heating_power_w <= 0:
            return RoomMpcComputeResult(
                valid=False,
                error=RoomMpcError(
                    code=RoomMpcErrorCode.NO_HEATING_POWER_AVAILABLE,
                    message=(
                        "No heating power available at current room and flow "
                        "temperatures"
                    ),
                ),
            )

        optimal_demand = self._find_optimal_demand_prediction(mpc_input)
        stabilized_demand_pct = self._apply_demand_rate_limiting(
            mpc_input, optimal_demand.demand_pct
        )

        requested_heating_power_w = round_to_step(
            available_heating_power_w * (stabilized_demand_pct / 100), 0.01
        )

        recommended_flow_temperature_c = (
            self._emitter_model.calculate_recommended_flow_temperature_c(
                requested_heating_power_w, mpc_input.room_temp_c
            )
        )

        learning_state = self._update_learning_telemetry(
            mpc_input, requested_heating_power_w, optimal_demand.predicted_temperature_c
        )

        result = RoomMpcResult(
            trv_targets=self._emitter_model.calculate_target_temperatures(
                stabilized_demand_pct
            ),
            input=mpc_input,
            demand_pct=stabilized_demand_pct,
            requested_heating_power_w=requested_heating_power_w,
            available_heating_power_w=available_heating_power_w,
            recommended_flow_temperature_c=recommended_flow_temperature_c,
            learning_state=learning_state,
        )
        return RoomMpcComputeResult(valid=True, result=result)

    def _find_optimal_demand_prediction(self, mpc_input: RoomMpcInput) -> _DemandPrediction:
        best = _DemandPrediction(
            demand_pct=0.0,
            predicted_temperature_c=mpc_input.room_temp_c,
            prediction_error=float("inf"),
        )

        demand_pct = 0
        while demand_pct <= 100:
            predicted_temperature_c = self._predict_room_temperature_c(
                mpc_input, demand_pct, MPC_PREDICTION_HORIZON_S
            )
            prediction_error = abs(mpc_input.target_temp_c - predicted_temperature_c)

            if prediction_error < best.prediction_error:
                best = _DemandPrediction(
                    demand_pct=demand_pct,
                    predicted_temperature_c=predicted_temperature_c,
                    prediction_error=prediction_error,
                )

            demand_pct += 5

        return best

    def _predict_room_temperature_c(
        self, mpc_input: RoomMpcInput, demand_pct: float, duration_s: float
    ) -> float:
        simulated_room_temperature_c = mpc_input.room_temp_c

        step_count = max(1, -(-duration_s // MPC_SIMULATION_STEP_S))  # ceil div
        step_count = int(step_count)

        for _ in range(step_count):
            available_heating_power_w = (
                self._emitter_model.calculate_available_heating_power_w(
                    simulated_room_temperature_c, mpc_input.flow_temp_c
                )
            )
            heating_power_w = available_heating_power_w * (demand_pct / 100)
            heat_loss_w = self._loss_model.calculate_heat_loss_w(
                simulated_room_temperature_c, mpc_input.outdoor_temp_c
            )
            net_heating_power_w = heating_power_w - heat_loss_w

            predicted_delta_c = self._capacity_model.predict_temperature_change_c(
                net_heating_power_w, MPC_SIMULATION_STEP_S
            )

            simulated_room_temperature_c += predicted_delta_c
            simulated_room_temperature_c = clamp(simulated_room_temperature_c, 0, 35)

            if abs(predicted_delta_c) < 0.001:
                break

        return simulated_room_temperature_c

    def _apply_demand_rate_limiting(
        self, mpc_input: RoomMpcInput, demand_pct: float
    ) -> float:
        config = self._rate_limit_config

        self._target_demand_pct = clamp(
            demand_pct,
            self._target_demand_pct - config.max_demand_step_pct,
            self._target_demand_pct + config.max_demand_step_pct,
        )

        if (
            abs(self._target_demand_pct - self._last_output_demand_pct)
            < config.demand_hysteresis_pct
        ):
            return self._last_output_demand_pct

        if (
            mpc_input.now_ts - self._last_demand_update_ts < config.hold_time_s
            and abs(self._target_demand_pct - self._last_output_demand_pct)
            < config.hold_override_demand_pct
        ):
            return self._last_output_demand_pct

        self._last_output_demand_pct = self._target_demand_pct
        self._last_demand_update_ts = mpc_input.now_ts

        return self._last_output_demand_pct

    def _update_learning_telemetry(
        self,
        mpc_input: RoomMpcInput,
        requested_heating_power_w: float,
        predicted_room_temperature_c: float,
    ):
        self._learner.append_history(mpc_input, requested_heating_power_w)
        self._learner.set_prediction(
            LearnerPrediction(
                timestamp=mpc_input.now_ts,
                predicted_room_temperature_c=predicted_room_temperature_c,
                prediction_horizon_s=MPC_PREDICTION_HORIZON_S,
            )
        )
        return self._learner.get_learning_state()

    def run_learning_cycle(self) -> None:
        """Called by the coordinator every 30 minutes."""
        self._learner.run_learning_cycle()

    def consume_persisted_learning_factors(self) -> LearningFactors | None:
        return self._learner.consume_persisted_learning_factors()

    def recalibrate_learning_factors(self, factors: LearningFactors) -> None:
        self._learner.recalibrate(factors)

    def enable_learning(self) -> None:
        self._learner.enable()

    def disable_learning(self) -> None:
        self._learner.disable()

    def suppress_learning_for_interval(self, duration_s: float) -> None:
        self._learner.suppress_for_interval(duration_s)
