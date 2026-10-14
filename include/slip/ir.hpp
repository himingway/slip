#pragma once
#include "slip/ast.hpp"
#include <cstdint>
#include <map>

namespace slip {
struct IRSignal {
    std::string name, width, array;
    bool is_signed = false;
    bool declared = true;
    std::string direction; // empty for internal storage
    std::string inferred_from;
    Location loc;
    std::string type = "logic";
    bool infer_width = true, direction_explicit = false;
    bool interface_field = false, interface_port = false;
};
struct IRConnectionInfo {
    std::string port, direction, width, array, signal, origin;
    Location loc;
};
struct IRInstance {
    Location loc;
    std::string module, name;
    std::vector<std::pair<std::string, std::string>> parameters, connections;
    std::vector<IRConnectionInfo> connection_details = {};
};
struct IRNativeInterface {
    Location loc;
    std::string name, type, modport;
    bool port = false;
    std::vector<std::pair<std::string, std::string>> parameters;
    std::vector<IRSignal> fields;
    std::map<std::string, std::map<std::string, std::string>> modports;
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
    std::vector<Location> localparam_locations, assignment_locations, process_locations;
    Body declarations;
    std::map<std::string, std::vector<std::string>> bundles;
    std::map<std::string, std::string> bundle_types;
    std::map<std::string, IRNativeInterface> native_interfaces;
};
} // namespace slip
