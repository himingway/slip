from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParamInfo:
    name: str
    type_: str
    default: str | None
    is_local: bool = False


@dataclass(frozen=True)
class PortInfo:
    name: str
    direction: str
    width: str | None


@dataclass(frozen=True)
class ModuleInfo:
    params: tuple[ParamInfo, ...]
    ports: tuple[PortInfo, ...]


def reflect_module(sv_path: Path, module_name: str) -> ModuleInfo:
    """Reflect a SystemVerilog module's ports and params using pyslang."""
    from pyslang import SyntaxTree, Compilation

    source = sv_path.read_text()
    tree = SyntaxTree.fromText(source, str(sv_path))
    comp = Compilation()
    comp.addSyntaxTree(tree)
    root = comp.getRoot()

    top = root.lookupName(module_name)
    if top is None:
        raise ValueError(f"module '{module_name}' not found in {sv_path}")

    body = top.body

    # Collect params
    params: list[ParamInfo] = []
    for sym in body:
        from pyslang import SymbolKind
        if sym.kind == SymbolKind.Parameter:
            val = str(sym.value) if hasattr(sym, 'value') and sym.value else None
            is_local = getattr(sym, 'isLocalParam', False)
            params.append(ParamInfo(sym.name, "int", val, is_local=is_local))

    # Collect ports
    ports: list[PortInfo] = []
    for port in body.portList:
        direction = str(port.direction).lower() if hasattr(port, 'direction') else "input"
        if "inout" in direction:
            direction = "inout"
        elif "out" in direction:
            direction = "output"
        else:
            direction = "input"
        width = None
        if hasattr(port, 'type') and port.type:
            t = port.type
            if hasattr(t, 'bitWidth') and t.bitWidth > 1:
                bw = t.bitWidth
                width = f"[{bw - 1}:0]"
        ports.append(PortInfo(port.name, direction, width))

    return ModuleInfo(params=tuple(params), ports=tuple(ports))
