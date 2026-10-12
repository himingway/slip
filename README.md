# Slip

**S**treamlined **L**anguage for **I**C **P**rototyping — a minimal HDL DSL compiler that compiles `.slip` source files into synthesizable SystemVerilog.

> *Slip* — to move smoothly and effortlessly. Write hardware descriptions that flow from intent to implementation.

English | **[中文](README_CN.md)** | **[User Manual (PDF)](docs/tex/user-manual.pdf)**

> The IEEE standard documents referenced during development (1364-2005, 1800-2017) are not distributed with this repository — obtain them from [IEEE Xplore](https://ieeexplore.ieee.org/).

## Overview

Slip is a compact hardware description language designed as syntactic sugar over SystemVerilog. It provides a streamlined syntax for common hardware design patterns — signal declarations, combinational and sequential logic, module instantiation with regex port mapping, and compile-time metaprogramming — while generating clean, human-readable SystemVerilog output.

Slip is a C++20 compiler that links directly to [slang](https://github.com/MikePopoloski/slang) for constant evaluation, IP reflection and whole-design validation. The Python implementation is maintained on the [`python-reference` branch](https://github.com/himingway/slip/tree/python-reference). See [compiler design and compatibility](docs/development.md).

## Features

- **Inferred port directions** — no `input`/`output` keywords; directions are derived from signal usage
- **Implicit signal declarations** — referenced names that aren't ports or instances become `logic` signals automatically, annotated with `// implicit, no width` for easy review
- **Instance port width inference** — signals connected to instance ports automatically inherit the target port's width, annotated with `// width from X.Y` in generated SV
- **Sequential blocks** — `seq (clk, neg: rst_n) { ... }` generates `always_ff` with automatic blocking-to-nonblocking conversion
- **Combinational blocks** — `comb { ... }` generates `always_comb`
- **Initial blocks** — `initial { ... }` generates `initial begin ... end` for testbenches and initialization
- **Procedural for loops** — `for` inside `seq`/`comb` blocks generates SV `for` statements, with `i++` and `i += expr` step support
- **Case statements** — `case`/`casez`/`casex` with multi-pattern, default, and `?` wildcard support
- **Inside operator** — `x inside {1, 2, 3}` for set membership testing
- **Compound assignments** — `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, `<<<=`, `>>>=` desugared at parse time
- **Compile-time metaprogramming** — `` `for `` loops and `` `if `` conditionals with SystemVerilog constant evaluation
- **Template identifiers** — `` `for `` loop variables expand inside identifier names, including multi-variable names like `a`i_`j`
- **Full operator set** — arithmetic shifts (`<<<`/`>>>`), exponentiation (`**`), case equality (`===`/`!==`), width cast (`8'(expr)`)
- **Replication syntax** — `{4{1'b0}}` generates correct SystemVerilog replication
- **Module instantiation** — concise syntax with same-name shorthand (`.clk`), explicit connections, and regex port mapping
- **Include directive** — `include "helpers.slip"` imports `defun` functions and modules from other Slip files with recursive resolution and cycle detection
- **IP integration** — automatic port/parameter reflection of external SystemVerilog IP via slang, with VCS filelist (`-f`) support and recursive directory scanning
- **Parameter and localparam** — module-level parameters with override, body-level localparams without
- **Multi-driver detection** — a signal driven by multiple `seq`/`comb` blocks or continuous assignments raises a compile error (disjoint bit-ranges are allowed)
- **Combinational loop detection** — feedback loops inside `comb` blocks are detected and reported as errors
- **Width mismatch warnings** — assignment and instance port width mismatches are reported as warnings; unsized constants are range-checked against the target instead of assumed 32-bit
- **Module topological sort** — interfaces are resolved in dependency order; cyclic dependencies raise a compile error
- **Constant validation** — bare integers in port connections are rejected; integer literal radix is validated
- **Dangling port marker** — `.rst_n(_)` leaves a port intentionally unconnected

## Quick Example

```slip
module pipeline #(param STAGES = 3, param WIDTH = 8) (clk, rst_n, din, dout) {
    logic clk;
    logic rst_n;
    logic [WIDTH-1:0] din;
    logic [WIDTH-1:0] dout;
    logic [WIDTH-1:0] stage [0:STAGES-1];   // unpacked array of stages

    seq (clk, neg: rst_n) {
        if (!rst_n) {
            // Compile-time loop unrolling with template identifiers
            `for (`i = 0; `i < STAGES; `i = `i + 1) {
                stage[`i] = 0;
            }
        } else {
            stage[0] = din;
            `for (`i = 1; `i < STAGES; `i = `i + 1) {
                stage[`i] = stage[`i - 1];   // template variable in an index
            }
        }
    }

    assign dout = stage[STAGES-1];
}
```

Generates (all blocking assignments in `seq` become nonblocking, so every
stage samples the pre-clock value — a true shift register):

```systemverilog
module pipeline #(
    parameter STAGES = 3,
    parameter WIDTH = 8
) (
    input logic clk,
    input logic rst_n,
    input logic [WIDTH - 1:0] din,
    output logic [WIDTH - 1:0] dout
);

    if (STAGES !== (3)) begin : __slip_frozen_STAGES
        $error("STAGES controls Slip compile-time expansion and cannot be overridden");
    end

    logic [WIDTH - 1:0] stage [0:STAGES - 1];

    assign dout = stage[STAGES - 1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage[0] <= 0;
            stage[1] <= 0;
            stage[2] <= 0;
        end else begin
            stage[0] <= din;
            stage[1] <= stage[0];
            stage[2] <= stage[1];
        end
    end

endmodule
```

## Syntax Reference

### Include Directive

```slip
include "helpers.slip";     // import defun functions and modules from another file
include "utils/common.slip"; // relative paths resolved from the including file

module top (clk, rst_n) {
    logic clk;
    logic rst_n;
    inner u1 { .clk, .rst_n, "data_(.*)" => "$prefix(\1)" };
}
```

Include statements must appear at the top level (outside module bodies). Included files are lexed and parsed, and their `defun` functions and module definitions are merged into the compilation unit. Recursive includes are supported; cycles are detected via absolute path deduplication.

### Module Declaration

```slip
module name #(param W = 8, param DEPTH = 16) (clk, rst_n, data_in, data_out) {
    // body
}
```

Parameters use the `param` keyword. Ports are listed by name only — directions are inferred automatically.

### Signals

```slip
logic [7:0] data;          // explicit width
logic flag;                // 1-bit
signed [15:0] val;         // signed
data;                      // bare declaration (defaults to logic)
logic [7:0] mem [0:15];    // array
```

### Assignments

```slip
assign y = a & b;          // with keyword
y = a + b;                 // bare assignment
```

### Sequential Logic

```slip
seq (clk, neg: rst_n) {
    if (!rst_n) begin
        counter <= 0;
    end else begin
        counter <= counter + 1;
    end
}
```

Blocking `=` inside `seq` blocks is automatically converted to non-blocking `<=`.

### Combinational Logic

```slip
comb {
    if (sel) { y = a; }
    else { y = b; }
}
```

### Case Statements

```slip
case (sel) {
    2'b00: y = a;
    2'b01: y = b;
    2'b10, 2'b11: y = c;
    default: y = 0;
}

// casez with ? wildcard
casez (opcode) {
    4'b1???: y = a;
    4'b01??: y = b;
    default: y = 0;
}
```

### Inside Operator

```slip
if (state inside {IDLE, RUN, DONE}) {
    // ...
}
```

### Initial Blocks

```slip
initial {
    clk = 0;
    forever #5 clk = ~clk;
}
```

### Metaprogramming

```slip
// Compile-time loop with template identifiers
`for (`i = 0; `i < N; `i = `i + 1) {
    logic [7:0] data_`i;
    assign data_`i = `i;
}

// Conditional compilation
`if (ENABLE_FIFO) {
    fifo #(.DEPTH(16)) u_fifo { .clk, .din, .dout };
}
`else {
    assign dout = din;
}
```

### Module Instantiation

```slip
// Same-name shorthand: .clk means .clk(clk)
inner #(.W(16)) u1 { .clk, .data_in, .data_out(result) };

// Dangling port (left unconnected)
inner u2 { .clk, .rst_n(_), .data };

// Regex port mapping
child u3 { .clk, "data_(.*)" => "prefix_\1" };

// Multiple regex rules: first matching rule wins
child u4 { .clk, "data_(.*)" => "bus_\1", "out_(.*)" => "result_\1" };

// Regex functions: transform captured groups
child u5 { .clk, "data_(.*)" => "bus_$upper(\1)" };     // uppercase
child u6 { .clk, "ch_(.*)" => "port_$add(\1, 1)" };     // arithmetic
child u7 { .clk, "a_(.*)" => "pre_$upper(\1)_post" };   // prefix + suffix
```

**Regex Port Mapping Priority:**
1. Explicit connections (highest priority)
2. Same-name shorthand
3. Regex patterns (processed in order, first match wins)

**Built-in Regex Functions:**
- String: `$upper`, `$lower`, `$reverse`, `$substr`, `$replace`, `$concat`
- Arithmetic: `$add`, `$sub`, `$mul`, `$div`, `$mod`
- Bit: `$bit_reverse`, `$bit_select`

**Native Custom Functions (defun):**
```slip
defun prefix(s):
    return "bus_" + s

defun to_upper(s):
    return s.upper()

defun inc(n):
    return n + 1

child u1 {
    .clk,
    "data_(.*)" => "$prefix(\1)",
    "name_(.*)" => "$to_upper(\1)",
    "ch_(.*)" => "$inc(\1)"
};
```
`defun` uses a restricted Python-style expression language evaluated by the C++ interpreter. Supported features include string concatenation (`+`), string methods (`.upper()`, `.lower()`, `.reverse()`, `.replace()`, `.strip()`, `.split()`, `.startswith()`, etc.), arithmetic (`+`, `-`, `*`, `/`, `%`), method chaining, built-in functions (`len()`, `int()`, `str()`), indexing/slicing (`s[0]`, `s[1:3]`, `s[3:]`, `s[:3]`, `s[-1]`), ternary expressions.

### Special Constants

```slip
'0    // zero-fill (all bits 0)
'1    // one-fill (all bits 1)
1'b0  // width-prefixed (required for port connections)
```

## Installation

### Native C++ compiler

Requires a C++20 compiler, CMake >= 3.24 and PCRE2 development libraries. CMake uses an installed slang 10 package or fetches a pinned version and its dependencies. Building slang requires Python; running Slip does not.

```bash
cmake --preset release
cmake --build --preset release --parallel 2
ctest --preset release
build/release/slip check tests/fixtures/simple.slip
```

See [docs/development.md](docs/development.md) for offline builds, sanitizers and compatibility limits.

Install the CLI:

```sh
cmake --install build/release --prefix "$HOME/.local"
```

With `$HOME/.local/bin` on `PATH`, `slip` runs the C++ compiler.

## Usage

### Build

```bash
slip build design.slip                    # output to ./build
slip build -o output design.slip          # output to ./output
slip build -ip ip_dir design.slip         # include external IP directory (recursive)
slip build -f ip.f design.slip            # use VCS-format filelist
slip build -f ip.f -ip ip_dir design.slip # filelist + directory (combined)
```

### Check

```bash
slip check design.slip                    # full pipeline (incl. SV validation), nothing written
slip check -ip ip_dir design.slip         # with IP directory
slip check -f ip.f design.slip            # with filelist
slip check --strict design.slip           # explicit signals; width mismatches are errors
```

### Compilation guarantees

- Generated modules and external IP are elaborated together by slang, using the same parsed IP sources, defines, and include paths as interface reflection. Invalid port/parameter names and unresolved identifiers are errors.
- All modules are validated before any output file is written. A compilation error preserves existing build artifacts.
- Interfaces propagate from child modules through every wrapper. Parameter-dependent dimensions are translated into the parent scope, including instance overrides and localparam dependencies.
- Hardware expressions preserve their literal widths, signedness, four-state values, and assignment context. Slip substitutes loop variables without applying Python arithmetic to the resulting hardware expression.
- Parameters used directly or indirectly by Slip metaprogram controls are fixed at their defaults for that generated module. Overrides are rejected in Slip; generated elaboration checks also reject different values supplied by downstream SV. To change them, change the source configuration and rebuild. Parameters used only for ordinary RTL dimensions remain overridable.
- `--strict` requires explicit signal and port declarations and treats assignment/port width mismatches as errors. It is recommended for CI; the default continues to support annotated implicit signals. Normal single-bit declarations are accepted.

### Filelist Format

Slip supports VCS-format filelist (`.f`) files:

```
// Comment
+incdir+./include
+define+DATA_WIDTH=32
./rtl/fifo.sv
./rtl/arbiter.sv
-f sub_filelist.f
```

- `+incdir+path` — include search directory
- `+define+MACRO=value` — macro definition
- `-f sub.f` — nested filelist reference
- File paths are resolved relative to the filelist location
- Duplicate files are automatically deduplicated

## Architecture

```
Source (.slip)
    │
    ▼
┌─────────┐    ┌─────────┐    ┌───────────────────┐    ┌──────────┐
│  Lexer  │───▶│  Parser │───▶│ Semantic Analysis │───▶│ Codegen  │
└─────────┘    └─────────┘    └───────────────────┘    └──────────┘
                                   │
                                   ├── Include resolution
                                   ├── Metaprogramming expansion
                                   ├── Symbol collection
                                   ├── Driver analysis
                                   ├── Assignment correction
                                   └── Instance resolution (with width inference)
                                                │
                                                ▼
                                       SystemVerilog (.sv)
```

The C++ implementation lives in `src/` and `include/slip/`; its tests and shared HDL fixtures live in `tests/`. The Python implementation is maintained on the [`python-reference` branch](https://github.com/himingway/slip/tree/python-reference).

1. **Lexer** — tokenization with compound operators, comments and template identifiers
2. **Parser** — recursive-descent for statements, Pratt parser for expressions
3. **Semantic Analysis** — include resolution, metaprogramming expansion, symbol collection, driver analysis, combinational loop detection, assignment correction, width mismatch checking, IR building, instance resolution with port width inference
4. **Codegen** — IR-to-SystemVerilog emission with slang validation and review annotations (`// implicit`, `// no width`, `// width from X.Y`)

## Running Tests

```sh
ctest --preset release
cmake --preset sanitize
cmake --build --preset sanitize --parallel 2
ctest --preset sanitize
```

With Verilator installed, CTest also runs four independent simulations covering pipeline arithmetic, combinational logic, state machines, and parameterized arrays. See [testing and coverage](docs/testing.md) for independent regressions, sanitizer checks, coverage reports and fuzzing.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
