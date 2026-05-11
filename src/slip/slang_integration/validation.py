from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SVDiagnostic:
    severity: str
    message: str
    line: int
    col: int


def validate_sv(sv_text: str, filename: str = "<generated>") -> list[SVDiagnostic]:
    """Validate SystemVerilog text with pyslang. Returns diagnostics."""
    from pyslang import SyntaxTree, Compilation, DiagnosticEngine

    tree = SyntaxTree.fromText(sv_text, filename)
    comp = Compilation()
    comp.addSyntaxTree(tree)
    diags = comp.getAllDiagnostics()

    results: list[SVDiagnostic] = []
    for d in diags:
        loc = d.location
        sm = comp.sourceManager
        line_col = sm.getLineCol(loc)
        severity = "error" if d.isError() else "warning"
        msg = d.formattedMessage if hasattr(d, 'formattedMessage') else str(d)
        results.append(SVDiagnostic(severity, msg, line_col[0], line_col[1]))

    return results
