from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from slip.codegen.emitter import emit
from slip.errors.codegen import SlipCodegenError
from slip.ir import HDLModule
from slip.ir.dependency import topological_sort

if TYPE_CHECKING:
    from slip.slang_integration.ip_scanner import IPIndex


class CodeGenerator:
    def generate(
        self,
        ir_modules: list[HDLModule],
        output_dir: Path | None = None,
        *,
        ip_index: IPIndex | None = None,
    ) -> dict[str, str]:
        """Generate SystemVerilog for all IR modules.

        Modules are topologically sorted so that dependencies are emitted
        before the modules that instantiate them.

        Returns a mapping of module_name -> sv_text.
        """
        results: dict[str, str] = {}
        sorted_modules = topological_sort(ir_modules)

        for mod in sorted_modules:
            sv_text = emit(mod, validate=False)
            results[mod.name] = sv_text

        context = ip_index if ip_index is not None else getattr(ir_modules, "ip_index", None)
        validate_design(results, context, strict=getattr(ir_modules, "strict", False))

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, sv_text in results.items():
                out_file = output_dir / f"{name}.sv"
                out_file.write_text(sv_text, encoding="utf-8")

        if output_dir is not None:
            _warn_stale_outputs(output_dir, set(results))

        return results


def validate_design(modules: dict[str, str], ip_index: IPIndex | None = None, *, strict: bool = False) -> None:
    """Elaborate every generated module and external IP in one compilation."""
    from pyslang import Compilation, DiagnosticEngine, SourceManager, SyntaxTree

    compilation = Compilation()
    source_manager = SourceManager()
    if ip_index is not None and ip_index.syntax_tree is not None:
        source_manager = ip_index.syntax_tree.sourceManager
        compilation.addSyntaxTree(ip_index.syntax_tree)
    for name, source in modules.items():
        compilation.addSyntaxTree(SyntaxTree.fromText(source, source_manager, f"{name}.sv"))
    errors = [
        d for d in compilation.getAllDiagnostics()
        if d.isError() or (strict and any(code in str(d.code) for code in (
            "PortWidthExpand", "PortWidthTruncate", "WidthExpand", "WidthTruncate",
        )))
    ]
    if errors:
        raise SlipCodegenError(
            "<design>", 0, 0,
            "pyslang validation failed:\n" +
            DiagnosticEngine.reportAll(compilation.sourceManager, errors)
        )


def _warn_stale_outputs(output_dir: Path, written: set[str]) -> None:
    """Warn about .sv files in the output directory this run did not write.

    Stale modules (e.g. left behind after a module was renamed or deleted)
    get picked up by downstream glob-based compile flows, so surface them
    rather than letting them silently mix into the build.
    """
    stale = sorted(
        p.name for p in output_dir.glob("*.sv")
        if p.stem not in written
    )
    if stale:
        import warnings
        warnings.warn(
            f"output directory {output_dir} contains SystemVerilog files not "
            f"produced by this run: {', '.join(stale)}. Remove them if they "
            f"are stale — downstream tools that compile the whole directory "
            f"would include them.",
            stacklevel=2,
        )
