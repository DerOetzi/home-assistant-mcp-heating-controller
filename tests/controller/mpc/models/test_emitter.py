from heating_controller.const import (
    DesignTemperatureSystem,
    HeatEmitterType,
    PanelRadiatorType,
)
from heating_controller.controller.mpc.models.emitter import HeatEmitterModel
from heating_controller.controller.mpc.types import RoomThermalConfig, TrvConfig


def make_model(trvs, design_temperature_system=DesignTemperatureSystem.SYSTEM_55_45):
    return HeatEmitterModel(
        RoomThermalConfig(design_temperature_system=design_temperature_system), trvs
    )


def test_available_power_is_zero_when_room_at_or_above_mean_temperature():
    model = make_model([TrvConfig(name="trv1")])
    # design system 55/45 has a mean temperature of 50C; room at 50C -> no delta
    assert model.calculate_available_heating_power_w(50, flow_temperature_c=55) == 0


def test_available_power_increases_with_lower_room_temperature():
    model = make_model([TrvConfig(name="trv1")])
    power_at_20 = model.calculate_available_heating_power_w(20, flow_temperature_c=55)
    power_at_10 = model.calculate_available_heating_power_w(10, flow_temperature_c=55)
    assert power_at_10 > power_at_20 > 0


def test_target_temperature_at_zero_demand_is_min_target():
    model = make_model(
        [TrvConfig(name="trv1", min_target_temperature_c=6, max_target_temperature_c=28)]
    )
    assert model.calculate_target_temperatures(0) == [6]


def test_target_temperature_at_full_demand_is_max_target():
    model = make_model(
        [TrvConfig(name="trv1", min_target_temperature_c=6, max_target_temperature_c=28)]
    )
    assert model.calculate_target_temperatures(100) == [28]


def test_two_trvs_split_demand_by_distribution_weight():
    big = TrvConfig(
        name="big",
        radiator_type=PanelRadiatorType.TYPE_22,
        width_mm=1400,
        height_mm=600,
    )
    small = TrvConfig(
        name="small",
        radiator_type=PanelRadiatorType.TYPE_22,
        width_mm=500,
        height_mm=600,
    )
    model = make_model([big, small])
    targets = model.calculate_target_temperatures(80)
    # the larger emitter should be asked to run hotter than the smaller one
    assert targets[0] >= targets[1]


def test_towel_radiator_uses_nominal_power_w():
    model = make_model([TrvConfig(name="towel", emitter_type=HeatEmitterType.TOWEL, nominal_power_w=600)])
    power = model.calculate_available_heating_power_w(20, flow_temperature_c=55)
    assert power > 0


def test_recommended_flow_temperature_increases_with_required_power():
    model = make_model([TrvConfig(name="trv1")])
    low_power_flow = model.calculate_recommended_flow_temperature_c(200, 20)
    high_power_flow = model.calculate_recommended_flow_temperature_c(800, 20)
    assert high_power_flow > low_power_flow


def test_recommended_flow_temperature_zero_when_no_power_required():
    model = make_model([TrvConfig(name="trv1")])
    assert model.calculate_recommended_flow_temperature_c(0, 20) == 0


def test_recommended_flow_uses_part_load_spread():
    """At part load the spread collapses, so less flow is needed than the
    design spread implies. Pinning this against an explicit design-spread
    calculation keeps the two directions from silently converging again."""
    model = HeatEmitterModel(
        RoomThermalConfig(room_heat_load_w=1200), [TrvConfig(name="trv1")]
    )
    required_w = 300  # a quarter of the design load -> spread 2.5 K, not 10 K

    flow_c = model.calculate_recommended_flow_temperature_c(required_w, 20)

    assert model.calculate_available_heating_power_w(20, flow_c, 2.5) >= required_w
    # With the design spread the same flow would look insufficient, which is
    # what used to push the recommendation several kelvin too high.
    assert model.calculate_available_heating_power_w(20, flow_c) < required_w


def test_forward_direction_keeps_design_spread():
    """The valves-throttling direction must not inherit the part-load spread."""
    model = HeatEmitterModel(
        RoomThermalConfig(room_heat_load_w=1200), [TrvConfig(name="trv1")]
    )
    assert model.calculate_available_heating_power_w(
        20, 45
    ) == model.calculate_available_heating_power_w(20, 45, 10.0)
