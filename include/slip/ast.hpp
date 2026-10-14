#pragma once

#include <memory>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace slip {

struct Location {
    std::string file = "<input>";
    unsigned line = 1;
    unsigned column = 1;
    std::string expansion = {}; // Metaprogram loop bindings at this source location.
};

class Error : public std::runtime_error {
public:
    Location location;
    std::string code;
    std::string message;
    Error(Location location, std::string code, std::string message);
};

struct Expr;
using ExprPtr = std::shared_ptr<const Expr>;
struct Identifier { std::string name; bool meta = false; };
struct Literal { std::string text; bool string = false; };
struct Unary { std::string op; ExprPtr operand; };
struct Binary { std::string op; ExprPtr left, right; };
struct Ternary { ExprPtr condition, yes, no; };
struct Select { ExprPtr base, first, last; bool slice = false; std::string indexed = {}; };
struct Concat { std::vector<ExprPtr> parts; };
struct Repeat { ExprPtr count, value; };
struct Call { std::string name; std::vector<ExprPtr> args; };
struct Method { ExprPtr object; std::string name; std::vector<ExprPtr> args; bool field = false; };
struct Paren { ExprPtr value; };
struct Cast { std::string type; ExprPtr value; };
struct Expr {
    Location loc;
    using Node = std::variant<Identifier, Literal, Unary, Binary, Ternary, Select,
                              Concat, Repeat, Call, Method, Paren, Cast>;
    Node node;
    unsigned depth = 1;
};
ExprPtr make_expression(Location loc, Expr::Node node);
template<class T> ExprPtr expression(Location loc, T value) {
    return make_expression(std::move(loc), Expr::Node{std::move(value)});
}
template<class... Ts> struct Overloaded : Ts... { using Ts::operator()...; };
template<class... Ts> Overloaded(Ts...) -> Overloaded<Ts...>;

struct Statement;
using Body = std::vector<Statement>;
struct SignalDecl {
    std::string name;
    ExprPtr width;
    ExprPtr array_first, array_last;
    bool is_signed = false;
    std::vector<std::pair<ExprPtr, ExprPtr>> dimensions = {};
    std::string type = "logic", direction = {};
};
struct LocalParam { std::string name; ExprPtr value; };
struct Assignment { ExprPtr target, value; bool nonblocking = false; };
enum class ProcessKind { sequential, combinational, initial };
struct Process {
    ProcessKind kind;
    std::string clock, reset, edge;
    Body body;
    std::string clock_edge = "pos";
};
struct If { ExprPtr condition; Body yes, no; bool meta = false; };
struct For {
    std::string variable, step_variable;
    ExprPtr init, condition, step;
    Body body;
    bool meta = false;
};
struct CaseArm { std::vector<ExprPtr> patterns; Body body; };
struct Case { std::string kind; ExprPtr value; std::vector<CaseArm> arms; };
struct NamedValue { std::string name; ExprPtr value; };
struct Connection {
    std::string port;
    ExprPtr value;
    std::string pattern, replacement;
    bool regex = false;
};
struct Instance {
    std::string module, name;
    std::vector<NamedValue> parameters;
    std::vector<Connection> connections;
};
struct Group { Body body; };
struct TypeDecl {
    std::string name, sv;
    std::vector<std::pair<std::string, ExprPtr>> constants = {};
};
struct Return { ExprPtr value; };
struct Assertion { ExprPtr condition; std::string message; bool compile_time = false; };
struct RTLFunction { SignalDecl result; std::vector<SignalDecl> arguments; Body body; };
struct BundleUse {
    std::string schema, name, role;
    std::vector<NamedValue> parameters;
    bool native = false;
    std::string modport;
    std::vector<Connection> connections;
};
struct Statement {
    Location loc;
    std::variant<SignalDecl, LocalParam, Assignment, Process, If, For, Case, Instance, Group,
                 TypeDecl, Return, Assertion, RTLFunction, BundleUse> node;
};
struct PortDecl { std::string name; ExprPtr width; Location loc; };
struct Module {
    Location loc;
    std::string name;
    std::vector<NamedValue> parameters;
    std::vector<PortDecl> ports;
    Body body;
    std::vector<std::pair<std::string, std::int64_t>> frozen = {};
};
struct Function {
    Location loc;
    std::string name;
    std::vector<std::string> parameters;
    ExprPtr result;
};
struct Include { Location loc; std::string path; };
struct BundleSchema { Location loc; std::string name; std::vector<NamedValue> parameters; std::vector<SignalDecl> fields; };
struct Unit {
    std::vector<Module> modules;
    std::vector<Function> functions;
    std::vector<Include> includes;
    std::vector<Statement> declarations = {};
    std::vector<BundleSchema> bundles = {};
};

Unit parse(std::string_view source, std::string filename = "<input>");
ExprPtr parse_expression(std::string_view source, std::string filename = "<expression>");
std::string to_sv(const ExprPtr& expr);
std::string unquote(std::string_view text);
std::vector<std::string> references(const ExprPtr& expr);

} // namespace slip
