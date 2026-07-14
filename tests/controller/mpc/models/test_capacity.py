from heating_controller.controller.mpc.models.capacity import (
    MAX_LEARNED_CAPACITY_FACTOR,
    MIN_LEARNED_CAPACITY_FACTOR,
    ThermalCapacityModel,
)
from heating_controller.controller.mpc.types import RoomThermalConfig


def test_base_capacity_from_heat_load():
    model = ThermalCapacityModel(RoomThermalConfig(room_heat_load_w=1000))
    assert model.effective_capacity_j_per_k == 1000 * 7200


def test_predict_temperature_change_scales_with_power_and_duration():
    model = ThermalCapacityModel(RoomThermalConfig(room_heat_load_w=1000))
    delta = model.predict_temperature_change_c(
        net_heating_power_w=1000 * 7200, duration_seconds=1
    )
    assert delta == 1.0


def test_calculate_required_energy_for_temperature_rise():
    model = ThermalCapacityModel(RoomThermalConfig(room_heat_load_w=1000))
    energy = model.calculate_required_energy_j(
        current_temperature_c=18, target_temperature_c=20
    )
    assert energy == 2 * 1000 * 7200


def test_learned_capacity_factor_is_clamped():
    model = ThermalCapacityModel(RoomThermalConfig())

    model.learned_capacity_factor = 100
    assert model.learned_capacity_factor == MAX_LEARNED_CAPACITY_FACTOR

    model.learned_capacity_factor = -5
    assert model.learned_capacity_factor == MIN_LEARNED_CAPACITY_FACTOR
