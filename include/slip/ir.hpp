#pragma once
#include "slip/ast.hpp"
#include <cstdint>

namespace slip {
struct IRSignal {
    std::string name, width, array;
    bool is_signed = false;
    bool declared = true;
    std::string direction; // empty for internal storage
    std::string inferred_from;
};
struct IRInstance {
    Location loc;
    std::string module, name;
    std::vector<std::pair<std::string, std::string>> parameters, connections;
};
struct IRModule {
    Location loc;
    std::string name;
    std::vector<NamedValue> parameters, localparams;
    std::vector<IRSignal> ports, signals;
    std::vector<Assignment> assignments;
    std::vector<Process> processes;
    std::vector<IRInstance> instances;
    std::vector<std::pair<std::string, std::int64_t>> frozen_parameters;
};
} // namespace slip
