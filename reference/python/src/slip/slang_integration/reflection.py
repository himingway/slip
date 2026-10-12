from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParamInfo:
    name: str
    type_: str
    default: str | None
    is_local: bool = False
    expression: str | None = None


@dataclass(frozen=True)
class PortInfo:
    name: str
    direction: str
    width: str | None
    width_expression: str | None = None
    array_dim: str | None = None
    is_signed: bool = False


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
            syntax = getattr(sym, "syntax", None)
            initializer = getattr(syntax, "initializer", None)
            expression = str(initializer.expr).strip() if initializer is not None else val
            params.append(ParamInfo(sym.name, "int", val, is_local, expression))

    ports: list[PortInfo] = []
    previous_type = None
    for port in body.portList:
        symbol = getattr(port, "internalSymbol", None)
        declarator = getattr(symbol, "syntax", None)
        declaration = getattr(declarator, "parent", None)
        header = getattr(declaration, "header", None)
        dtype = getattr(header, "dataType", None) if header is not None else getattr(declaration, "dataType", None)
        # ANSI declarations like `input logic [W-1:0] a, b` inherit a's type.
        if dtype is not None and (str(dtype).strip() or (header is not None and str(header).strip())):
            previous_type = dtype
        elif header is not None and not str(header).strip():
            dtype = previous_type
        dimensions = getattr(dtype, "dimensions", ())
        width_expression = "".join(str(d).strip() for d in dimensions) or None
        array_dim = "".join(str(d).strip() for d in getattr(declarator, "dimensions", ())) or None
        ports.append(PortInfo(
            port.name, _direction_of(port), _width_of(port),
            width_expression, array_dim, bool(port.type.isSigned),
        ))
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
