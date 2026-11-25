"""Semantic robot actions, shared by application policy and adapters."""

from enum import StrEnum


class Command(StrEnum):
    VACUUM = "start"
    START_MAPPING = "train"
    POINT_CLEAN = "point_clean"
    RESUME = "resume"
    PAUSE = "pause"
    SKIP = "skip"
    CANCEL = "stop"
    DOCK = "dock"
    LOCATE = "find"
    REBOOT = "reset"
    EMPTY_BIN = "evac"
    REFILL = "fluidRefill"
    WASH_MOP = "washPad"
    DRY_MOP = "dryPad"
    STOP_DRYING = "stopPadDry"
