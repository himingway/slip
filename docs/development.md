# C++ compiler development

The native compiler implements the Slip language in C++20. Its lexer, Pratt
parser, metaprogram expander, semantic analysis, interface resolution and SV
emitter run without Python. It links directly to slang for IP reflection,
SystemVerilog constant evaluation and whole-design elaboration.

The Python implementation is maintained on the [`python-reference` branch](https://github.com/himingway/slip/tree/python-reference). The CLI keeps `build`, `check`, `-o`, `-ip`, `-f`, and `--strict`.
Native additions are stdin input (`-`), `build --stdout`, and
`--diagnostics=json`. Exit codes are 0 for success, 1 for compilation failure,
and 2 for invalid arguments or malformed project configuration. Diagnostics use stable codes such as `E_PARSE`,
`E_CONSTANT`, `E_CONNECTION`, `E_MULTIPLE_DRIVERS`, and `E_SV`.

`inspect` runs the validated compilation pipeline without publishing SV. Its text
or `--format=json` report includes resolved interfaces and connection origins.
API users can set `Options::collect_inspection` to populate `Result::inspection`.
`--no-implicit` and `--widths-as-errors` select the two strict checks independently;
`--strict` enables both. Default implicit declarations produce `W_IMPLICIT`.

The emitter keeps a source location for each generated line. Backend diagnostics
use generated buffer IDs to recover original Slip locations without modifying SV
output or confusing IP files with generated modules of the same basename. Loop
bindings are preserved in `Location::expansion`; JSON diagnostics expose that field
when nonempty. Text CLI diagnostics show a source excerpt, including stdin input.

## RTL language extensions

See [RTL features](rtl-features.md) for syntax and examples. The typed AST retains
field accesses, indexed selects, extra array dimensions and clock edges. Module
specialization runs before lowering, evaluates generation bindings in the caller
context, caches effective bindings and propagates structural constraints through
wrappers. One compilation caps distinct specializations at 1,024 and dependency
depth at 128. Typedefs, functions and assertions preserve source locations in the IR.

Bundle schemas expand into ordinary signals and ports before interface resolution;
group connections expand after the child interface is known. Explicit directions
and declared scalar widths are retained as constraints. RTL functions use local
scope and blocking assignments; nonlocal signal dependencies, timing constructs,
missing returns and incomplete return paths are rejected. Static assertions also
emit elaboration checks so downstream parameter overrides remain constrained.

Native SV interfaces follow a separate path from flattened bundles. `BundleUse`
retains a native flag, modport and constructor connections. The backend indexes
interface definitions and reflects data fields and modport directions lazily.
Lowering retains `IRNativeInterface` objects and uses dotted identifiers as field
storage keys; these checking-only signals are omitted from SV declarations.
Internal objects emit real SV instances, and exported objects emit modport ports.
Whole-object connections validate type and modport compatibility, then register
output field drivers. Slang elaboration resolves actual interface parameterization
and field widths; its analysis also reports conflicting drivers involving interface
RTL. JSON inspection exposes `interfaces` metadata. See
[native interfaces](native-interfaces.md) for syntax and current boundaries.

The IP backend indexes definitions and reflects requested modules lazily. Only
roots from the generated design are selected for validation, avoiding accidental
elaboration of unrelated vendor roots. Simulation covers the combined extensions
for 160 cycles and verifies that an intentionally violated runtime assertion fails.

## Project settings and RTL analysis

`src/project.cpp` reads the CLI-only `slip.conf` configuration. No configuration
is loaded by the compiler API. Paths are configuration-relative; explicit CLI
inputs remain independent of project settings unless `--project` is supplied.
The format and precedence rules are documented in the README. Invalid keys,
duplicate scalar keys or invalid values report `E_CONFIG` at the offending line.

After successful elaboration, the backend freezes the compilation and runs slang
analysis with one worker per independent compilation. Analysis warnings are
mapped back to Slip source locations. `W_UNDRIVEN` and `W_LATCH` are filtered to
generated buffers; external IP participates in analysis. Regex rules that make
no connections report `W_REGEX_UNUSED`; omitted instance ports report
`W_UNCONNECTED`, with explicit `.port(_)` treated as intentional. These checks
remain warnings in strict mode.

## Build

Requirements: a C++20 compiler, CMake >= 3.24, PCRE2 8-bit development libraries,
and slang 10. If slang is not installed, CMake downloads the pinned upstream
commit `ace09c5d7c9f4e28eed654d2f353c6dc792ebf67` into the ignored build
directory. Upstream slang also needs fmt >= 12.1 and a Python interpreter to
generate its C++ headers during its build. The resulting executable does not
need Python or pyslang at runtime.

On Ubuntu, install `build-essential cmake git python3 libpcre2-dev` first.

```sh
cmake --preset release
cmake --build --preset release --parallel 2
ctest --preset release
build/release/slip build tests/fixtures/simple.slip -o build/rtl
build/release/slip check tests/fixtures/ip_top_fifo_user.slip -ip tests/fixtures/ip
```

An offline build can use an installed slang and fmt prefix:

```sh
cmake --preset release -DCMAKE_PREFIX_PATH=/path/to/dependencies -DSLIP_FETCH_SLANG=OFF
```

Some installed slang 10 packages omit `BS_thread_pool.hpp`, which its analysis
API needs when threading is enabled. CMake uses the source header if available,
or downloads the header from the same pinned slang commit and verifies SHA-256.
For an offline installed-package build, also set
`-DSLIP_SLANG_THREAD_POOL_INCLUDE_DIR=/path/to/slang/external` if needed.

Alternatively, use `-DFETCHCONTENT_SOURCE_DIR_SLANG=/path/to/slang/source` with
an installed fmt package. Keep the slang and Slip debug/release configurations
compatible; their allocator layouts differ. CMake rejects a mismatched
single-configuration installed package.

```sh
cmake --preset sanitize
cmake --build --preset sanitize --parallel 2
ctest --preset sanitize
```

LeakSanitizer cannot inspect processes under some traced or restricted sandboxes.
In that environment, use `ASAN_OPTIONS=detect_leaks=0 ctest --preset sanitize`;
address and undefined-behavior checks remain enabled. CI uses the default
sanitizer settings.

## Architecture

- `include/slip/ast.hpp`: source locations and typed `std::variant` AST nodes;
  expression subtrees have immutable shared ownership and bounded depth.
- `include/slip/ir.hpp`: resolved module interfaces, storage, processes and instances.
- `include/slip/compiler.hpp`: reusable `compile` / `compile_file` API and options.
- `src/frontend.cpp`: lexer, Pratt parser, serializer, and expression traversal.
- `src/functions.cpp`: a typed interpreter for `defun` and regex replacements;
  no Python `eval`, global function registry, or shell execution.
- `src/pattern.cpp`: PCRE2 patterns with bounded match work and recursion.
- `src/slang_backend.cpp`: an owned source manager, retained IP syntax tree,
  per-compilation constant cache, and whole-design validation.
- `src/compiler.cpp`: ordered compilation passes, dependency sorting, instance
  inference, driver checks, combinational dependency analysis and SV emission.
- `src/main.cpp`: CLI and human-readable / JSON diagnostics.
- `src/project.cpp`: project configuration parsing and configuration-relative paths.

Each compilation owns its state. There are no mutable global registries, so
independent compilations can run concurrently. Output ordering is deterministic.
All generated modules and IP pass elaboration before any output is published.
`--strict` rejects implicit declarations and width mismatches; the default emits
width warnings and annotates implicit / inferred declarations.

## Tests and repository layout

The default CMake/CTest build uses only C++ and CMake tests. Independent named
regressions cover AST precedence, widths and signedness, parameter scope,
overlapping drivers, diagnostic locations, integer boundaries, resource limits,
object ownership and concurrent compilations with different functions and IP.
CTest also covers all shared `.slip` fixtures and CLI behavior. With Verilator,
four simulations cover pipeline arithmetic, combinational logic, a state machine,
and arrays with different widths and depths. Their expected behavior is defined
in independent RTL or testbench models, without the Python implementation.
CI runs Release, ASan/UBSan, GCC coverage and Clang libFuzzer jobs.
See [testing and coverage](testing.md) for commands, report scope and fuzz replay.

```sh
ctest --preset release
cmake --install build/release --prefix "$PWD/build/install"
build/install/bin/slip check tests/fixtures/simple.slip
```

- `include/slip/`: public C++ AST, IR and compiler API.
- `src/`: C++ implementation and CLI.
- `tests/`: C++ API tests, CMake CLI/simulation tests and shared HDL fixtures.
- `docs/`: current language specification and C++ user/developer documentation.

The C++ `slip::core` build target exposes the reusable compiler API.
Installation currently publishes the CLI executable. Python is needed only
when generating slang headers from source.

## Bounds and compatibility

Compilation defaults cap metaprogram iterations at 10,000 across a module,
expanded statements at 100,000, and include depth at 128. A repeated loop value
is diagnosed immediately. The API exposes these limits in `Options`. Expression
depth is capped at 256 and each source at 1,000,000 tokens. Regex matching and
defun evaluation have separate depth / work / string-size limits.

Metaprogram control results and defun integers must fit a signed 64-bit integer;
overflow is an error. Hardware literals and arithmetic retain their full SV
widths and four-state semantics. The native defun string interpreter operates
on bytes; Python Unicode case conversion and indexing are not reproduced.
Defun string methods support the documented helpers and diagnose unsupported
arities. PCRE2 covers the common Python
regex syntax used by Slip, including named groups and inline flags, but it is
not an implementation of every Python `re` extension. External SV definitions are indexed before use and reflected lazily. Interface
ports and type parameters on modules actually connected to Slip are explicitly
rejected; unused definitions do not fail merely because of those reflection limits.

This suite establishes compatibility for existing examples and test programs;
it is not a formal proof of equivalence for every possible input.
