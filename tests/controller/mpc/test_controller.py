from heating_controller.controller.mpc.controller import (
    MpcRateLimitConfig,
    RoomMpcController,
)
from heating_controller.controller.mpc.results import RoomMpcErrorCode
from heating_controller.controller.mpc.types import RoomThermalConfig, TrvConfig


def make_controller(**rate_limit_overrides):
    return RoomMpcController(
        thermal_config=RoomThermalConfig(room_heat_load_w=1200),
        trvs=[TrvConfig(name="trv1")],
        rate_limit_config=MpcRateLimitConfig(**rate_limit_overrides),
        max_sensor_age_s=1800,
    )


def test_compute_fails_without_sensor_data():
    controller = make_controller()
    result = controller.compute(target_temperature_c=21.0)
    assert result.valid is False
    assert result.error.code == RoomMpcErrorCode.MISSING_ROOM_TEMPERATURE


def test_compute_returns_higher_demand_for_colder_room():
    warm = make_controller()
    warm.set_room_sensor_temperature(20.0)
    warm.set_outdoor_temperature(5.0)
    warm.set_flow_temperature(45.0)
    warm_result = warm.compute(target_temperature_c=21.0)

    cold = make_controller()
    cold.set_room_sensor_temperature(15.0)
    cold.set_outdoor_temperature(-10.0)
    cold.set_flow_temperature(45.0)
    cold_result = cold.compute(target_temperature_c=21.0)

    assert warm_result.valid and cold_result.valid
    assert cold_result.result.demand_pct >= warm_result.result.demand_pct


def test_demand_rate_limiting_caps_step_change():
    controller = make_controller(max_demand_step_pct=10, demand_hysteresis_pct=0)
    controller.set_room_sensor_temperature(10.0)
    controller.set_outdoor_temperature(-15.0)
    controller.set_flow_temperature(45.0)

    first = controller.compute(target_temperature_c=25.0)
    second = controller.compute(target_temperature_c=25.0)

    assert first.valid and second.valid
    assert abs(second.result.demand_pct - first.result.demand_pct) <= 10


def test_hysteresis_suppresses_small_demand_changes():
    controller = make_controller(demand_hysteresis_pct=50, max_demand_step_pct=100)
    controller.set_room_sensor_temperature(19.0)
    controller.set_outdoor_temperature(-5.0)
    controller.set_flow_temperature(45.0)

    first = controller.compute(target_temperature_c=20.0)
    second = controller.compute(target_temperature_c=20.5)

    assert first.result.demand_pct == second.result.demand_pct


def test_enable_learning_and_run_learning_cycle_does_not_raise():
    controller = make_controller()
    controller.enable_learning()
    controller.set_room_sensor_temperature(19.0)
    controller.set_outdoor_temperature(-5.0)
    controller.set_flow_temperature(45.0)
    controller.compute(target_temperature_c=21.0)

    controller.run_learning_cycle()
    controller.disable_learning()
