#pragma once

#include <memory>
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
struct Select { ExprPtr base, first, last; bool slice = false; };
struct Concat { std::vector<ExprPtr> parts; };
struct Repeat { ExprPtr count, value; };
struct Call { std::string name; std::vector<ExprPtr> args; };
struct Method { ExprPtr object; std::string name; std::vector<ExprPtr> args; };
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
};
struct LocalParam { std::string name; ExprPtr value; };
struct Assignment { ExprPtr target, value; bool nonblocking = false; };
enum class ProcessKind { sequential, combinational, initial };
struct Process {
    ProcessKind kind;
    std::string clock, reset, edge;
    Body body;
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
struct Statement {
    Location loc;
    std::variant<SignalDecl, LocalParam, Assignment, Process, If, For, Case, Instance, Group> node;
};
struct PortDecl { std::string name; ExprPtr width; Location loc; };
struct Module {
    Location loc;
    std::string name;
    std::vector<NamedValue> parameters;
    std::vector<PortDecl> ports;
    Body body;
};
struct Function {
    Location loc;
    std::string name;
    std::vector<std::string> parameters;
    ExprPtr result;
};
struct Include { Location loc; std::string path; };
struct Unit {
    std::vector<Module> modules;
    std::vector<Function> functions;
    std::vector<Include> includes;
};

Unit parse(std::string_view source, std::string filename = "<input>");
ExprPtr parse_expression(std::string_view source, std::string filename = "<expression>");
std::string to_sv(const ExprPtr& expr);
std::string unquote(std::string_view text);
std::vector<std::string> references(const ExprPtr& expr);

} // namespace slip
