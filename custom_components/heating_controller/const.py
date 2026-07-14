"""Constants and shared enums for the Heating Controller integration."""

from __future__ import annotations

from enum import StrEnum

DOMAIN = "heating_controller"

DEFAULT_COMFORT_TEMPERATURE_C = 22.0
DEFAULT_ECO_TEMPERATURE_OFFSET_C = -2.0


class HeatMode(StrEnum):
    """The four heat modes selectable via select.heating_mode_<room>."""

    COMFORT = "comfort"
    ECO = "eco"
    BOOST = "boost"
    FROST_PROTECTION = "frost_protection"


class HeatEmitterType(StrEnum):
    """Type of heat emitter a TRV controls."""

    PANEL = "panel"
    TOWEL = "towel"


class PanelRadiatorType(StrEnum):
    """EN 442 panel radiator type numbers."""

    TYPE_10 = "10"
    TYPE_11 = "11"
    TYPE_21 = "21"
    TYPE_22 = "22"
    TYPE_33 = "33"


class DesignTemperatureSystem(StrEnum):
    """Radiator design flow/return temperature system."""

    SYSTEM_75_65 = "system_75_65"
    SYSTEM_70_55 = "system_70_55"
    SYSTEM_55_45 = "system_55_45"
    SYSTEM_45_35 = "system_45_35"
    SYSTEM_35_30 = "system_35_30"


class RoomTemperatureStrategy(StrEnum):
    """Which source was used to determine the room temperature this cycle."""

    ROOM_SENSOR = "room_sensor"
    TRV_AVERAGE = "trv_average"


class LearningStatus(StrEnum):
    """Outcome of the most recent MPC learning cycle."""

    LEARNED = "learned"
    DISABLED = "disabled"
    SKIPPED = "skipped"
    SUPPRESSED = "suppressed"
    WAITING_INTERVAL = "waiting_interval"
