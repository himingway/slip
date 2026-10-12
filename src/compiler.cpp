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
ExprPtr rewrite(const ExprPtr& expr, const std::function<ExprPtr(const Identifier&, const Location&)>& identifier) {
    if (!expr) return {};
    auto sub = [&](const ExprPtr& value) { return rewrite(value, identifier); };
    return std::visit(Overloaded{
        [&](const Identifier& node) { return identifier(node, expr->loc); },
        [&](const Literal&) { return expr; },
        [&](const Unary& node) { return expression(expr->loc, Unary{node.op, sub(node.operand)}); },
        [&](const Binary& node) { return expression(expr->loc, Binary{node.op, sub(node.left), sub(node.right)}); },
        [&](const Ternary& node) { return expression(expr->loc, Ternary{sub(node.condition), sub(node.yes), sub(node.no)}); },
        [&](const Select& node) { return expression(expr->loc, Select{sub(node.base), sub(node.first), sub(node.last), node.slice}); },
        [&](const Concat& node) { std::vector<ExprPtr> parts; for (auto& part : node.parts) parts.push_back(sub(part)); return expression(expr->loc, Concat{std::move(parts)}); },
        [&](const Repeat& node) { return expression(expr->loc, Repeat{sub(node.count), sub(node.value)}); },
        [&](const Call& node) { std::vector<ExprPtr> args; for (auto& arg : node.args) args.push_back(sub(arg)); return expression(expr->loc, Call{node.name, std::move(args)}); },
        [&](const Method& node) { std::vector<ExprPtr> args; for (auto& arg : node.args) args.push_back(sub(arg)); return expression(expr->loc, Method{sub(node.object), node.name, std::move(args)}); },
        [&](const Paren& node) { return expression(expr->loc, Paren{sub(node.value)}); },
        [&](const Cast& node) { return expression(expr->loc, Cast{node.type, sub(node.value)}); }
    }, expr->node);
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
        if (auto select = std::get_if<Select>(&expr->node)) return expression(expr->loc, Select{hardware(select->base, values), index(select->first, values), index(select->last, values), select->slice});
        return sub(expr, values);
    }
public:
    Expander(Backend& backend, const Options& options) : backend(backend), options(options) {}
    Body expand(const Body& body, Environment env, Substitutions values = {}) {
        Body result;
        for (const auto& statement : body) {
            auto loc = statement.loc;
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
                    return {loc, SignalDecl{substitute_name(node.name, values), width, index(node.array_first, values), index(node.array_last, values), node.is_signed}};
                },
                [&](const LocalParam& node) -> Statement {
                    auto name = substitute_name(node.name, values); auto value = hardware(node.value, values);
                    set_environment(env, name, to_sv(value)); return {loc, LocalParam{name, value}};
                },
                [&](const Assignment& node) -> Statement { return {loc, Assignment{hardware(node.target, values), hardware(node.value, values), node.nonblocking}}; },
                [&](const Process& node) -> Statement { return {loc, Process{node.kind, substitute_name(node.clock, values), substitute_name(node.reset, values), node.edge, expand(node.body, env, values)}}; },
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
                [&](const Group& node) -> Statement { return {loc, Group{expand(node.body, env, values)}}; }
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
    walk(module.body, [&](const Statement& statement) {
        auto add = [&](const ExprPtr& expr) { for (auto& ref : references(expr)) dependencies.insert(ref); };
        if (auto conditional = std::get_if<If>(&statement.node); conditional && conditional->meta) add(conditional->condition);
        if (auto loop = std::get_if<For>(&statement.node); loop && loop->meta) { add(loop->init); add(loop->condition); add(loop->step); }
        if (auto local = std::get_if<LocalParam>(&statement.node)) declarations[local->name] = local->value;
    });
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
    auto operator<=>(const Storage&) const = default;
};
bool overlap(const Storage& a, const Storage& b) {
    if (a.name != b.name) return false;
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
    if (auto select = std::get_if<Select>(&expr->node)) {
        auto result = storage(select->base); auto first = literal_integer(select->first); auto last = select->slice ? literal_integer(select->last) : first;
        std::optional<std::pair<std::int64_t, std::int64_t>> range;
        if (first && last) range = std::minmax(*first, *last);
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
        [&](const Method& node) { add(node.object); for (auto& arg : node.args) add(arg); },
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
            if (auto select = std::get_if<Select>(&node.target->node)) { auto refs = reads(select->first); deps.insert(refs.begin(), refs.end()); refs = reads(select->last); deps.insert(refs.begin(), refs.end()); }
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
        [&](auto&) { throw Error(statement.loc, "E_CONTEXT", "instances and seq/comb/initial blocks must be at module level"); }
    }, statement.node);
}

struct Lowered {
    IRModule ir;
    std::vector<std::pair<Location, Instance>> unresolved;
    Drivers drivers;
    Environment environment;
};
Lowered lower(const Module& original, Backend& backend, const Options& options, std::vector<Diagnostic>& warnings) {
    Lowered result;
    result.ir.loc = original.loc; result.ir.name = original.name; result.ir.parameters = original.parameters;
    result.ir.frozen_parameters = frozen_parameters(original, backend);
    for (auto& parameter : original.parameters) result.environment.emplace_back(parameter.name, to_sv(parameter.value));
    std::function<void(const Body&)> top_locals = [&](const Body& body) {
        for (auto& statement : body) {
            if (auto local = std::get_if<LocalParam>(&statement.node)) result.environment.emplace_back(local->name, to_sv(local->value));
            if (auto group = std::get_if<Group>(&statement.node)) top_locals(group->body);
        }
    };
    top_locals(original.body);
    Module module = original;
    module.body = Expander(backend, options).expand(original.body, result.environment);
    std::map<std::string, SignalDecl> declarations;
    std::map<std::string, ExprPtr> locals;
    std::set<std::string> reserved, loop_vars, driven;
    std::vector<std::string> used;
    auto use = [&](const ExprPtr& expr) { for (auto& name : references(expr)) if (std::find(used.begin(), used.end(), name) == used.end()) used.push_back(name); };
    auto use_name = [&](const std::string& name, Location loc) { if (!name.empty()) use(expression(loc, Identifier{name})); };
    for (auto& parameter : module.parameters) reserved.insert(parameter.name);
    auto declare = [&](const std::string& name, const Location& loc) {
        if (!reserved.insert(name).second) throw Error(loc, "E_DUPLICATE", "duplicate declaration of '" + name + "'");
    };
    walk(module.body, [&](const Statement& statement) {
        auto loc = statement.loc;
        std::visit(Overloaded{
            [&](const SignalDecl& node) { declare(node.name, loc); declarations.emplace(node.name, node); use(node.width); use(node.array_first); use(node.array_last); },
            [&](const LocalParam& node) { declare(node.name, loc); locals.emplace(node.name, node.value); result.ir.localparams.push_back({node.name, node.value}); },
            [&](const Assignment& node) { use(node.target); use(node.value); for (auto& target : storage(node.target)) driven.insert(target.name); },
            [&](const Process& node) { use_name(node.clock, loc); use_name(node.reset, loc); },
            [&](const If& node) { use(node.condition); },
            [&](const For& node) { loop_vars.insert(node.variable); use(node.init); use(node.condition); use(node.step); },
            [&](const Case& node) { use(node.value); for (auto& arm : node.arms) for (auto& pattern : arm.patterns) use(pattern); },
            [&](const Instance& node) { declare(node.name, loc); for (auto& parameter : node.parameters) use(parameter.value); for (auto& connection : node.connections) { if (connection.value) use(connection.value); else if (!connection.regex) use_name(connection.port, loc); } },
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
        if (auto found = declarations.find(name); found != declarations.end()) {
            auto& decl = found->second;
            signal.width = dimension(port ? port_expr(decl.width, {}) : decl.width); signal.is_signed = decl.is_signed;
            if (decl.array_first) signal.array = "[" + to_sv(port ? port_expr(decl.array_first, {}) : decl.array_first) + ":" + to_sv(port ? port_expr(decl.array_last, {}) : decl.array_last) + "]";
        } else { signal.declared = port ? !module.ports.empty() : false; signal.width = dimension(port_expr(port_width, {})); }
        if (port) signal.direction = driven.contains(name) ? "output" : "input";
        return signal;
    };
    std::set<std::string> port_names;
    for (auto& port : module.ports) {
        if (!port_names.insert(port.name).second || (reserved.contains(port.name) && !declarations.contains(port.name))) throw Error(port.loc, "E_DUPLICATE", "duplicate or conflicting port '" + port.name + "'");
        result.ir.ports.push_back(make_signal(port.name, true, port.width));
    }
    if (module.ports.empty()) for (auto& name : used)
        if (!reserved.contains(name) && !loop_vars.contains(name)) { port_names.insert(name); result.ir.ports.push_back(make_signal(name, true)); result.ir.ports.back().declared = false; }
    // Preserve declaration order rather than map order for stable generated source.
    walk(module.body, [&](const Statement& statement) {
        if (auto decl = std::get_if<SignalDecl>(&statement.node); decl && !port_names.contains(decl->name)) result.ir.signals.push_back(make_signal(decl->name, false));
    });
    for (auto& name : used) if (!reserved.contains(name) && !port_names.contains(name) && !loop_vars.contains(name)) result.ir.signals.push_back(make_signal(name, false));
    std::map<std::string, std::string> reset_polarities;
    std::size_t process_id = 0, assignment_id = 0;
    for (auto& statement : module.body) {
        if (auto assignment = std::get_if<Assignment>(&statement.node)) {
            if (assignment->nonblocking) throw Error(statement.loc, "E_CONTEXT", "nonblocking assignment is not allowed at module level");
            result.ir.assignments.push_back(*assignment);
            for (auto& target : storage(assignment->target)) result.drivers.add(target, "assign " + std::to_string(++assignment_id), statement.loc);
        } else if (auto process = std::get_if<Process>(&statement.node)) {
            auto converted = *process; std::set<Storage> written;
            correct_process(converted.body, process->kind == ProcessKind::sequential, written, warnings);
            if (process->kind != ProcessKind::initial) {
                auto owner = "process " + std::to_string(++process_id);
                for (auto& target : written) result.drivers.add({target.name, {}}, owner, statement.loc);
            }
            if (!process->reset.empty()) {
                auto [found, added] = reset_polarities.emplace(process->reset, process->edge);
                if (!added && found->second != process->edge) throw Error(statement.loc, "E_RESET", "reset signal used with conflicting polarity");
            }
            result.ir.processes.push_back(std::move(converted));
        } else if (auto instance = std::get_if<Instance>(&statement.node)) result.unresolved.emplace_back(statement.loc, *instance);
        else if (!std::holds_alternative<SignalDecl>(statement.node) && !std::holds_alternative<LocalParam>(statement.node)) throw Error(statement.loc, "E_CONTEXT", "runtime if/for/case must be inside a comb, seq or initial block");
    }
    detect_loops(module);
    return result;
}

Interface interface_of(const IRModule& module) {
    Interface result; result.parameters = module.parameters; result.localparams = module.localparams;
    for (auto& port : module.ports) result.ports.push_back({port.name, port.direction, port.width, port.array, port.is_signed});
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
        std::regex range(R"(\[([^\[\]]+):([^\[\]]+)\])"); std::size_t prior = 0;
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

void resolve_instances(Lowered& module, const std::map<std::string, Interface>& interfaces, const std::set<std::string>& local_names, Backend& backend, Functions& functions, const Options& options, std::vector<Diagnostic>& warnings) {
    for (auto& [loc, instance] : module.unresolved) {
        auto found = interfaces.find(instance.module);
        if (found == interfaces.end()) throw Error(loc, "E_MODULE", "cannot resolve target module '" + instance.module + "' (pass -ip/-f for external IP)");
        auto ports = instantiate(instance, found->second, backend, loc);
        std::map<std::string, ExprPtr> connections;
        std::vector<std::string> order;
        for (auto& connection : instance.connections) if (!connection.regex) {
            if (connections.contains(connection.port)) throw Error(loc, "E_CONNECTION", "duplicate connection to port '" + connection.port + "'");
            if (std::none_of(ports.begin(), ports.end(), [&](const auto& port) { return port.name == connection.port; })) throw Error(loc, "E_CONNECTION", "unknown port '" + connection.port + "' in '" + instance.module + "'");
            auto value = connection.value ? connection.value : expression(loc, Identifier{connection.port});
            if (auto literal = std::get_if<Literal>(&value->node); literal && !literal->string && literal->text.find_first_not_of("0123456789_") == std::string::npos)
                throw Error(value->loc, "E_CONNECTION", "bare integer in port connection requires explicit width or '0/'1");
            connections.emplace(connection.port, value); order.push_back(connection.port);
        }
        struct Rule { Pattern pattern; std::string replacement; };
        std::vector<Rule> rules;
        for (auto& connection : instance.connections) if (connection.regex) {
            rules.push_back({Pattern(connection.pattern, loc), connection.replacement});
        }
        for (auto& port : ports) if (!connections.contains(port.name)) {
            bool matched = false;
            for (auto& rule : rules) {
                auto captures = rule.pattern.match(port.name);
                if (!captures) continue;
                auto candidate = functions.replacement(rule.replacement, *captures);
                if (candidate != "_" && !std::regex_match(candidate, std::regex("[A-Za-z_][A-Za-z0-9_]*"))) throw Error(loc, "E_REGEX", "replacement must produce a valid signal name");
                connections.emplace(port.name, expression(loc, Identifier{candidate})); order.push_back(port.name); matched = true; break;
            }
            if (!matched && port.direction != "output" && (local_names.contains(instance.module) || !rules.empty())) throw Error(loc, "E_CONNECTION", "unconnected input port '" + port.name + "' of '" + instance.module + "'");
            if (!matched && port.direction == "output" && !rules.empty()) warnings.push_back({loc, "W_UNCONNECTED", "unconnected output port '" + port.name + "' in '" + instance.name + "'"});
        }
        for (auto& port : ports) {
            auto connected = connections.find(port.name); if (connected == connections.end() || to_sv(connected->second) == "_") continue;
            auto expr = connected->second;
            auto whole = std::get_if<Identifier>(&expr->node);
            if (whole && !std::any_of(module.ir.ports.begin(), module.ir.ports.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.signals.begin(), module.ir.signals.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.parameters.begin(), module.ir.parameters.end(), [&](const auto& p) { return p.name == whole->name; }) &&
                !std::any_of(module.ir.localparams.begin(), module.ir.localparams.end(), [&](const auto& p) { return p.name == whole->name; })) module.ir.signals.push_back({whole->name, {}, {}, false, false, {}, {}});
            auto targets = storage(expr);
            auto infer = [&](std::vector<IRSignal>& signals) {
                for (auto& signal : signals) {
                    if (whole && whole->name == signal.name) {
                        if (signal.width.empty()) { signal.width = port.width; signal.is_signed |= port.is_signed; if (!port.width.empty()) signal.inferred_from = instance.module + "." + port.name; }
                        if (signal.array.empty()) signal.array = port.array;
                    }
                    if (!signal.direction.empty() && std::any_of(targets.begin(), targets.end(), [&](const auto& target) { return target.name == signal.name; })) {
                        if (port.direction == "output" && signal.direction == "input") signal.direction = "output";
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
        module.ir.instances.push_back(std::move(resolved));
    }
    if (options.strict) for (auto* signals : {&module.ir.ports, &module.ir.signals}) for (auto& signal : *signals)
        if (!signal.declared) throw Error(module.ir.loc, "E_IMPLICIT", "strict mode requires explicit declaration of '" + signal.name + "'");
}

std::string emit_body(const Body& body, unsigned level) {
    std::string result, indent(level * 4, ' ');
    for (auto& statement : body) std::visit(Overloaded{
        [&](const Assignment& node) { result += indent + to_sv(node.target) + (node.nonblocking ? " <= " : " = ") + to_sv(node.value) + ";\n"; },
        [&](const If& node) {
            result += indent + "if (" + to_sv(node.condition) + ") begin\n" + emit_body(node.yes, level + 1) + indent + "end";
            if (!node.no.empty()) result += " else begin\n" + emit_body(node.no, level + 1) + indent + "end";
            result += '\n';
        },
        [&](const For& node) { result += indent + "for (int " + node.variable + " = " + to_sv(node.init) + "; " + to_sv(node.condition) + "; " + node.step_variable + " = " + to_sv(node.step) + ") begin\n" + emit_body(node.body, level + 1) + indent + "end\n"; },
        [&](const Case& node) {
            result += indent + node.kind + " (" + to_sv(node.value) + ")\n";
            for (auto& arm : node.arms) { std::vector<std::string> patterns; for (auto& pattern : arm.patterns) patterns.push_back(to_sv(pattern)); result += indent + "    " + (patterns.empty() ? "default" : join(patterns, ", ")) + ": begin\n" + emit_body(arm.body, level + 2) + indent + "    end\n"; }
            result += indent + "endcase\n";
        },
        [&](const Group& node) { result += emit_body(node.body, level); },
        [](const SignalDecl&) {}, [](const LocalParam&) {},
        [&](const auto&) { throw Error(statement.loc, "E_INTERNAL", "unsupported procedural IR node"); }
    }, statement.node);
    return result;
}
std::string signal_decl(const IRSignal& signal) {
    return (signal.direction.empty() ? "" : signal.direction + " ") + std::string("logic ") + (signal.is_signed ? "signed " : "") +
        (signal.width.empty() ? "" : signal.width + " ") + signal.name + (signal.array.empty() ? "" : " " + signal.array);
}
std::string emit(const IRModule& module) {
    auto annotation = [](const IRSignal& signal) {
        std::vector<std::string> tags;
        if (!signal.declared) tags.push_back("implicit");
        if (signal.width.empty()) tags.push_back("no width");
        if (!signal.inferred_from.empty()) tags.push_back("width from " + signal.inferred_from);
        return tags.empty() ? std::string{} : "    // " + join(tags, ", ") + "\n";
    };
    std::string source = "module " + module.name;
    if (!module.parameters.empty()) {
        source += " #(\n";
        for (std::size_t i = 0; i < module.parameters.size(); ++i) source += "    parameter " + module.parameters[i].name + " = " + to_sv(module.parameters[i].value) + (i + 1 == module.parameters.size() ? "\n" : ",\n");
        source += ")";
    }
    if (!module.ports.empty()) {
        source += " (\n";
        for (std::size_t i = 0; i < module.ports.size(); ++i) source += annotation(module.ports[i]) + "    " + signal_decl(module.ports[i]) + (i + 1 == module.ports.size() ? "\n" : ",\n");
        source += ")";
    }
    source += ";\n";
    for (auto& parameter : module.localparams) source += "    localparam " + parameter.name + " = " + to_sv(parameter.value) + ";\n";
    for (auto& signal : module.signals) source += annotation(signal) + "    " + signal_decl(signal) + ";\n";
    for (auto& [name, value] : module.frozen_parameters) source += "    if (" + name + " !== (" + std::to_string(value) + ")) begin : __slip_frozen_" + name + "\n        $error(\"" + name + " controls Slip compile-time expansion and cannot be overridden\");\n    end\n";
    for (auto& assignment : module.assignments) source += "    assign " + to_sv(assignment.target) + " = " + to_sv(assignment.value) + ";\n";
    for (auto& process : module.processes) {
        source += "    ";
        if (process.kind == ProcessKind::combinational) source += "always_comb";
        else if (process.kind == ProcessKind::initial) source += "initial";
        else { source += "always_ff @(posedge " + process.clock; if (!process.reset.empty()) source += " or " + std::string(process.edge == "pos" ? "posedge " : "negedge ") + process.reset; source += ")"; }
        source += " begin\n" + emit_body(process.body, 2) + "    end\n";
    }
    for (auto& instance : module.instances) {
        source += "    " + instance.module;
        if (!instance.parameters.empty()) {
            source += " #(\n";
            for (std::size_t i = 0; i < instance.parameters.size(); ++i) source += "        ." + instance.parameters[i].first + "(" + instance.parameters[i].second + ")" + (i + 1 == instance.parameters.size() ? "\n" : ",\n");
            source += "    )";
        }
        source += " " + instance.name + " (";
        std::vector<std::string> ports; for (auto& [port, signal] : instance.connections) if (signal != "_") ports.push_back("        ." + port + "(" + signal + ")");
        if (!ports.empty()) source += "\n" + join(ports, ",\n") + "\n    ";
        source += ");\n";
    }
    return source + "endmodule\n";
}

void resolve_includes(Unit& unit, const std::filesystem::path& base, std::set<std::filesystem::path>& seen, const Options& options, std::size_t depth = 0) {
    if (depth > options.max_include_depth) throw Error({base.string()}, "E_LIMIT", "include nesting limit exceeded");
    for (auto& include : unit.includes) {
        auto path = std::filesystem::weakly_canonical(base / include.path);
        if (!seen.insert(path).second) continue;
        auto included = parse(read_file(path), path.string()); resolve_includes(included, path.parent_path(), seen, options, depth + 1);
        unit.modules.insert(unit.modules.end(), std::make_move_iterator(included.modules.begin()), std::make_move_iterator(included.modules.end()));
        unit.functions.insert(unit.functions.end(), std::make_move_iterator(included.functions.begin()), std::make_move_iterator(included.functions.end()));
    }
    unit.includes.clear();
}
Result compile_unit(Unit unit, const Options& options) {
    Backend backend(options); Functions functions(unit.functions); Result result;
    std::map<std::string, Lowered> modules;
    std::set<std::string> local_names;
    for (auto& module : unit.modules) {
        if (!local_names.insert(module.name).second || backend.ips.contains(module.name)) throw Error(module.loc, "E_DUPLICATE", "duplicate module '" + module.name + "'");
        modules.emplace(module.name, lower(module, backend, options, result.warnings));
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
        interfaces[name] = interface_of(module.ir); result.modules[name] = emit(module.ir);
        for (auto& parent : dependents[name]) if (--dependencies[parent] == 0) ready.insert(parent);
    }
    if (result.modules.size() != modules.size()) throw Error({}, "E_MODULE_CYCLE", "cyclic module instantiation dependency");
    backend.validate(result.modules, options.strict, result.warnings);
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
    std::filesystem::create_directories(directory);
    for (auto& [name, source] : result.modules) {
        auto file = directory / (name + ".sv");
        std::ofstream output(file, std::ios::binary | std::ios::trunc);
        if (!output || !(output << source)) throw Error({file.string()}, "E_IO", "cannot write output");
    }
}
} // namespace slip
