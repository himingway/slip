#include "slip/compiler.hpp"
#include <future>
#include <iostream>

namespace {
int failures = 0;
void require(bool condition, const char* message) {
    if (!condition) { ++failures; std::cerr << "FAIL: " << message << '\n'; }
}
void rejected(std::string_view source, std::string_view code, const slip::Options& options = {}) {
    try { slip::compile(source, "test.slip", options); require(false, "invalid source accepted"); }
    catch (const slip::Error& error) { require(error.code == code, error.what()); }
}
} // namespace
int main() {
    try {
        auto result = slip::compile("module simple (a,b,y) { logic [7:0] a; logic [7:0] b; logic [7:0] y; assign y = a & b; }");
        require(result.modules.at("simple").find("output logic [7:0] y") != std::string::npos, "output direction and width");
        require(slip::to_sv(slip::parse_expression("a + b << c * d")) == "a + b << c * d", "expression precedence");
        auto pipeline = slip::compile("module pipe (clk,d,q) { logic [7:0] d; logic [7:0] q; seq(clk) { q = d; } }");
        require(pipeline.modules.at("pipe").find("q <= d;") != std::string::npos, "seq becomes nonblocking");
        auto expanded = slip::compile("module gen #(param N=2) (a,y) { logic [N-1:0] a; logic [N-1:0] y; `for (`i=0; `i<N; `i=`i+1) { assign y[`i] = a[`i]; } }");
        require(expanded.modules.at("gen").find("assign y[1] = a[1];") != std::string::npos, "metaprogram unrolling");
        require(expanded.modules.at("gen").find("__slip_frozen_N") != std::string::npos, "expanded parameter override guard");
        auto ordered = slip::compile("module top(a,y) { mid u {.a,.y}; } module mid(a,y) { leaf u {.a,.y}; } module leaf #(param W=8)(a,y) { logic [W-1:0] a; logic [W-1:0] y; assign y=a; }");
        require(ordered.modules.at("top").find("output logic [7:0] y") != std::string::npos, "hierarchical interface propagation");
        auto constants = slip::compile("module c(y) { logic y; `if (2 || 4) { assign y = 1'b1; } `else { assign y = 1'b0; } }");
        require(constants.modules.at("c").find("1'b1") != std::string::npos, "SV logical semantics");
        auto arithmetic = slip::compile("module c(y) { logic [15:0] y; assign y = (8'hFF + 8'h01); }");
        require(arithmetic.modules.at("c").find("8'hFF + 8'h01") != std::string::npos, "context-dependent arithmetic is preserved");
        auto accumulate = slip::compile("module c(a,y) { comb { y=0; y=y+a; } }");
        require(!accumulate.modules.empty(), "initialized comb accumulator is not feedback");
        rejected("module x { comb { seq(clk) { q=d; } } }", "E_CONTEXT");
        rejected("module x { assign y <= a; }", "E_CONTEXT");
        rejected("module x { if(a) y=b; }", "E_CONTEXT");
        rejected("module x { assign a=b; assign b=a; }", "E_COMB_LOOP");
        rejected("module x { comb { if(y) y=1'b0; else y=1'b1; } }", "E_COMB_LOOP");
        rejected("module x { assign y=a; assign y=b; }", "E_MULTIPLE_DRIVERS");
        rejected("module x { logic a; logic a; }", "E_DUPLICATE");
        rejected("module x {} module x {}", "E_DUPLICATE");
        rejected("module x { x u {}; }", "E_MODULE_CYCLE");
        rejected("module x { missing u {}; }", "E_MODULE");
        rejected("module x { `for (`i=0; `i<1; `i=`i) { logic q_`i; } }", "E_META");
        rejected("module x { `if (4'bxxxx) { logic a; } }", "E_CONSTANT");
        slip::Options strict; strict.strict = true;
        rejected("module x { assign y=a; }", "E_IMPLICIT", strict);
        rejected("module x(a,y) { logic [7:0] a; logic [3:0] y; assign y=a; }", "E_SV", strict);
        rejected("module x(y) { logic [7:0] y; assign y=300; }", "E_SV", strict);
        rejected("module x { `if ('1) { logic y; } }", "E_CONSTANT");
        rejected("defun unsafe(s):\n    return open(s)\nmodule x {}", "E_FUNCTION");
        rejected("defun unsafe(s):\n    return s.__getattribute__(s)\nmodule x {}", "E_FUNCTION");
        auto local_loop = slip::compile("module m { logic [7:0] data; comb { for(i=0;i<4;i=i+1) { data=i; } } }");
        require(local_loop.modules.at("m").find("input logic i") == std::string::npos, "runtime loop variable is process-local");
        std::string deep = "module m(a,y) { assign y=a";
        for (unsigned i = 0; i < 300; ++i) deep += "+a";
        rejected(deep + "; }", "E_LIMIT");
        slip::Options bounded; bounded.max_meta_iterations = 2;
        rejected("module m { `for (`i=0;`i<3;`i=`i+1) { logic q_`i; } }", "E_LIMIT", bounded);
        auto width_warning = slip::compile("module m(y) { logic [7:0] y; assign y=300; }");
        require(!width_warning.warnings.empty(), "width loss is reported in default mode");
        auto wide_param = slip::compile("module m #(param MASK=128'hffffffffffffffffffffffffffffffff)(y) { logic [127:0] y; localparam VALUE=MASK; assign y=VALUE; }");
        require(wide_param.modules.at("m").find("128'hffffffffffffffffffffffffffffffff") != std::string::npos, "hardware parameters retain widths beyond meta integer limits");
        auto radix_names = slip::compile("module child #(param h1=0,param WIDTH=8'h1)(a,y) { logic [WIDTH-1:0] a; logic [WIDTH-1:0] y; assign y=a; } module top(a,y) { child u {.a,.y}; }");
        require(radix_names.modules.at("top").find("output logic [0:0] y") != std::string::npos, "parameter substitution does not rewrite radix digits");
        // Compiler state and function definitions must not leak across concurrent calls.
        auto one = std::async(std::launch::async, [] { return slip::compile("module a(i,o) { assign o=i; }"); });
        auto two = std::async(std::launch::async, [] { return slip::compile("module b(i,o) { assign o=~i; }"); });
        require(one.get().modules.contains("a") && two.get().modules.contains("b"), "concurrent compiler contexts");
    } catch (const std::exception& error) { ++failures; std::cerr << error.what() << '\n'; }
    return failures ? 1 : 0;
}
