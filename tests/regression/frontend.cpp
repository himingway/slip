#include "../test_support.hpp"

namespace {
std::string shape(const slip::ExprPtr& expr) {
    if (!expr) return "_";
    return std::visit(slip::Overloaded{
        [](const slip::Identifier& n) { return n.name; },
        [](const slip::Literal& n) { return n.text; },
        [](const slip::Binary& n) { return n.op + '(' + shape(n.left) + ',' + shape(n.right) + ')'; },
        [](const slip::Unary& n) { return n.op + '(' + shape(n.operand) + ')'; },
        [](const slip::Ternary& n) { return "?(" + shape(n.condition) + ',' + shape(n.yes) + ',' + shape(n.no) + ')'; },
        [](const slip::Select& n) { return "select(" + shape(n.base) + ',' + shape(n.first) + ',' + shape(n.last) + ')'; },
        [](const slip::Paren& n) { return shape(n.value); },
        [](const auto&) -> std::string { throw std::runtime_error("Unexpected AST kind"); }
    }, expr->node);
}
void tree(std::string_view source, std::string_view expected) {
    auto ast = slip::parse_expression(source);
    CHECK(shape(ast) == expected);
    CHECK(shape(slip::parse_expression(slip::to_sv(ast))) == expected);
}
}

TEST_CASE(precedence_multiplication) {
    tree("a+b*c", "+(a,*(b,c))");
    tree("a*b+c", "+(*(a,b),c)");
}
TEST_CASE(precedence_shift_addition) {
    tree("a+b<<c*d", "<<(+(a,b),*(c,d))");
    tree("a<<b+c", "<<(a,+(b,c))");
}
TEST_CASE(precedence_relation_equality) {
    tree("a==b<c", "==(a,<(b,c))");
    tree("a<b==c", "==(<(a,b),c)");
}
TEST_CASE(precedence_bitwise_logical) {
    tree("a|b^c&d", "|(a,^(b,&(c,d)))");
    tree("a||b&&c", "||(a,&&(b,c))");
    tree("a&b==c", "&(a,==(b,c))");
}
TEST_CASE(precedence_unary_power) {
    tree("-a**b", "**(-(a),b)");
    tree("a**b*c", "*(**(a,b),c)");
}
TEST_CASE(associativity_subtraction_division_power) {
    tree("a-b-c", "-(-(a,b),c)");
    tree("a/b/c", "/(/(a,b),c)");
    tree("a**b**c", "**(**(a,b),c)");
}
TEST_CASE(associativity_ternary) {
    tree("a?b:c?d:e", "?(a,b,?(c,d,e))");
    tree("a?b?c:d:e", "?(a,?(b,c,d),e)");
    tree("a||b?c:d", "?(||(a,b),c,d)");
}
TEST_CASE(parentheses_override_precedence) {
    tree("(a+b)*c", "*(+(a,b),c)");
    tree("a-(b-c)", "-(a,-(b,c))");
}
TEST_CASE(postfix_binds_before_unary) {
    tree("~a[i+1]", "~(select(a,+(i,1),_))");
    tree("a[7:0]+b[3]", "+(select(a,7,0),select(b,3,_))");
}
TEST_CASE(concatenation_replication_cast_nodes) {
    const auto concat = slip::parse_expression("{a,b[0]}");
    CHECK(std::get<slip::Concat>(concat->node).parts.size() == 2);
    const auto repeat = slip::parse_expression("{4{a}}");
    CHECK(std::get<slip::Literal>(std::get<slip::Repeat>(repeat->node).count->node).text == "4");
    const auto cast = slip::parse_expression("8'(a+b)");
    CHECK(std::get<slip::Cast>(cast->node).type == "8'");
}
TEST_CASE(four_state_literals_and_longest_operators) {
    for (auto value : {"8'hxF", "4'b10?z", "'0", "'1"})
        CHECK(std::get<slip::Literal>(slip::parse_expression(value)->node).text == value);
    tree("a===b", "===(a,b)");
    tree("a!==b", "!==(a,b)");
    tree("a<<<b", "<<<(a,b)");
    tree("a>>>b", ">>>(a,b)");
}
TEST_CASE(nested_comments_and_template_identifiers) {
    auto unit = slip::parse("/* a /* b */ c */ module m { `for (`i=0;`i<2;`i=`i+1) { logic a_`i; } }");
    CHECK(unit.modules.size() == 1);
    const auto& loop = std::get<slip::For>(unit.modules[0].body[0].node);
    CHECK(loop.meta);
    CHECK(std::get<slip::SignalDecl>(loop.body[0].node).name == "a_`i");
}
TEST_CASE(expression_rejects_trailing_tokens) {
    test::error([] { slip::parse_expression("a b", "expr.slip"); }, "E_PARSE", "trailing");
    test::error([] { slip::parse_expression("{}", "expr.slip"); }, "E_PARSE", "empty concatenation");
}
