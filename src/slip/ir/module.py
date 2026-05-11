from dataclasses import dataclass, field


@dataclass(frozen=True)
class HDLParam:
    name: str
    default: str  # SV expression text


@dataclass(frozen=True)
class HDLModule:
    name: str
    params: tuple = ()       # tuple[HDLParam, ...]
    localparams: tuple = ()  # tuple[HDLParam, ...]
    ports: tuple = ()        # tuple[HDLPort, ...]
    signals: tuple = ()      # tuple[HDLSignal, ...]
    assigns: tuple = ()      # tuple[HDLAssignment, ...]
    logic_blocks: tuple = () # tuple[LogicBlock, ...]
    instances: tuple = ()    # tuple[HDLInstance, ...]
