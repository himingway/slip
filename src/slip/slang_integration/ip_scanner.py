"""Two-pass IP scanner for building module indices.

Pass 1: Collect files, defines, and include paths from filelist and IP directories.
Pass 2: Parse all IP files together with shared preprocessor context via pyslang.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pyslang import Compilation, SyntaxTree

from slip.slang_integration.filelist import FilelistData, parse_filelist
from slip.slang_integration.reflection import ModuleInfo, ParamInfo, PortInfo


@dataclass
class IPIndex:
    """IP module index for fast lookup."""
    _modules: dict[str, ModuleInfo] = field(default_factory=dict)

    def get_module(self, name: str) -> ModuleInfo | None:
        """Get module info by name, or None if not found."""
        return self._modules.get(name)

    def get_ports(self, name: str) -> list[tuple[str, str, str | None]] | None:
        """Get ports as (name, direction, width) tuples, or None if not found."""
        info = self._modules.get(name)
        if info is None:
            return None
        return [(p.name, p.direction, p.width) for p in info.ports]

    def get_localparams(self, name: str) -> set[str]:
        """Get localparam names for a module, or empty set if not found."""
        info = self._modules.get(name)
        if info is None:
            return set()
        return {p.name for p in info.params if p.is_local}


def build_ip_index(
    filelists: list[Path] | None,
    ip_dirs: list[Path],
) -> IPIndex:
    """Build IP module index via two-pass scanning.

    Args:
        filelists: Paths to VCS-format .f files (optional).
        ip_dirs: IP source directories to scan recursively.

    Returns:
        IPIndex with all discovered modules.
    """
    # Pass 1: Collect all files, incdirs, defines
    all_files: list[Path] = []
    all_incdirs: list[Path] = []
    all_defines: list[str] = []
    seen_files: set[Path] = set()

    # Parse filelists
    for fl_path in (filelists or []):
        fl_data = parse_filelist(fl_path)
        for f in fl_data.files:
            resolved = f.resolve()
            if resolved not in seen_files:
                seen_files.add(resolved)
                all_files.append(f)
        for d in fl_data.incdirs:
            if d not in all_incdirs:
                all_incdirs.append(d)
        for d in fl_data.defines:
            if d not in all_defines:
                all_defines.append(d)

    # Scan IP directories recursively
    for ip_dir in ip_dirs:
        if not ip_dir.is_dir():
            continue
        for ext in ("*.sv", "*.v"):
            for f in sorted(ip_dir.rglob(ext)):
                resolved = f.resolve()
                if resolved not in seen_files:
                    seen_files.add(resolved)
                    all_files.append(f)

    if not all_files:
        return IPIndex()

    # Pass 2: Parse all files together and reflect modules
    return _reflect_all_modules(all_files, all_incdirs, all_defines)


def _reflect_all_modules(
    files: list[Path],
    incdirs: list[Path],
    defines: list[str],
) -> IPIndex:
    """Parse all IP files together and extract module information."""
    index = IPIndex()

    # Build options with include paths
    from pyslang import Bag, PreprocessorOptions

    popts = PreprocessorOptions()
    for d in incdirs:
        popts.additionalIncludePaths.append(str(d))

    # Note: predefines API is unreliable in pyslang, skip for now
    # Defines within files are handled by the shared preprocessor context

    bag = Bag([popts])

    # Parse all files into a single syntax tree (shared preprocessor context)
    file_paths = [str(f) for f in files if f.exists()]
    if not file_paths:
        return index

    try:
        tree = SyntaxTree.fromFiles(file_paths, bag)
    except Exception:
        # If batch parsing fails, fall back to per-file parsing
        return _reflect_per_file(files)

    # Create compilation and add the tree
    comp = Compilation()
    comp.addSyntaxTree(tree)

    # Extract all module definitions
    _extract_modules_from_compilation(comp, index)

    return index


def _extract_modules_from_compilation(
    comp: Compilation,
    index: IPIndex,
) -> None:
    """Extract module info from a pyslang Compilation."""
    from pyslang import SymbolKind

    root = comp.getRoot()

    # Iterate all definitions in the compilation
    for defn in comp.getDefinitions():
        name = defn.name
        try:
            top = root.lookupName(name)
            if top is None:
                continue
            body = top.body

            # Collect params
            params: list[ParamInfo] = []
            for sym in body:
                if sym.kind == SymbolKind.Parameter:
                    val = str(sym.value) if hasattr(sym, 'value') and sym.value else None
                    is_local = getattr(sym, 'isLocalParam', False)
                    params.append(ParamInfo(sym.name, "int", val, is_local=is_local))

            # Collect ports
            ports: list[PortInfo] = []
            for port in body.portList:
                direction = str(port.direction).lower() if hasattr(port, 'direction') else "input"
                if "inout" in direction:
                    direction = "inout"
                elif "out" in direction:
                    direction = "output"
                else:
                    direction = "input"
                width = None
                if hasattr(port, 'type') and port.type:
                    t = port.type
                    if hasattr(t, 'bitWidth') and t.bitWidth > 1:
                        bw = t.bitWidth
                        width = f"[{bw - 1}:0]"
                ports.append(PortInfo(port.name, direction, width))

            index._modules[name] = ModuleInfo(
                params=tuple(params),
                ports=tuple(ports),
            )
        except Exception:
            # Skip modules that fail to reflect
            continue


def _reflect_per_file(files: list[Path]) -> IPIndex:
    """Fallback: reflect modules from individual files."""
    from slip.slang_integration.reflection import reflect_module

    index = IPIndex()
    # First pass: collect all module names by trying to reflect common patterns
    for f in files:
        if not f.exists():
            continue
        try:
            source = f.read_text()
            tree = SyntaxTree.fromText(source, str(f))
            comp = Compilation()
            comp.addSyntaxTree(tree)

            for defn in comp.getDefinitions():
                name = defn.name
                if name in index._modules:
                    continue
                try:
                    info = reflect_module(f, name)
                    index._modules[name] = info
                except Exception:
                    continue
        except Exception:
            continue

    return index
