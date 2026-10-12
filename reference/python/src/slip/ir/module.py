from dataclasses import dataclass
from typing import TYPE_CHECKING

from slip.ir.assignment import HDLAssignment
from slip.ir.instance import HDLInstance
from slip.ir.logic_block import LogicBlock
from slip.ir.port import HDLPort
from slip.ir.signal import HDLSignal

if TYPE_CHECKING:
    from slip.slang_integration.ip_scanner import IPIndex


@dataclass(frozen=True)
class HDLParam:
    name: str
    default: str  # SV expression text


@dataclass(frozen=True)
class HDLModule:
    name: str
    params: tuple[HDLParam, ...] = ()
    localparams: tuple[HDLParam, ...] = ()
    ports: tuple[HDLPort, ...] = ()
    signals: tuple[HDLSignal, ...] = ()
    assigns: tuple[HDLAssignment, ...] = ()
    logic_blocks: tuple[LogicBlock, ...] = ()
    instances: tuple[HDLInstance, ...] = ()
    frozen_params: tuple[tuple[str, int], ...] = ()  # (compile-time param, value)


class HDLDesign(list[HDLModule]):
    """Analyzed modules together with the IP source context used to resolve them.

    This remains a list for compatibility with existing API clients. Keeping
    the parsed IP tree avoids reparsing with different preprocessor settings
    when the generator validates the complete design.
    """

    def __init__(self, modules, ip_index: "IPIndex", *, strict: bool = False):
        super().__init__(modules)
        self.ip_index = ip_index
        self.strict = strict
