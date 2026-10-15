#include "internal.hpp"
#include <algorithm>
#include <cctype>
#include <fstream>
#include <sstream>

namespace slip {

ExprPtr make_expression(Location loc, Expr::Node node) {
    unsigned depth = 0;
    auto add = [&](const ExprPtr& value) { if (value) depth = std::max(depth, value->depth); };
    std::visit(Overloaded{
        [](const Identifier&) {}, [](const Literal&) {},
        [&](const Unary& value) { add(value.operand); },
        [&](const Binary& value) { add(value.left); add(value.right); },
        [&](const Ternary& value) { add(value.condition); add(value.yes); add(value.no); },
        [&](const Select& value) { add(value.base); add(value.first); add(value.last); },
        [&](const Concat& value) { for (auto& part : value.parts) add(part); },
        [&](const Repeat& value) { add(value.count); add(value.value); },
        [&](const Call& value) { for (auto& arg : value.args) add(arg); },
        [&](const Method& value) { add(value.object); for (auto& arg : value.args) add(arg); },
        [&](const Paren& value) { add(value.value); },
        [&](const Cast& value) { add(value.value); }
    }, node);
    if (++depth > 256) throw Error(loc, "E_LIMIT", "expression tree depth limit exceeded");
    return std::make_shared<const Expr>(Expr{std::move(loc), std::move(node), depth});
}

Error::Error(Location where, std::string id, std::string message)
    : std::runtime_error(where.file + ":" + std::to_string(where.line) + ":" +
                         std::to_string(where.column) + ": " + id + ": " + message),
      location(std::move(where)), code(std::move(id)), message(std::move(message)) {}

std::string read_file(const std::filesystem::path& file) {
    std::ifstream input(file, std::ios::binary);
    if (!input) throw Error({file.string()}, "E_IO", "cannot read file");
    std::ostringstream text;
    text << input.rdbuf();
    if (input.bad()) throw Error({file.string()}, "E_IO", "failed while reading file");
    return text.str();
}
std::string join(const std::vector<std::string>& parts, std::string_view delimiter) {
    std::string result;
    for (const auto& part : parts) {
        if (!result.empty()) result += delimiter;
        result += part;
    }
    return result;
}
std::string trim(std::string_view value) {
    auto first = value.find_first_not_of(" \t\n\r");
    if (first == value.npos) return {};
    return std::string(value.substr(first, value.find_last_not_of(" \t\n\r") - first + 1));
}
std::string unquote(std::string_view text) {
    if (text.size() < 2) return std::string(text);
    std::string result;
    for (std::size_t i = 1; i + 1 < text.size(); ++i) {
        char ch = text[i];
        if (ch == '\\' && i + 2 < text.size()) {
            ch = text[++i];
            switch (ch) {
                case 'n': ch = '\n'; break;
                case 'r': ch = '\r'; break;
                case 't': ch = '\t'; break;
                case '\\': case '"': break;
                default: result += '\\'; break;
            }
        }
        result += ch;
    }
    return result;
}

namespace {
enum class TokenKind { name, number, string, symbol, meta, end };
struct Token { TokenKind kind; std::string text; Location loc; };
bool alpha(char ch) { return std::isalpha(static_cast<unsigned char>(ch)) || ch == '_'; }
bool digit(char ch) { return std::isdigit(static_cast<unsigned char>(ch)); }
bool alnum(char ch) { return alpha(ch) || digit(ch); }
const std::set<std::string> keywords = {
    "module", "param", "localparam", "logic", "signed", "assign", "seq", "comb",
    "initial", "pos", "neg", "if", "else", "for", "case", "casez", "casex",
    "default", "inside", "defun", "return", "include", "typedef", "enum", "struct", "packed",
    "function", "automatic", "assert", "static_assert", "bundle", "master", "slave", "bus", "input", "output", "inout", "int", "bit", "interface"
};
std::vector<Token> lex(std::string_view source, const std::string& filename) {
    std::vector<Token> tokens;
    std::size_t pos = 0;
    Location loc{filename};
    auto advance = [&] {
        if (source[pos++] == '\n') { ++loc.line; loc.column = 1; }
        else ++loc.column;
    };
    const std::vector<std::string> operators = {
        "<<<=", ">>>=", "<<=", ">>=", "===", "!==", "<<<", ">>>", "=>", "<=", ">=",
        "::", "(*", "*)", "+:", "-:", "==", "!=", "<<", ">>", "**", "&&", "||", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^="
    };
    while (pos < source.size()) {
        if (std::isspace(static_cast<unsigned char>(source[pos]))) { advance(); continue; }
        if (source.substr(pos, 2) == "//") {
            while (pos < source.size() && source[pos] != '\n') advance();
            continue;
        }
        if (source.substr(pos, 2) == "/*") {
            auto start = loc;
            unsigned depth = 1;
            advance(); advance();
            while (pos < source.size() && depth) {
                if (source.substr(pos, 2) == "/*") { ++depth; advance(); advance(); }
                else if (source.substr(pos, 2) == "*/") { --depth; advance(); advance(); }
                else advance();
            }
            if (depth) throw Error(start, "E_LEX", "unterminated block comment");
            continue;
        }
        auto start = pos;
        auto start_loc = loc;
        TokenKind kind = TokenKind::symbol;
        if (source[pos] == '"') {
            kind = TokenKind::string;
            advance();
            while (pos < source.size() && source[pos] != '"') {
                if (source[pos] == '\\') { advance(); if (pos == source.size()) break; }
                advance();
            }
            if (pos == source.size()) throw Error(start_loc, "E_LEX", "unterminated string literal");
            advance();
        } else if (digit(source[pos]) || (source[pos] == '\'' && pos + 1 < source.size() && std::string_view("bBdDhHoOsS").find(source[pos + 1]) != std::string_view::npos)) {
            kind = TokenKind::number;
            while (pos < source.size() && (digit(source[pos]) || source[pos] == '_')) advance();
            auto radix_pos = pos + 1;
            if (radix_pos < source.size() && (source[radix_pos] == 's' || source[radix_pos] == 'S')) ++radix_pos;
            if (pos < source.size() && source[pos] == '\'' && radix_pos < source.size() &&
                std::string_view("bBdDhHoO").find(source[radix_pos]) != std::string_view::npos) {
                advance();
                if (source[pos] == 's' || source[pos] == 'S') advance();
                char radix = static_cast<char>(std::tolower(source[pos]));
                advance();
                auto digits_start = pos;
                std::string_view valid = radix == 'b' ? "01" : radix == 'o' ? "01234567" :
                                         radix == 'd' ? "0123456789" : "0123456789abcdefABCDEF";
                bool actual_digit = false;
                while (pos < source.size() && (alnum(source[pos]) || source[pos] == '?')) {
                    char ch = source[pos];
                    if (ch != '_') actual_digit = true;
                    if (valid.find(ch) == valid.npos && std::string_view("_xXzZ?").find(ch) == std::string_view::npos)
                        throw Error(start_loc, "E_LEX", "invalid digit in integer literal");
                    advance();
                }
                if (pos == digits_start || !actual_digit) throw Error(start_loc, "E_LEX", "integer literal has no digits");
            }
            if (pos == start) throw Error(start_loc, "E_LEX", "invalid based integer literal");
        } else if (alpha(source[pos]) || source[pos] == '$') {
            kind = TokenKind::name;
            if (source[pos] == '$') advance();
            if (pos == source.size() || !alpha(source[pos])) throw Error(start_loc, "E_LEX", "invalid identifier");
            while (pos < source.size() && alnum(source[pos])) advance();
        } else if (source[pos] == '`') {
            kind = TokenKind::meta;
            advance();
            while (pos < source.size() && std::isspace(static_cast<unsigned char>(source[pos]))) advance();
            if (pos == source.size() || !alpha(source[pos])) throw Error(start_loc, "E_LEX", "expected name after backtick");
            while (pos < source.size() && alnum(source[pos])) advance();
        } else if (source[pos] == '\'' && pos + 1 < source.size() && std::string_view("01xXzZ").find(source[pos + 1]) != std::string_view::npos) {
            kind = TokenKind::number; advance(); advance();
        } else {
            bool matched = false;
            for (const auto& op : operators) {
                if (source.substr(pos, op.size()) == op) {
                    for (std::size_t i = 0; i < op.size(); ++i) advance();
                    matched = true; break;
                }
            }
            if (!matched) {
                if (std::string_view("=<>+-*/%!~&|^?'@{}[]();:,.#").find(source[pos]) == std::string_view::npos)
                    throw Error(start_loc, "E_LEX", "unexpected character");
                advance();
            }
        }
        if (tokens.size() >= 1000000) throw Error(start_loc, "E_LIMIT", "source token limit exceeded");
        std::string text(source.substr(start, pos - start));
        if (kind == TokenKind::meta) text = "`" + trim(std::string_view(text).substr(1));
        if (kind == TokenKind::meta && !tokens.empty() && tokens.back().kind == TokenKind::name &&
            !keywords.contains(tokens.back().text)) tokens.back().text += text;
        else tokens.push_back({kind, std::move(text), start_loc});
    }
    tokens.push_back({TokenKind::end, "", loc});
    return tokens;
}

int precedence(std::string_view op) {
    if (op == "?") return 1;
    if (op == "||") return 2;
    if (op == "&&") return 3;
    if (op == "|") return 4;
    if (op == "^") return 5;
    if (op == "&") return 6;
    if (op == "==" || op == "!=" || op == "===" || op == "!==") return 7;
    if (op == "<" || op == ">" || op == "<=" || op == ">=" || op == "inside") return 8;
    if (op == "<<" || op == ">>" || op == "<<<" || op == ">>>") return 9;
    if (op == "+" || op == "-") return 10;
    if (op == "*" || op == "/" || op == "%") return 11;
    if (op == "**") return 12;
    return 0;
}

class Parser {
    std::vector<Token> tokens;
    std::size_t pos = 0;
    unsigned nesting = 0;
    bool function_context = false;
    struct Depth {
        unsigned& value;
        explicit Depth(unsigned& value, const Location& loc) : value(value) {
            if (++value > 256) throw Error(loc, "E_LIMIT", "syntax nesting limit exceeded");
        }
        ~Depth() { --value; }
    };
    const Token& peek(std::size_t offset = 0) const { return tokens[std::min(pos + offset, tokens.size() - 1)]; }
    Token take() { auto value = peek(); if (value.kind != TokenKind::end) ++pos; return value; }
    bool eat(std::string_view text) { if (peek().text != text) return false; take(); return true; }
    Token expect(std::string_view text) {
        auto tok = take();
        if (tok.kind == TokenKind::end || tok.text != text)
            throw Error(tok.loc, "E_PARSE", "expected '" + std::string(text) + "', got '" + tok.text + "'");
        return tok;
    }
    Token name(bool meta = false) {
        auto tok = take();
        if (!meta && tok.kind == TokenKind::meta)
            throw Error(tok.loc, "E_PARSE", "metaprogram variable '" + tok.text + "' requires `for (with a backtick); a procedural for inside comb/seq uses plain identifiers");
        if (meta && tok.kind == TokenKind::name)
            throw Error(tok.loc, "E_PARSE", "compile-time `for requires a backtick variable, such as `i");
        if (tok.kind != (meta ? TokenKind::meta : TokenKind::name) || keywords.contains(tok.text))
            throw Error(tok.loc, "E_PARSE", "expected identifier, got '" + tok.text + "'");
        if (meta) tok.text.erase(0, 1);
        return tok;
    }
    Token member_name() {
        auto tok = take();
        if (tok.kind != TokenKind::name) throw Error(tok.loc, "E_PARSE", "expected member identifier, got '" + tok.text + "'");
        return tok;
    }
    std::vector<ExprPtr> args() {
        expect("(");
        std::vector<ExprPtr> values;
        if (!eat(")")) { do { values.push_back(expr()); } while (eat(",")); expect(")"); }
        return values;
    }
    ExprPtr width() {
        expect("[");
        auto first = expr();
        if (eat(":")) first = expression(first->loc, Binary{":", first, expr()});
        expect("]"); return first;
    }
    ExprPtr primary() {
        auto tok = take();
        if (tok.kind == TokenKind::name) while (eat("::")) tok.text += "::" + member_name().text;
        if (tok.text == "+" || tok.text == "-" || tok.text == "!" || tok.text == "~" ||
            tok.text == "&" || tok.text == "|" || tok.text == "^")
            return expression(tok.loc, Unary{tok.text, expr(13)});
        if (tok.text == "(") { auto value = expr(); expect(")"); return expression(tok.loc, Paren{value}); }
        if (tok.text == "{") {
            if (peek().text == "}") throw Error(tok.loc, "E_PARSE", "empty concatenation is not allowed");
            auto first = expr();
            if (eat("{")) {
                auto value = expr(); expect("}"); expect("}");
                return expression(tok.loc, Repeat{first, value});
            }
            std::vector<ExprPtr> parts{first};
            while (eat(",")) parts.push_back(expr());
            expect("}"); return expression(tok.loc, Concat{std::move(parts)});
        }
        if ((tok.kind == TokenKind::number || tok.kind == TokenKind::name) && eat("'")) {
            expect("("); auto value = expr(); expect(")");
            return expression(tok.loc, Cast{tok.text + "'", value});
        }
        if (tok.kind == TokenKind::number || tok.kind == TokenKind::string)
            return expression(tok.loc, Literal{tok.text, tok.kind == TokenKind::string});
        if (tok.kind == TokenKind::meta && tok.text != "`for" && tok.text != "`if" && tok.text != "`else")
            return expression(tok.loc, Identifier{tok.text.substr(1), true});
        if (tok.kind == TokenKind::name && (!keywords.contains(tok.text) || (function_context && tok.text == "int")) && tok.text != "unsigned")
            return expression(tok.loc, Identifier{tok.text});
        throw Error(tok.loc, "E_PARSE", "unexpected token '" + tok.text + "' in expression");
    }
    Body block() {
        Depth guard(nesting, peek().loc);
        expect("{"); Body body;
        while (!eat("}")) {
            if (peek().kind == TokenKind::end) throw Error(peek().loc, "E_PARSE", "unterminated block");
            body.push_back(statement());
        }
        return body;
    }
    Body branch() { if (peek().text == "{") return block(); return {statement()}; }
    ExprPtr type_value() {
        const auto start = peek();
        auto text = member_name().text;
        while (eat("::")) text += "::" + member_name().text;
        if (peek().text == "signed" || peek().text == "unsigned") text += " " + take().text;
        while (peek().text == "[") {
            const auto value = width();
            if (const auto* range = std::get_if<Binary>(&value->node); range && range->op == ":") text += " [" + to_sv(range->left) + ":" + to_sv(range->right) + "]";
            else text += " [" + to_sv(value) + "-1:0]";
        }
        return expression(start.loc, Literal{text});
    }
    NamedValue parameter(bool module) {
        if (module) {
            expect("param"); const bool type = eat("type"); auto tok = name(); expect("="); return {tok.text, type ? type_value() : expr(), type};
        }
        expect("."); auto tok = name(); expect("(");
        const bool type = peek().text == "logic" || peek().text == "bit" || peek().text == "int";
        auto value = type ? type_value() : expr(); expect(")"); return {tok.text, value, type};
    }
    std::vector<NamedValue> attributes() {
        std::vector<NamedValue> result;
        while (eat("(*")) {
            do {
                const auto attribute = member_name();
                result.push_back({attribute.text, eat("=") ? expr() : ExprPtr{}});
            } while (eat(","));
            expect("*)");
        }
        return result;
    }
    bool assignable(const ExprPtr& value) {
        if (auto id = std::get_if<Identifier>(&value->node)) return id->name != "_";
        if (auto select = std::get_if<Select>(&value->node)) return assignable(select->base);
        if (auto field = std::get_if<Method>(&value->node)) return field->field && assignable(field->object);
        if (auto group = std::get_if<Paren>(&value->node)) return assignable(group->value);
        if (auto concat = std::get_if<Concat>(&value->node)) return std::all_of(concat->parts.begin(), concat->parts.end(), [&](auto& part) { return assignable(part); });
        return false;
    }
    SignalDecl declaration() {
        SignalDecl value;
        value.type_explicit = false;
        if (peek().text == "input" || peek().text == "output" || peek().text == "inout") value.direction = take().text;
        value.is_signed = eat("signed");
        if (peek().text == "logic" || peek().text == "bit" || peek().text == "int" ||
            (peek().kind == TokenKind::name && (peek(1).kind == TokenKind::name || peek(1).text == "::"))) {
            value.type = take().text;
            while (eat("::")) value.type += "::" + member_name().text;
            value.type_explicit = true;
        }
        if (eat("signed")) value.is_signed = true;
        if (peek().text == "[") value.width = width();
        value.name = name().text;
        while (eat("[")) {
            auto first = expr(); expect(":"); auto last = expr(); expect("]");
            if (!value.array_first) { value.array_first = first; value.array_last = last; }
            else value.dimensions.emplace_back(first, last);
        }
        return value;
    }
    std::string type_text(const SignalDecl& value) {
        auto text = value.type + (value.is_signed ? " signed" : "");
        if (value.width) {
            if (auto range = std::get_if<Binary>(&value.width->node); range && range->op == ":")
                text += " [" + to_sv(range->left) + ":" + to_sv(range->right) + "]";
            else text += " [" + to_sv(value.width) + "-1:0]";
        }
        return text;
    }
    Statement type_declaration();
    RTLFunction hardware_function() {
        eat("automatic");
        RTLFunction function; function.result = declaration(); expect("(");
        if (!eat(")")) {
            do {
                auto arg = declaration();
                if (!arg.direction.empty() && arg.direction != "input") throw Error(peek().loc, "E_FUNCTION", "RTL function arguments must be inputs");
                function.arguments.push_back(std::move(arg));
            } while (eat(","));
            expect(")");
        }
        function.body = block();
        return function;
    }
    Assignment assignment() {
        auto target = expr(14);
        if (!assignable(target)) throw Error(target->loc, "E_PARSE", "assignment requires an assignable target");
        auto op = take();
        auto value = expr();
        if (op.text != "=" && op.text != "<=") {
            if (op.text.size() < 2 || op.text.back() != '=' || !precedence(op.text.substr(0, op.text.size() - 1)))
                throw Error(op.loc, "E_PARSE", "expected assignment operator");
            value = expression(op.loc, Binary{op.text.substr(0, op.text.size() - 1), target, value});
        }
        expect(";"); return {target, value, op.text == "<="};
    }
    Statement statement() {
        Depth guard(nesting, peek().loc);
        auto start = peek();
        if (peek().text == "(*") {
            const auto values = attributes();
            auto result = statement();
            std::function<void(Statement&)> attach = [&](Statement& item) {
                std::visit([&](auto& node) {
                    if constexpr (requires { node.attributes; }) node.attributes.insert(node.attributes.begin(), values.begin(), values.end());
                    else if constexpr (std::is_same_v<std::decay_t<decltype(node)>, Group>) for (auto& child : node.body) attach(child);
                    else throw Error(start.loc, "E_ATTRIBUTE", "attributes apply to modules, signals, instances and processes");
                }, item.node);
            };
            attach(result); return result;
        }
        if (peek().text == "typedef" || peek().text == "enum" || peek().text == "struct") return type_declaration();
        if (eat("function")) return {start.loc, hardware_function()};
        if (eat("return")) { auto value = expr(); expect(";"); return {start.loc, Return{value}}; }
        if (peek().text == "assert" || peek().text == "static_assert") {
            bool compile_time = take().text == "static_assert"; expect("("); auto condition = expr(); std::string message;
            if (eat(",")) { auto text = take(); if (text.kind != TokenKind::string) throw Error(text.loc, "E_PARSE", "assertion message must be a string"); message = text.text; }
            expect(")"); expect(";"); return {start.loc, Assertion{condition, message, compile_time}};
        }
        if (peek().text == "master" || peek().text == "slave" || peek().text == "bus" || peek().text == "interface") {
            BundleUse use; use.role = take().text; use.native = use.role == "interface"; use.schema = name().text;
            if (use.native && eat(".")) use.modport = member_name().text;
            if (eat("#")) { expect("("); if (!eat(")")) { do { use.parameters.push_back(parameter(false)); } while(eat(",")); expect(")"); } }
            use.name = name().text;
            while (use.native && eat("[")) {
                auto first = expr(); ExprPtr last;
                if (eat(":")) last = expr();
                else { last = expression(first->loc, Binary{"-", first, expression(first->loc, Literal{"1"})}); first = expression(first->loc, Literal{"0"}); }
                expect("]"); use.dimensions.emplace_back(first, last);
            }
            if (use.native && eat("{")) {
                if (!eat("}")) {
                    do {
                        expect("."); Connection connection; connection.port = member_name().text;
                        if (eat("(")) { connection.value = expr(); expect(")"); }
                        use.connections.push_back(std::move(connection));
                    } while (eat(","));
                    expect("}");
                }
            }
            expect(";"); return {start.loc, std::move(use)};
        }
        if (eat("localparam")) {
            Body declarations;
            do { auto tok = name(); expect("="); declarations.push_back({tok.loc, LocalParam{tok.text, expr()}}); } while (eat(","));
            expect(";"); return {start.loc, Group{std::move(declarations)}};
        }
        if (eat("assign")) return {start.loc, assignment()};
        if (peek().text == "seq" || peek().text == "comb" || peek().text == "initial") {
            auto kind = take().text;
            Process process{kind == "seq" ? ProcessKind::sequential : kind == "comb" ? ProcessKind::combinational : ProcessKind::initial, {}, {}, {}, {}};
            if (kind == "seq") {
                expect("(");
                if (peek().text == "pos" || peek().text == "neg") { process.clock_edge = take().text; expect(":"); }
                process.clock = to_sv(expr(14));
                if (eat(",")) {
                    auto edge = take();
                    if (edge.text != "pos" && edge.text != "neg") throw Error(edge.loc, "E_PARSE", "expected pos or neg reset edge");
                    process.edge = edge.text; expect(":"); process.reset = to_sv(expr(14));
                }
                expect(")");
            }
            process.body = block(); return {start.loc, std::move(process)};
        }
        if (peek().text == "if" || peek().text == "`if") {
            bool meta = take().text == "`if";
            expect("("); auto condition = expr(); expect(")");
            auto yes = meta ? block() : branch(); Body no;
            if (eat(meta ? "`else" : "else")) no = meta ? block() : branch();
            return {start.loc, If{condition, std::move(yes), std::move(no), meta}};
        }
        if (peek().text == "for" || peek().text == "`for") {
            bool meta = take().text == "`for";
            expect("(");
            if (!meta && (peek().text == "int" || peek().text == "integer")) take();
            auto var = name(meta); expect("="); auto init = expr(); expect(";");
            auto condition = expr(); expect(";"); auto step_var = name(meta); auto op = take();
            ExprPtr step;
            if ((op.text == "+" || op.text == "-") && eat(op.text))
                step = expression(op.loc, Binary{op.text, expression(op.loc, Identifier{step_var.text, meta}), expression(op.loc, Literal{"1"})});
            else {
                step = expr();
                if (op.text != "=") {
                    if (op.text.size() < 2 || op.text.back() != '=' || !precedence(op.text.substr(0, op.text.size() - 1)))
                        throw Error(op.loc, "E_PARSE", "invalid loop step");
                    step = expression(op.loc, Binary{op.text.substr(0, op.text.size() - 1), expression(op.loc, Identifier{step_var.text, meta}), step});
                }
            }
            expect(")"); return {start.loc, For{var.text, step_var.text, init, condition, step, block(), meta}};
        }
        if (peek().text == "case" || peek().text == "casez" || peek().text == "casex") {
            auto kind = take().text; expect("("); auto value = expr(); expect(")"); expect("{");
            std::vector<CaseArm> arms;
            while (!eat("}")) {
                std::vector<ExprPtr> patterns;
                if (!eat("default")) { do { patterns.push_back(expr()); } while (eat(",")); }
                expect(":"); arms.push_back({std::move(patterns), branch()});
            }
            return {start.loc, Case{kind, value, std::move(arms)}};
        }
        if (peek().kind == TokenKind::name && !keywords.contains(peek().text) &&
            ((peek(1).kind == TokenKind::name && !keywords.contains(peek(1).text) && peek(2).text == "{") || peek(1).text == "#")) {
            Instance instance;
            instance.module = name().text;
            if (eat("#")) {
                expect("(");
                if (!eat(")")) { do { instance.parameters.push_back(parameter(false)); } while (eat(",")); expect(")"); }
            }
            instance.name = name().text; expect("{");
            if (!eat("}")) {
                do {
                    if (peek().text == "}") break;
                    Connection connection;
                    if (peek().kind == TokenKind::string) {
                        // Replacement backslashes are templates, not string escape sequences.
                        auto pattern = take(); expect("=>"); auto replacement = take();
                        if (replacement.kind != TokenKind::string) throw Error(replacement.loc, "E_PARSE", "expected replacement string");
                        connection.regex = true;
                        connection.pattern = pattern.text.substr(1, pattern.text.size() - 2);
                        connection.replacement = replacement.text.substr(1, replacement.text.size() - 2);
                    } else {
                        expect("."); connection.port = member_name().text;
                        if (eat("(")) { connection.value = expr(); expect(")"); }
                    }
                    instance.connections.push_back(std::move(connection));
                } while (eat(","));
                expect("}");
            }
            expect(";"); return {start.loc, std::move(instance)};
        }
        if (peek().text == "{") return {start.loc, assignment()};
        if (peek().kind == TokenKind::name && !keywords.contains(peek().text) &&
            (peek(1).text == "." || peek(1).text == "=" || peek(1).text == "<=" || peek(1).text == "[" ||
             (peek(1).text.size() > 1 && peek(1).text.back() == '='))) return {start.loc, assignment()};
        auto signal = declaration();
        Body declarations{{start.loc, signal}};
        while (eat(",")) {
            auto copy = signal;
            const auto identifier = name(); copy.name = identifier.text;
            copy.array_first = {}; copy.array_last = {}; copy.dimensions.clear();
            while (eat("[")) {
                auto first = expr(); expect(":"); auto last = expr(); expect("]");
                if (!copy.array_first) { copy.array_first = first; copy.array_last = last; }
                else copy.dimensions.emplace_back(first, last);
            }
            declarations.push_back({identifier.loc, std::move(copy)});
        }
        expect(";");
        if (declarations.size() == 1) return declarations.front();
        return {start.loc, Group{std::move(declarations)}};
    }
public:
    Parser(std::string_view source, const std::string& filename) : tokens(lex(source, filename)) {}
    ExprPtr expr(int min_precedence = 1) {
        Depth guard(nesting, peek().loc);
        auto left = primary();
        while (true) {
            auto tok = peek();
            if (function_context && tok.text == "if" && min_precedence == 1) {
                take(); auto condition = expr(2); expect("else");
                left = expression(tok.loc, Ternary{condition, left, expr()});
                continue;
            }
            if (tok.text == "[" && min_precedence <= 14) {
                take(); ExprPtr first, last;
                if (peek().text != ":") first = expr();
                std::string indexed;
                if (peek().text == "+:" || peek().text == "-:") indexed = take().text;
                bool slice = !indexed.empty() || eat(":");
                if (slice && peek().text != "]") last = expr();
                expect("]"); left = expression(tok.loc, Select{left, first, last, slice, indexed}); continue;
            }
            if (tok.text == "(" && min_precedence <= 14) {
                auto id = std::get_if<Identifier>(&left->node);
                if (!id || id->meta) throw Error(tok.loc, "E_PARSE", "function call requires an identifier");
                left = expression(tok.loc, Call{id->name, args()}); continue;
            }
            if (tok.text == "." && min_precedence <= 14) {
                take(); auto method = member_name(); bool field = peek().text != "(";
                left = expression(tok.loc, Method{left, method.text, field ? std::vector<ExprPtr>{} : args(), field}); continue;
            }
            int level = precedence(tok.text);
            if (!level || level < min_precedence) break;
            take();
            if (tok.text == "?") {
                auto yes = expr(); expect(":"); left = expression(tok.loc, Ternary{left, yes, expr(level)});
            } else left = expression(tok.loc, Binary{tok.text, left, expr(level + 1)});
        }
        return left;
    }
    ExprPtr whole_expression() {
        auto result = expr();
        if (peek().kind != TokenKind::end) throw Error(peek().loc, "E_PARSE", "unexpected trailing expression tokens");
        return result;
    }
    ExprPtr whole_type() {
        auto result = type_value();
        if (peek().kind != TokenKind::end) throw Error(peek().loc, "E_PARSE", "unexpected trailing type tokens");
        return result;
    }
    Unit unit() {
        Unit result;
        while (peek().kind != TokenKind::end) {
            const auto module_attributes = attributes();
            auto tok = take();
            if (!module_attributes.empty() && tok.text != "module") throw Error(tok.loc, "E_ATTRIBUTE", "top-level attributes require a module");
            if (tok.text == "include") {
                auto path = take();
                if (path.kind != TokenKind::string) throw Error(path.loc, "E_PARSE", "expected include path");
                expect(";"); result.includes.push_back({tok.loc, unquote(path.text)}); continue;
            }
            if (tok.text == "typedef" || tok.text == "enum" || tok.text == "struct" || tok.text == "function") {
                --pos; result.declarations.push_back(statement()); continue;
            }
            if (tok.text == "bundle") {
                BundleSchema schema; schema.loc = tok.loc; schema.name = name().text;
                if (eat("#")) { expect("("); if (!eat(")")) { do { schema.parameters.push_back(parameter(true)); } while(eat(",")); expect(")"); } }
                expect("{");
                while (!eat("}")) {
                    auto field = declaration(); expect(";");
                    if (field.direction != "input" && field.direction != "output") throw Error(tok.loc, "E_BUNDLE", "bundle fields require input or output directions as seen by a master");
                    schema.fields.push_back(std::move(field));
                }
                eat(";"); result.bundles.push_back(std::move(schema)); continue;
            }
            if (tok.text == "defun") {
                Function function{tok.loc, name().text, {}, {}};
                expect("(");
                if (!eat(")")) { do { function.parameters.push_back(name().text); } while (eat(",")); expect(")"); }
                expect(":");
                function_context = true;
                while (peek().kind != TokenKind::end && peek().loc.column > tok.loc.column) {
                    expect("return"); auto value = expr(); eat(";");
                    if (!function.result) function.result = value;
                }
                function_context = false;
                if (!function.result) throw Error(tok.loc, "E_FUNCTION", "function has no return statement");
                result.functions.push_back(std::move(function)); continue;
            }
            if (tok.text != "module") throw Error(tok.loc, "E_PARSE", "expected module, include or defun");
            Module module{tok.loc, name().text, {}, {}, {}};
            module.attributes = module_attributes;
            if (eat("#")) {
                expect("(");
                if (!eat(")")) { do { module.parameters.push_back(parameter(true)); } while (eat(",")); expect(")"); }
            }
            if (eat("(")) {
                if (!eat(")")) {
                    do { auto port = name(); ExprPtr dimension; if (peek().text == "[") dimension = width(); module.ports.push_back({port.text, dimension, port.loc}); } while (eat(","));
                    expect(")");
                }
            }
            module.body = block(); result.modules.push_back(std::move(module));
        }
        return result;
    }
};

Statement Parser::type_declaration() {
    auto loc = peek().loc;
    bool alias = eat("typedef");
    TypeDecl type;
    std::string body;
    if (eat("enum")) {
        SignalDecl base; base.type = "int";
        if (peek().text == "logic" || peek().text == "bit" || peek().text == "int") base.type = take().text;
        if (eat("signed")) base.is_signed = true;
        if (peek().text == "[") { base.width = width(); if (base.type == "int") base.type = "logic"; }
        expect("{"); std::vector<std::string> entries; ExprPtr previous;
        do {
            auto item = name();
            ExprPtr value;
            if (eat("=")) value = expr();
            else value = previous ? expression(item.loc, Binary{"+", previous, expression(item.loc, Literal{"1"})}) : expression(item.loc, Literal{"0"});
            entries.push_back(item.text + " = " + to_sv(value));
            type.constants.emplace_back(item.text, value);
            previous = expression(item.loc, Identifier{item.text});
        } while (eat(",") && peek().text != "}");
        expect("}");
        body = "enum " + type_text(base) + " {" + join(entries, ", ") + "}";
    } else if (eat("struct")) {
        expect("packed"); expect("{"); std::vector<std::string> fields;
        while (!eat("}")) {
            auto field = declaration(); expect(";");
            if (!field.direction.empty() || field.array_first) throw Error(loc, "E_TYPE", "packed struct fields must be packed data without port directions");
            fields.push_back(type_text(field) + " " + field.name + ";");
        }
        if (fields.empty()) throw Error(loc, "E_TYPE", "packed struct requires at least one field");
        body = "struct packed {" + join(fields, " ") + "}";
    } else {
        if (!alias) throw Error(loc, "E_PARSE", "expected enum or struct");
        auto value = declaration(); expect(";");
        type.name = value.name; type.sv = "typedef " + type_text(value) + " " + value.name + ";";
        return {loc, std::move(type)};
    }
    auto last = name(); expect(";");
    type.name = alias ? last.text : "__slip_type_" + std::to_string(loc.line) + "_" + std::to_string(loc.column);
    type.sv = "typedef " + body + " " + type.name + ";";
    if (alias) return {loc, std::move(type)};
    SignalDecl signal; signal.name = last.text; signal.type = type.name;
    return {loc, Group{Body{{loc, std::move(type)}, {last.loc, std::move(signal)}}}};
}

int expression_level(const ExprPtr& expr) {
    if (auto binary = std::get_if<Binary>(&expr->node)) return precedence(binary->op);
    if (std::holds_alternative<Ternary>(expr->node)) return 1;
    if (std::holds_alternative<Unary>(expr->node)) return 13;
    return 99;
}
std::string serialize(const ExprPtr& expr, int context) {
    if (!expr) return {};
    auto sv = [](const ExprPtr& value, int level = 0) { return serialize(value, level); };
    auto args = [&](const std::vector<ExprPtr>& values) {
        std::vector<std::string> text; for (const auto& value : values) text.push_back(sv(value)); return join(text, ", ");
    };
    auto text = std::visit(Overloaded{
        [](const Identifier& node) { return (node.meta ? "`" : "") + node.name; },
        [](const Literal& node) { return node.text; },
        [&](const Unary& node) { return node.op + sv(node.operand, 14); },
        [&](const Binary& node) { return sv(node.left, precedence(node.op)) + " " + node.op + " " + sv(node.right, precedence(node.op) + 1); },
        [&](const Ternary& node) { return sv(node.condition, 2) + " ? " + sv(node.yes) + " : " + sv(node.no); },
        [&](const Select& node) { return sv(node.base, 99) + "[" + sv(node.first) + (node.slice ? (node.indexed.empty() ? ":" : " " + node.indexed + " ") + sv(node.last) : "") + "]"; },
        [&](const Concat& node) { return "{" + args(node.parts) + "}"; },
        [&](const Repeat& node) { return "{" + sv(node.count) + "{" + sv(node.value) + "}}"; },
        [&](const Call& node) { return node.name + "(" + args(node.args) + ")"; },
        [&](const Method& node) { return sv(node.object) + "." + node.name + (node.field ? "" : "(" + args(node.args) + ")"); },
        [&](const Paren& node) { return "(" + sv(node.value) + ")"; },
        [&](const Cast& node) { return node.type + "(" + sv(node.value) + ")"; }
    }, expr->node);
    return expression_level(expr) < context ? "(" + text + ")" : text;
}
} // namespace

Unit parse(std::string_view source, std::string filename) { return Parser(source, filename).unit(); }
ExprPtr parse_expression(std::string_view source, std::string filename) { return Parser(source, filename).whole_expression(); }
ExprPtr parse_type_expression(std::string_view source, std::string filename) { return Parser(source, filename).whole_type(); }
std::string to_sv(const ExprPtr& expr) { return serialize(expr, 0); }
void walk_expression(const ExprPtr& expr, const std::function<void(const Expr&)>& visitor) {
    if (!expr) return;
    visitor(*expr);
    auto walk = [&](const ExprPtr& value) { walk_expression(value, visitor); };
    std::visit(Overloaded{
        [](const Identifier&) {}, [](const Literal&) {},
        [&](const Unary& node) { walk(node.operand); },
        [&](const Binary& node) { walk(node.left); walk(node.right); },
        [&](const Ternary& node) { walk(node.condition); walk(node.yes); walk(node.no); },
        [&](const Select& node) { walk(node.base); walk(node.first); walk(node.last); },
        [&](const Concat& node) { for (auto& part : node.parts) walk(part); },
        [&](const Repeat& node) { walk(node.count); walk(node.value); },
        [&](const Call& node) { for (auto& arg : node.args) walk(arg); },
        [&](const Method& node) { walk(node.object); for (auto& arg : node.args) walk(arg); },
        [&](const Paren& node) { walk(node.value); },
        [&](const Cast& node) { walk(node.value); }
    }, expr->node);
}
std::vector<std::string> references(const ExprPtr& expr) {
    std::vector<std::string> result;
    if (!expr) return result;
    auto add = [&](const ExprPtr& value) { for (auto& name : references(value)) if (std::find(result.begin(), result.end(), name) == result.end()) result.push_back(std::move(name)); };
    std::visit(Overloaded{
        [&](const Identifier& node) { if (node.name != "_" && node.name.find("::") == node.name.npos) result.push_back(node.name); },
        [](const Literal&) {},
        [&](const Unary& node) { add(node.operand); },
        [&](const Binary& node) { add(node.left); add(node.right); },
        [&](const Ternary& node) { add(node.condition); add(node.yes); add(node.no); },
        [&](const Select& node) { add(node.base); add(node.first); add(node.last); },
        [&](const Concat& node) { for (auto& part : node.parts) add(part); },
        [&](const Repeat& node) { add(node.count); add(node.value); },
        [&](const Call& node) { for (auto& arg : node.args) add(arg); },
        [&](const Method& node) { add(node.object); for (auto& arg : node.args) add(arg); },
        [&](const Paren& node) { add(node.value); },
        [&](const Cast& node) { add(node.value); }
    }, expr->node);
    return result;
}
} // namespace slip
