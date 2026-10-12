#include "slip/compiler.hpp"
#include <cstdint>
#include <cstdlib>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
    if (!size || size > 8192) return 0;
    const std::string_view input(reinterpret_cast<const char*>(data), size);
    slip::Options options;
    options.max_meta_iterations = 64;
    options.max_expanded_statements = 512;
    options.max_include_depth = 4;
    try {
        const auto unit = slip::parse(input, "fuzz.slip");
        // Inputs are untrusted; the fuzz target never follows filesystem includes.
        if (unit.includes.empty()) slip::compile(input, "fuzz.slip", options);
    } catch (const slip::Error&) {}
    slip::ExprPtr expr;
    try { expr = slip::parse_expression(input, "fuzz.expr"); }
    catch (const slip::Error&) {}
    if (expr) {
        const auto printed = slip::to_sv(expr);
        const auto again = slip::to_sv(slip::parse_expression(printed, "roundtrip.expr"));
        if (printed != again) std::abort();
    }

    // Structured inputs keep exercising semantics even when byte mutations
    // fail lexing. Loop counts and widths are small and deterministic.
    const auto width = std::to_string(1 + data[0] % 16);
    const auto value = std::to_string(data[size/2] % 16);
    std::string source;
    switch (data[size-1] % 6) {
        case 0:
            source = "module m(a,y) { logic ["+width+"-1:0] a; logic ["+width+"-1:0] y; comb { y=0; for(i=0;i<4;i=i+1) { y=y+a; } } }";
            break;
        case 1:
            source = "module m(y) { logic ["+width+"-1:0] y; `for (`i=0;`i<"+width+";`i=`i+1) { assign y[`i]=1'b"+std::to_string(data[0]%2)+"; } }";
            break;
        case 2:
            source = "defun f(s):\n    return \"ok\" if "+value+" else \"no\"\nmodule leaf(p_x) { logic p_x; } module m { leaf u { \"p_(.*)\" => \"v_$f(\\1)\" }; }";
            break;
        case 3:
            source = "module leaf #(param W=8)(a,y) { logic [W-1:0] a; logic [W-1:0] y; assign y=a; } module m(a,y) { leaf #(.W("+width+")) u {.a,.y}; }";
            break;
        case 4:
            source = "module m(clk,a,y) { logic clk; logic ["+width+"-1:0] a; logic ["+width+"-1:0] y; seq(clk) { y=a+"+value+"; } }";
            break;
        default:
            source = "module m(a,y) { signed logic ["+width+"-1:0] a; signed logic ["+width+"-1:0] y; assign y=a >>> "+std::to_string(data[0]%4)+"; }";
    }
    // Every structured program is valid. Failure here is a compiler regression,
    // not an expected rejection of a randomly corrupted input.
    const auto first = slip::compile(source, "structured.slip", options);
    const auto second = slip::compile(source, "structured.slip", options);
    if (first.modules != second.modules || first.modules.empty()) std::abort();
    return 0;
}
