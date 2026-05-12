from __future__ import annotations

import warnings
from pathlib import Path
from typing import Union

from slip.ast.module import Module
from slip.ir import HDLModule
from slip.parser.parser import CompilationUnit
from slip.semantic import driver_analysis, seq_correction, symbol_collector
from slip.semantic.defun_eval import register_funcdef
from slip.semantic.gen_expand import expand_module
from slip.semantic.instance_resolve import resolve_instances
from slip.semantic.ir_builder import build as ir_build
from slip.semantic.regex_funcs import clear_custom
from slip.semantic.width_check import check_width_mismatches


class SemanticAnalyzer:
    def analyze(
        self,
        unit: Union[CompilationUnit, list[Module]],
        ip_dirs: list[Path] | None = None,
        filelists: list[Path] | None = None,
    ) -> list[HDLModule]:
        if ip_dirs is None:
            ip_dirs = []

        # Handle backward compatibility: accept list[Module] or CompilationUnit
        if isinstance(unit, list):
            modules = unit
            funcdefs = []
        else:
            modules = unit.modules
            funcdefs = unit.funcdefs

        # Phase 0: Clear custom functions and register defun functions
        clear_custom()
        for funcdef in funcdefs:
            register_funcdef(funcdef)

        # Phase 1: Process modules
        expanded_modules: list[Module] = []
        results: list[HDLModule] = []
        for mod in modules:
            expanded = expand_module(mod)
            expanded_modules.append(expanded)
            results.append(self._analyze_module(expanded))

        # Build module index for cross-module width checks
        module_index = {m.name: m for m in expanded_modules}

        # Width mismatch warnings (FEAT-009)
        for mod in expanded_modules:
            for w in check_width_mismatches(mod, module_index):
                warnings.warn(
                    f"{w.file}:{w.line}:{w.col}: {w.message}",
                    stacklevel=2,
                )

        return resolve_instances(results, ip_dirs, filelists)

    def _analyze_module(self, module: Module) -> HDLModule:
        # 0. Expand metaprogramming (#for, #if) — already done in analyze()
        expanded = module

        # 1. Collect symbols
        symbols = symbol_collector.collect(expanded)

        # 2. Analyze drivers
        drivers = driver_analysis.analyze(expanded, symbols)

        # 3. Correct seq blocks (blocking -> nonblocking)
        corrected = seq_correction.correct(expanded)

        # 4. Build IR
        return ir_build(corrected, symbols, drivers)
