"""Dock operation policy based on the dock's own capabilities and states."""

from dataclasses import dataclass, field

from .actions import Command
from .capabilities import DockCapabilities


@dataclass(frozen=True)
class DockOperation:
    capability: str
    component: str
    ready_states: frozenset[int]
    result_states: frozenset[int]
    running_states: frozenset[int] = frozenset()


OPERATIONS = {
    Command.EMPTY_BIN: DockOperation(
        "evacuation", "evacuation", frozenset({301, 303}), frozenset({302, 303}), frozenset({302})
    ),
    Command.REFILL: DockOperation(
        "manual_refill",
        "refill",
        frozenset({401, 404}),
        frozenset({402, 403, 404}),
        frozenset({402, 403}),
    ),
    Command.WASH_MOP: DockOperation(
        "wash", "pad_wash", frozenset({601, 603, 608}), frozenset({602, 603}), frozenset({602})
    ),
    Command.DRY_MOP: DockOperation(
        "dry",
        "pad_dry",
        frozenset({701, 703, 704, 705, 706}),
        frozenset({702, 703}),
        frozenset({702}),
    ),
    Command.STOP_DRYING: DockOperation("dry", "pad_dry", frozenset({702}), frozenset({701, 706})),
}

ACTIVE_STATES = frozenset({302, 304, 402, 403, 602, 607, 702})
UPDATING_STATES = frozenset({305, 406, 606, 707})
DOCK_FIELDS = {
    "evacuation": ("evacuation_state", 350, 400),
    "refill": ("refill_state", 449, 500),
    "pad_wash": ("pad_wash_state", 649, 700),
    "pad_dry": ("pad_dry_state", 749, 800),
}
DOCK_COMPONENT_CAPABILITIES = {
    "evacuation": "evacuation",
    "refill": "refill",
    "pad_wash": "wash",
    "pad_dry": "dry",
}


def component_fault(component: str, status: int | None) -> bool:
    _, lower, upper = DOCK_FIELDS[component]
    return status is not None and lower <= status < upper


@dataclass(frozen=True)
class DockSnapshot:
    capabilities: DockCapabilities = field(default_factory=DockCapabilities)
    evacuation: int | None = None
    refill: int | None = None
    pad_wash: int | None = None
    pad_dry: int | None = None
    fault: int | None = None
    pad_attached: bool | None = None
    tank_present: bool | None = None

    def supports(self, operation: DockOperation) -> bool:
        return (
            self.capabilities.recognized is True
            and getattr(self.capabilities, operation.capability) is True
        )

    def status(self, operation: DockOperation) -> int | None:
        return getattr(self, operation.component)

    def _applicable_status(self, source: str) -> int | None:
        if getattr(self.capabilities, DOCK_COMPONENT_CAPABILITIES[source]) is False:
            return None
        return getattr(self, source)

    @property
    def component_states(self) -> tuple[int | None, ...]:
        return tuple(self._applicable_status(source) for source in DOCK_FIELDS)

    @property
    def wet_cleaning_blocked(self) -> bool:
        refill = self._applicable_status("refill")
        wash = self._applicable_status("pad_wash")
        if self.capabilities.wash is not False and wash is None:
            wash = self.refill
        return (
            bool(self.fault)
            or component_fault("refill", refill)
            or component_fault("pad_wash", wash)
            or bool(UPDATING_STATES.intersection(self.component_states))
        )

    def allows(self, command: Command, operation: DockOperation) -> bool:
        if self.status(operation) not in operation.ready_states:
            return False
        if command is Command.STOP_DRYING:
            return True
        if self.fault != 0 or (ACTIVE_STATES | UPDATING_STATES).intersection(self.component_states):
            return False
        if command in {Command.WASH_MOP, Command.DRY_MOP}:
            return self.pad_attached is True
        return command is not Command.REFILL or self.tank_present is True
