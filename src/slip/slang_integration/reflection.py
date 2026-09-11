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


def _direction_of(port) -> str:
    direction = str(port.direction).lower() if hasattr(port, 'direction') else "input"
    if "inout" in direction:
        return "inout"
    if "out" in direction:
        return "output"
    return "input"


def _width_of(port) -> str | None:
    """Reflected width text like ``[7:0]``, or None for 1-bit/unknown.

    Only little-endian ``[N-1:0]`` ranges are reconstructed; a port
    declared with a non-standard range (e.g. ``[0:7]``) keeps its bit
    count here, which is what width inference needs.
    """
    if hasattr(port, 'type') and port.type:
        t = port.type
        if hasattr(t, 'bitWidth') and t.bitWidth > 1:
            bw = t.bitWidth
            return f"[{bw - 1}:0]"
    return None


def _reflect_body(body) -> ModuleInfo:
    """Extract params and ports from a pyslang module body symbol."""
    from pyslang import SymbolKind

    params: list[ParamInfo] = []
    for sym in body:
        if sym.kind == SymbolKind.Parameter:
            # `sym.value` of 0 is falsy — do not treat it as missing
            val = str(sym.value) if getattr(sym, 'value', None) is not None else None
            is_local = getattr(sym, 'isLocalParam', False)
            params.append(ParamInfo(sym.name, "int", val, is_local=is_local))

    ports: list[PortInfo] = [
        PortInfo(port.name, _direction_of(port), _width_of(port))
        for port in body.portList
    ]
    return ModuleInfo(params=tuple(params), ports=tuple(ports))


def reflect_module(sv_path: Path, module_name: str) -> ModuleInfo:
    """Reflect a SystemVerilog module's ports and params using pyslang."""
    from pyslang import SyntaxTree, Compilation

    source = sv_path.read_text(encoding="utf-8")
    tree = SyntaxTree.fromText(source, str(sv_path))
    comp = Compilation()
    comp.addSyntaxTree(tree)
    root = comp.getRoot()

    top = root.lookupName(module_name)
    if top is None:
        raise ValueError(f"module '{module_name}' not found in {sv_path}")

    return _reflect_body(top.body)
