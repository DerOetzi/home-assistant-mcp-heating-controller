"""Freshness + outlier filtering for MPC temperature inputs.

The room temperature is determined by a fixed rule: use the configured room
sensor if it is fresh, otherwise fall back to the arithmetic mean of the
fresh TRV temperatures.
"""

from __future__ import annotations

import time

from ...const import RoomTemperatureStrategy
from .results import (
    RoomMpcError,
    RoomMpcErrorCode,
    RoomMpcInput,
    RoomMpcInputResult,
    RoomTemperatureResult,
)
from .types import TrvConfig

SENSOR_OUTLIER_MIN_SAMPLES = 3
SENSOR_OUTLIER_MAX_DELTA_C = 5.0
SENSOR_OUTLIER_WINDOW_SIZE = 10
SENSOR_OUTLIER_DRIFT_REPEAT_COUNT = 3
SENSOR_OUTLIER_DRIFT_MATCH_DELTA_C = 1.0
SENSOR_OUTLIER_DRIFT_MAX_INTERVAL_S = 5 * 60

TRV_MAX_COUNT = 3


class SensorEntry:
    """A single temperature input with a freshness window and outlier filter."""

    def __init__(self, max_age_s: float, outlier_filter_enabled: bool) -> None:
        self._value: float | None = None
        self._timestamp = 0.0
        self._max_age_s = max_age_s
        self._outlier_filter_enabled = outlier_filter_enabled
        self._accepted_values: list[float] = []
        self._pending_outlier_value: float | None = None
        self._pending_outlier_count = 0
        self._pending_outlier_last_ts = 0.0

    def set_value(self, new_value: float | None) -> None:
        if self._should_ignore_value(new_value):
            return
        self._store_value(new_value)

    def get_fresh_value(self, now_ts: float | None = None) -> float | None:
        now_ts = time.time() if now_ts is None else now_ts
        return self._value if self._is_fresh(now_ts) else None

    def _is_fresh(self, now_ts: float) -> bool:
        if self._value is None:
            return False
        if self._max_age_s <= 0:
            return True
        return now_ts - self._timestamp <= self._max_age_s

    @property
    def raw_value(self) -> float | None:
        return self._value

    def _should_ignore_value(self, new_value: float | None) -> bool:
        if new_value is None or self._value is None:
            return False
        if not self._is_outlier(new_value):
            return False
        if self._should_accept_outlier_as_drift(new_value, time.time()):
            return False
        return True

    def _is_outlier(self, new_value: float) -> bool:
        if not self._outlier_filter_enabled:
            return False
        if len(self._accepted_values) < SENSOR_OUTLIER_MIN_SAMPLES:
            return False
        baseline = self._calculate_median(self._accepted_values)
        return abs(new_value - baseline) > SENSOR_OUTLIER_MAX_DELTA_C

    @staticmethod
    def _calculate_median(values: list[float]) -> float:
        sorted_values = sorted(values)
        middle = len(sorted_values) // 2
        if len(sorted_values) % 2 == 0:
            return (sorted_values[middle - 1] + sorted_values[middle]) / 2
        return sorted_values[middle]

    def _store_value(self, new_value: float | None) -> None:
        self._value = new_value
        if new_value is None:
            return

        self._reset_outlier_drift_candidate()
        self._timestamp = time.time()
        self._accepted_values.append(new_value)
        self._trim_accepted_values()

    def _should_accept_outlier_as_drift(self, new_value: float, now_ts: float) -> bool:
        candidate_expired = (
            self._pending_outlier_last_ts > 0
            and now_ts - self._pending_outlier_last_ts
            > SENSOR_OUTLIER_DRIFT_MAX_INTERVAL_S
        )

        if (
            self._pending_outlier_value is None
            or candidate_expired
            or abs(new_value - self._pending_outlier_value)
            > SENSOR_OUTLIER_DRIFT_MATCH_DELTA_C
        ):
            self._pending_outlier_value = new_value
            self._pending_outlier_count = 1
            self._pending_outlier_last_ts = now_ts
            return False

        self._pending_outlier_count += 1
        self._pending_outlier_last_ts = now_ts

        previous_count = self._pending_outlier_count - 1
        self._pending_outlier_value = (
            self._pending_outlier_value * previous_count + new_value
        ) / self._pending_outlier_count

        return self._pending_outlier_count >= SENSOR_OUTLIER_DRIFT_REPEAT_COUNT

    def _reset_outlier_drift_candidate(self) -> None:
        self._pending_outlier_value = None
        self._pending_outlier_count = 0
        self._pending_outlier_last_ts = 0.0

    def _trim_accepted_values(self) -> None:
        overflow = len(self._accepted_values) - SENSOR_OUTLIER_WINDOW_SIZE
        if overflow > 0:
            del self._accepted_values[:overflow]


class RoomMpcSensors:
    """Freshness- and outlier-filtered temperature inputs for one room."""

    def __init__(self, trvs: list[TrvConfig], max_sensor_age_s: float) -> None:
        max_age_s = max(0.0, max_sensor_age_s)

        self._trv_temperatures = [
            SensorEntry(max_age_s, outlier_filter_enabled=True)
            for _ in trvs[:TRV_MAX_COUNT]
        ]
        self._room_sensor = SensorEntry(max_age_s, outlier_filter_enabled=True)
        self._outdoor_temperature_sensor = SensorEntry(
            max_age_s, outlier_filter_enabled=True
        )
        self._flow_temperature_sensor = SensorEntry(
            max_age_s, outlier_filter_enabled=True
        )

    def set_trv_temperature(self, index: int, value: float | None) -> None:
        if index >= len(self._trv_temperatures):
            return
        self._trv_temperatures[index].set_value(value)

    def set_room_sensor_temperature(self, value: float | None) -> None:
        self._room_sensor.set_value(value)

    def set_outdoor_temperature(self, value: float | None) -> None:
        self._outdoor_temperature_sensor.set_value(value)

    def set_flow_temperature(self, value: float | None) -> None:
        self._flow_temperature_sensor.set_value(value)

    def get_room_temperature(self, now_ts: float | None = None) -> RoomTemperatureResult:
        now_ts = time.time() if now_ts is None else now_ts
        trv_temperatures = [
            entry.get_fresh_value(now_ts) for entry in self._trv_temperatures
        ]
        room_sensor_temperature = self._room_sensor.get_fresh_value(now_ts)

        if room_sensor_temperature is not None:
            return RoomTemperatureResult(
                valid=True,
                temperature_c=room_sensor_temperature,
                used_strategy=RoomTemperatureStrategy.ROOM_SENSOR,
                trv_temperatures=trv_temperatures,
            )

        valid_trv_temperatures = [t for t in trv_temperatures if t is not None]
        if not valid_trv_temperatures:
            return RoomTemperatureResult(
                valid=False,
                error=RoomMpcError(
                    code=RoomMpcErrorCode.MISSING_ROOM_TEMPERATURE,
                    message="Missing room sensor and TRV temperatures",
                    details={"trv_temperatures": trv_temperatures},
                ),
            )

        average_temperature = sum(valid_trv_temperatures) / len(valid_trv_temperatures)
        return RoomTemperatureResult(
            valid=True,
            temperature_c=average_temperature,
            used_strategy=RoomTemperatureStrategy.TRV_AVERAGE,
            trv_temperatures=trv_temperatures,
        )

    def create_input(
        self, target_temp_c: float, now_ts: float | None = None
    ) -> RoomMpcInputResult:
        now_ts = time.time() if now_ts is None else now_ts
        room_temperature_result = self.get_room_temperature(now_ts)
        outdoor_temp_c = self._outdoor_temperature_sensor.get_fresh_value(now_ts)

        if not room_temperature_result.valid:
            return RoomMpcInputResult(valid=False, error=room_temperature_result.error)

        if outdoor_temp_c is None:
            return RoomMpcInputResult(
                valid=False,
                error=RoomMpcError(
                    code=RoomMpcErrorCode.MISSING_OUTDOOR_TEMPERATURE,
                    message="Missing outdoor temperature",
                ),
            )

        return RoomMpcInputResult(
            valid=True,
            input=RoomMpcInput(
                now_ts=now_ts,
                target_temp_c=target_temp_c,
                room_temp_c=room_temperature_result.temperature_c,
                outdoor_temp_c=outdoor_temp_c,
                flow_temp_c=self._flow_temperature_sensor.get_fresh_value(now_ts),
                used_room_sensor_strategy=room_temperature_result.used_strategy,
                trv_temperatures=room_temperature_result.trv_temperatures,
            ),
        )
