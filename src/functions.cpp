#include "internal.hpp"
#include <algorithm>
#include <charconv>
#include <cctype>
#include <limits>

namespace slip {
namespace {
using Integer = std::int64_t;
Integer add(Integer a, Integer b) {
    if ((b > 0 && a > std::numeric_limits<Integer>::max() - b) || (b < 0 && a < std::numeric_limits<Integer>::min() - b))
        throw Error({}, "E_LIMIT", "defun integer overflow");
    return a + b;
}
Integer negate(Integer a) {
    if (a == std::numeric_limits<Integer>::min()) throw Error({}, "E_LIMIT", "defun integer overflow");
    return -a;
}
Integer subtract(Integer a, Integer b) {
    if ((b > 0 && a < std::numeric_limits<Integer>::min() + b) ||
        (b < 0 && a > std::numeric_limits<Integer>::max() + b))
        throw Error({}, "E_LIMIT", "defun integer overflow");
    return a - b;
}
Integer multiply(Integer a, Integer b) {
    if (!a || !b) return 0;
    if ((a == -1 && b == std::numeric_limits<Integer>::min()) || (b == -1 && a == std::numeric_limits<Integer>::min())) throw Error({}, "E_LIMIT", "defun integer overflow");
    if (a > 0 ? (b > 0 ? a > std::numeric_limits<Integer>::max() / b : b < std::numeric_limits<Integer>::min() / a) :
                (b > 0 ? a < std::numeric_limits<Integer>::min() / b : a < std::numeric_limits<Integer>::max() / b)) throw Error({}, "E_LIMIT", "defun integer overflow");
    return a * b;
}
Integer divide(Integer a, Integer b) {
    if (!b) throw Error({}, "E_FUNCTION", "division by zero");
    if (a == std::numeric_limits<Integer>::min() && b == -1) throw Error({}, "E_LIMIT", "defun integer overflow");
    Integer q = a / b;
    if (a % b && ((a < 0) != (b < 0))) --q;
    return q;
}
Integer remainder(Integer a, Integer b) {
    if (!b) throw Error({}, "E_FUNCTION", "division by zero");
    // C++ min % -1 is undefined even though the mathematical remainder is zero.
    if (b == -1) return 0;
    auto result = a % b;
    return result && ((result < 0) != (b < 0)) ? add(result, b) : result;
}
Integer numeric(std::string_view text) {
    auto source = trim(text);
    if (source.starts_with('+')) source.erase(0, 1);
    Integer result{};
    auto [end, error] = std::from_chars(source.data(), source.data() + source.size(), result);
    if (error == std::errc::result_out_of_range) throw Error({}, "E_LIMIT", "defun integer exceeds signed 64-bit range");
    if (error != std::errc{} || end != source.data() + source.size()) throw Error({}, "E_FUNCTION", "expected decimal integer: " + source);
    return result;
}
std::size_t slice_index(Integer value, std::size_t length) {
    if (value < 0) value = std::max<Integer>(0, value + static_cast<Integer>(length));
    return static_cast<std::size_t>(std::min<Integer>(value, static_cast<Integer>(length)));
}
void append_bounded(std::string& output, std::string_view value) {
    if (value.size() > 1000000 || output.size() > 1000000 - value.size())
        throw Error({}, "E_LIMIT", "defun string size limit exceeded");
    output.append(value);
}
std::string join_bounded(const std::vector<std::string>& values, std::string_view separator) {
    std::string output;
    bool first = true;
    for (const auto& value : values) {
        if (!first) append_bounded(output, separator);
        append_bounded(output, value);
        first = false;
    }
    return output;
}
std::string replace_all(std::string input, const std::string& old, const std::string& replacement, Integer count = -1) {
    std::string result;
    Integer replaced = 0;
    for (std::size_t pos = 0; pos <= input.size();) {
        if ((count < 0 || replaced < count) && input.compare(pos, old.size(), old) == 0) {
            append_bounded(result, replacement); ++replaced;
            if (!old.empty()) { pos += old.size(); continue; }
        }
        if (pos == input.size()) break;
        result += input[pos++];
        if (result.size() > 1000000) throw Error({}, "E_LIMIT", "defun string size limit exceeded");
    }
    return result;
}
} // namespace

Functions::Functions(const std::vector<Function>& values) {
    for (const auto& value : values) {
        if (definitions.contains(value.name)) throw Error(value.loc, "E_DUPLICATE", "duplicate defun '" + value.name + "'");
        std::set<std::string> parameters;
        for (const auto& parameter : value.parameters)
            if (!parameters.insert(parameter).second) throw Error(value.loc, "E_DUPLICATE", "duplicate defun parameter '" + parameter + "'");
        definitions.emplace(value.name, value);
    }
    const std::set<std::string> helpers = {"len", "int", "str", "min", "max", "abs", "reverse", "upper", "lower", "substr", "replace", "concat", "add", "sub", "mul", "div", "mod", "bit_reverse", "bit_select"};
    const std::set<std::string> methods = {"upper", "lower", "reverse", "replace", "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "startswith", "endswith", "find", "rfind", "index", "count", "join", "zfill", "rjust", "ljust", "title", "capitalize", "swapcase", "casefold", "isdigit", "isalpha", "isalnum", "isnumeric", "islower", "isupper", "removeprefix", "removesuffix"};
    for (const auto& value : values) walk_expression(value.result, [&](const Expr& expr) {
        if (auto call = std::get_if<Call>(&expr.node); call && !helpers.contains(call->name) && !definitions.contains(call->name)) throw Error(expr.loc, "E_FUNCTION", "unknown function '" + call->name + "'");
        if (auto method = std::get_if<Method>(&expr.node); method && method->field) throw Error(expr.loc, "E_FUNCTION", "field access is only supported for RTL data");
        if (auto select = std::get_if<Select>(&expr.node); select && !select->indexed.empty()) throw Error(expr.loc, "E_FUNCTION", "indexed part selects are only supported for RTL data");
        if (auto method = std::get_if<Method>(&expr.node); method && !methods.contains(method->name)) throw Error(expr.loc, "E_FUNCTION", "method '." + method->name + "()' is not allowed in defun");
    });
}
std::string Functions::text(const Value& value) {
    if (auto boolean = std::get_if<bool>(&value)) return *boolean ? "True" : "False";
    if (auto number = std::get_if<Integer>(&value)) return std::to_string(*number);
    if (auto string = std::get_if<std::string>(&value)) return *string;
    return join_bounded(std::get<std::vector<std::string>>(value), ", ");
}
Integer Functions::integer(const Value& value) {
    if (auto boolean = std::get_if<bool>(&value)) return *boolean ? 1 : 0;
    if (auto number = std::get_if<Integer>(&value)) return *number;
    return numeric(text(value));
}
bool Functions::truth(const Value& value) {
    if (auto boolean = std::get_if<bool>(&value)) return *boolean;
    if (auto number = std::get_if<Integer>(&value)) return *number != 0;
    if (auto string = std::get_if<std::string>(&value)) return !string->empty();
    return !std::get<std::vector<std::string>>(value).empty();
}

Functions::Value Functions::eval(const ExprPtr& expr, const std::map<std::string, Value>& env, unsigned depth) {
    if (depth > 64) throw Error(expr->loc, "E_LIMIT", "defun evaluation depth exceeded");
    auto run = [&](const ExprPtr& value) { return eval(value, env, depth + 1); };
    try { return std::visit(Overloaded{
        [&](const Literal& node) -> Value { return node.string ? Value{unquote(node.text)} : Value{numeric(node.text)}; },
        [&](const Identifier& node) -> Value {
            auto found = env.find(node.name);
            if (found == env.end()) throw Error(expr->loc, "E_FUNCTION", "undefined function argument '" + node.name + "'");
            return found->second;
        },
        [&](const Paren& node) -> Value { return run(node.value); },
        [&](const Unary& node) -> Value {
            auto value = run(node.operand);
            if (node.op == "!") return !truth(value);
            auto n = integer(value);
            if (node.op == "+") return n;
            if (node.op == "-") return negate(n);
            if (node.op == "~") return ~n;
            throw Error(expr->loc, "E_FUNCTION", "unsupported defun unary operator");
        },
        [&](const Binary& node) -> Value {
            auto a = run(node.left);
            if (node.op == "&&" && !truth(a)) return false;
            if (node.op == "||" && truth(a)) return true;
            auto b = run(node.right);
            if (node.op == "+" && (std::holds_alternative<std::string>(a) || std::holds_alternative<std::string>(b))) {
                if (text(a).size() + text(b).size() > 1000000) throw Error(expr->loc, "E_LIMIT", "defun string size limit exceeded");
                return text(a) + text(b);
            }
            if (node.op == "==" || node.op == "===" || node.op == "!=" || node.op == "!==") {
                const auto number = [](const Value& v) { return std::holds_alternative<Integer>(v) || std::holds_alternative<bool>(v); };
                const bool equal = number(a) && number(b) ? integer(a) == integer(b) : a == b;
                return node.op == "!=" || node.op == "!==" ? !equal : equal;
            }
            if (node.op == "&&") return truth(b);
            if (node.op == "||") return truth(b);
            if (std::holds_alternative<std::string>(a) && std::holds_alternative<std::string>(b)) {
                if (node.op == "<") return text(a) < text(b);
                if (node.op == ">") return text(a) > text(b);
                if (node.op == "<=") return text(a) <= text(b);
                if (node.op == ">=") return text(a) >= text(b);
            }
            auto x = integer(a), y = integer(b);
            if (node.op == "+") return add(x, y);
            if (node.op == "-") return subtract(x, y);
            if (node.op == "*") return multiply(x, y);
            if (node.op == "/") return divide(x, y);
            if (node.op == "%") return remainder(x, y);
            if (node.op == "&") return x & y;
            if (node.op == "|") return x | y;
            if (node.op == "^") return x ^ y;
            if (node.op == "<") return x < y;
            if (node.op == ">") return x > y;
            if (node.op == "<=") return x <= y;
            if (node.op == ">=") return x >= y;
            if (node.op == "<<" || node.op == "<<<") {
                if (y < 0 || y > 62) throw Error(expr->loc, "E_LIMIT", "defun shift out of range");
                return multiply(x, Integer(1) << y);
            }
            if (node.op == ">>" || node.op == ">>>") {
                if (y < 0 || y > 63) throw Error(expr->loc, "E_LIMIT", "defun shift out of range");
                return x >> y;
            }
            if (node.op == "**") {
                if (y < 0 || y > 63) throw Error(expr->loc, "E_LIMIT", "defun exponent out of range");
                Integer result = 1; while (y--) result = multiply(result, x); return result;
            }
            throw Error(expr->loc, "E_FUNCTION", "unsupported defun operator '" + node.op + "'");
        },
        [&](const Ternary& node) -> Value { return run(truth(run(node.condition)) ? node.yes : node.no); },
        [&](const Call& node) -> Value {
            std::vector<Value> args; for (auto& arg : node.args) args.push_back(run(arg));
            return call(node.name, args, depth + 1, expr->loc);
        },
        [&](const Method& node) -> Value {
            auto object = run(node.object); std::vector<Value> args; for (auto& arg : node.args) args.push_back(run(arg));
            return method(node.name, object, args, expr->loc);
        },
        [&](const Select& node) -> Value {
            auto value = run(node.base);
            auto length = std::holds_alternative<std::vector<std::string>>(value) ? std::get<std::vector<std::string>>(value).size() : text(value).size();
            Integer index = node.first ? integer(run(node.first)) : 0;
            if (node.slice) {
                auto first = slice_index(index, length);
                auto last = node.last ? slice_index(integer(run(node.last)), length) : length;
                if (auto list = std::get_if<std::vector<std::string>>(&value)) return std::vector<std::string>(list->begin() + first, list->begin() + std::max(first, last));
                return text(value).substr(first, last > first ? last - first : 0);
            }
            if (index < 0) index += static_cast<Integer>(length);
            if (index < 0 || static_cast<std::size_t>(index) >= length) throw Error(expr->loc, "E_FUNCTION", "defun index out of range");
            if (auto list = std::get_if<std::vector<std::string>>(&value)) return (*list)[index];
            return text(value).substr(index, 1);
        },
        [&](const auto&) -> Value { throw Error(expr->loc, "E_FUNCTION", "unsupported expression in defun"); }
    }, expr->node); }
    catch (const Error& error) {
        if (error.location.file == "<input>" && error.location.line == 1 && error.location.column == 1)
            throw Error(expr->loc, error.code, error.message);
        throw;
    }
}

Functions::Value Functions::call(const std::string& name, const std::vector<Value>& args, unsigned depth, Location loc) {
    if (depth > 64) throw Error(loc, "E_LIMIT", "defun recursion limit exceeded");
    auto count = [&](std::size_t n) { if (args.size() != n) throw Error(loc, "E_FUNCTION", name + " expects " + std::to_string(n) + " arguments"); };
    if (auto found = definitions.find(name); found != definitions.end()) {
        count(found->second.parameters.size());
        std::map<std::string, Value> env;
        for (std::size_t i = 0; i < args.size(); ++i) {
            auto value = args[i];
            if (auto str = std::get_if<std::string>(&value)) { try { value = numeric(*str); } catch (const Error&) {} }
            env.emplace(found->second.parameters[i], std::move(value));
        }
        return eval(found->second.result, env, depth + 1);
    }
    if (name == "str") { count(1); return text(args[0]); }
    if (name == "int") { count(1); return integer(args[0]); }
    if (name == "len") { count(1); if (auto list = std::get_if<std::vector<std::string>>(&args[0])) return Integer(list->size()); return Integer(text(args[0]).size()); }
    if (name == "abs") { count(1); auto n = integer(args[0]); return n < 0 ? negate(n) : n; }
    if (name == "min" || name == "max") {
        if (args.empty()) throw Error(loc, "E_FUNCTION", "min/max require arguments");
        auto result = integer(args[0]); for (const auto& arg : args) result = name == "min" ? std::min(result, integer(arg)) : std::max(result, integer(arg)); return result;
    }
    if (name == "add" || name == "sub" || name == "mul" || name == "div" || name == "mod") {
        count(2); auto x = integer(args[0]), y = integer(args[1]);
        if (name == "add") return std::to_string(add(x, y));
        if (name == "sub") return std::to_string(subtract(x, y));
        if (name == "mul") return std::to_string(multiply(x, y));
        if (name == "div") return std::to_string(divide(x, y));
        return std::to_string(remainder(x, y));
    }
    if (name == "concat") { count(2); auto result = text(args[0]); append_bounded(result, text(args[1])); return result; }
    if (name == "substr" || name == "bit_select") {
        count(3); auto source = text(args[0]); auto first = integer(args[1]), last = integer(args[2]);
        if (name == "bit_select") { if (first < last || first < 0 || first >= static_cast<Integer>(source.size())) throw Error(loc, "E_FUNCTION", "bit_select out of range"); std::swap(first, last); ++last; }
        else last = add(first, last);
        auto start = slice_index(first, source.size()), end = slice_index(last, source.size());
        return source.substr(start, end > start ? end - start : 0);
    }
    if (name == "upper" || name == "lower" || name == "reverse" || name == "bit_reverse") { count(1); return method(name == "bit_reverse" ? "reverse" : name, args[0], {}, loc); }
    if (name == "replace") { count(3); return method("replace", args[0], {args[1], args[2]}, loc); }
    throw Error(loc, "E_FUNCTION", "unknown function '" + name + "'");
}

Functions::Value Functions::method(const std::string& name, const Value& object, const std::vector<Value>& args, Location loc) {
    if (!std::holds_alternative<std::string>(object)) throw Error(loc, "E_FUNCTION", "string method requires a string");
    auto value = text(object);
    auto count = [&](std::size_t low, std::size_t high) { if (args.size() < low || args.size() > high) throw Error(loc, "E_FUNCTION", "invalid arguments to ." + name); };
    if (name == "upper" || name == "lower" || name == "casefold" || name == "reverse" || name == "capitalize" || name == "title" || name == "swapcase") {
        count(0, 0);
        if (name == "reverse") { std::reverse(value.begin(), value.end()); return value; }
        bool word = true;
        for (std::size_t i = 0; i < value.size(); ++i) {
            unsigned char ch = value[i];
            bool upper = name == "upper" || (name == "capitalize" && i == 0) || (name == "title" && word) || (name == "swapcase" && std::islower(ch));
            value[i] = static_cast<char>(upper ? std::toupper(ch) : std::tolower(ch));
            word = !std::isalnum(ch);
        }
        return value;
    }
    if (name == "strip" || name == "lstrip" || name == "rstrip") {
        count(0, 1); auto chars = args.empty() ? std::string(" \t\n\r\v\f") : text(args[0]);
        auto first = name == "rstrip" ? 0 : value.find_first_not_of(chars);
        if (first == value.npos) return std::string{};
        auto last = name == "lstrip" ? value.size() - 1 : value.find_last_not_of(chars);
        return last == value.npos || last < first ? std::string{} : value.substr(first, last - first + 1);
    }
    if (name == "replace") { count(2, 3); return replace_all(value, text(args[0]), text(args[1]), args.size() == 3 ? integer(args[2]) : -1); }
    if (name == "startswith" || name == "endswith" || name == "removeprefix" || name == "removesuffix") {
        bool predicate = name == "startswith" || name == "endswith";
        count(1, predicate ? 3 : 1); auto part = text(args[0]); bool start = name == "startswith" || name == "removeprefix";
        auto first = args.size() > 1 ? slice_index(integer(args[1]), value.size()) : 0;
        auto last = args.size() > 2 ? slice_index(integer(args[2]), value.size()) : value.size();
        bool valid = last >= first && (args.size() < 2 || integer(args[1]) <= static_cast<Integer>(value.size()));
        auto selected = valid ? value.substr(first, last - first) : std::string{};
        bool matched = valid && (start ? selected.starts_with(part) : selected.ends_with(part));
        if (name == "startswith" || name == "endswith") return matched;
        return matched ? (start ? value.substr(part.size()) : value.substr(0, value.size() - part.size())) : value;
    }
    if (name == "find" || name == "rfind" || name == "index" || name == "count") {
        count(1, 3); auto part = text(args[0]);
        auto first = args.size() > 1 ? slice_index(integer(args[1]), value.size()) : 0;
        auto last = args.size() > 2 ? slice_index(integer(args[2]), value.size()) : value.size();
        bool valid = last >= first && (args.size() < 2 || integer(args[1]) <= static_cast<Integer>(value.size()));
        auto selected = valid ? value.substr(first, last - first) : std::string{};
        if (name == "count") { Integer n = 0; if (!valid) return n; for (std::size_t pos = 0; pos <= selected.size();) { pos = selected.find(part, pos); if (pos == selected.npos) break; ++n; pos += std::max<std::size_t>(part.size(), 1); } return n; }
        auto index = !valid ? selected.npos : name == "rfind" ? selected.rfind(part) : selected.find(part);
        if (name == "index" && index == value.npos) throw Error(loc, "E_FUNCTION", "substring not found");
        return index == value.npos ? Integer(-1) : static_cast<Integer>(index + first);
    }
    if (name == "zfill" || name == "rjust" || name == "ljust") {
        count(1, name == "zfill" ? 1 : 2); auto width = integer(args[0]);
        if (width > 1000000) throw Error(loc, "E_LIMIT", "defun string size limit exceeded");
        if (width <= static_cast<Integer>(value.size())) return value;
        auto fill = args.size() == 2 ? text(args[1]) : name == "zfill" ? "0" : " ";
        if (fill.size() != 1) throw Error(loc, "E_FUNCTION", "fill character must have length one");
        std::string padding(static_cast<std::size_t>(width) - value.size(), fill[0]);
        if (name == "zfill" && (value.starts_with('-') || value.starts_with('+'))) return value.substr(0, 1) + padding + value.substr(1);
        return name == "ljust" ? value + padding : padding + value;
    }
    if (name == "split" || name == "rsplit" || name == "splitlines") {
        count(0, name == "splitlines" ? 1 : 2);
        if (name == "splitlines") {
            std::vector<std::string> parts; std::size_t start = 0;
            for (std::size_t pos = 0; pos < value.size(); ++pos) {
                if (std::string_view("\r\n\v\f\x1c\x1d\x1e").find(value[pos]) == std::string_view::npos) continue;
                auto end = pos;
                if (value[pos] == '\r' && pos + 1 < value.size() && value[pos + 1] == '\n') ++pos;
                parts.push_back(value.substr(start, (!args.empty() && truth(args[0]) ? pos + 1 : end) - start)); start = pos + 1;
            }
            if (start < value.size()) parts.push_back(value.substr(start));
            return parts;
        }
        std::string separator = args.empty() ? "" : text(args[0]);
        if (!args.empty() && separator.empty()) throw Error(loc, "E_FUNCTION", "empty separator");
        Integer remaining = args.size() == 2 ? integer(args[1]) : -1;
        std::vector<std::string> parts;
        if (name == "rsplit" && !separator.empty()) {
            std::size_t end = value.size();
            while (remaining != 0 && end >= separator.size()) {
                auto pos = value.rfind(separator, end - separator.size());
                if (pos == value.npos) break;
                parts.push_back(value.substr(pos + separator.size(), end - pos - separator.size())); end = pos;
                if (remaining > 0) --remaining;
            }
            parts.push_back(value.substr(0, end)); std::reverse(parts.begin(), parts.end()); return parts;
        }
        std::size_t pos = 0;
        while (pos <= value.size()) {
            if (separator.empty()) {
                while (pos < value.size() && std::isspace(static_cast<unsigned char>(value[pos]))) ++pos;
                if (pos == value.size()) break;
                auto end = pos;
                if (remaining == 0) end = value.size();
                else while (end < value.size() && !std::isspace(static_cast<unsigned char>(value[end]))) ++end;
                parts.push_back(value.substr(pos, end - pos)); pos = end;
            } else {
                auto end = remaining == 0 ? value.npos : value.find(separator, pos);
                if (end == value.npos) { if (name != "splitlines" || pos != value.size()) parts.push_back(value.substr(pos)); break; }
                parts.push_back(value.substr(pos, end - pos)); pos = end + separator.size();
            }
            if (remaining > 0) --remaining;
        }
        return parts;
    }
    if (name == "join") {
        count(1, 1);
        if (auto list = std::get_if<std::vector<std::string>>(&args[0])) return join_bounded(*list, value);
        std::string result;
        bool first = true;
        for (char ch : text(args[0])) {
            if (!first) append_bounded(result, value);
            append_bounded(result, std::string_view(&ch, 1));
            first = false;
        }
        return result;
    }
    if (name == "isdigit" || name == "isnumeric" || name == "isalpha" || name == "isalnum" || name == "islower" || name == "isupper") {
        count(0, 0); bool okay = !value.empty(), cased = false;
        for (unsigned char ch : value) {
            if (name == "isdigit" || name == "isnumeric") okay &= bool(std::isdigit(ch));
            else if (name == "isalpha") okay &= bool(std::isalpha(ch));
            else if (name == "isalnum") okay &= bool(std::isalnum(ch));
            else if (std::isalpha(ch)) { cased = true; okay &= name == "islower" ? bool(std::islower(ch)) : bool(std::isupper(ch)); }
        }
        if (name == "islower" || name == "isupper") okay &= cased;
        return okay;
    }
    throw Error(loc, "E_FUNCTION", "method '." + name + "()' is not allowed in defun");
}

std::string Functions::replacement(std::string_view source, const std::vector<std::string>& captures) {
    // Expand templates once. Function output is never interpreted as another template.
    std::function<std::string(std::string_view, unsigned)> expand = [&](std::string_view value, unsigned depth) -> std::string {
        if (depth > 64) throw Error({}, "E_LIMIT", "replacement nesting limit exceeded");
        std::string result;
        for (std::size_t i = 0; i < value.size();) {
            if (value[i] == '\\' && i + 1 < value.size() && std::isdigit(static_cast<unsigned char>(value[i+1]))) {
                auto group = static_cast<std::size_t>(value[i+1] - '0');
                if (group >= captures.size()) throw Error({}, "E_REGEX", "invalid backreference");
                result += captures[group]; i += 2;
            } else if (value[i] == '$') {
                auto begin = ++i;
                while (i < value.size() && (std::isalnum(static_cast<unsigned char>(value[i])) || value[i] == '_')) ++i;
                std::string name(value.substr(begin, i - begin));
                if (name.empty() || i == value.size() || value[i] != '(') throw Error({}, "E_REGEX", "malformed replacement function");
                auto arg_start = ++i; unsigned parentheses = 1;
                std::vector<Value> args;
                while (i < value.size() && parentheses) {
                    if (value[i] == '(') ++parentheses;
                    if (value[i] == ')') --parentheses;
                    if ((value[i] == ',' && parentheses == 1) || !parentheses) {
                        auto raw = trim(value.substr(arg_start, i - arg_start));
                        if (!raw.empty() || !args.empty()) args.emplace_back(expand(raw, depth + 1));
                        arg_start = i + 1;
                    }
                    ++i;
                }
                if (parentheses) throw Error({}, "E_REGEX", "unbalanced replacement parentheses");
                result += text(call(name, args, depth + 1, {}));
            } else result += value[i++];
            if (result.size() > 1000000) throw Error({}, "E_LIMIT", "replacement size limit exceeded");
        }
        return result;
    };
    return expand(source, 0);
}
} // namespace slip
