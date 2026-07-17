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


def test_compute_returns_zero_result_instead_of_error_when_no_heating_power_available():
    # room already warmer than the emitter's mean temperature at this flow
    # temp (e.g. summer, heating switched off) -- a normal, valid state, not
    # an error: demand/power/flow-temperature should read 0, not "unknown".
    controller = make_controller()
    controller.set_room_sensor_temperature(26.9)
    controller.set_outdoor_temperature(26.2)
    controller.set_flow_temperature(27.0)

    result = controller.compute(target_temperature_c=8.0)

    assert result.valid is True
    assert result.result.demand_pct == 0
    assert result.result.requested_heating_power_w == 0
    assert result.result.recommended_flow_temperature_c == 0


def test_recommended_flow_floored_at_heat_loss_when_current_flow_too_cold():
    # Below target, but the current flow is too cold to extract anything right
    # now (available power 0). The recommended flow must still report the flow
    # needed to hold the target (floored at the heat loss at target), not 0.
    controller = make_controller()
    controller.set_room_sensor_temperature(19.0)
    controller.set_outdoor_temperature(-5.0)
    controller.set_flow_temperature(20.0)

    result = controller.compute(target_temperature_c=22.0)

    assert result.valid
    assert result.result.available_heating_power_w == 0
    assert result.result.recommended_flow_temperature_c > 22.0


def test_recommended_flow_is_the_hold_flow_independent_of_current_room_temp():
    # The floored (hold-the-target) flow is evaluated at the target operating
    # point, so it depends only on (target, outdoor) -- two rooms at different
    # current temperatures but the same target/outdoor get the same flow.
    colder = make_controller()
    colder.set_room_sensor_temperature(18.0)
    colder.set_outdoor_temperature(-5.0)
    colder.set_flow_temperature(20.0)
    colder_result = colder.compute(target_temperature_c=22.0)

    warmer = make_controller()
    warmer.set_room_sensor_temperature(21.0)
    warmer.set_outdoor_temperature(-5.0)
    warmer.set_flow_temperature(20.0)
    warmer_result = warmer.compute(target_temperature_c=22.0)

    assert colder_result.valid and warmer_result.valid
    assert (
        colder_result.result.recommended_flow_temperature_c
        == warmer_result.result.recommended_flow_temperature_c
    )


def test_recommended_flow_zero_when_ambient_alone_holds_target():
    # Outdoor warmer than the target: heat loss at target is non-positive, so
    # no heat-source flow is required to hold the target.
    controller = make_controller()
    controller.set_room_sensor_temperature(19.0)
    controller.set_outdoor_temperature(24.0)
    controller.set_flow_temperature(20.0)

    result = controller.compute(target_temperature_c=22.0)

    assert result.valid
    assert result.result.recommended_flow_temperature_c == 0


def test_recommended_flow_zero_while_room_coasts_above_target_and_outdoor():
    # Regression (live): room well above target due to solar gain, outdoor
    # mild but still below target (so heat_loss(target, outdoor) alone would
    # be > 0). The room is not yet losing the buffer below target -- it is
    # coasting towards outdoor, not towards a heating need -- so the
    # recommended flow must read 0, not the steady-state hold flow.
    controller = make_controller()
    controller.set_room_sensor_temperature(27.5)
    controller.set_outdoor_temperature(21.1)
    controller.set_flow_temperature(26.0)

    result = controller.compute(target_temperature_c=23.0)

    assert result.valid
    assert result.result.recommended_flow_temperature_c == 0


def test_recommended_flow_resumes_once_room_drops_to_target_while_above_outdoor():
    # Same target/outdoor as above, but the room has now cooled down exactly
    # to target while still above outdoor -- the buffer is used up, so the
    # hold flow must be reported again (not the coasting zero).
    controller = make_controller()
    controller.set_room_sensor_temperature(23.0)
    controller.set_outdoor_temperature(21.1)
    controller.set_flow_temperature(26.0)

    result = controller.compute(target_temperature_c=23.0)

    assert result.valid
    assert result.result.recommended_flow_temperature_c > 0


def test_recommended_flow_combines_hold_and_requested_branches_independently():
    # Regression: hold_power_w (evaluated at target) and requested_heating_power_w
    # (evaluated at the actual, much colder room) must each be converted to a
    # flow using their OWN reference and then maximised -- picking a single
    # power+reference pair by "whichever power is larger" is wrong, because the
    # emitter's power/flow relationship depends heavily on the reference room
    # temperature: converting the (larger) requested power at the cold actual
    # room (5C) alone yields a much lower flow than converting the (smaller)
    # hold power at the warmer target (22C) -- if only the larger-power branch
    # were kept, the flow actually needed to hold the target would be
    # under-reported.
    controller = make_controller()
    controller.set_room_sensor_temperature(5.0)
    controller.set_outdoor_temperature(18.0)
    controller.set_flow_temperature(45.0)

    result = controller.compute(target_temperature_c=22.0)

    assert result.valid
    assert result.result.requested_heating_power_w > 0
    # The hold-branch flow (~34.5C, hold_power ~150W at target=22) must win
    # even though requested_heating_power_w (~247W) is larger in magnitude,
    # because it is evaluated at the much colder actual room (5C) where far
    # less flow suffices for that power.
    assert result.result.recommended_flow_temperature_c >= 34.0


def test_enable_learning_and_run_learning_cycle_does_not_raise():
    controller = make_controller()
    controller.enable_learning()
    controller.set_room_sensor_temperature(19.0)
    controller.set_outdoor_temperature(-5.0)
    controller.set_flow_temperature(45.0)
    controller.compute(target_temperature_c=21.0)

    controller.run_learning_cycle()
    controller.disable_learning()
