#pragma once

#include "slip/compiler.hpp"

namespace slip::cli {
struct Project {
    std::string entry;
    std::filesystem::path output;
    Options options;
    Location loc;
};

// Paths in slip.conf are resolved against the configuration file's directory.
Project read_project(const std::filesystem::path& file);
} // namespace slip::cli
