from __future__ import annotations

from pathlib import Path

from slip.codegen.emitter import emit
from slip.ir import HDLModule


class CodeGenerator:
    def generate(
        self,
        ir_modules: list[HDLModule],
        output_dir: Path | None = None,
    ) -> dict[str, str]:
        """Generate SystemVerilog for all IR modules.

        Returns a mapping of module_name -> sv_text.
        """
        results: dict[str, str] = {}

        for mod in ir_modules:
            sv_text = emit(mod)
            results[mod.name] = sv_text

            if output_dir is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                out_file = output_dir / f"{mod.name}.sv"
                out_file.write_text(sv_text)

        return results
