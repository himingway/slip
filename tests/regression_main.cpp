#include "test_support.hpp"
#include <iostream>

std::vector<test::Case>& test::cases() { static std::vector<Case> values; return values; }

int main(int argc, char** argv) {
    unsigned run = 0, failed = 0;
    for (const auto& entry : test::cases()) {
        if (argc > 1 && entry.name != argv[1]) continue;
        ++run;
        try { entry.run(); }
        catch (const std::exception& error) {
            ++failed;
            std::cerr << entry.name << ": " << error.what() << '\n';
        }
    }
    if (!run) { std::cerr << "Unknown test case\n"; return 2; }
    std::cout << run - failed << '/' << run << " cases passed\n";
    return failed ? 1 : 0;
}
