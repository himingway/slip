from __future__ import annotations

from pathlib import Path

from slip.ast.module import Module
from slip.ir import HDLModule
from slip.semantic import driver_analysis, seq_correction, symbol_collector
from slip.semantic.gen_expand import expand_module
from slip.semantic.instance_resolve import resolve_instances
from slip.semantic.ir_builder import build as ir_build


class SemanticAnalyzer:
    def analyze(
        self,
        modules: list[Module],
        ip_dirs: list[Path] | None = None,
    ) -> list[HDLModule]:
        if ip_dirs is None:
            ip_dirs = []
        results: list[HDLModule] = []
        for mod in modules:
            results.append(self._analyze_module(mod))
        return resolve_instances(results, ip_dirs)

    def _analyze_module(self, module: Module) -> HDLModule:
        # 0. Expand metaprogramming (#for, #if)
        expanded = expand_module(module)

        # 1. Collect symbols
        symbols = symbol_collector.collect(expanded)

        # 2. Analyze drivers
        drivers = driver_analysis.analyze(expanded, symbols)

        # 3. Correct seq blocks (blocking -> nonblocking)
        corrected = seq_correction.correct(expanded)

        # 4. Build IR
        return ir_build(corrected, symbols, drivers)
