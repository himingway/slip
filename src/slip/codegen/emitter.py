from __future__ import annotations

import warnings

from slip.errors.codegen import SlipCodegenError
from slip.ir import HDLModule
from slip.codegen import fragment

# Diagnostics to suppress during single-module validation
_SUPPRESSED_DIAG_CODES = {
    "UnknownModule",
    "UndeclaredIdentifier",
    "CouldNotResolve",
    "NotAModule",
}


def emit(mod: HDLModule) -> str:
    """Emit a complete SystemVerilog module as text, then validate with pyslang."""
    lines: list[str] = []

    # Header
    lines.append(fragment.module_header(mod))
    lines.append("")

    # Localparam declarations
    for lp in mod.localparams:
        lines.append(fragment.localparam_decl(lp))
    if mod.localparams:
        lines.append("")

    # Signal declarations
    for sig in mod.signals:
        lines.append(fragment.signal_decl(sig))
    if mod.signals:
        lines.append("")

    # Assign statements
    for a in mod.assigns:
        lines.append(fragment.assign_stmt(a))
    if mod.assigns:
        lines.append("")

    # Logic blocks (always_ff, always_comb)
    for block in mod.logic_blocks:
        lines.append(fragment.logic_block(block))
        lines.append("")

    # Instances
    for inst in mod.instances:
        lines.append(fragment.instance(inst))
        lines.append("")

    # Footer
    lines.append(fragment.module_footer())

    sv_text = "\n".join(lines)

    # Validate with pyslang
    try:
        from pyslang import SyntaxTree, Compilation, DiagnosticEngine
        tree = SyntaxTree.fromText(sv_text, f"{mod.name}.sv")
        comp = Compilation()
        comp.addSyntaxTree(tree)
        diags = comp.getAllDiagnostics()
        errors = [
            d for d in diags
            if d.isError() and _is_relevant_diagnostic(d)
        ]
        if errors:
            report = DiagnosticEngine.reportAll(comp.sourceManager, errors)
            raise SlipCodegenError(
                f"{mod.name}.sv", 0, 0,
                f"pyslang validation failed:\n{report}"
            )
    except ImportError:
        warnings.warn(
            "pyslang not installed — skipping SystemVerilog validation. "
            "Install pyslang for compile-time error checking.",
            stacklevel=2,
        )

    return sv_text


def _is_relevant_diagnostic(d) -> bool:
    """Filter out diagnostics that are expected in single-module compilation."""
    code_str = str(d.code) if hasattr(d, 'code') else ""
    for suppressed in _SUPPRESSED_DIAG_CODES:
        if suppressed in code_str:
            return False
    return True
