#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t*, std::size_t);

int main(int argc, char** argv) {
    std::filesystem::path corpus;
    unsigned runs = 3000;
    std::uint64_t seed = 42;
    try {
        for (int i=1; i<argc; ++i) {
            const std::string arg=argv[i];
            if (++i==argc) throw std::runtime_error("Missing option value");
            if (arg=="--corpus") corpus=argv[i];
            else if (arg=="--runs") runs=std::stoul(argv[i]);
            else if (arg=="--seed") seed=std::stoull(argv[i]);
            else throw std::runtime_error("Unknown option: "+arg);
        }
        std::vector<std::filesystem::path> files;
        for(const auto& file:std::filesystem::directory_iterator(corpus))
            if(file.is_regular_file()) files.push_back(file.path());
        std::sort(files.begin(),files.end());
        std::vector<std::string> inputs;
        for(const auto& file:files) {
            std::ifstream stream(file,std::ios::binary);
            inputs.emplace_back(std::istreambuf_iterator<char>(stream),std::istreambuf_iterator<char>());
        }
        if(inputs.empty()) throw std::runtime_error("Empty corpus");
        std::mt19937_64 random(seed);
        auto exercise=[&](const std::string& input) {
            // Write before execution so a sanitizer failure has a reproducible input.
            std::ofstream("fuzz-last-input",std::ios::binary).write(input.data(),input.size());
            LLVMFuzzerTestOneInput(reinterpret_cast<const std::uint8_t*>(input.data()),input.size());
        };
        for(const auto& input:inputs) exercise(input);
        for(unsigned run=0;run<runs;++run) {
            auto input=inputs[random()%inputs.size()];
            for(unsigned edit=0,count=1+random()%8;edit<count;++edit) {
                const auto position=random()%(input.size()+1);
                switch(random()%4) {
                    case 0: input.insert(position,1,static_cast<char>(random()%256)); break;
                    case 1: if(position<input.size()) input.erase(position,1+random()%std::min<std::size_t>(16,input.size()-position)); break;
                    case 2: if(position<input.size()) input[position]^=static_cast<char>(1u<<(random()%8)); break;
                    default: if(!input.empty() && input.size()<4096) input.insert(position,input.substr(random()%input.size(),1+random()%32)); break;
                }
            }
            exercise(input);
        }
        std::filesystem::remove("fuzz-last-input");
        std::cout<<"PASS: "<<runs<<" byte mutations and "<<inputs.size()<<" seeds; RNG seed="<<seed<<'\n';
    } catch(const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; }
}
