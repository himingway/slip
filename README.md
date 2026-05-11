# Slip

A minimal HDL DSL compiler that compiles `.slip` source files into synthesizable SystemVerilog.

English | **[中文](README_CN.md)**

## Overview

Slip is a compact hardware description language designed as syntactic sugar over SystemVerilog. It provides a streamlined syntax for common hardware design patterns — signal declarations, combinational and sequential logic, module instantiation with regex port mapping, and compile-time metaprogramming — while generating clean, human-readable SystemVerilog output.

Every Slip construct maps directly to a SystemVerilog equivalent. The generated output is validated against the IEEE 1800-2017 standard via [pyslang](https://github.com/MikePopoloski/slang) (Python bindings for the [slang](https://github.com/MikePopoloski/slang) compiler).

## Features

- **Inferred port directions** — no `input`/`output` keywords; directions are derived from signal usage
- **Implicit signal declarations** — referenced names that aren't ports or instances become `logic` signals automatically
- **Sequential blocks** — `seq (clk, neg: rst_n) { ... }` generates `always_ff` with automatic blocking-to-nonblocking conversion
- **Combinational blocks** — `comb { ... }` generates `always_comb`
- **Compile-time metaprogramming** — `` `for `` loops and `` `if `` conditionals with constant folding
- **Template identifiers** — `` `for `` loop variables expand inside identifier names (e.g., `data_`i` → `data_0`)
- **Module instantiation** — concise syntax with same-name shorthand (`.clk`), explicit connections, and regex port mapping
- **IP integration** — automatic port/parameter reflection of external SystemVerilog IP via pyslang
- **Parameter and localparam** — module-level parameters with override, body-level localparams without
- **Constant validation** — bare integers in port connections are rejected; use width-prefixed (`1'b0`) or fill constants (`'0`, `'1`)
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
```

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
slip build -ip ip_dir design.slip         # include external IP directory
```

### Check

```bash
slip check design.slip                    # validate without generating output
slip check -ip ip_dir design.slip         # with IP directory
```

## Architecture

```
Source (.slip)
    │
    ▼
┌─────────┐    ┌─────────┐    ┌───────────────────┐    ┌──────────┐
│  Lexer  │───▶│  Parser │───▶│ Semantic Analysis │───▶│ Codegen  │
└─────────┘    └─────────┘    └───────────────────┘    └──────────┘
                                   │
                                   ├── Metaprogramming expansion
                                   ├── Symbol collection
                                   ├── Driver analysis
                                   ├── Assignment correction
                                   └── Instance resolution
                                                │
                                                ▼
                                       SystemVerilog (.sv)
```

1. **Lexer** — regex-based tokenizer with post-lex merging for compound tokens
2. **Parser** — recursive-descent for statements, Pratt parser for expressions
3. **Semantic Analysis** — metaprogramming expansion, symbol collection, driver analysis, assignment correction, IR building, instance resolution
4. **Codegen** — IR-to-SystemVerilog emission with pyslang validation

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=slip --cov-report=term-missing
```

## License

MIT
