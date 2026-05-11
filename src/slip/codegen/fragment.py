from __future__ import annotations

from slip.ir import (
    HDLAssignment,
    HDLIfBlock,
    HDLInstance,
    HDLModule,
    HDLParam,
    HDLPort,
    HDLSignal,
    LogicBlock,
)


def localparam_decl(p: HDLParam) -> str:
    return f"    localparam {p.name} = {p.default};"


def module_header(mod: HDLModule) -> str:
    parts = [f"module {mod.name}"]

    # Parameters
    if mod.params:
        parts.append(" #(")
        param_lines = []
        for i, p in enumerate(mod.params):
            comma = "," if i < len(mod.params) - 1 else ""
            param_lines.append(f"    parameter {p.name} = {p.default}{comma}")
        parts.append("\n".join(param_lines))
        parts.append(")")

    # Ports
    if mod.ports:
        parts.append(" (")
        port_lines = []
        for i, p in enumerate(mod.ports):
            comma = "," if i < len(mod.ports) - 1 else ""
            port_lines.append(f"    {p.decl_sv()}{comma}")
        parts.append("\n".join(port_lines))
        parts.append(")")

    parts.append(";")
    return "\n".join(parts)


def signal_decl(sig: HDLSignal) -> str:
    return f"    {sig.decl_sv()}"


def assign_stmt(a: HDLAssignment) -> str:
    if a.is_nonblocking:
        return f"    assign {a.target} <= {a.value};"
    return f"    assign {a.target} = {a.value};"


def logic_block(block: LogicBlock) -> str:
    if block.kind == "always_comb":
        lines = ["    always_comb begin"]
    else:
        lines = [f"    {block.kind} @({block.sensitivity}) begin"]
    for item in block.body:
        lines.extend(_emit_block_item(item, indent=2))
    lines.append("    end")
    return "\n".join(lines)


def instance(inst: HDLInstance) -> str:
    parts = [f"    {inst.target}"]

    # Parameters
    if inst.param_map:
        param_parts = []
        for i, (name, val) in enumerate(inst.param_map):
            comma = "," if i < len(inst.param_map) - 1 else ""
            param_parts.append(f"        .{name}({val}){comma}")
        parts.append(" #(")
        parts.append("\n".join(param_parts))
        parts.append(")")

    parts.append(f" {inst.inst_name}")

    # Port connections
    if inst.port_map:
        visible = [(port, sig) for port, sig in inst.port_map if sig != "_"]
        port_parts = []
        for i, (port, sig) in enumerate(visible):
            comma = "," if i < len(visible) - 1 else ""
            port_parts.append(f"        .{port}({sig}){comma}")
        parts.append(" (")
        parts.append("\n".join(port_parts))
        parts.append(")")

    parts.append(";")
    return "\n".join(parts)


def module_footer() -> str:
    return "endmodule"


def _emit_block_item(item: object, indent: int = 2) -> list[str]:
    prefix = "    " * indent
    if isinstance(item, HDLAssignment):
        op = "<=" if item.is_nonblocking else "="
        return [f"{prefix}{item.target} {op} {item.value};"]
    if isinstance(item, HDLIfBlock):
        lines = [f"{prefix}if ({item.cond}) begin"]
        for sub in item.then_body:
            lines.extend(_emit_block_item(sub, indent + 1))
        if item.else_body:
            lines.append(f"{prefix}end else begin")
            for sub in item.else_body:
                lines.extend(_emit_block_item(sub, indent + 1))
        lines.append(f"{prefix}end")
        return lines
    return []
