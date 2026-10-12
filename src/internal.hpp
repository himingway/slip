#pragma once
#include "slip/compiler.hpp"
#include <cstdint>
#include <functional>
#include <optional>
#include <set>

namespace slip {
using Environment = std::vector<std::pair<std::string, std::string>>;
struct InterfacePort {
    std::string name, direction, width, array;
    bool is_signed = false;
};
struct Interface {
    std::vector<NamedValue> parameters, localparams;
    std::vector<InterfacePort> ports;
    std::set<std::string> frozen;
};

class Backend {
public:
    explicit Backend(const Options& options);
    ~Backend();
    Backend(const Backend&) = delete;
    Backend& operator=(const Backend&) = delete;
    std::map<std::string, Interface> ips;
    std::int64_t constant(std::string_view expression, const Environment& environment, Location loc);
    void validate(const std::map<std::string, std::string>& modules, bool strict, std::vector<Diagnostic>& warnings);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

class Functions {
public:
    explicit Functions(const std::vector<Function>& definitions);
    std::string replacement(std::string_view text, const std::vector<std::string>& captures);
private:
    using Value = std::variant<std::int64_t, std::string, std::vector<std::string>, bool>;
    std::map<std::string, Function> definitions;
    Value eval(const ExprPtr& expr, const std::map<std::string, Value>& environment, unsigned depth);
    Value call(const std::string& name, const std::vector<Value>& args, unsigned depth, Location loc);
    Value method(const std::string& name, const Value& object, const std::vector<Value>& args, Location loc);
    static std::string text(const Value& value);
    static std::int64_t integer(const Value& value);
    static bool truth(const Value& value);
};

// PCRE2 preserves familiar Python pattern constructs and bounds matching work.
class Pattern {
public:
    Pattern(std::string_view source, Location loc);
    ~Pattern();
    Pattern(Pattern&&) noexcept;
    Pattern& operator=(Pattern&&) noexcept;
    std::optional<std::vector<std::string>> match(std::string_view text) const;
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

std::string read_file(const std::filesystem::path& file);
std::string join(const std::vector<std::string>& parts, std::string_view delimiter);
std::string trim(std::string_view value);
void walk_expression(const ExprPtr& expr, const std::function<void(const Expr&)>& visitor);
} // namespace slip
