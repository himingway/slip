from __future__ import annotations

from slip.ir import (
    HDLAssignment,
    HDLCaseBlock,
    HDLCaseItem,
    HDLForLoop,
    HDLIfBlock,
    HDLInstance,
    HDLModule,
    HDLParam,
    HDLPort,
    HDLSignal,
    LogicBlock,
)


class IndentationManager:
    """Manages indentation levels for HDL code generation."""
    
    def __init__(self, base_indent: int = 4, base_level: int = 1):
        self.base_indent = base_indent
        self.level = base_level
    
    def indent(self) -> str:
        """Return current indentation string."""
        return " " * (self.base_indent * self.level)
    
    def increase(self) -> None:
        """Increase indentation level."""
        self.level += 1
    
    def decrease(self) -> None:
        """Decrease indentation level."""
        self.level = max(0, self.level - 1)
    
    def reset(self) -> None:
        """Reset indentation to base level."""
        self.level = 0


def localparam_decl(p: HDLParam) -> str:
    indent = IndentationManager()
    return f"{indent.indent()}localparam {p.name} = {p.default};"


def module_header(mod: HDLModule) -> str:
    indent = IndentationManager(base_level=0)
    header = f"module {mod.name}"

    # Parameters
    if mod.params:
        param_lines = []
        indent.increase()
        for i, p in enumerate(mod.params):
            comma = "," if i < len(mod.params) - 1 else ""
            param_lines.append(f"{indent.indent()}parameter {p.name} = {p.default}{comma}")
        indent.decrease()
        header += " #(\n" + "\n".join(param_lines) + "\n)"

    # Ports
    if mod.ports:
        port_lines = []
        indent.increase()
        for i, p in enumerate(mod.ports):
            tags = []
            has_width = p.type_ and p.type_.width_sv
            if not p.declared:
                tags.append("implicit")
            if not has_width:
                tags.append("no width")
            if p.width_inferred_from:
                tags.append(f"width from {p.width_inferred_from}")
            if tags:
                port_lines.append(
                    f"{indent.indent()}// {', '.join(tags)}"
                )
            comma = "," if i < len(mod.ports) - 1 else ""
            port_lines.append(f"{indent.indent()}{p.decl_sv()}{comma}")
        indent.decrease()
        header += " (\n" + "\n".join(port_lines) + "\n)"

    header += ";"
    return header


def signal_decl(sig: HDLSignal) -> str:
    indent = IndentationManager()
    return f"{indent.indent()}{sig.decl_sv()}"


def assign_stmt(a: HDLAssignment) -> str:
    indent = IndentationManager()
    if a.is_nonblocking:
        return f"{indent.indent()}assign {a.target} <= {a.value};"
    return f"{indent.indent()}assign {a.target} = {a.value};"


def logic_block(block: LogicBlock) -> str:
    indent = IndentationManager()
    
    if block.kind == "always_comb":
        lines = [f"{indent.indent()}always_comb begin"]
    elif block.kind == "always_latch":
        lines = [f"{indent.indent()}always_latch begin"]
    elif block.kind == "initial":
        lines = [f"{indent.indent()}initial begin"]
    else:
        lines = [f"{indent.indent()}{block.kind} @({block.sensitivity}) begin"]
    
    indent.increase()
    for item in block.body:
        lines.extend(_emit_block_item(item, indent))
    indent.decrease()
    lines.append(f"{indent.indent()}end")
    
    return "\n".join(lines)


def instance(inst: HDLInstance) -> str:
    indent = IndentationManager()
    line = f"{indent.indent()}{inst.target}"

    # Parameters
    if inst.param_map:
        param_parts = []
        indent.increase()
        for i, (name, val) in enumerate(inst.param_map):
            comma = "," if i < len(inst.param_map) - 1 else ""
            param_parts.append(f"{indent.indent()}.{name}({val}){comma}")
        indent.decrease()
        line += " #(\n" + "\n".join(param_parts) + f"\n{indent.indent()})"

    line += f" {inst.inst_name}"

    # Port connections
    if inst.port_map:
        visible = [(port, sig) for port, sig in inst.port_map if sig != "_"]
        port_parts = []
        indent.increase()
        for i, (port, sig) in enumerate(visible):
            comma = "," if i < len(visible) - 1 else ""
            port_parts.append(f"{indent.indent()}.{port}({sig}){comma}")
        indent.decrease()
        line += " (\n" + "\n".join(port_parts) + f"\n{indent.indent()})"

    line += ";"
    return line


def module_footer() -> str:
    return "endmodule"


def _emit_block_item(item: object, indent: IndentationManager) -> list[str]:
    if isinstance(item, HDLAssignment):
        op = "<=" if item.is_nonblocking else "="
        return [f"{indent.indent()}{item.target} {op} {item.value};"]
    if isinstance(item, HDLIfBlock):
        lines = [f"{indent.indent()}if ({item.cond}) begin"]
        indent.increase()
        for sub in item.then_body:
            lines.extend(_emit_block_item(sub, indent))
        indent.decrease()
        if item.else_body:
            lines.append(f"{indent.indent()}end else begin")
            indent.increase()
            for sub in item.else_body:
                lines.extend(_emit_block_item(sub, indent))
            indent.decrease()
        lines.append(f"{indent.indent()}end")
        return lines
    if isinstance(item, HDLForLoop):
        lines = [f"{indent.indent()}for (int {item.init}; {item.cond}; {item.step}) begin"]
        indent.increase()
        for sub in item.body:
            lines.extend(_emit_block_item(sub, indent))
        indent.decrease()
        lines.append(f"{indent.indent()}end")
        return lines
    if isinstance(item, HDLCaseBlock):
        lines = [f"{indent.indent()}{item.kind} ({item.expr})"]
        indent.increase()
        for ci in item.items:
            if ci.patterns:
                pat_str = ", ".join(ci.patterns)
                lines.append(f"{indent.indent()}{pat_str}: begin")
            else:
                lines.append(f"{indent.indent()}default: begin")
            indent.increase()
            for sub in ci.body:
                lines.extend(_emit_block_item(sub, indent))
            indent.decrease()
            lines.append(f"{indent.indent()}end")
        indent.decrease()
        lines.append(f"{indent.indent()}endcase")
        return lines
    return []
