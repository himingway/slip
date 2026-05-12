# Slip

**S**treamlined **L**anguage for **I**C **P**rototyping — a minimal HDL DSL compiler that compiles `.slip` source files into synthesizable SystemVerilog.

> *Slip* — to move smoothly and effortlessly. Write hardware descriptions that flow from intent to implementation.

English | **[中文](README_CN.md)** | **[User Manual (PDF)](docs/tex/user-manual.pdf)**

## Overview

Slip is a compact hardware description language designed as syntactic sugar over SystemVerilog. It provides a streamlined syntax for common hardware design patterns — signal declarations, combinational and sequential logic, module instantiation with regex port mapping, and compile-time metaprogramming — while generating clean, human-readable SystemVerilog output.

Every Slip construct maps directly to a SystemVerilog equivalent. The generated output is validated against the IEEE 1800-2017 standard via [pyslang](https://github.com/MikePopoloski/slang) (Python bindings for the [slang](https://github.com/MikePopoloski/slang) compiler).

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
- **Compile-time metaprogramming** — `` `for `` loops and `` `if `` conditionals with constant folding
- **Template identifiers** — `` `for `` loop variables expand inside identifier names, including multi-variable names like `a`i_`j`
- **Full operator set** — arithmetic shifts (`<<<`/`>>>`), exponentiation (`**`), case equality (`===`/`!==`), width cast (`8'(expr)`)
- **Replication syntax** — `{4{1'b0}}` generates correct SystemVerilog replication
- **Module instantiation** — concise syntax with same-name shorthand (`.clk`), explicit connections, and regex port mapping
- **Include directive** — `include "helpers.slip"` imports `defun` functions and modules from other Slip files with recursive resolution and cycle detection
- **IP integration** — automatic port/parameter reflection of external SystemVerilog IP via pyslang, with VCS filelist (`-f`) support and recursive directory scanning
- **Parameter and localparam** — module-level parameters with override, body-level localparams without
- **Multi-driver detection** — signals driven by multiple `seq`/`comb` blocks raise a compile error
- **Combinational loop detection** — feedback loops inside `comb` blocks are detected and reported as errors
- **Width mismatch warnings** — assignment and instance port width mismatches are reported as warnings
- **Module topological sort** — modules are emitted in dependency order; cyclic dependencies raise a compile error
- **Constant validation** — bare integers in port connections are rejected; integer literal radix is validated
- **Dangling port marker** — `.rst_n(_)` leaves a port intentionally unconnected

## Quick Example

```slip
module pipeline #(param STAGES = 3, param WIDTH = 8) (clk, rst_n, din, dout) {
    logic clk;
    logic rst_n;
    logic [WIDTH-1:0] din;
    logic [WIDTH-1:0] dout;

    // Compile-time loop unrolling with template identifiers
    `for (`i = 0; `i < STAGES; `i = `i + 1) {
        logic [WIDTH-1:0] stage_`i;
    }

    seq (clk, neg: rst_n) {
        if (!rst_n) {
            `for (`i = 0; `i < STAGES; `i = `i + 1) {
                stage_`i = 0;
            }
        } else {
            stage_0 = din;
            `for (`i = 1; `i < STAGES; `i = `i + 1) {
                stage_`i = stage_`i - 1;
            }
        }
    }

    assign dout = stage_2;
}
```

Generates:

```systemverilog
module pipeline
    #(
        parameter STAGES = 3,
        parameter WIDTH = 8
    )
(
    input logic clk,
    input logic rst_n,
    input logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout
);

    logic [WIDTH-1:0] stage_0;
    logic [WIDTH-1:0] stage_1;
    logic [WIDTH-1:0] stage_2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage_0 <= 0;
            stage_1 <= 0;
            stage_2 <= 0;
        end else begin
            stage_0 <= din;
            stage_1 <= stage_0;
            stage_2 <= stage_1;
        end
    end

    assign dout = stage_2;

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
    inner u1 { .clk, .rst_n, "data_(.*)" => "$prefix(\\1)" };
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

**Custom Functions (Python API):**
```python
from slip.semantic.regex_funcs import register

def my_func(s: str) -> str:
    return f"prefix_{s}"

register("my_func", my_func)
```
Then use `$my_func(\1)` in Slip. Custom functions can override built-in ones.

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
Supported: full Python expressions including string concatenation (`+`), string methods (`.upper()`, `.lower()`, `.reverse()`, `.replace()`, `.strip()`, `.split()`, `.startswith()`, etc.), arithmetic (`+`, `-`, `*`, `/`, `%`), method chaining, built-in functions (`len()`, `int()`, `str()`), indexing/slicing (`s[0]`, `s[1:3]`, `s[3:]`, `s[:3]`, `s[-1]`), ternary expressions.

### Special Constants

```slip
'0    // zero-fill (all bits 0)
'1    // one-fill (all bits 1)
1'b0  // width-prefixed (required for port connections)
```

## Installation

```bash
# Clone
git clone https://github.com/user/slip.git
cd slip

# Install dependencies (requires uv)
uv sync

# Or with pip
pip install -e .
```

Requires Python >= 3.10.

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
slip check design.slip                    # validate without generating output
slip check -ip ip_dir design.slip         # with IP directory
slip check -f ip.f design.slip            # with filelist
```

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

1. **Lexer** — regex-based tokenizer with post-lex merging for compound tokens
2. **Parser** — recursive-descent for statements, Pratt parser for expressions
3. **Semantic Analysis** — include resolution, metaprogramming expansion, symbol collection, driver analysis, combinational loop detection, assignment correction, width mismatch checking, IR building, instance resolution with port width inference
4. **Codegen** — IR-to-SystemVerilog emission with pyslang validation and review annotations (`// implicit`, `// no width`, `// width from X.Y`)

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=slip --cov-report=term-missing
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
