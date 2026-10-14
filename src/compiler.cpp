#include "internal.hpp"
#include "slip/ir.hpp"
#include <algorithm>
#include <cctype>
#include <fstream>
#include <limits>
#include <regex>

namespace slip {
namespace {
using Substitutions = std::map<std::string, ExprPtr>;
ExprPtr rewrite(const ExprPtr& expr, const std::function<ExprPtr(const Identifier&, const Location&)>& identifier,
                const std::function<ExprPtr(const ExprPtr&)>& after = {}) {
    if (!expr) return {};
    auto sub = [&](const ExprPtr& value) { return rewrite(value, identifier, after); };
    auto result = std::visit(Overloaded{
        [&](const Identifier& node) { return identifier(node, expr->loc); },
        [&](const Literal&) { return expr; },
        [&](const Unary& node) { return expression(expr->loc, Unary{node.op, sub(node.operand)}); },
        [&](const Binary& node) { return expression(expr->loc, Binary{node.op, sub(node.left), sub(node.right)}); },
        [&](const Ternary& node) { return expression(expr->loc, Ternary{sub(node.condition), sub(node.yes), sub(node.no)}); },
        [&](const Select& node) { return expression(expr->loc, Select{sub(node.base), sub(node.first), sub(node.last), node.slice, node.indexed}); },
        [&](const Concat& node) { std::vector<ExprPtr> parts; for (auto& part : node.parts) parts.push_back(sub(part)); return expression(expr->loc, Concat{std::move(parts)}); },
        [&](const Repeat& node) { return expression(expr->loc, Repeat{sub(node.count), sub(node.value)}); },
        [&](const Call& node) { std::vector<ExprPtr> args; for (auto& arg : node.args) args.push_back(sub(arg)); return expression(expr->loc, Call{node.name, std::move(args)}); },
        [&](const Method& node) { std::vector<ExprPtr> args; for (auto& arg : node.args) args.push_back(sub(arg)); return expression(expr->loc, Method{sub(node.object), node.name, std::move(args), node.field}); },
        [&](const Paren& node) { return expression(expr->loc, Paren{sub(node.value)}); },
        [&](const Cast& node) { return expression(expr->loc, Cast{node.type, sub(node.value)}); }
    }, expr->node);
    return after ? after(result) : result;
}
std::string substitute_name(std::string name, const Substitutions& values) {
    std::vector<std::pair<std::string, ExprPtr>> ordered(values.begin(), values.end());
    std::sort(ordered.begin(), ordered.end(), [](const auto& a, const auto& b) { return a.first.size() > b.first.size(); });
    for (const auto& [variable, value] : ordered) {
        auto needle = "`" + variable;
        for (std::size_t pos = 0; (pos = name.find(needle, pos)) != std::string::npos;) {
            auto replacement = to_sv(value); name.replace(pos, needle.size(), replacement); pos += replacement.size();
        }
    }
    return name;
}
ExprPtr substitute(const ExprPtr& expr, const Substitutions& values) {
    return rewrite(expr, [&](const Identifier& id, const Location& loc) {
        if (auto found = values.find(id.name); found != values.end()) return found->second;
        return expression(loc, Identifier{substitute_name(id.name, values), id.meta});
    });
}
void walk(const Body& body, const std::function<void(const Statement&)>& visitor) {
    for (const auto& statement : body) {
        visitor(statement);
        std::visit(Overloaded{
            [&](const Process& node) { walk(node.body, visitor); },
            [&](const If& node) { walk(node.yes, visitor); walk(node.no, visitor); },
            [&](const For& node) { walk(node.body, visitor); },
            [&](const Case& node) { for (auto& arm : node.arms) walk(arm.body, visitor); },
            [&](const Group& node) { walk(node.body, visitor); },
            [](const auto&) {}
        }, statement.node);
    }
}
void set_environment(Environment& env, const std::string& name, std::string value) {
    for (auto& [key, current] : env) if (key == name) { current = std::move(value); return; }
    env.emplace_back(name, std::move(value));
}
std::string dimension(const ExprPtr& expr) {
    if (!expr) return {};
    if (auto binary = std::get_if<Binary>(&expr->node); binary && binary->op == ":") return "[" + to_sv(binary->left) + ":" + to_sv(binary->right) + "]";
    return "[" + to_sv(expr) + "-1:0]";
}

class Expander {
    Backend& backend;
    const Options& options;
    std::size_t statements = 0, iterations = 0;
    std::int64_t evaluate_meta(const ExprPtr& expr, const Environment& env, const Location& loc) {
        walk_expression(expr, [&](const Expr& value) {
            if (auto literal = std::get_if<Literal>(&value.node); literal && (literal->text == "'0" || literal->text == "'1"))
                throw Error(loc, "E_CONSTANT", "unsized fill constant cannot be evaluated in metaprogram controls");
        });
        return backend.constant(to_sv(expr), env, loc);
    }
    ExprPtr sub(const ExprPtr& expr, const Substitutions& values) {
        auto result = substitute(expr, values);
        // Fold indices only, and only plain decimal arithmetic. Datapath expressions
        // retain their SV context-determined width and four-state behavior.
        return rewrite(result, [](const Identifier& id, const Location& loc) {
            if (id.meta) throw Error(loc, "E_META", "unbound metaprogram variable '" + id.name + "'");
            if (id.name.find('`') != std::string::npos) throw Error(loc, "E_META", "unbound template identifier '" + id.name + "'");
            return expression(loc, id);
        });
    }
    ExprPtr index(const ExprPtr& expr, const Substitutions& values) {
        auto result = sub(expr, values);
        if (!result || !references(result).empty()) return result;
        auto text = to_sv(result);
        if (text.find_first_not_of("0123456789_ +-*/%<>=!~&|^()") != std::string::npos) return result;
        try {
            auto value = backend.constant(text, {}, result->loc);
            if (value >= std::numeric_limits<std::int32_t>::min() && value <= std::numeric_limits<std::int32_t>::max()) return expression(result->loc, Literal{std::to_string(value)});
        } catch (const Error&) {}
        return result;
    }
    ExprPtr hardware(const ExprPtr& expr, const Substitutions& values) {
        if (!expr) return {};
        if (auto select = std::get_if<Select>(&expr->node)) return expression(expr->loc, Select{hardware(select->base, values), index(select->first, values), index(select->last, values), select->slice, select->indexed});
        return sub(expr, values);
    }
public:
    Expander(Backend& backend, const Options& options) : backend(backend), options(options) {}
    Body expand(const Body& body, Environment env, Substitutions values = {}) {
        Body result;
        for (const auto& statement : body) {
            auto loc = statement.loc;
            if (!values.empty()) {
                std::vector<std::string> bindings;
                for (const auto& [name, value] : values) bindings.push_back(name + "=" + to_sv(value));
                loc.expansion = join(bindings, ", ");
            }
            auto append = [&](Body added) { result.insert(result.end(), std::make_move_iterator(added.begin()), std::make_move_iterator(added.end())); };
            if (auto conditional = std::get_if<If>(&statement.node); conditional && conditional->meta) {
                auto condition = substitute(conditional->condition, values);
                append(expand(evaluate_meta(condition, env, loc) ? conditional->yes : conditional->no, env, values));
                continue;
            }
            if (auto loop = std::get_if<For>(&statement.node); loop && loop->meta) {
                if (loop->variable != loop->step_variable) throw Error(loc, "E_META", "metaprogram step variable must match loop variable");
                auto current = evaluate_meta(substitute(loop->init, values), env, loc);
                std::set<std::int64_t> seen;
                while (true) {
                    auto inner_values = values;
                    inner_values[loop->variable] = expression(loc, Literal{std::to_string(current)});
                    auto inner_env = env; set_environment(inner_env, loop->variable, std::to_string(current));
                    if (!evaluate_meta(substitute(loop->condition, inner_values), inner_env, loc)) break;
                    if (++iterations > options.max_meta_iterations) throw Error(loc, "E_LIMIT", "metaprogram loop iteration limit exceeded");
                    if (!seen.insert(current).second) throw Error(loc, "E_META", "metaprogram loop repeats a value and cannot terminate");
                    append(expand(loop->body, inner_env, inner_values));
                    current = evaluate_meta(substitute(loop->step, inner_values), inner_env, loc);
                }
                continue;
            }
            if (++statements > options.max_expanded_statements) throw Error(loc, "E_LIMIT", "expanded statement limit exceeded");
            auto expanded = std::visit(Overloaded{
                [&](const SignalDecl& node) -> Statement {
                    ExprPtr width;
                    if (auto range = node.width ? std::get_if<Binary>(&node.width->node) : nullptr; range && range->op == ":") width = expression(node.width->loc, Binary{":", index(range->left, values), index(range->right, values)});
                    else width = index(node.width, values);
                    auto decl = node; decl.name = substitute_name(node.name, values); decl.width = width;
                    decl.array_first = index(node.array_first, values); decl.array_last = index(node.array_last, values);
                    for (auto& [first, last] : decl.dimensions) { first = index(first, values); last = index(last, values); }
                    return {loc, std::move(decl)};
                },
                [&](const LocalParam& node) -> Statement {
                    auto name = substitute_name(node.name, values); auto value = hardware(node.value, values);
                    set_environment(env, name, to_sv(value)); return {loc, LocalParam{name, value}};
                },
                [&](const Assignment& node) -> Statement { return {loc, Assignment{hardware(node.target, values), hardware(node.value, values), node.nonblocking}}; },
                [&](const Process& node) -> Statement { return {loc, Process{node.kind, substitute_name(node.clock, values), substitute_name(node.reset, values), node.edge, expand(node.body, env, values), node.clock_edge}}; },
                [&](const If& node) -> Statement { return {loc, If{hardware(node.condition, values), expand(node.yes, env, values), expand(node.no, env, values), false}}; },
                [&](const For& node) -> Statement { return {loc, For{substitute_name(node.variable, values), substitute_name(node.step_variable, values), hardware(node.init, values), hardware(node.condition, values), hardware(node.step, values), expand(node.body, env, values), false}}; },
                [&](const Case& node) -> Statement {
                    std::vector<CaseArm> arms;
                    for (auto& arm : node.arms) { std::vector<ExprPtr> patterns; for (auto& pattern : arm.patterns) patterns.push_back(hardware(pattern, values)); arms.push_back({std::move(patterns), expand(arm.body, env, values)}); }
                    return {loc, Case{node.kind, hardware(node.value, values), std::move(arms)}};
                },
                [&](const Instance& node) -> Statement {
                    auto instance = node; instance.name = substitute_name(node.name, values);
                    for (auto& param : instance.parameters) param.value = hardware(param.value, values);
                    for (auto& connection : instance.connections) { connection.value = hardware(connection.value, values); connection.port = substitute_name(connection.port, values); connection.pattern = substitute_name(connection.pattern, values); connection.replacement = substitute_name(connection.replacement, values); }
                    return {loc, std::move(instance)};
                },
                [&](const Group& node) -> Statement { return {loc, Group{expand(node.body, env, values)}}; },
                [&](const TypeDecl& node) -> Statement {
                    auto value = node; value.name = substitute_name(value.name, values); value.sv = substitute_name(value.sv, values);
                    for (auto& [name, expr] : value.constants) { name = substitute_name(name, values); expr = hardware(expr, values); set_environment(env, name, to_sv(expr)); }
                    return {loc, std::move(value)};
                },
                [&](const Assertion& node) -> Statement { return {loc, Assertion{hardware(node.condition, values), node.message, node.compile_time}}; },
                [&](const Return& node) -> Statement { return {loc, Return{hardware(node.value, values)}}; },
                [&](const RTLFunction& node) -> Statement { auto value = node; auto inner = env;
                    std::set<std::string> shadowed;
                    for (const auto& argument : node.arguments) shadowed.insert(argument.name);
                    walk(node.body, [&](const Statement& statement) { if (auto local = std::get_if<SignalDecl>(&statement.node)) shadowed.insert(local->name); });
                    std::erase_if(inner, [&](const auto& item) { return shadowed.contains(item.first); });
                    value.body = expand(node.body, inner, values); return {loc, std::move(value)}; },
                [&](const BundleUse& node) -> Statement {
                    auto value = node; value.name = substitute_name(value.name, values);
                    for (auto& parameter : value.parameters) parameter.value = hardware(parameter.value, values);
                    for (auto& connection : value.connections) { connection.value = hardware(connection.value, values); connection.port = substitute_name(connection.port, values); }
                    return {loc, std::move(value)};
                }
            }, statement.node);
            if (auto group = std::get_if<Group>(&expanded.node)) append(std::move(group->body));
            else result.push_back(std::move(expanded));
        }
        return result;
    }
};

std::vector<std::pair<std::string, std::int64_t>> frozen_parameters(const Module& module, Backend& backend) {
    std::set<std::string> dependencies;
    std::map<std::string, ExprPtr> declarations;
    for (const auto& parameter : module.parameters) declarations[parameter.name] = parameter.value;
    std::function<void(const Statement&)> controls = [&](const Statement& statement) {
        if (auto function = std::get_if<RTLFunction>(&statement.node)) walk(function->body, controls);
        auto add = [&](const ExprPtr& expr) { for (auto& ref : references(expr)) dependencies.insert(ref); };
        if (auto conditional = std::get_if<If>(&statement.node); conditional && conditional->meta) add(conditional->condition);
        if (auto loop = std::get_if<For>(&statement.node); loop && loop->meta) { add(loop->init); add(loop->condition); add(loop->step); }
        if (auto local = std::get_if<LocalParam>(&statement.node)) declarations[local->name] = local->value;
    }; walk(module.body, controls);
    std::vector<std::string> pending(dependencies.begin(), dependencies.end());
    for (std::size_t i = 0; i < pending.size(); ++i) if (auto found = declarations.find(pending[i]); found != declarations.end())
        for (auto& reference : references(found->second)) if (dependencies.insert(reference).second) pending.push_back(reference);
    Environment env;
    std::vector<std::pair<std::string, std::int64_t>> result;
    std::set<std::string> names;
    for (auto& parameter : module.parameters) {
        if (!names.insert(parameter.name).second) throw Error(module.loc, "E_DUPLICATE", "duplicate parameter '" + parameter.name + "'");
        if (dependencies.contains(parameter.name)) result.emplace_back(parameter.name, backend.constant(to_sv(parameter.value), env, module.loc));
        env.emplace_back(parameter.name, to_sv(parameter.value));
    }
    return result;
}

// A reference describes storage, including each unpacked / packed select.
// A missing range is conservative; an empty vector means the whole variable.
struct Storage {
    std::string name;
    std::vector<std::optional<std::pair<std::int64_t, std::int64_t>>> ranges;
    std::vector<std::string> members = {};
    auto operator<=>(const Storage&) const = default;
};
bool overlap(const Storage& a, const Storage& b) {
    if (a.name != b.name) return false;
    for (std::size_t i = 0; i < std::min(a.members.size(), b.members.size()); ++i) if (a.members[i] != b.members[i]) return false;
    for (std::size_t i = 0; i < std::min(a.ranges.size(), b.ranges.size()); ++i) {
        if (!a.ranges[i] || !b.ranges[i]) continue;
        if (a.ranges[i]->first > b.ranges[i]->second || b.ranges[i]->first > a.ranges[i]->second) return false;
    }
    return true;
}
std::optional<std::int64_t> literal_integer(const ExprPtr& expr) {
    if (!expr) return {};
    auto text = to_sv(expr);
    if (text.empty() || text.find_first_not_of("-0123456789_") != text.npos) return {};
    text.erase(std::remove(text.begin(), text.end(), '_'), text.end());
    try { return std::stoll(text); } catch (const std::exception&) { return {}; }
}
std::vector<Storage> storage(const ExprPtr& expr) {
    if (!expr) return {};
    if (auto id = std::get_if<Identifier>(&expr->node)) {
        if (id->name == "_") return {};
        Storage target; target.name = id->name;
        return {std::move(target)};
    }
    if (auto paren = std::get_if<Paren>(&expr->node)) return storage(paren->value);
    if (auto concat = std::get_if<Concat>(&expr->node)) { std::vector<Storage> result; for (auto& part : concat->parts) { auto added = storage(part); result.insert(result.end(), added.begin(), added.end()); } return result; }
    if (auto member = std::get_if<Method>(&expr->node); member && member->field) {
        auto result = storage(member->object); for (auto& value : result) value.members.push_back(member->name); return result;
    }
    if (auto select = std::get_if<Select>(&expr->node)) {
        auto result = storage(select->base); auto first = literal_integer(select->first); auto last = select->slice ? literal_integer(select->last) : first;
        std::optional<std::pair<std::int64_t, std::int64_t>> range;
        if (first && last) {
            if (select->indexed.empty()) range = std::minmax(*first, *last);
            else if (*last > 0) {
                if (select->indexed == "+:" && *first <= std::numeric_limits<std::int64_t>::max() - (*last - 1)) range = std::pair{*first, *first + *last - 1};
                if (select->indexed == "-:" && *first >= std::numeric_limits<std::int64_t>::min() + (*last - 1)) range = std::pair{*first - *last + 1, *first};
            }
        }
        for (auto& item : result) item.ranges.push_back(range);
        return result;
    }
    return {};
}
std::set<Storage> reads(const ExprPtr& expr) {
    std::set<Storage> result;
    if (!expr) return result;
    auto add = [&](const ExprPtr& value) { auto added = reads(value); result.insert(added.begin(), added.end()); };
    std::visit(Overloaded{
        [&](const Identifier&) { for (auto& item : storage(expr)) result.insert(item); },
        [](const Literal&) {},
        [&](const Select& node) { for (auto& item : storage(expr)) result.insert(item); add(node.first); add(node.last); },
        [&](const Unary& node) { add(node.operand); },
        [&](const Binary& node) { add(node.left); add(node.right); },
        [&](const Ternary& node) { add(node.condition); add(node.yes); add(node.no); },
        [&](const Concat& node) { for (auto& part : node.parts) add(part); },
        [&](const Repeat& node) { add(node.count); add(node.value); },
        [&](const Call& node) { for (auto& arg : node.args) add(arg); },
        [&](const Method& node) { if (node.field) {
            for (auto& item : storage(expr)) result.insert(item);
            walk_expression(node.object, [&](const Expr& value) { if (auto select = std::get_if<Select>(&value.node)) { add(select->first); add(select->last); } });
        } else add(node.object); for (auto& arg : node.args) add(arg); },
        [&](const Paren& node) { add(node.value); },
        [&](const Cast& node) { add(node.value); }
    }, expr->node);
    return result;
}
using DependencyState = std::map<Storage, std::set<Storage>>;
std::set<Storage> resolve_reads(const std::set<Storage>& references, const DependencyState& state) {
    std::set<Storage> result;
    for (auto& reference : references) {
        bool matched = false;
        for (auto it = state.lower_bound(Storage{reference.name, {}}); it != state.end() && it->first.name == reference.name; ++it)
            if (overlap(reference, it->first)) { matched = true; result.insert(it->second.begin(), it->second.end()); }
        if (!matched) result.insert(reference);
    }
    return result;
}
void merge_states(DependencyState& state, const std::vector<DependencyState>& branches, bool complete) {
    std::set<Storage> keys;
    for (auto& branch : branches) for (auto& [key, unused] : branch) keys.insert(key);
    for (auto& key : keys) {
        std::set<Storage> sources;
        bool all = complete;
        for (auto& branch : branches) {
            auto found = branch.find(key);
            if (found == branch.end()) all = false;
            else sources.insert(found->second.begin(), found->second.end());
        }
        if (!all) sources.insert(key);
        state[key] = std::move(sources);
    }
}
void scan_comb(const Body& body, DependencyState& graph, DependencyState& state, const std::set<Storage>& controls = {}) {
    for (auto& statement : body) std::visit(Overloaded{
        [&](const Assignment& node) {
            auto deps = reads(node.value);
            // Select indices on the target are reads, not driven storage.
            walk_expression(node.target, [&](const Expr& value) { if (auto select = std::get_if<Select>(&value.node)) { auto refs = reads(select->first); deps.insert(refs.begin(), refs.end()); refs = reads(select->last); deps.insert(refs.begin(), refs.end()); } });
            deps = resolve_reads(deps, state); deps.insert(controls.begin(), controls.end());
            for (auto& target : storage(node.target)) { graph[target].insert(deps.begin(), deps.end()); state[target] = deps; }
        },
        [&](const If& node) {
            auto deps = resolve_reads(reads(node.condition), state); deps.insert(controls.begin(), controls.end());
            auto yes = state, no = state; scan_comb(node.yes, graph, yes, deps); scan_comb(node.no, graph, no, deps); merge_states(state, {yes, no}, true);
        },
        [&](const Case& node) {
            auto refs = reads(node.value);
            for (auto& arm : node.arms) for (auto& pattern : arm.patterns) { auto added = reads(pattern); refs.insert(added.begin(), added.end()); }
            auto deps = resolve_reads(refs, state); deps.insert(controls.begin(), controls.end());
            std::vector<DependencyState> branches; bool complete = false;
            for (auto& arm : node.arms) { auto branch = state; scan_comb(arm.body, graph, branch, deps); branches.push_back(std::move(branch)); complete |= arm.patterns.empty(); }
            merge_states(state, branches, complete);
        },
        [&](const For& node) {
            auto refs = reads(node.condition);
            for (auto& expression : {node.init, node.step}) { auto added = reads(expression); refs.insert(added.begin(), added.end()); }
            auto deps = resolve_reads(refs, state); deps.insert(controls.begin(), controls.end());
            auto branch = state; scan_comb(node.body, graph, branch, deps); merge_states(state, {state, branch}, true);
        },
        [&](const Group& node) { scan_comb(node.body, graph, state, controls); },
        [](const auto&) {}
    }, statement.node);
}
void detect_loops(const Module& module) {
    DependencyState graph;
    for (auto& statement : module.body) {
        DependencyState state;
        if (auto process = std::get_if<Process>(&statement.node); process && process->kind == ProcessKind::combinational) scan_comb(process->body, graph, state);
        if (std::holds_alternative<Assignment>(statement.node)) scan_comb({statement}, graph, state);
    }
    std::map<Storage, int> colors;
    std::map<std::string, std::vector<Storage>> targets_by_name;
    for (const auto& [target, dependencies] : graph) { (void)dependencies; targets_by_name[target.name].push_back(target); }
    // Iterative DFS avoids stack exhaustion on long integration chains.
    for (auto& [root, unused] : graph) {
        if (colors[root]) continue;
        std::vector<std::pair<Storage, bool>> pending{{root, false}};
        while (!pending.empty()) {
            auto [current, finish] = std::move(pending.back()); pending.pop_back();
            if (finish) { colors[current] = 2; continue; }
            if (colors[current] == 2) continue;
            if (colors[current] == 1) throw Error(module.loc, "E_COMB_LOOP", "combinational loop detected involving '" + current.name + "'");
            colors[current] = 1; pending.emplace_back(current, true);
            for (auto& read : graph[current]) for (auto& target : targets_by_name[read.name]) {
                if (overlap(read, target)) {
                    if (colors[target] == 1) throw Error(module.loc, "E_COMB_LOOP", "combinational loop detected involving '" + target.name + "'");
                    if (!colors[target]) pending.emplace_back(target, false);
                }
            }
        }
    }
}

struct Drivers {
    std::map<std::string, std::vector<std::pair<Storage, std::string>>> sources;
    void add(Storage target, const std::string& source, const Location& loc) {
        auto& existing = sources[target.name];
        for (auto& [previous, owner] : existing) if (owner != source && overlap(target, previous))
            throw Error(loc, "E_MULTIPLE_DRIVERS", "signal '" + target.name + "' driven by multiple drivers (" + owner + " and " + source + ")");
        existing.emplace_back(std::move(target), source);
    }
};
void correct_process(Body& body, bool sequential, std::set<Storage>& written, std::vector<Diagnostic>& warnings) {
    for (auto& statement : body) std::visit(Overloaded{
        [&](Assignment& node) {
            if (sequential && !node.nonblocking) {
                for (auto& target : storage(node.target)) for (auto& read : reads(node.value)) if (overlap(target, read))
                    if (std::any_of(written.begin(), written.end(), [&](const auto& prior) { return overlap(prior, read); })) {
                        warnings.push_back({statement.loc, "W_SEQ_CONVERSION", "blocking assignment to '" + target.name + "' reads a prior write; conversion samples the pre-clock value"}); break;
                    }
                node.nonblocking = true;
            }
            for (auto& target : storage(node.target)) written.insert(target);
        },
        [&](If& node) { auto yes = written, no = written; correct_process(node.yes, sequential, yes, warnings); correct_process(node.no, sequential, no, warnings); written.insert(yes.begin(), yes.end()); written.insert(no.begin(), no.end()); },
        [&](For& node) {
            auto prior = written;
            walk(node.body, [&](const Statement& statement) { if (auto assignment = std::get_if<Assignment>(&statement.node)) for (auto& target : storage(assignment->target)) prior.insert(target); });
            correct_process(node.body, sequential, prior, warnings); written.insert(prior.begin(), prior.end());
        },
        [&](Case& node) { for (auto& arm : node.arms) { auto branch = written; correct_process(arm.body, sequential, branch, warnings); written.insert(branch.begin(), branch.end()); } },
        [&](Group& node) { correct_process(node.body, sequential, written, warnings); },
        [&](SignalDecl&) {}, [&](LocalParam&) {},
        [&](Assertion& node) { if (node.compile_time) throw Error(statement.loc, "E_CONTEXT", "static_assert belongs at module level"); },
        [&](auto&) { throw Error(statement.loc, "E_CONTEXT", "instances and seq/comb/initial blocks must be at module level"); }
    }, statement.node);
}

void map_body(Body& body, const std::function<ExprPtr(const ExprPtr&)>& expression_map) {
    for (auto& statement : body) {
        auto apply = [&](ExprPtr& value) { if (value) value = expression_map(value); };
        std::visit(Overloaded{
            [&](Assignment& value) { apply(value.target); apply(value.value); },
            [&](LocalParam& value) { apply(value.value); },
            [&](SignalDecl& value) {
                apply(value.width); apply(value.array_first); apply(value.array_last);
                for (auto& [first,last] : value.dimensions) { apply(first); apply(last); }
            },
            [&](Process& value) {
                auto event = [&](std::string& text) {
                    if (text.empty()) return;
                    auto parsed = parse_expression(text, statement.loc.file);
                    auto located = rewrite(parsed, [](const Identifier& id, const Location& loc) { return expression(loc, id); },
                        [&](const ExprPtr& value) { return make_expression(statement.loc, value->node); });
                    text = to_sv(expression_map(located));
                };
                event(value.clock); event(value.reset); map_body(value.body, expression_map);
            },
            [&](If& value) { apply(value.condition); map_body(value.yes, expression_map); map_body(value.no, expression_map); },
            [&](For& value) { apply(value.init); apply(value.condition); apply(value.step); map_body(value.body, expression_map); },
            [&](Case& value) { apply(value.value); for (auto& arm : value.arms) { for (auto& pattern : arm.patterns) apply(pattern); map_body(arm.body, expression_map); } },
            [&](Instance& value) { for (auto& parameter : value.parameters) apply(parameter.value); for (auto& connection : value.connections) apply(connection.value); },
            [&](BundleUse& value) { for (auto& parameter : value.parameters) apply(parameter.value); for (auto& connection : value.connections) apply(connection.value); },
            [&](Assertion& value) { apply(value.condition); },
            [&](Return& value) { apply(value.value); },
            [&](RTLFunction& value) { map_body(value.body, expression_map); },
            [&](Group& value) { map_body(value.body, expression_map); },
            [](auto&) {}
        }, statement.node);
    }
}
struct BundleExpansion {
    std::map<std::string, std::vector<std::string>> groups;
    std::map<std::string, std::string> schemas;
};
BundleExpansion expand_bundles(Module& module, const std::vector<BundleSchema>& schemas);

BundleExpansion expand_bundles(Module& module, const std::vector<BundleSchema>& schemas) {
    BundleExpansion result;
    Body expanded;
    for (const auto& statement : module.body) {
        auto use = std::get_if<BundleUse>(&statement.node);
        if (!use) { expanded.push_back(statement); continue; }
        auto schema = std::find_if(schemas.begin(), schemas.end(), [&](const auto& value) { return value.name == use->schema; });
        if (schema == schemas.end()) throw Error(statement.loc, "E_BUNDLE", "unknown bundle schema '" + use->schema + "'");
        if (schema->fields.empty()) throw Error(statement.loc, "E_BUNDLE", "bundle must contain fields");
        if (result.groups.contains(use->name)) throw Error(statement.loc, "E_DUPLICATE", "duplicate bundle '" + use->name + "'");
        std::map<std::string, ExprPtr> defaults, overrides, bindings;
        for (const auto& parameter : schema->parameters) if (!defaults.emplace(parameter.name, parameter.value).second) throw Error(schema->loc, "E_DUPLICATE", "duplicate bundle parameter");
        for (const auto& parameter : use->parameters) {
            if (!defaults.contains(parameter.name)) throw Error(statement.loc, "E_PARAMETER", "unknown bundle parameter '" + parameter.name + "'");
            if (!overrides.emplace(parameter.name, parameter.value).second) throw Error(statement.loc, "E_PARAMETER", "duplicate bundle parameter override");
        }
        std::set<std::string> active;
        std::function<ExprPtr(const std::string&)> resolve = [&](const std::string& name) -> ExprPtr {
            if (overrides.contains(name)) return overrides.at(name);
            if (bindings.contains(name)) return bindings.at(name);
            if (!active.insert(name).second) throw Error(statement.loc, "E_PARAMETER", "cyclic bundle parameter defaults");
            auto value = rewrite(defaults.at(name), [&](const Identifier& id, const Location& loc) {
                return defaults.contains(id.name) ? expression(loc, Paren{resolve(id.name)}) : expression(loc, id);
            });
            active.erase(name); return bindings[name] = value;
        };
        for (const auto& [name, value] : defaults) { (void)value; bindings[name] = resolve(name); }
        auto port = std::find_if(module.ports.begin(), module.ports.end(), [&](const auto& value) { return value.name == use->name; });
        const bool exported = port != module.ports.end();
        if (exported && use->role == "bus") throw Error(statement.loc, "E_BUNDLE", "bundle ports require master or slave role");
        std::vector<PortDecl> ports;
        for (auto field : schema->fields) {
            if (std::find(result.groups[use->name].begin(), result.groups[use->name].end(), field.name) != result.groups[use->name].end())
                throw Error(schema->loc, "E_DUPLICATE", "duplicate bundle field '" + field.name + "'");
            result.groups[use->name].push_back(field.name);
            field.name = use->name + "_" + field.name;
            auto substitute_parameter = [&](const ExprPtr& value) {
                return rewrite(value, [&](const Identifier& id, const Location& loc) {
                    return bindings.contains(id.name) ? expression(loc, Paren{bindings.at(id.name)}) : expression(loc, id);
                });
            };
            field.width = substitute_parameter(field.width);
            field.array_first = substitute_parameter(field.array_first); field.array_last = substitute_parameter(field.array_last);
            for (auto& [first,last] : field.dimensions) { first = substitute_parameter(first); last = substitute_parameter(last); }
            if (!exported) field.direction.clear();
            else if (use->role == "slave") field.direction = field.direction == "input" ? "output" : "input";
            expanded.push_back({statement.loc, field});
            if (exported) ports.push_back({field.name, {}, statement.loc});
        }
        if (exported) { auto index = port - module.ports.begin(); module.ports.erase(module.ports.begin() + index); module.ports.insert(module.ports.begin() + index, ports.begin(), ports.end()); }
        result.schemas[use->name] = use->schema;
    }
    module.body = std::move(expanded);
    if (result.groups.empty()) return result;
    map_body(module.body, [&](const ExprPtr& value) {
        return rewrite(value, [](const Identifier& id, const Location& loc) { return expression(loc, id); }, [&](const ExprPtr& current) {
            auto field = std::get_if<Method>(&current->node);
            if (!field || !field->field) return current;
            auto base = std::get_if<Identifier>(&field->object->node);
            if (!base || !result.groups.contains(base->name)) return current;
            const auto& fields = result.groups.at(base->name);
            if (std::find(fields.begin(), fields.end(), field->name) == fields.end()) throw Error(current->loc, "E_BUNDLE", "unknown field '" + field->name + "' in bundle '" + base->name + "'");
            return expression(current->loc, Identifier{base->name + "_" + field->name});
        });
    });
    return result;
}

void validate_function(const RTLFunction& function, const Environment& environment, const Location& loc) {
    std::set<std::string> allowed;
    for (const auto& [name, value] : environment) { (void)value; allowed.insert(name); }
    for (const auto& argument : function.arguments) allowed.insert(argument.name);
    bool returns = false;
    walk(function.body, [&](const Statement& statement) {
        if (auto value = std::get_if<SignalDecl>(&statement.node)) allowed.insert(value->name);
        if (auto value = std::get_if<LocalParam>(&statement.node)) allowed.insert(value->name);
        if (auto value = std::get_if<For>(&statement.node)) allowed.insert(value->variable);
        if (auto value = std::get_if<TypeDecl>(&statement.node)) for (const auto& [name, expression] : value->constants) { (void)expression; allowed.insert(name); }
        if (std::holds_alternative<Return>(statement.node)) returns = true;
        if (std::holds_alternative<Process>(statement.node) || std::holds_alternative<Instance>(statement.node) ||
            std::holds_alternative<RTLFunction>(statement.node) || std::holds_alternative<BundleUse>(statement.node))
            throw Error(statement.loc, "E_FUNCTION", "RTL functions require combinational statements");
        if (auto assignment = std::get_if<Assignment>(&statement.node); assignment && assignment->nonblocking)
            throw Error(statement.loc, "E_FUNCTION", "RTL functions require blocking assignments");
    });
    if (!returns) throw Error(loc, "E_FUNCTION", "RTL function requires a return statement");
    auto check = [&](const ExprPtr& value) { for (const auto& name : references(value)) if (!allowed.contains(name)) throw Error(value->loc, "E_FUNCTION", "RTL function references nonlocal signal '" + name + "'"); };
    Body copy = function.body;
    map_body(copy, [&](const ExprPtr& value) { check(value); return value; });
    check(function.result.width);
    for (const auto& argument : function.arguments) { check(argument.width); check(argument.array_first); check(argument.array_last); }
}

std::vector<InterfacePort> instantiate(const Instance& instance, const Interface& interface, Backend& backend, Location loc);

void check_modport(const NativeInterface& definition, const std::string& type, const std::string& view, Location loc) {
    if (view.empty()) return;
    if (!definition.modports.contains(view)) throw Error(loc, "E_INTERFACE", "unknown modport '" + type + "." + view + "'");
    if (auto found = definition.unsupported_modports.find(view); found != definition.unsupported_modports.end())
        throw Error(loc, "E_INTERFACE", "unsupported " + found->second + " in modport '" + type + "." + view + "'");
}

// Keep interface objects in emitted SV. Dotted field identifiers are only an
// internal representation so the existing signal and storage checks can see them.
std::map<std::string, IRNativeInterface> expand_native_interfaces(Module& module, Backend& backend) {
    std::map<std::string, IRNativeInterface> result;
    Body body;
    for (const auto& statement : module.body) {
        auto use = std::get_if<BundleUse>(&statement.node);
        if (!use || !use->native) { body.push_back(statement); continue; }
        const auto& definition = backend.reflect_native(use->schema, statement.loc);
        IRNativeInterface info; info.loc = statement.loc; info.name = use->name; info.type = use->schema; info.modport = use->modport;
        info.port = std::any_of(module.ports.begin(), module.ports.end(), [&](const auto& port) { return port.name == use->name; });
        if (info.port && info.modport.empty()) throw Error(statement.loc, "E_INTERFACE", "Slip interface ports require a modport, for example 'interface " + info.type + ".master " + info.name + ";'");
        if (info.port && (!use->parameters.empty() || !use->connections.empty()))
            throw Error(statement.loc, "E_INTERFACE", "interface ports inherit parameters and constructor connections from the connected instance; configure an internal interface instance instead");
        if (!info.port && !use->modport.empty()) throw Error(statement.loc, "E_INTERFACE", "declare interface instances without a modport; select a modport at a port or connection");
        check_modport(definition, info.type, info.modport, statement.loc);
        info.modports = definition.modports;
        if (std::any_of(module.parameters.begin(), module.parameters.end(), [&](const auto& parameter) { return parameter.name == info.name; }))
            throw Error(statement.loc, "E_DUPLICATE", "interface name conflicts with parameter '" + info.name + "'");
        for (const auto& parameter : use->parameters) info.parameters.emplace_back(parameter.name, to_sv(parameter.value));
        Instance instance{use->schema, use->name, use->parameters, use->connections};
        auto fields = definition.constructor; fields.ports = definition.fields;
        // Substitution also validates parameter names, duplicates and localparams.
        auto reflected = instantiate(instance, fields, backend, statement.loc);
        for (const auto& field : reflected) {
            if (info.port && !info.modport.empty() && !info.modports.at(info.modport).contains(field.name)) continue;
            IRSignal signal; signal.name = info.name + "." + field.name; signal.loc = statement.loc;
            signal.interface_field = true; signal.infer_width = false;
            signal.is_signed = field.is_signed;
            signal.type = "type(" + signal.name + ")";
            signal.width = "[$bits(" + signal.name + ")-1:0]"; signal.array = field.array;
            if (info.port) {
                signal.direction = info.modport.empty() ? "inout" : info.modports.at(info.modport).at(field.name);
                signal.direction_explicit = true;
            } else {
                auto port = std::find_if(definition.constructor.ports.begin(), definition.constructor.ports.end(), [&](const auto& p) { return p.name == field.name; });
                if (port != definition.constructor.ports.end() && port->direction == "input") { signal.direction = "input"; signal.direction_explicit = true; }
            }
            info.fields.push_back(std::move(signal));
        }
        if (!result.emplace(info.name, info).second) throw Error(statement.loc, "E_DUPLICATE", "duplicate interface '" + info.name + "'");
        if (!info.port) body.push_back({statement.loc, std::move(instance)});
    }
    module.body = std::move(body);
    if (result.empty()) return result;
    map_body(module.body, [&](const ExprPtr& value) {
        return rewrite(value, [](const Identifier& id, const Location& loc) { return expression(loc, id); }, [&](const ExprPtr& current) {
            const auto* field = std::get_if<Method>(&current->node);
            if (!field || !field->field) return current;
            const auto* base = std::get_if<Identifier>(&field->object->node);
            if (!base || !result.contains(base->name)) return current;
            const auto& info = result.at(base->name);
            const auto name = base->name + "." + field->name;
            if (!std::any_of(info.fields.begin(), info.fields.end(), [&](const auto& item) { return item.name == name; }) && !info.modports.contains(field->name))
                throw Error(current->loc, "E_INTERFACE", "unknown or inaccessible interface field '" + name + "'");
            return expression(current->loc, Identifier{name});
        });
    });
    return result;
}

struct Lowered {
    IRModule ir;
    std::vector<std::pair<Location, Instance>> unresolved;
    Drivers drivers;
    Environment environment;
};
Lowered lower(const Module& original, Backend& backend, const Options& options, std::vector<Diagnostic>& warnings, const std::vector<BundleSchema>& schemas) {
    Lowered result;
    result.ir.loc = original.loc; result.ir.name = original.name; result.ir.parameters = original.parameters;
    for (auto& [name, value] : original.frozen) result.ir.frozen_parameters.emplace_back(name, value);
    for (auto& parameter : original.parameters) result.environment.emplace_back(parameter.name, to_sv(parameter.value));
    std::function<void(const Body&)> top_locals = [&](const Body& body) {
        for (auto& statement : body) {
            if (auto local = std::get_if<LocalParam>(&statement.node)) result.environment.emplace_back(local->name, to_sv(local->value));
            if (auto type = std::get_if<TypeDecl>(&statement.node)) for (auto& [name, value] : type->constants) result.environment.emplace_back(name, to_sv(value));
            if (auto group = std::get_if<Group>(&statement.node)) top_locals(group->body);
        }
    };
    top_locals(original.body);
    Module module = original;
    module.body = Expander(backend, options).expand(original.body, result.environment);
    result.ir.native_interfaces = expand_native_interfaces(module, backend);
    auto bundles = expand_bundles(module, schemas);
    result.ir.bundles = bundles.groups; result.ir.bundle_types = bundles.schemas;
    std::map<std::string, SignalDecl> declarations;
    std::map<std::string, Location> signal_locations, first_uses;
    std::map<std::string, ExprPtr> locals;
    std::set<std::string> reserved, loop_vars, driven;
    std::vector<std::string> used;
    for (const auto& [name, fields] : bundles.groups) { (void)fields; reserved.insert(name); }
    for (const auto& [name, info] : result.ir.native_interfaces) {
        if (!reserved.insert(name).second) throw Error(info.loc, "E_DUPLICATE", "conflicting interface declaration '" + name + "'");
        for (const auto& field : info.fields) { reserved.insert(field.name); result.ir.signals.push_back(field); }
        for (const auto& [view, fields] : info.modports) { (void)fields; reserved.insert(name + "." + view); }
    }
    std::string use_expansion;
    auto use = [&](const ExprPtr& expr) {
        walk_expression(expr, [&](const Expr& value) {
            if (auto id = std::get_if<Identifier>(&value.node); id && id->name != "_") {
                auto loc = value.loc; loc.expansion = use_expansion;
                first_uses.try_emplace(id->name, std::move(loc));
            }
        });
        for (auto& name : references(expr)) if (std::find(used.begin(), used.end(), name) == used.end()) used.push_back(name);
    };
    auto use_name = [&](const std::string& name, Location loc) { if (!name.empty()) use(expression(loc, Identifier{name})); };
    for (auto& parameter : module.parameters) reserved.insert(parameter.name);
    auto declare = [&](const std::string& name, const Location& loc) {
        if (!reserved.insert(name).second) throw Error(loc, "E_DUPLICATE", "duplicate declaration of '" + name + "'");
    };
    walk(module.body, [&](const Statement& statement) {
        auto loc = statement.loc;
        use_expansion = loc.expansion;
        std::visit(Overloaded{
            [&](const SignalDecl& node) { declare(node.name, loc); declarations.emplace(node.name, node); signal_locations.emplace(node.name, loc); use(node.width); use(node.array_first); use(node.array_last); for (auto& [first, last] : node.dimensions) { use(first); use(last); } },
            [&](const LocalParam& node) { declare(node.name, loc); locals.emplace(node.name, node.value); result.ir.localparams.push_back({node.name, node.value}); result.ir.localparam_locations.push_back(loc); },
            [&](const Assignment& node) { use(node.target); use(node.value); for (auto& target : storage(node.target)) driven.insert(target.name); },
            [&](const Process& node) { if (!node.clock.empty()) use(parse_expression(node.clock, loc.file)); if (!node.reset.empty()) use(parse_expression(node.reset, loc.file)); },
            [&](const If& node) { use(node.condition); },
            [&](const For& node) { loop_vars.insert(node.variable); use(node.init); use(node.condition); use(node.step); },
            [&](const Case& node) { use(node.value); for (auto& arm : node.arms) for (auto& pattern : arm.patterns) use(pattern); },
            [&](const Instance& node) { if (!result.ir.native_interfaces.contains(node.name) || result.ir.native_interfaces.at(node.name).port || result.ir.native_interfaces.at(node.name).type != node.module) declare(node.name, loc); for (auto& parameter : node.parameters) use(parameter.value); for (auto& connection : node.connections) { if (connection.value) use(connection.value); else if (!connection.regex) use_name(connection.port, loc); } },
            [&](const TypeDecl& node) { declare(node.name, loc); for (auto& [name, value] : node.constants) { (void)value; declare(name, loc); } },
            [&](const RTLFunction& node) { declare(node.result.name, loc); },
            [&](const Assertion& node) { use(node.condition); },
            [](const Return&) {}, [](const BundleUse&) {},
            [](const Group&) {}
        }, statement.node);
    });
    // Inline body localparams in ANSI headers, while preserving module parameters.
    std::function<ExprPtr(const ExprPtr&, std::set<std::string>)> port_expr = [&](const ExprPtr& expr, std::set<std::string> active) {
        return rewrite(expr, [&](const Identifier& id, const Location& loc) {
            auto found = locals.find(id.name);
            if (found == locals.end()) return expression(loc, id);
            if (!active.insert(id.name).second) throw Error(loc, "E_CONSTANT", "cyclic localparam dependency");
            return expression(loc, Paren{port_expr(found->second, active)});
        });
    };
    auto make_signal = [&](const std::string& name, bool port, const ExprPtr& port_width = ExprPtr{}) {
        IRSignal signal; signal.name = name;
        signal.loc = first_uses.contains(name) ? first_uses.at(name) : module.loc;
        if (auto found = declarations.find(name); found != declarations.end()) {
            signal.loc = signal_locations.at(name);
            auto& decl = found->second;
            signal.type = decl.type; signal.infer_width = false; signal.direction_explicit = !decl.direction.empty();
            signal.width = dimension(port ? port_expr(decl.width, {}) : decl.width); signal.is_signed = decl.is_signed;
            if (decl.array_first) signal.array = "[" + to_sv(port ? port_expr(decl.array_first, {}) : decl.array_first) + ":" + to_sv(port ? port_expr(decl.array_last, {}) : decl.array_last) + "]";
            for (auto& [first, last] : decl.dimensions) signal.array += "[" + to_sv(port ? port_expr(first, {}) : first) + ":" + to_sv(port ? port_expr(last, {}) : last) + "]";
        } else { signal.declared = port ? !module.ports.empty() : false; signal.width = dimension(port_expr(port_width, {})); }
        if (port) signal.direction = driven.contains(name) ? "output" : "input";
        if (port && declarations.contains(name) && !declarations.at(name).direction.empty()) signal.direction = declarations.at(name).direction;
        if (signal.direction_explicit && signal.direction == "input" && driven.contains(name)) throw Error(signal.loc, "E_DIRECTION", "input port '" + name + "' is driven inside the module");
        return signal;
    };
    std::set<std::string> port_names;
    for (auto& port : module.ports) {
        if (result.ir.native_interfaces.contains(port.name)) {
            if (!port_names.insert(port.name).second) throw Error(port.loc, "E_DUPLICATE", "duplicate interface port '" + port.name + "'");
            if (port.width) throw Error(port.loc, "E_INTERFACE", "interface port arrays and widths are not supported");
            const auto& info = result.ir.native_interfaces.at(port.name);
            IRSignal signal; signal.name = port.name; signal.loc = info.loc; signal.interface_port = true; signal.infer_width = false;
            signal.type = info.type + (info.modport.empty() ? "" : "." + info.modport);
            result.ir.ports.push_back(std::move(signal));
            continue;
        }
        if (!port_names.insert(port.name).second || (reserved.contains(port.name) && !declarations.contains(port.name))) throw Error(port.loc, "E_DUPLICATE", "duplicate or conflicting port '" + port.name + "'");
        result.ir.ports.push_back(make_signal(port.name, true, port.width));
        if (!declarations.contains(port.name)) result.ir.ports.back().loc = port.loc;
    }
    if (module.ports.empty()) for (auto& name : used)
        if (!reserved.contains(name) && !loop_vars.contains(name)) { port_names.insert(name); result.ir.ports.push_back(make_signal(name, true)); result.ir.ports.back().declared = false; }
    // Preserve declaration order rather than map order for stable generated source.
    walk(module.body, [&](const Statement& statement) {
        if (auto decl = std::get_if<SignalDecl>(&statement.node); decl && !port_names.contains(decl->name)) result.ir.signals.push_back(make_signal(decl->name, false));
    });
    for (auto& name : used) if (!reserved.contains(name) && !port_names.contains(name) && !loop_vars.contains(name)) result.ir.signals.push_back(make_signal(name, false));
    for (const auto& signal : result.ir.signals) if (signal.interface_field && signal.direction == "input" && driven.contains(signal.name))
        throw Error(signal.loc, "E_DIRECTION", "input interface field '" + signal.name + "' is driven inside the module");
    std::map<std::string, std::string> reset_polarities;
    std::size_t process_id = 0, assignment_id = 0;
    for (auto& statement : module.body) {
        if (auto assignment = std::get_if<Assignment>(&statement.node)) {
            if (assignment->nonblocking) throw Error(statement.loc, "E_CONTEXT", "nonblocking assignment is not allowed at module level");
            result.ir.assignments.push_back(*assignment);
            result.ir.assignment_locations.push_back(statement.loc);
            for (auto& target : storage(assignment->target)) result.drivers.add(target, "assign " + std::to_string(++assignment_id), statement.loc);
        } else if (auto process = std::get_if<Process>(&statement.node)) {
            auto converted = *process; std::set<Storage> written;
            correct_process(converted.body, process->kind == ProcessKind::sequential, written, warnings);
            if (process->kind != ProcessKind::initial) {
                auto owner = "process " + std::to_string(++process_id);
                for (auto& target : written) { Storage owned{target.name, {}}; owned.members = target.members; result.drivers.add(std::move(owned), owner, statement.loc); }
            }
            if (!process->reset.empty()) {
                auto [found, added] = reset_polarities.emplace(process->reset, process->edge);
                if (!added && found->second != process->edge) throw Error(statement.loc, "E_RESET", "reset signal used with conflicting polarity");
            }
            result.ir.processes.push_back(std::move(converted));
            result.ir.process_locations.push_back(statement.loc);
        } else if (std::holds_alternative<TypeDecl>(statement.node) || std::holds_alternative<RTLFunction>(statement.node)) {
            if (auto function = std::get_if<RTLFunction>(&statement.node)) validate_function(*function, result.environment, statement.loc);
            result.ir.declarations.push_back(statement);
        }
        else if (auto assertion = std::get_if<Assertion>(&statement.node)) {
            if (!assertion->compile_time) throw Error(statement.loc, "E_CONTEXT", "assert must be inside comb, seq, initial or a function; use static_assert at module level");
            try {
                if (backend.constant("!(" + to_sv(assertion->condition) + ")", result.environment, statement.loc) != 0) throw Error(statement.loc, "E_ASSERT", assertion->message.empty() ? "static assertion failed" : unquote(assertion->message));
            } catch (const Error& error) {
                if (error.code != "E_CONSTANT") throw; // Type queries and RTL functions are checked in the complete SV context.
            }
            result.ir.declarations.push_back(statement);
        } else if (auto instance = std::get_if<Instance>(&statement.node)) result.unresolved.emplace_back(statement.loc, *instance);
        else if (!std::holds_alternative<SignalDecl>(statement.node) && !std::holds_alternative<LocalParam>(statement.node)) throw Error(statement.loc, "E_CONTEXT", "runtime if/for/case must be inside a comb, seq or initial block");
    }
    detect_loops(module);
    return result;
}

Interface interface_of(const IRModule& module) {
    Interface result; result.parameters = module.parameters; result.localparams = module.localparams;
    for (auto& port : module.ports) {
        InterfacePort info{port.name, port.direction, port.width, port.array, port.is_signed};
        if (port.interface_port) {
            const auto& native = module.native_interfaces.at(port.name);
            info.native = true; info.direction = "interface"; info.interface_type = native.type; info.modport = native.modport;
        }
        result.ports.push_back(std::move(info));
    }
    for (const auto& [name, fields] : module.bundles) if (!fields.empty() && std::any_of(module.ports.begin(), module.ports.end(), [&](const auto& port) { return port.name == name + "_" + fields.front(); })) { result.bundles[name] = fields; result.bundle_types[name] = module.bundle_types.at(name); }
    for (auto& [name, value] : module.frozen_parameters) { (void)value; result.frozen.insert(name); }
    return result;
}
std::string substitute_sv(std::string_view text, const std::map<std::string, std::string>& values) {
    std::string result;
    for (std::size_t i = 0; i < text.size();) {
        auto start = i;
        if (text[i] == '"') {
            ++i;
            while (i < text.size()) {
                if (text[i] == '\\' && i + 1 < text.size()) i += 2;
                else if (text[i++] == '"') break;
            }
            result += text.substr(start, i - start); continue;
        }
        if (std::isdigit(static_cast<unsigned char>(text[i])) || text[i] == '\'') {
            while (i < text.size() && (std::isdigit(static_cast<unsigned char>(text[i])) || text[i] == '_')) ++i;
            if (i < text.size() && text[i] == '\'') {
                auto radix = i + 1;
                if (radix < text.size() && (text[radix] == 's' || text[radix] == 'S')) ++radix;
                if (radix < text.size() && std::string_view("bBoOdDhH").find(text[radix]) != std::string_view::npos) {
                    i = radix + 1;
                    while (i < text.size() && (std::isalnum(static_cast<unsigned char>(text[i])) || text[i] == '_' || text[i] == '?')) ++i;
                } else if (i + 1 < text.size() && (text[i+1] == '0' || text[i+1] == '1')) i += 2;
            }
            if (i == start) ++i;
            result += text.substr(start, i - start); continue;
        }
        if (text[i] == '$') {
            ++i;
            while (i < text.size() && (std::isalnum(static_cast<unsigned char>(text[i])) || text[i] == '_')) ++i;
            result += text.substr(start, i - start); continue;
        }
        if (std::isalpha(static_cast<unsigned char>(text[i])) || text[i] == '_') {
            ++i;
            while (i < text.size() && (std::isalnum(static_cast<unsigned char>(text[i])) || text[i] == '_')) ++i;
            auto name = std::string(text.substr(start, i - start)); auto found = values.find(name);
            if ((start > 0 && text[start-1] == '.') || (start > 1 && text.substr(start-2, 2) == "::")) found = values.end();
            result += found == values.end() ? name : "(" + found->second + ")";
        } else result += text[i++];
    }
    return result;
}
std::vector<InterfacePort> instantiate(const Instance& instance, const Interface& interface, Backend& backend, Location loc) {
    std::map<std::string, std::string> overrides, defaults, resolved;
    for (auto& parameter : interface.parameters) defaults[parameter.name] = to_sv(parameter.value);
    for (auto& parameter : interface.localparams) defaults[parameter.name] = to_sv(parameter.value);
    for (auto& parameter : instance.parameters) {
        if (overrides.contains(parameter.name)) throw Error(loc, "E_PARAMETER", "duplicate parameter override '" + parameter.name + "'");
        if (std::none_of(interface.parameters.begin(), interface.parameters.end(), [&](const auto& declared) { return declared.name == parameter.name; })) throw Error(loc, "E_PARAMETER", "unknown parameter or non-overridable localparam '" + parameter.name + "'");
        if (interface.frozen.contains(parameter.name)) throw Error(loc, "E_PARAMETER", "cannot override parameter '" + parameter.name + "': it controls expanded structure");
        overrides[parameter.name] = to_sv(parameter.value);
    }
    std::set<std::string> active;
    std::function<std::string(const std::string&)> resolve = [&](const std::string& name) -> std::string {
        if (auto found = resolved.find(name); found != resolved.end()) return found->second;
        if (auto found = overrides.find(name); found != overrides.end()) return resolved[name] = found->second;
        if (!active.insert(name).second) throw Error(loc, "E_PARAMETER", "cyclic parameter default involving '" + name + "'");
        std::map<std::string, std::string> dependencies;
        auto expr = defaults.at(name);
        for (auto& [other, value] : defaults) { (void)value; if (other != name && substitute_sv(expr, {{other, "__slip_dependency"}}) != expr) dependencies[other] = resolve(other); }
        auto result = substitute_sv(expr, dependencies); active.erase(name); return resolved[name] = result;
    };
    for (auto& [name, value] : defaults) { (void)value; resolve(name); }
    auto simplify = [&](const std::string& dimension) {
        std::string text = substitute_sv(dimension, resolved), result;
        static const std::regex range(R"(\[([^\[\]]+):([^\[\]]+)\])"); std::size_t prior = 0;
        for (auto it = std::sregex_iterator(text.begin(), text.end(), range); it != std::sregex_iterator(); ++it) {
            auto& match = *it; result += text.substr(prior, match.position() - prior);
            try { result += "[" + std::to_string(backend.constant(match[1].str(), {}, loc)) + ":" + std::to_string(backend.constant(match[2].str(), {}, loc)) + "]"; }
            catch (const Error&) { result += match.str(); }
            prior = match.position() + match.length();
        }
        result += text.substr(prior); return result;
    };
    auto ports = interface.ports;
    for (auto& port : ports) { port.width = simplify(port.width); port.array = simplify(port.array); }
    return ports;
}

void resolve_instances(Lowered& module, std::map<std::string, Interface>& interfaces, const std::set<std::string>& local_names, Backend& backend, Functions& functions, const Options& options, std::vector<Diagnostic>& warnings) {
    for (auto& [loc, instance] : module.unresolved) {
        if (backend.interface_names.contains(instance.module) &&
            (!module.ir.native_interfaces.contains(instance.name) || module.ir.native_interfaces.at(instance.name).type != instance.module))
            throw Error(loc, "E_INTERFACE", "declare SV interface instances with 'interface " + instance.module + " " + instance.name + "'");
        auto found = interfaces.find(instance.module);
        if (found == interfaces.end()) if (auto external = backend.reflect(instance.module)) found = interfaces.emplace(instance.module, *external).first;
        if (found == interfaces.end()) throw Error(loc, "E_MODULE", "cannot resolve target module '" + instance.module + "' (pass -ip/-f for external IP)");
        auto ports = instantiate(instance, found->second, backend, loc);
        std::vector<Connection> expanded_connections;
        std::set<std::string> bundle_ports;
        for (const auto& connection : instance.connections) {
            if (connection.regex || !found->second.bundles.contains(connection.port)) { expanded_connections.push_back(connection); continue; }
            auto value = connection.value ? connection.value : expression(loc, Identifier{connection.port});
            auto group = std::get_if<Identifier>(&value->node);
            if (!group || !module.ir.bundles.contains(group->name)) throw Error(loc, "E_BUNDLE", "group connection requires a declared bundle");
            if (module.ir.bundle_types.at(group->name) != found->second.bundle_types.at(connection.port))
                throw Error(loc, "E_BUNDLE", "bundle schema mismatch at '" + instance.name + "." + connection.port + "'");
            const auto& fields = found->second.bundles.at(connection.port);
            if (fields != module.ir.bundles.at(group->name)) throw Error(loc, "E_BUNDLE", "bundle fields do not match");
            for (const auto& field : fields) {
                Connection expanded; expanded.port = connection.port + "_" + field;
                expanded.value = expression(value->loc, Identifier{group->name + "_" + field});
                bundle_ports.insert(expanded.port); expanded_connections.push_back(std::move(expanded));
            }
        }
        std::map<std::string, ExprPtr> connections;
        std::map<std::string, std::string> origins;
        std::vector<std::string> order;
        for (auto& connection : expanded_connections) if (!connection.regex) {
            if (connections.contains(connection.port)) throw Error(loc, "E_CONNECTION", "duplicate connection to port '" + connection.port + "'");
            if (std::none_of(ports.begin(), ports.end(), [&](const auto& port) { return port.name == connection.port; })) throw Error(loc, "E_CONNECTION", "unknown port '" + connection.port + "' in '" + instance.module + "'");
            auto value = connection.value ? connection.value : expression(loc, Identifier{connection.port});
            if (auto literal = std::get_if<Literal>(&value->node); literal && !literal->string && literal->text.find_first_not_of("0123456789_") == std::string::npos)
                throw Error(value->loc, "E_CONNECTION", "bare integer in port connection requires explicit width or '0/'1");
            connections.emplace(connection.port, value); order.push_back(connection.port);
            origins[connection.port] = bundle_ports.contains(connection.port) ? "bundle" : connection.value ? "explicit" : "shorthand";
        }
        struct Rule { Pattern pattern; std::string replacement, source; std::size_t connections = 0; };
        std::vector<Rule> rules;
        for (auto& connection : expanded_connections) if (connection.regex) {
            rules.push_back({Pattern(connection.pattern, loc), connection.replacement, connection.pattern});
        }
        for (auto& port : ports) if (!connections.contains(port.name)) {
            bool matched = false;
            for (auto& rule : rules) {
                auto captures = rule.pattern.match(port.name);
                if (!captures) continue;
                auto candidate = functions.replacement(rule.replacement, *captures);
                if (candidate != "_" && !std::regex_match(candidate, std::regex("[A-Za-z_][A-Za-z0-9_]*"))) throw Error(loc, "E_REGEX", "replacement must produce a valid signal name");
                connections.emplace(port.name, expression(loc, Identifier{candidate})); order.push_back(port.name);
                origins[port.name] = "regex: " + rule.source; ++rule.connections; matched = true; break;
            }
            if (!matched && (port.native || (port.direction != "output" && (local_names.contains(instance.module) || !rules.empty())))) throw Error(loc, "E_CONNECTION", "unconnected " + (port.native ? std::string("interface") : std::string("input")) + " port '" + port.name + "' of '" + instance.module + "'");
            if (!matched) warnings.push_back({loc, "W_UNCONNECTED", "unconnected " + port.direction + " port '" + port.name + "' in '" + instance.name + "'; use ." + port.name + "(_) if intentional"});
        }
        for (const auto& rule : rules) if (rule.connections == 0)
            warnings.push_back({loc, "W_REGEX_UNUSED", "regex rule '" + rule.source + "' connected no ports in '" + instance.name +
                "'; check its spelling, explicit connections and earlier rules"});
        for (auto& port : ports) {
            auto connected = connections.find(port.name);
            if (port.native && (connected == connections.end() || to_sv(connected->second) == "_"))
                throw Error(loc, "E_CONNECTION", "interface port '" + instance.name + "." + port.name + "' requires an interface instance");
            if (connected == connections.end() || to_sv(connected->second) == "_") continue;
            auto expr = connected->second;
            auto whole = std::get_if<Identifier>(&expr->node);
            if (port.native) {
                if (!whole) throw Error(expr->loc, "E_INTERFACE", "interface connection requires a declared interface instance or port");
                auto dot = whole->name.find('.');
                auto root = whole->name.substr(0, dot);
                auto found_native = module.ir.native_interfaces.find(root);
                if (found_native == module.ir.native_interfaces.end()) throw Error(expr->loc, "E_INTERFACE", "'" + root + "' is not a declared interface");
                const auto& actual = found_native->second;
                if (!port.interface_type.empty() && actual.type != port.interface_type)
                    throw Error(expr->loc, "E_INTERFACE", "interface type mismatch at '" + instance.name + "." + port.name + "': expected " + port.interface_type + ", got " + actual.type);
                const auto& definition = backend.reflect_native(actual.type, expr->loc);
                const auto selected = dot == std::string::npos ? std::string{} : whole->name.substr(dot + 1);
                check_modport(definition, actual.type, selected, expr->loc);
                check_modport(definition, actual.type, port.modport, expr->loc);
                if ((!selected.empty() && !port.modport.empty() && selected != port.modport) ||
                    (!actual.modport.empty() && ((!selected.empty() && selected != actual.modport) || port.modport != actual.modport)))
                    throw Error(expr->loc, "E_DIRECTION", "incompatible modport connection at '" + instance.name + "." + port.name + "'");
                const auto view = !port.modport.empty() ? port.modport : selected;
                for (const auto& field : actual.fields) {
                    const auto member = field.name.substr(actual.name.size() + 1);
                    if (!view.empty() && !actual.modports.at(view).contains(member)) continue;
                    const auto direction = view.empty() ? "inout" : actual.modports.at(view).at(member);
                    if (field.direction == "input" && direction != "input")
                        throw Error(expr->loc, "E_DIRECTION", "instance '" + instance.name + "' drives input interface field '" + field.name + "'");
                    if (direction == "output") module.drivers.add(Storage{field.name, {}}, instance.name + "." + port.name + "." + member, expr->loc);
                }
                origins[port.name] = "interface";
                continue;
            }
            if (whole && module.ir.native_interfaces.contains(whole->name))
                throw Error(expr->loc, "E_INTERFACE", "ordinary port '" + port.name + "' requires a field expression, not a whole interface");
            if (whole && !std::any_of(module.ir.ports.begin(), module.ir.ports.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.signals.begin(), module.ir.signals.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.parameters.begin(), module.ir.parameters.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.localparams.begin(), module.ir.localparams.end(), [&](const auto& p) { return p.name == whole->name; })) {
                IRSignal signal;
                signal.name = whole->name; signal.declared = false; signal.loc = loc;
                module.ir.signals.push_back(std::move(signal));
            }
            auto targets = storage(expr);
            auto infer = [&](std::vector<IRSignal>& signals) {
                for (auto& signal : signals) {
                    if (whole && whole->name == signal.name) {
                        if (signal.width.empty() && signal.infer_width && signal.type == "logic") { signal.width = port.width; signal.is_signed |= port.is_signed; if (!port.width.empty()) signal.inferred_from = instance.module + "." + port.name; }
                        if (signal.array.empty()) signal.array = port.array;
                    }
                    if (!signal.direction.empty() && std::any_of(targets.begin(), targets.end(), [&](const auto& target) { return target.name == signal.name; })) {
                        if ((port.direction == "output" || port.direction == "inout") && signal.direction == "input" && signal.direction_explicit)
                            throw Error(expr->loc, "E_DIRECTION", "instance " + port.direction + " drives explicit input '" + signal.name + "'");
                        if (port.direction == "output" && signal.direction == "input") {
                            signal.direction = "output";
                        }
                        if (port.direction == "inout") signal.direction = "inout";
                    }
                }
            };
            infer(module.ir.signals); infer(module.ir.ports);
            if (port.direction == "output") {
                if (targets.empty()) throw Error(expr->loc, "E_CONNECTION", "output port requires an assignable connection");
                for (auto& target : targets) module.drivers.add(target, instance.name + "." + port.name, expr->loc);
            }
        }
        IRInstance resolved{loc, instance.module, instance.name, {}, {}};
        for (auto& parameter : instance.parameters) resolved.parameters.emplace_back(parameter.name, to_sv(parameter.value));
        for (auto& port : order) resolved.connections.emplace_back(port, to_sv(connections.at(port)));
        for (auto& port : ports) {
            auto connected = connections.find(port.name);
            auto connection_loc = connected == connections.end() ? loc : connected->second->loc;
            connection_loc.expansion = loc.expansion;
            resolved.connection_details.push_back({port.name, port.direction, port.width, port.array,
                connected == connections.end() ? "" : to_sv(connected->second),
                connected == connections.end() ? "unconnected" : origins.at(port.name), connection_loc});
        }
        module.ir.instances.push_back(std::move(resolved));
    }
    std::vector<const IRSignal*> explicit_signals;
    for (auto* signals : {&module.ir.ports, &module.ir.signals}) for (const auto& signal : *signals)
        if (signal.declared) explicit_signals.push_back(&signal);
    std::size_t suggestion_budget = 1000000;
    for (auto* signals : {&module.ir.ports, &module.ir.signals}) for (auto& signal : *signals) {
        if (signal.declared) continue;
        if (options.strict || options.no_implicit)
            throw Error(signal.loc, "E_IMPLICIT", "explicit declaration required for '" + signal.name + "'; add a signal declaration or list it as a port");
        std::string message = "implicit " + std::string(signal.direction.empty() ? "signal" : "port") + " '" + signal.name + "'";
        message += signal.width.empty() ? " defaults to 1-bit" : " has inferred width " + signal.width;
        if (!signal.inferred_from.empty()) message += " from " + signal.inferred_from;
        // Suggest only explicit declarations, within this module, with a small edit distance.
        auto distance = [](std::string_view a, std::string_view b) {
            std::vector<std::size_t> row(b.size() + 1);
            for (std::size_t j = 0; j <= b.size(); ++j) row[j] = j;
            for (std::size_t i = 1; i <= a.size(); ++i) {
                auto diagonal = row[0]; row[0] = i;
                for (std::size_t j = 1; j <= b.size(); ++j) {
                    auto previous = row[j];
                    row[j] = std::min({row[j] + 1, row[j - 1] + 1, diagonal + (a[i - 1] != b[j - 1])});
                    diagonal = previous;
                }
            }
            return row.back();
        };
        std::string suggestion;
        std::size_t best = signal.name.size() >= 4 ? 3 : 2;
        bool ambiguous = false;
        for (auto* item : explicit_signals) {
            if (explicit_signals.size() > 512 || suggestion_budget == 0 || signal.name.size() < 3 || signal.name.size() > 64) { suggestion.clear(); break; }
            const auto& candidate = *item;
            if (candidate.name == signal.name || candidate.name.size() < 3 || candidate.name.size() > 64) continue;
            if (candidate.name.size() > signal.name.size() + 2 || signal.name.size() > candidate.name.size() + 2) continue;
            auto work = signal.name.size() * candidate.name.size();
            if (work > suggestion_budget) { suggestion_budget = 0; suggestion.clear(); break; }
            suggestion_budget -= work;
            auto edits = distance(signal.name, candidate.name);
            if (edits < best) { best = edits; suggestion = candidate.name; ambiguous = false; }
            else if (edits == best) ambiguous = true;
        }
        if (!suggestion.empty() && !ambiguous) message += "; did you mean '" + suggestion + "'?";
        else message += "; declare it explicitly or use --no-implicit to reject implicit declarations";
        warnings.push_back({signal.loc, "W_IMPLICIT", std::move(message)});
    }
}

struct EmittedSource {
    std::string text;
    std::vector<Location> lines;
    void line(std::string value, const Location& loc) {
        text += value + '\n';
        lines.push_back(loc);
    }
};
std::string signal_decl(const IRSignal& signal);
void emit_body(EmittedSource& output, const Body& body, unsigned level, bool function = false) {
    std::string indent(level * 4, ' ');
    for (auto& statement : body) std::visit(Overloaded{
        [&](const Assignment& node) { output.line(indent + to_sv(node.target) + (node.nonblocking ? " <= " : " = ") + to_sv(node.value) + ";", statement.loc); },
        [&](const If& node) {
            output.line(indent + "if (" + to_sv(node.condition) + ") begin", statement.loc);
            emit_body(output, node.yes, level + 1, function);
            if (!node.no.empty()) {
                output.line(indent + "end else begin", statement.loc);
                emit_body(output, node.no, level + 1, function);
            }
            output.line(indent + "end", statement.loc);
        },
        [&](const For& node) {
            output.line(indent + "for (int " + node.variable + " = " + to_sv(node.init) + "; " + to_sv(node.condition) + "; " + node.step_variable + " = " + to_sv(node.step) + ") begin", statement.loc);
            emit_body(output, node.body, level + 1, function);
            output.line(indent + "end", statement.loc);
        },
        [&](const Case& node) {
            output.line(indent + node.kind + " (" + to_sv(node.value) + ")", statement.loc);
            for (auto& arm : node.arms) {
                std::vector<std::string> patterns; for (auto& pattern : arm.patterns) patterns.push_back(to_sv(pattern));
                auto loc = arm.patterns.empty() ? statement.loc : arm.patterns.front()->loc;
                loc.expansion = statement.loc.expansion;
                output.line(indent + "    " + (patterns.empty() ? "default" : join(patterns, ", ")) + ": begin", loc);
                emit_body(output, arm.body, level + 2, function);
                output.line(indent + "    end", loc);
            }
            output.line(indent + "endcase", statement.loc);
        },
        [&](const Group& node) { emit_body(output, node.body, level, function); },
        [&](const Assertion& node) {
            if (node.compile_time) throw Error(statement.loc, "E_CONTEXT", "static_assert belongs at module level");
            output.line(indent + "assert (" + to_sv(node.condition) + ") else $error(" +
                (node.message.empty() ? "\"Slip assertion failed\"" : node.message) + ");", statement.loc);
        },
        [&](const Return& node) {
            if (!function) throw Error(statement.loc, "E_CONTEXT", "return belongs in an RTL function");
            output.line(indent + "return " + to_sv(node.value) + ";", statement.loc);
        },
        [&](const SignalDecl& node) {
            if (!function) return;
            IRSignal signal; signal.name = node.name; signal.type = node.type; signal.is_signed = node.is_signed; signal.width = dimension(node.width);
            if (node.array_first) signal.array = "[" + to_sv(node.array_first) + ":" + to_sv(node.array_last) + "]";
            for (auto& [first,last] : node.dimensions) signal.array += "[" + to_sv(first) + ":" + to_sv(last) + "]";
            output.line(indent + signal_decl(signal) + ";", statement.loc);
        },
        [&](const LocalParam& node) { if (function) output.line(indent + "localparam " + node.name + " = " + to_sv(node.value) + ";", statement.loc); },
        [&](const TypeDecl& node) { if (function) output.line(indent + node.sv, statement.loc); },
        [&](const auto&) { throw Error(statement.loc, "E_CONTEXT", "unsupported statement in this procedural scope"); }
    }, statement.node);
}
std::string signal_decl(const IRSignal& signal) {
    return (signal.direction.empty() ? "" : signal.direction + " ") + signal.type + " " + (signal.is_signed ? "signed " : "") +
        (signal.width.empty() ? "" : signal.width + " ") + signal.name + (signal.array.empty() ? "" : " " + signal.array);
}
EmittedSource emit(const IRModule& module) {
    EmittedSource output;
    auto annotation = [](const IRSignal& signal) {
        std::vector<std::string> tags;
        if (!signal.declared) tags.push_back("implicit");
        if (signal.width.empty() && (signal.type == "logic" || signal.type == "bit")) tags.push_back("no width");
        if (!signal.inferred_from.empty()) tags.push_back("width from " + signal.inferred_from);
        return tags.empty() ? std::string{} : "    // " + join(tags, ", ");
    };
    const bool typed_ports = std::any_of(module.ports.begin(), module.ports.end(), [](const auto& port) { return port.type != "logic" && port.type != "bit" && port.type != "int"; });
    std::string source = "module " + module.name;
    if (!module.parameters.empty()) {
        output.line(source + " #(", module.loc);
        for (std::size_t i = 0; i < module.parameters.size(); ++i) output.line("    parameter " + module.parameters[i].name + " = " + to_sv(module.parameters[i].value) + (i + 1 == module.parameters.size() ? "" : ","), module.parameters[i].value->loc);
        source = ")";
    }
    if (!module.ports.empty()) {
        output.line(source + " (", module.loc);
        for (std::size_t i = 0; i < module.ports.size(); ++i) {
            const auto& port = module.ports[i];
            auto comment = annotation(port); if (!comment.empty()) output.line(comment, port.loc);
            output.line("    " + (typed_ports ? port.name : signal_decl(port)) + (i + 1 == module.ports.size() ? "" : ","), port.loc);
        }
        source = ")";
    }
    output.line(source + ";", module.loc);
    for (const auto& declaration : module.declarations) if (auto type = std::get_if<TypeDecl>(&declaration.node)) output.line("    " + type->sv, declaration.loc);
    if (typed_ports) for (const auto& port : module.ports) output.line("    " + signal_decl(port) + ";", port.loc);
    for (std::size_t i = 0; i < module.localparams.size(); ++i) {
        const auto& parameter = module.localparams[i];
        output.line("    localparam " + parameter.name + " = " + to_sv(parameter.value) + ";", module.localparam_locations.at(i));
    }
    for (auto& signal : module.signals) {
        if (signal.interface_field) continue;
        auto comment = annotation(signal); if (!comment.empty()) output.line(comment, signal.loc);
        output.line("    " + signal_decl(signal) + ";", signal.loc);
    }
    for (const auto& declaration : module.declarations) if (auto function = std::get_if<RTLFunction>(&declaration.node)) {
        IRSignal result; result.name = function->result.name; result.type = function->result.type;
        result.is_signed = function->result.is_signed; result.width = dimension(function->result.width);
        std::vector<std::string> args;
        for (const auto& arg : function->arguments) {
            IRSignal signal; signal.name = arg.name; signal.type = arg.type; signal.direction = "input"; signal.is_signed = arg.is_signed; signal.width = dimension(arg.width);
            if (arg.array_first) signal.array = "[" + to_sv(arg.array_first) + ":" + to_sv(arg.array_last) + "]";
            for (auto& [first,last] : arg.dimensions) signal.array += "[" + to_sv(first) + ":" + to_sv(last) + "]";
            args.push_back(signal_decl(signal));
        }
        output.line("    function automatic " + signal_decl(result) + "(" + join(args, ", ") + ");", declaration.loc);
        emit_body(output, function->body, 2, true);
        output.line("    endfunction", declaration.loc);
    }
    std::size_t assertion_id = 0;
    for (const auto& declaration : module.declarations) if (auto assertion = std::get_if<Assertion>(&declaration.node)) {
        output.line("    if ((!(" + to_sv(assertion->condition) + ")) !== 1'b0) begin : __slip_static_assert_" + std::to_string(assertion_id++), declaration.loc);
        output.line("        $error(" + (assertion->message.empty() ? "\"static assertion failed\"" : assertion->message) + ");", declaration.loc);
        output.line("    end", declaration.loc);
    }
    for (auto& [name, value] : module.frozen_parameters) {
        output.line("    if (" + name + " !== (" + std::to_string(value) + ")) begin : __slip_frozen_" + name, module.loc);
        output.line("        $error(\"" + name + " controls Slip compile-time expansion and cannot be overridden\");", module.loc);
        output.line("    end", module.loc);
    }
    for (std::size_t i = 0; i < module.assignments.size(); ++i) {
        const auto& assignment = module.assignments[i];
        output.line("    assign " + to_sv(assignment.target) + " = " + to_sv(assignment.value) + ";", module.assignment_locations.at(i));
    }
    for (std::size_t i = 0; i < module.processes.size(); ++i) {
        const auto& process = module.processes[i];
        const auto& loc = module.process_locations.at(i);
        source = "    ";
        if (process.kind == ProcessKind::combinational) source += "always_comb";
        else if (process.kind == ProcessKind::initial) source += "initial";
        else { source += "always_ff @(" + std::string(process.clock_edge == "neg" ? "negedge " : "posedge ") + process.clock; if (!process.reset.empty()) source += " or " + std::string(process.edge == "pos" ? "posedge " : "negedge ") + process.reset; source += ")"; }
        output.line(source + " begin", loc);
        emit_body(output, process.body, 2);
        output.line("    end", loc);
    }
    for (auto& instance : module.instances) {
        source = "    " + instance.module;
        if (!instance.parameters.empty()) {
            output.line(source + " #(", instance.loc);
            for (std::size_t i = 0; i < instance.parameters.size(); ++i) output.line("        ." + instance.parameters[i].first + "(" + instance.parameters[i].second + ")" + (i + 1 == instance.parameters.size() ? "" : ","), instance.loc);
            source = "    )";
        }
        source += " " + instance.name + " (";
        std::vector<std::pair<std::string, Location>> ports;
        for (auto& [port, signal] : instance.connections) if (signal != "_") {
            const auto info = std::find_if(instance.connection_details.begin(), instance.connection_details.end(), [&](const auto& value) { return value.port == port; });
            ports.emplace_back("        ." + port + "(" + signal + ")", info == instance.connection_details.end() ? instance.loc : info->loc);
        }
        if (!ports.empty()) {
            output.line(source, instance.loc);
            for (std::size_t i = 0; i < ports.size(); ++i) output.line(ports[i].first + (i + 1 == ports.size() ? "" : ","), ports[i].second);
            source = "    ";
        }
        output.line(source + ");", instance.loc);
    }
    output.line("endmodule", module.loc);
    return output;
}

void resolve_includes(Unit& unit, const std::filesystem::path& base, std::set<std::filesystem::path>& seen, const Options& options, std::size_t depth = 0) {
    if (depth > options.max_include_depth) throw Error({base.string()}, "E_LIMIT", "include nesting limit exceeded");
    for (auto& include : unit.includes) {
        auto path = std::filesystem::weakly_canonical(base / include.path);
        if (!seen.insert(path).second) continue;
        auto included = parse(read_file(path), path.string()); resolve_includes(included, path.parent_path(), seen, options, depth + 1);
        unit.modules.insert(unit.modules.end(), std::make_move_iterator(included.modules.begin()), std::make_move_iterator(included.modules.end()));
        unit.functions.insert(unit.functions.end(), std::make_move_iterator(included.functions.begin()), std::make_move_iterator(included.functions.end()));
        unit.declarations.insert(unit.declarations.end(), included.declarations.begin(), included.declarations.end());
        unit.bundles.insert(unit.bundles.end(), included.bundles.begin(), included.bundles.end());
    }
    unit.includes.clear();
}
class Specializer {
    Backend& backend;
    const Options& options;
    std::map<std::string, Module> templates, generated;
    std::map<std::string, int> state;
    std::map<std::string, std::string> cache;
    std::size_t depth = 0;
    void process(const std::string& name) {
        if (state[name] == 2) return;
        if (state[name] == 1) throw Error(generated.at(name).loc, "E_MODULE_CYCLE", "cyclic module instantiation dependency");
        if (++depth > 128) throw Error(generated.at(name).loc, "E_LIMIT", "specialization dependency depth exceeded");
        state[name] = 1;
        auto& module = generated.at(name);
        module.frozen = frozen_parameters(module, backend);
        Environment env;
        std::map<std::string, ExprPtr> definitions;
        for (const auto& parameter : module.parameters) { env.emplace_back(parameter.name, to_sv(parameter.value)); definitions[parameter.name] = parameter.value; }
        walk(module.body, [&](const Statement& statement) {
            if (auto local = std::get_if<LocalParam>(&statement.node)) definitions[local->name] = local->value;
        });
        std::function<void(const Body&)> collect = [&](const Body& body) { for (const auto& statement : body) {
            if (auto type = std::get_if<TypeDecl>(&statement.node)) for (auto& [key, value] : type->constants) env.emplace_back(key, to_sv(value));
            if (auto local = std::get_if<LocalParam>(&statement.node)) env.emplace_back(local->name, to_sv(local->value));
            if (auto group = std::get_if<Group>(&statement.node)) collect(group->body);
        } }; collect(module.body);
        module.body = Expander(backend, options).expand(module.body, env);
        rewrite_instances(module.body, module, env, definitions);
        state[name] = 2; --depth;
    }
    void rewrite_instances(Body& body, Module& parent, const Environment& env, const std::map<std::string, ExprPtr>& definitions);
public:
    Specializer(Backend& backend, const Options& options) : backend(backend), options(options) {}
    void run(Unit& unit) {
        for (auto module : unit.modules) {
            module.body.insert(module.body.begin(), unit.declarations.begin(), unit.declarations.end());
            if (!templates.emplace(module.name, module).second) throw Error(module.loc, "E_DUPLICATE", "duplicate module '" + module.name + "'");
            generated.emplace(module.name, std::move(module));
        }
        for (const auto& [name, module] : templates) { (void)module; process(name); }
        unit.modules.clear();
        for (auto& [name, module] : generated) { (void)name; unit.modules.push_back(std::move(module)); }
    }
};

void Specializer::rewrite_instances(Body& body, Module& parent, const Environment& env, const std::map<std::string, ExprPtr>& definitions) {
    for (auto& statement : body) {
        if (auto group = std::get_if<Group>(&statement.node)) { rewrite_instances(group->body, parent, env, definitions); continue; }
        auto instance = std::get_if<Instance>(&statement.node);
        if (!instance || !templates.contains(instance->module)) continue;
        const auto original_name = instance->module;
        const auto& target = templates.at(original_name);
        process(original_name);
        const auto defaults = generated.at(original_name).frozen;
        std::map<std::string, std::int64_t> frozen(defaults.begin(), defaults.end()), overrides;
        std::set<std::string> seen;
        bool changed = false;
        for (const auto& parameter : instance->parameters) {
            if (!seen.insert(parameter.name).second) throw Error(statement.loc, "E_PARAMETER", "duplicate parameter override '" + parameter.name + "'");
            if (!frozen.contains(parameter.name)) continue;
            auto value = backend.constant(to_sv(parameter.value), env, statement.loc);
            overrides[parameter.name] = value; changed |= value != frozen.at(parameter.name);
            std::vector<std::string> pending = references(parameter.value); std::set<std::string> visited;
            for (std::size_t i = 0; i < pending.size(); ++i) {
                const auto key = pending[i];
                if (!visited.insert(key).second) continue;
                auto declaration = definitions.find(key);
                if (declaration != definitions.end()) {
                    for (auto& ref : references(declaration->second)) pending.push_back(ref);
                    if (std::any_of(parent.parameters.begin(), parent.parameters.end(), [&](const auto& item) { return item.name == key; }) &&
                        std::none_of(parent.frozen.begin(), parent.frozen.end(), [&](const auto& item) { return item.first == key; }))
                        parent.frozen.emplace_back(key, backend.constant(key, env, statement.loc));
                }
            }
        }
        if (changed) {
            Environment effective;
            for (const auto& parameter : target.parameters) effective.emplace_back(parameter.name, overrides.contains(parameter.name) ? std::to_string(overrides.at(parameter.name)) : to_sv(parameter.value));
            std::string key = original_name;
            for (const auto& [name, value] : frozen) { (void)value; key += ";" + name + "=" + std::to_string(backend.constant(name, effective, statement.loc)); }
            auto found = cache.find(key);
            if (found != cache.end()) instance->module = found->second;
            else {
                if (cache.size() >= 1024) throw Error(statement.loc, "E_LIMIT", "module specialization limit exceeded");
                std::uint64_t hash = 14695981039346656037ull;
                for (unsigned char ch : key) { hash ^= ch; hash *= 1099511628211ull; }
                auto clone = target; clone.name += "__slip_" + std::to_string(hash);
                if (generated.contains(clone.name)) throw Error(statement.loc, "E_DUPLICATE", "specialized module name collision");
                for (auto& parameter : clone.parameters) if (overrides.contains(parameter.name))
                    parameter.value = expression(statement.loc, Literal{std::to_string(overrides.at(parameter.name))});
                instance->module = clone.name; cache[key] = clone.name;
                generated.emplace(clone.name, std::move(clone));
            }
        }
        std::erase_if(instance->parameters, [&](const auto& parameter) { return frozen.contains(parameter.name); });
        process(instance->module);
    }
}

Result compile_unit(Unit unit, const Options& options) {
    Backend backend(options);
    std::set<std::string> schema_names;
    for (const auto& schema : unit.bundles) if (!schema_names.insert(schema.name).second) throw Error(schema.loc, "E_DUPLICATE", "duplicate bundle schema '" + schema.name + "'");
    Specializer(backend, options).run(unit);
    Functions functions(unit.functions); Result result;
    SourceMaps source_maps;
    std::map<std::string, Lowered> modules;
    std::set<std::string> local_names;
    bool native_interfaces = false;
    for (auto& module : unit.modules) {
        if (!local_names.insert(module.name).second || backend.ip_names.contains(module.name)) throw Error(module.loc, "E_DUPLICATE", "duplicate module '" + module.name + "'");
        modules.emplace(module.name, lower(module, backend, options, result.warnings, unit.bundles));
        native_interfaces |= !modules.at(module.name).ir.native_interfaces.empty();
    }
    std::map<std::string, std::size_t> dependencies;
    std::map<std::string, std::set<std::string>> dependents;
    std::set<std::string> ready;
    for (auto& [name, module] : modules) {
        std::set<std::string> used;
        for (auto& [loc, instance] : module.unresolved) { (void)loc; if (modules.contains(instance.module)) used.insert(instance.module); }
        dependencies[name] = used.size();
        if (used.empty()) ready.insert(name);
        for (auto& target : used) dependents[target].insert(name);
    }
    auto interfaces = backend.ips;
    while (!ready.empty()) {
        auto name = *ready.begin(); ready.erase(ready.begin());
        auto& module = modules.at(name);
        resolve_instances(module, interfaces, local_names, backend, functions, options, result.warnings);
        interfaces[name] = interface_of(module.ir);
        auto emitted = emit(module.ir);
        result.modules[name] = std::move(emitted.text);
        source_maps[name] = std::move(emitted.lines);
        if (options.collect_inspection) result.inspection.emplace(name, std::move(module.ir));
        for (auto& parent : dependents[name]) if (--dependencies[parent] == 0) ready.insert(parent);
    }
    if (result.modules.size() != modules.size()) throw Error({}, "E_MODULE_CYCLE", "cyclic module instantiation dependency");
    backend.validate(result.modules, source_maps, options.strict || options.widths_as_errors, result.warnings, native_interfaces);
    return result;
}
} // namespace

Result compile(std::string_view source, std::string filename, const Options& options) {
    auto unit = parse(source, filename);
    std::set<std::filesystem::path> seen;
    auto path = std::filesystem::path(filename);
    if (std::filesystem::is_regular_file(path)) seen.insert(std::filesystem::weakly_canonical(path));
    resolve_includes(unit, path.parent_path(), seen, options);
    return compile_unit(std::move(unit), options);
}
Result compile_file(const std::filesystem::path& file, const Options& options) { return compile(read_file(file), file.string(), options); }
void write_outputs(const Result& result, const std::filesystem::path& directory) {
    std::error_code error;
    std::filesystem::create_directories(directory, error);
    if (error) throw Error({directory.string()}, "E_IO", "cannot create output directory: " + error.message());
    for (const auto& [name, source] : result.modules) {
        (void)source;
        auto file = directory / (name + ".sv");
        auto state = std::filesystem::status(file, error);
        if (error == std::errc::no_such_file_or_directory) error.clear();
        if (error) throw Error({file.string()}, "E_IO", "cannot inspect output path: " + error.message());
        if (std::filesystem::is_directory(state)) throw Error({file.string()}, "E_IO", "output path is a directory");
    }
    for (auto& [name, source] : result.modules) {
        auto file = directory / (name + ".sv");
        std::ofstream output(file, std::ios::binary | std::ios::trunc);
        if (!output || !(output << source)) throw Error({file.string()}, "E_IO", "cannot write output");
    }
}
} // namespace slip
