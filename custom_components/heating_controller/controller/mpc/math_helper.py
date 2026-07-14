"""Small numeric helpers shared by the MPC models."""

from __future__ import annotations


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def round_to_step(value: float, step: float) -> float:
    return round(value / step) * step
